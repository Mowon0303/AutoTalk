"""联系人记忆:人工可编辑档案(.md) + 机器维护的摘要(.summary.md)。

两者分文件存放:代码只写 .summary.md,绝不覆盖你手填的 .md。
"""
from __future__ import annotations

import re
from pathlib import Path

import appdirs
import llm

MEM_DIR = appdirs.base_dir() / "skills" / "memory"
MANUAL_START = "<!-- autotalk:manual-context:start -->"
MANUAL_END = "<!-- autotalk:manual-context:end -->"
MANUAL_SECTIONS = {
    "person_info": "对方信息",
    "goal": "目标(阶段性)",
    "avoid": "不要提/边界",
    "notes": "备注",
}


def _safe(title: str) -> str:
    return re.sub(r"[^\w一-鿿\-]", "_", title or "unknown")[:60]


def _profile_path(title: str) -> Path:
    return MEM_DIR / f"{_safe(title)}.md"


def _summary_path(title: str) -> Path:
    return MEM_DIR / f"{_safe(title)}.summary.md"


def _template(title: str) -> str:
    return (
        f"# {title}\n"
        "- 关系: (待填,例如:同事 / 朋友 / 对象)\n"
        "- 称呼: \n"
        "- 偏好: (例如:说话简短、别发表情)\n"
        "- 不要提: \n"
        "- 人设: \n"  # 留空则用 config 映射或默认人设
        "- 备注: \n"
    )


def _blank_manual_context() -> dict:
    return {key: "" for key in MANUAL_SECTIONS}


def _profile_text(title: str | None) -> str:
    if not title:
        return ""
    p = _profile_path(title)
    return p.read_text(encoding="utf-8") if p.exists() else ""


def _manual_block(values: dict) -> str:
    rows = [MANUAL_START, "## 手动上下文"]
    for key, heading in MANUAL_SECTIONS.items():
        rows.append(f"### {heading}")
        rows.append((values.get(key) or "").strip())
        rows.append("")
    rows.append(MANUAL_END)
    return "\n".join(rows).rstrip() + "\n"


def _strip_manual_block(text: str) -> str:
    pattern = re.compile(
        rf"\n?{re.escape(MANUAL_START)}.*?{re.escape(MANUAL_END)}\n?",
        re.DOTALL,
    )
    return pattern.sub("\n", text).rstrip() + "\n"


def profile_exists(title: str | None) -> bool:
    return bool(title) and _profile_path(title).exists()


def manual_context(title: str | None) -> dict:
    """读取 UI 可编辑的手动上下文。没有填写时返回空字段。"""
    text = _profile_text(title)
    if not text or MANUAL_START not in text or MANUAL_END not in text:
        return _blank_manual_context()
    block = text.split(MANUAL_START, 1)[1].split(MANUAL_END, 1)[0]
    out = _blank_manual_context()
    heading_to_key = {v: k for k, v in MANUAL_SECTIONS.items()}
    current = None
    bucket: list[str] = []
    for line in block.splitlines():
        if line.startswith("### "):
            if current:
                out[current] = "\n".join(bucket).strip()
            current = heading_to_key.get(line[4:].strip())
            bucket = []
        elif current:
            bucket.append(line)
    if current:
        out[current] = "\n".join(bucket).strip()
    return out


def has_manual_context(values: dict) -> bool:
    return any((values.get(k) or "").strip() for k in ("person_info", "goal", "avoid"))


def save_manual_context(title: str | None, values: dict) -> dict:
    """保存 UI 手动输入。写入 profile 文件中的专用块,不改自动摘要。"""
    if not title:
        raise ValueError("缺少联系人标题,请先读取一次对话。")
    MEM_DIR.mkdir(parents=True, exist_ok=True)
    p = _profile_path(title)
    if not p.exists():
        p.write_text(_template(title), encoding="utf-8")
    clean = {key: (values.get(key) or "").strip() for key in MANUAL_SECTIONS}
    base = _strip_manual_block(p.read_text(encoding="utf-8"))
    p.write_text(base.rstrip() + "\n\n" + _manual_block(clean), encoding="utf-8")
    return clean


def load(title: str | None) -> str:
    """返回供 prompt 使用的记忆全文。首次见到某人会自动创建可编辑档案模板。"""
    if not title:
        return ""
    MEM_DIR.mkdir(parents=True, exist_ok=True)
    profile = _profile_path(title)
    if not profile.exists():
        profile.write_text(_template(title), encoding="utf-8")
    parts = [_strip_manual_block(profile.read_text(encoding="utf-8"))]  # 手动上下文已单独高优注入,去重
    summ = _summary_path(title)
    if summ.exists():
        parts.append(summ.read_text(encoding="utf-8"))
    return "\n\n".join(parts).strip()


def update(title: str | None, recent_text: str, my_reply: str, model: str) -> None:
    """据最新一轮对话刷新自动摘要。失败不影响主流程。"""
    if not title:
        return
    try:
        sp = _summary_path(title)
        prev = sp.read_text(encoding="utf-8") if sp.exists() else ""
        prompt = (
            "你在为某个聊天软件联系人维护一份简短记忆笔记(中文 markdown,150 字以内),"
            "标题为 '## 自动摘要',记录对方近况、聊过的关键事、TA 的偏好等。\n\n"
            f"现有笔记:\n{prev or '(空)'}\n\n"
            f"最新一轮对话:\n{recent_text}\n我刚回复: {my_reply}\n\n"
            "输出更新后的完整笔记(只输出 markdown 正文):"
        )
        new = llm.call_text(model, "你是简洁的笔记维护助手。", prompt, max_tokens=400, temperature=0.3)
        if new:
            sp.write_text(new.strip() + "\n", encoding="utf-8")
    except Exception as e:  # 记忆更新失败不该中断回复流程
        print(f"  [记忆更新跳过] {e}")
