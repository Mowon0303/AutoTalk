"""运行时目录解析:开发态用项目目录(行为不变),打包态(.app)用可写的用户目录。

- 开发(直接 python 跑):base_dir() = 项目目录,和以前完全一样。
- 打包(py2app, sys.frozen):base_dir() = ~/Library/Application Support/AutoTalk,
  首次运行从 bundle 资源里拷出 config.example→config.yaml、人设,并建好 memory 目录。
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

_FROZEN = bool(getattr(sys, "frozen", False))
# 打包后只读资源在 Contents/Resources(py2app 设 RESOURCEPATH);开发态即本文件所在目录
_RES = Path(os.environ.get("RESOURCEPATH") or Path(__file__).resolve().parent)


def resource_dir() -> Path:
    """只读资源(默认人设 / 模板)所在目录。"""
    return _RES


def base_dir() -> Path:
    """可写用户数据目录(config.yaml / skills/memory / 截图 / 状态)。"""
    if not _FROZEN:
        return Path(__file__).resolve().parent          # 开发:项目目录
    d = Path.home() / "Library" / "Application Support" / "AutoTalk"
    d.mkdir(parents=True, exist_ok=True)
    _seed(d)
    return d


def _seed(d: Path) -> None:
    """首次运行:把只读默认拷进可写目录。"""
    cfg = d / "config.yaml"
    if not cfg.exists():
        ex = _RES / "config.example.yaml"
        if ex.exists():
            shutil.copy(ex, cfg)
    psrc, pdst = _RES / "skills" / "personas", d / "skills" / "personas"
    if psrc.exists() and not pdst.exists():
        shutil.copytree(psrc, pdst)
    (d / "skills" / "memory").mkdir(parents=True, exist_ok=True)
