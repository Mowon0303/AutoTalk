"""python main.py --snap —— 抓一张聊天软件截图,存「实际分析的区域」+ 预览打开 + 打印解析。

用来亲眼核对:图里是不是右侧对话区、读出的发言人/内容对不对。
"""
from __future__ import annotations

import os
import shutil
import subprocess

import capture
import llm
import vision

HERE = os.path.dirname(os.path.abspath(__file__))
DEST = os.path.join(HERE, "last_capture.png")


def run(cfg: dict) -> None:
    llm.configure(cfg.get("provider", "anthropic"), cfg.get("ollama_host", "http://localhost:11434"))
    vision.configure(cfg.get("read_mode", "vlm"), cfg.get("ocr_backend", "auto"),
                     cfg.get("me_side", "right"), cfg.get("crop_left", 0.0), cfg.get("crop_bottom", 0.0))
    capture.configure(cfg.get("app_aliases", []))

    try:
        png = capture.grab(cfg["app_name"])
    except Exception as e:
        print(f"❌ 截图失败:{e}")
        return

    wid = capture.window_id(cfg["app_name"])
    if wid:
        print(f"截图方式:按窗口ID #{wid}(只截聊天软件窗口,不受遮挡)✅")
    else:
        print("截图方式:区域截图(可能截到挡在上面的窗口!)⚠️ 没定位到聊天软件窗口。")
        print("  当前窗口 owner:", capture.list_window_owners())
        print("  若列表里聊天软件叫别的名,把 config.yaml 的 app_name 改成那个名。")

    # 保存「实际分析的区域」(已裁掉左侧会话列表 / 底部输入框)供你核对
    view, tmp = vision._apply_crop(png)
    shutil.copy(view, DEST)
    print(f"已保存(实际分析区域):{DEST}  → 正在用「预览」打开,核对是不是右侧对话\n")
    subprocess.run(["open", DEST], check=False)

    data = vision.read_messages(png, cfg["vision_model"], cfg["read_last_n"])
    for p in {png, tmp}:
        if p and p != DEST:
            try:
                os.remove(p)
            except OSError:
                pass

    print(f"解析:chat_title={data.get('chat_title')} | 群聊={data.get('is_group')} | 读模式={cfg.get('read_mode')}")
    msgs = data.get("messages") or []
    if not msgs:
        print("  (没读到消息)")
    for m in msgs:
        print(f"  {m.get('sender')} : {m.get('text', '').replace(chr(10), ' / ')}")
