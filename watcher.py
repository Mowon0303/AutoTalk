"""主循环:轮询截图 -> 检测新消息 -> 生成草稿 -> 人工确认 -> 发送。"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import agent
import capture
import confirm
import llm
import memory
import persona
import sender
import vision

STATE_PATH = Path(__file__).resolve().parent / ".state.json"


def _load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}
    return {}


def _save_state(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def _last_incoming(messages):
    """最后一条对方发的消息(跳过自己、系统、无法判定的)。"""
    for m in reversed(messages):
        if m.get("sender") not in ("我", "系统", "unknown"):
            return m
    return None


def step(cfg: dict, state: dict) -> None:
    """跑一轮:截图 -> 判断 -> 必要时生成并确认 -> 发送。"""
    png = capture.grab(cfg["app_name"])
    try:
        h = capture.file_hash(png)
        if h == state.get("_last_hash"):
            return  # 画面没变,省一次视觉调用
        state["_last_hash"] = h
        data = vision.read_messages(png, cfg["vision_model"], cfg["read_last_n"])
    finally:
        try:
            os.remove(png)
        except OSError:
            pass

    title = data.get("chat_title") or "unknown"
    messages = data.get("messages") or []
    if not messages:
        return

    last = messages[-1]
    sig = f'{last.get("sender")}:{last.get("text")}'
    if sig == state.get(title):
        return  # 这条已处理过

    incoming = _last_incoming(messages)
    # 仅当"对方"是最新一条时才回复;"我"/系统/unknown 都不触发,记下签名跳过
    if last.get("sender") in ("我", "系统", "unknown") or incoming is not last:
        state[title] = sig
        return

    print(f"\n[{title}] 新消息: {incoming.get('text')}")
    mem = memory.load(title)
    persona_text = persona.resolve(title, cfg, mem)
    draft = agent.draft_reply(messages, persona_text, mem, cfg["reply_model"], cfg["read_last_n"])
    print(f"  草稿: {draft}")

    decision, text = confirm.ask(incoming.get("text", ""), draft)
    if decision == "send" and text.strip():
        sender.send(text, cfg["app_name"], cfg["dry_run"], cfg["send_with"])
        if cfg.get("update_memory"):
            memory.update(
                title, agent.render(messages, cfg["read_last_n"]), text, cfg["summary_model"]
            )
        state[title] = f"我:{text}"  # 防止把自己刚发的当成新消息
    else:
        print("  已跳过")
        state[title] = sig


def run(cfg: dict, once: bool = False) -> None:
    state = _load_state()
    llm.configure(cfg.get("provider", "anthropic"), cfg.get("ollama_host", "http://localhost:11434"))
    vision.configure(cfg.get("read_mode", "vlm"), cfg.get("ocr_backend", "auto"),
                     cfg.get("me_side", "right"), cfg.get("crop_left", 0.0), cfg.get("crop_bottom", 0.0))
    capture.configure(cfg.get("app_aliases", []))
    interval = max(3, int(cfg.get("poll_interval_seconds", 5)))
    print(
        f"AutoTalk 启动 | 后端={cfg.get('provider', 'anthropic')} | 模型={cfg['model']} "
        f"| 轮询={interval}s | dry_run={cfg['dry_run']}"
    )
    print("请保持聊天软件窗口可见。Ctrl+C 退出。")
    try:
        while True:
            try:
                step(cfg, state)
            except Exception as e:
                print(f"[本轮出错,继续] {e}")
            finally:
                _save_state(state)
            if once:
                break
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n已退出。")
        _save_state(state)
