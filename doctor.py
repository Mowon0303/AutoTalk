"""体检:`python main.py --check` —— 跑真机前确认依赖/权限/ollama/微信都就绪。"""
from __future__ import annotations

import json
import os
import subprocess
import urllib.request

import capture


def _p(ok: bool, label: str, hint: str = "") -> bool:
    mark = "✅" if ok else "❌"
    print(f"  {mark} {label}" + (f"  → {hint}" if (not ok and hint) else ""))
    return ok


def run(cfg: dict) -> None:
    print("AutoTalk 体检\n")
    all_ok = True

    # 1) 截图(屏幕录制权限)
    try:
        png = capture.grab(cfg["app_name"])
        try:
            os.remove(png)
        except OSError:
            pass
        all_ok &= _p(True, "截图正常(屏幕录制权限 OK)")
    except Exception as e:
        all_ok &= _p(False, "截图", str(e))

    # 2) 微信在运行
    running = subprocess.run(["pgrep", "-x", cfg["app_name"]], capture_output=True).returncode == 0
    all_ok &= _p(running, f"微信进程「{cfg['app_name']}」在运行", "打开微信并停在某个会话")

    # 3) 模型后端
    if cfg["provider"] == "ollama":
        host = cfg["ollama_host"].rstrip("/")
        names, online = [], False
        try:
            data = json.loads(urllib.request.urlopen(host + "/api/tags", timeout=3).read())
            names = [m.get("name", "") for m in data.get("models", [])]
            online = True
        except Exception:
            pass
        all_ok &= _p(online, f"ollama 服务在线（{host}）", "先启动 ollama")
        if online:
            want = cfg["model"]
            has = any(want.split(":")[0] in n for n in names)
            all_ok &= _p(has, f"模型「{want}」已就绪", f"ollama pull {want}")
    else:
        all_ok &= _p(bool(os.environ.get("ANTHROPIC_API_KEY")),
                     "ANTHROPIC_API_KEY 已设置", "export ANTHROPIC_API_KEY=...")

    # 4) OCR 后端(read_mode=ocr 时)
    if cfg.get("read_mode") == "ocr":
        import importlib.util as u
        be = cfg.get("ocr_backend", "auto")
        if be in ("auto", "vision"):
            ok = bool(u.find_spec("Vision")) and bool(u.find_spec("Quartz"))
        elif be == "easyocr":
            ok = bool(u.find_spec("easyocr"))
        elif be == "paddleocr":
            ok = bool(u.find_spec("paddleocr"))
        else:
            ok = True
        _p(ok, f"OCR 后端（{be}）可用", "见 requirements 安装;或把 read_mode 改成 vlm（会回退）")

    print("\n" + ("✅ 全部就绪 → python main.py --once"
                  if all_ok else "❌ 先解决上面的 ❌ 再跑(截图项通常是给终端开屏幕录制权限)"))
