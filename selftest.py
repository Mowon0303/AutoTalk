#!/usr/bin/env python3
"""离线自检:对一张静态聊天截图跑 读取 -> 草稿(不截图、不发送、零权限)。

用法: python3 selftest.py <截图路径>
用于验证/调试视觉读取与草稿生成,尤其是切到本地 Ollama 之后。
"""
from __future__ import annotations

import sys

import agent
import config
import llm
import memory
import persona
import vision


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("用法: python3 selftest.py <截图路径>")
    path = sys.argv[1]

    cfg = config.load()
    llm.configure(cfg.get("provider", "anthropic"), cfg.get("ollama_host", "http://localhost:11434"))
    vision.configure(cfg.get("read_mode", "vlm"), cfg.get("ocr_backend", "auto"),
                     cfg.get("me_side", "right"), cfg.get("crop_left", 0.0), cfg.get("crop_bottom", 0.0))
    print(f"后端={cfg['provider']} | 读取={cfg['read_mode']} | 视觉模型={cfg['vision_model']} | 回复模型={cfg['reply_model']}\n")

    data = vision.read_messages(path, cfg["vision_model"], cfg["read_last_n"])
    title = data.get("chat_title") or "unknown"
    msgs = data.get("messages") or []
    print(f"[读取] chat_title={title} | 群聊={data.get('is_group')}")
    for m in msgs:
        print(f"  {m.get('sender')}: {m.get('text')}")
    if not msgs:
        print("\n没读到消息 —— 可能截图不是聊天窗口,或模型没认出来。换张更清晰的聊天截图再试。")
        return

    last = msgs[-1]
    if last.get("sender") in ("我", "系统", "unknown"):
        print(f"\n[检测] 最后一条是「{last.get('sender')}」→ 不触发回复(符合预期)。")
        print("       想看草稿,请换一张『对方』为最后一条的截图。")
        return

    mem = memory.load(title)
    p = persona.resolve(title, cfg, mem)
    draft = agent.draft_reply(msgs, p, mem, cfg["reply_model"], cfg["read_last_n"])
    print(f"\n[草稿] {draft}")


if __name__ == "__main__":
    main()
