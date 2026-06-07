"""根据上下文 + 人设 + 记忆生成回复草稿。"""
from __future__ import annotations

import llm

_BASE = (
    "你在帮用户本人回复聊天软件。根据对话上下文、下面的人设与对该联系人的记忆,"
    "以用户的身份生成下一条要发给对方的回复。\n"
    "要求:只输出回复正文;简短、口语化、像真人聊天;"
    "不要加引号、不要解释、不要署名;除非人设要求,否则不加表情符号。\n"
    "回复策略:\n"
    "- 先判断对方最后一句是不是问题、二选一或确认请求;如果是,先直接回答它。\n"
    "- 如果手动上下文里设了“目标”,每条回复都朝这个阶段性目标自然推进(循序渐进、别突兀、别用力过猛);没设目标就正常接话。\n"
    "- 不要反问对方已经问过的问题,也不要复述对方刚说过的信息。\n"
    "- 信息不足时,用一句自然的澄清或给出你的当前倾向,不要编造事实。"
)


def render(messages, last_n: int) -> str:
    """把消息列表渲染成 '发送者: 内容' 的多行文本。"""
    rows = []
    for m in messages[-last_n:]:
        rows.append(f"{m.get('sender', '?')}: {m.get('text', '')}")
    return "\n".join(rows)


def _render_manual_context(manual_context: dict | None) -> str:
    if not manual_context:
        return "(暂无)"
    labels = {
        "person_info": "对方信息",
        "goal": "目标(阶段性)",
        "avoid": "不要提/边界",
        "notes": "备注",
    }
    rows = []
    for key, label in labels.items():
        value = (manual_context.get(key) or "").strip()
        if value:
            rows.append(f"- {label}: {value}")
    return "\n".join(rows) if rows else "(暂无)"


def draft_reply(
    messages,
    persona_text: str,
    memory_text: str,
    model: str,
    last_n: int = 8,
    manual_context: dict | None = None,
) -> str:
    convo = render(messages, last_n)
    system = (
        f"{_BASE}\n\n## 当前人设\n{persona_text}\n\n"
        f"## 手动上下文(优先级最高)\n{_render_manual_context(manual_context)}\n\n"
        f"## 关于该联系人的记忆\n{memory_text or '(暂无)'}"
    )
    user = f"## 当前对话(最后一条是对方刚发的)\n{convo}\n\n请直接给出你要发送的回复:"
    return llm.call_text(model, system, user, max_tokens=300, temperature=0.4)
