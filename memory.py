"""联系人记忆:人工可编辑档案(.md) + 机器维护的摘要(.summary.md)。

两者分文件存放:代码只写 .summary.md,绝不覆盖你手填的 .md。
"""
from __future__ import annotations

import re
from pathlib import Path

import llm

MEM_DIR = Path(__file__).resolve().parent / "skills" / "memory"


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
        "- 人设: \n"  # 留空则用 config 映射或默认人设
        "- 备注: \n"
    )


def load(title: str | None) -> str:
    """返回供 prompt 使用的记忆全文。首次见到某人会自动创建可编辑档案模板。"""
    if not title:
        return ""
    MEM_DIR.mkdir(parents=True, exist_ok=True)
    profile = _profile_path(title)
    if not profile.exists():
        profile.write_text(_template(title), encoding="utf-8")
    parts = [profile.read_text(encoding="utf-8")]
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
