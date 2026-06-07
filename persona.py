"""人设(风格)skill 的加载与按联系人绑定。"""
from __future__ import annotations

import re
from pathlib import Path

import appdirs

PERSONA_DIR = appdirs.base_dir() / "skills" / "personas"


def load(name: str) -> str:
    p = PERSONA_DIR / f"{name}.md"
    return p.read_text(encoding="utf-8") if p.exists() else ""


def resolve(chat_title: str | None, cfg: dict, memory_text: str = "") -> str:
    """决定用哪个人设:记忆文件里的 "人设:" 优先 > config 映射 > 默认。"""
    name = None
    m = re.search(r"人设[:：]\s*([A-Za-z0-9_\-]+)", memory_text or "")
    if m:
        name = m.group(1)
    if not name and chat_title:
        name = (cfg.get("contacts") or {}).get(chat_title)
    if not name:
        name = cfg.get("default_persona", "serious")
    text = load(name) or load(cfg.get("default_persona", "serious"))
    return text or "用自然、得体的语气回复。"
