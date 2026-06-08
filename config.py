"""配置加载 + 运行时数据目录解析。

- 数据目录:开发态=项目目录(行为不变);打包态(py2app, sys.frozen)=
  ~/Library/Application Support/DraftMate(首次从 bundle 资源拷出 config.example→config.yaml、人设)。
- 配置:读 config.yaml,补默认值,处理模型回退。
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None


# ════════════════════ 数据目录(开发态 / py2app 打包态)════════════════════
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
    d = Path.home() / "Library" / "Application Support" / "DraftMate"
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


# ════════════════════ 配置加载与默认值 ════════════════════
_DEFAULTS = {
    "provider": "anthropic",
    "ollama_host": "http://localhost:11434",
    "read_mode": "vlm",
    "ocr_backend": "auto",
    "me_side": "right",
    "crop_left": 0.0,
    "crop_bottom": 0.0,
    "model": "claude-sonnet-4-6",
    "vision_model": None,
    "reply_model": None,
    "app_name": "",
    "app_aliases": [],
    "read_last_n": 8,
    "default_persona": "serious",
    "contacts": {},
}


def load(path: str | None = None) -> dict:
    """读取 config.yaml,补齐默认值,处理模型回退。"""
    if yaml is None:
        raise SystemExit("缺少依赖 PyYAML,请先运行: pip install -r requirements.txt")
    p = Path(path) if path else base_dir() / "config.yaml"
    cfg = dict(_DEFAULTS)
    if p.exists():
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        cfg.update({k: v for k, v in data.items() if v is not None})
    # 单独指定的模型为空时回退到主模型
    cfg["vision_model"] = cfg.get("vision_model") or cfg["model"]
    cfg["reply_model"] = cfg.get("reply_model") or cfg["model"]
    cfg["contacts"] = cfg.get("contacts") or {}
    return cfg
