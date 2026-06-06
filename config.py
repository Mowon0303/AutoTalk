"""配置加载与默认值。"""
from __future__ import annotations

from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

ROOT = Path(__file__).resolve().parent

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
    "summary_model": "claude-haiku-4-5-20251001",
    "app_name": "",
    "app_aliases": [],
    "poll_interval_seconds": 5,
    "read_last_n": 8,
    "dry_run": True,
    "send_with": "enter",
    "default_persona": "serious",
    "contacts": {},
    "update_memory": True,
}


def load(path: str | None = None) -> dict:
    """读取 config.yaml,补齐默认值,处理模型回退。"""
    if yaml is None:
        raise SystemExit("缺少依赖 PyYAML,请先运行: pip install -r requirements.txt")
    p = Path(path) if path else ROOT / "config.yaml"
    cfg = dict(_DEFAULTS)
    if p.exists():
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        cfg.update({k: v for k, v in data.items() if v is not None})
    # 单独指定的模型为空时回退到主模型
    cfg["vision_model"] = cfg.get("vision_model") or cfg["model"]
    cfg["reply_model"] = cfg.get("reply_model") or cfg["model"]
    cfg["summary_model"] = cfg.get("summary_model") or cfg["model"]
    cfg["contacts"] = cfg.get("contacts") or {}
    return cfg
