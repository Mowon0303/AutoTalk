#!/usr/bin/env python3
"""AutoTalk —— 微信桌面版自动回复助手。

截图读取微信 -> 大模型理解对话 -> 套人设+记忆生成草稿 -> 人工确认 -> 发送。
"""
from __future__ import annotations

import argparse

import config
import watcher


def main() -> None:
    ap = argparse.ArgumentParser(
        description="AutoTalk: 截图读微信 -> 生成草稿 -> 人工确认 -> 发送"
    )
    ap.add_argument("-c", "--config", help="配置文件路径(默认 ./config.yaml)")
    ap.add_argument("--once", action="store_true", help="只跑一轮(调试用)")
    ap.add_argument("--send", action="store_true", help="覆盖配置,真正发送(关闭 dry_run)")
    ap.add_argument("--check", action="store_true", help="体检:依赖/权限/ollama/微信 是否就绪")
    ap.add_argument("--snap", action="store_true", help="抓一张截图并存盘+预览打开+打印解析(看它捕捉到什么)")
    args = ap.parse_args()

    cfg = config.load(args.config)
    if args.check:
        import doctor
        doctor.run(cfg)
        return
    if args.snap:
        import snap
        snap.run(cfg)
        return
    if args.send:
        cfg["dry_run"] = False
    watcher.run(cfg, once=args.once)


if __name__ == "__main__":
    main()
