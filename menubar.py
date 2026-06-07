"""AutoTalk 菜单栏 App(macOS)。

功能:后台监听 + 草稿历史 + 看最近截图 + 人设快速切换 + 暂停时待办计数。
依赖: pip install rumps
运行: source .venv/bin/activate && python menubar.py

行为:
- 首次点「开始监听」启动后台轮询线程;之后「暂停/继续」只切换是否自动出草稿。
- 运行中:有新消息 → 出草稿 → 弹原生确认框 → 发送,并记入草稿历史。
- 暂停中:仍轻量轮询,只统计有多少会话有新消息(菜单栏显示 💬 N),不打扰你。
"""
from __future__ import annotations

import os
import subprocess
import threading
import time

try:
    import rumps
except ImportError:
    raise SystemExit("缺少依赖 rumps:pip install rumps")

import capture
import config
import llm
import vision
import watcher

HERE = os.path.dirname(os.path.abspath(__file__))
LAST_CAPTURE = os.path.join(HERE, "last_capture.png")
PERSONA_DIR = os.path.join(HERE, "skills", "personas")


class AutoTalkApp(rumps.App):
    def __init__(self) -> None:
        super().__init__("AutoTalk", title="💬", quit_button=None)
        self.cfg = config.load()
        llm.configure(self.cfg.get("provider", "anthropic"),
                      self.cfg.get("ollama_host", "http://localhost:11434"))
        vision.configure(self.cfg.get("read_mode", "vlm"), self.cfg.get("ocr_backend", "auto"),
                         self.cfg.get("me_side", "right"),
                         self.cfg.get("crop_left", 0.0), self.cfg.get("crop_bottom", 0.0))
        capture.configure(self.cfg.get("app_aliases", []))

        self.active = False
        self.history: list[dict] = []
        self.pending: dict[str, str] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

        self.status_item = rumps.MenuItem("状态:未启动")
        self.mode_item = rumps.MenuItem(self._mode_text())
        self.toggle_item = rumps.MenuItem("▶ 开始监听", callback=self.toggle)
        self.history_menu = rumps.MenuItem("📝 草稿历史")
        self.persona_menu = rumps.MenuItem("🎭 默认人设")
        self.menu = [
            self.status_item,
            self.mode_item,
            None,
            self.toggle_item,
            rumps.MenuItem("📂 看最近截图", callback=self.open_capture),
            self.history_menu,
            self.persona_menu,
            None,
            rumps.MenuItem("退出", callback=self.quit_app),
        ]
        self._build_persona_menu()
        self._refresh_history()
        self._update_ui()

    # ---------- 文案 / UI ----------
    def _mode_text(self) -> str:
        return (f"{self.cfg.get('provider')}/{self.cfg.get('read_mode')} · "
                f"人设={self.cfg.get('default_persona')} · dry_run={self.cfg.get('dry_run')}")

    def _update_ui(self) -> None:
        n = len(self.pending)
        started = self._thread is not None and self._thread.is_alive()
        if not started:
            self.title = "💬"
            self.status_item.title = "状态:未启动"
        elif self.active:
            self.title = "💬▶"
            self.status_item.title = "状态:运行中"
        else:
            self.title = f"💬 {n}" if n else "💬⏸"
            self.status_item.title = f"状态:已暂停 · {n} 条待回复" if n else "状态:已暂停"
        self.mode_item.title = self._mode_text()

    # ---------- 开始 / 暂停 ----------
    def toggle(self, _) -> None:
        if self._thread is None or not self._thread.is_alive():
            self.active = True
            self._stop.clear()
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()
        else:
            self.active = not self.active
        self.toggle_item.title = "⏸ 暂停监听" if self.active else "▶ 继续监听"
        self._update_ui()

    def _loop(self) -> None:
        state = watcher._load_state()
        while not self._stop.is_set():
            try:
                p = watcher.pending_incoming(self.cfg, state, LAST_CAPTURE)
                if p:
                    title, incoming, msgs = p
                    if self.active:
                        res = watcher.handle(self.cfg, state, title, msgs)
                        watcher._save_state(state)
                        self.pending.pop(title, None)
                        self.history.append({"t": time.strftime("%H:%M"), **res})
                        self.history = self.history[-12:]
                        self._refresh_history()
                    else:
                        self.pending[title] = incoming
                    self._update_ui()
            except Exception as e:
                self._notify("出错", str(e)[:120])
            interval = max(3, int(self.cfg.get("poll_interval_seconds", 5)))
            self._stop.wait(interval if self.active else interval * 2)

    # ---------- 草稿历史 ----------
    def _refresh_history(self) -> None:
        if self.history_menu._menu is not None:   # 已建过子菜单才能 clear(rumps 不自检)
            self.history_menu.clear()
        if not self.history:
            self.history_menu.add(rumps.MenuItem("(暂无)"))
            return
        for h in reversed(self.history):
            mark = "✅" if h.get("decision") == "sent" else "⏭"
            mi = rumps.MenuItem(f"{h['t']} {mark} {h['contact']}: {h['draft'][:18]}",
                                callback=self._copy_draft)
            mi._draft = h["draft"]
            self.history_menu.add(mi)
        self.history_menu.add(rumps.MenuItem("— 清空历史 —", callback=self._clear_history))

    def _copy_draft(self, sender) -> None:
        draft = getattr(sender, "_draft", "")
        if draft:
            subprocess.run(["pbcopy"], input=draft.encode("utf-8"), check=False)
            self._notify("已复制草稿到剪贴板", draft[:60])

    def _clear_history(self, _) -> None:
        self.history.clear()
        self._refresh_history()

    # ---------- 看最近截图 ----------
    def open_capture(self, _) -> None:
        if os.path.exists(LAST_CAPTURE):
            subprocess.run(["open", LAST_CAPTURE], check=False)
        else:
            self._notify("还没有截图", "开始监听、等下一轮后再看")

    # ---------- 人设快速切换 ----------
    def _build_persona_menu(self) -> None:
        if self.persona_menu._menu is not None:   # 同上:已建过才能 clear
            self.persona_menu.clear()
        cur = self.cfg.get("default_persona")
        names = []
        if os.path.isdir(PERSONA_DIR):
            names = sorted(f[:-3] for f in os.listdir(PERSONA_DIR) if f.endswith(".md"))
        for name in (names or ["serious"]):
            mi = rumps.MenuItem(name, callback=self.set_persona)
            mi.state = 1 if name == cur else 0
            self.persona_menu.add(mi)

    def set_persona(self, sender) -> None:
        self.cfg["default_persona"] = sender.title
        for it in self.persona_menu.values():
            try:
                it.state = 1 if it.title == sender.title else 0
            except Exception:
                pass
        self._update_ui()
        self._notify("默认人设已切换", sender.title + "(本次运行有效)")

    # ---------- 其它 ----------
    def quit_app(self, _) -> None:
        self._stop.set()
        rumps.quit_application()

    @staticmethod
    def _notify(title: str, msg: str) -> None:
        try:
            rumps.notification("AutoTalk", title, msg)
        except Exception:
            pass


if __name__ == "__main__":
    AutoTalkApp().run()
