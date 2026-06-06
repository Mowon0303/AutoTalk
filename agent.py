"""根据上下文 + 人设 + 记忆生成回复草稿。"""
from __future__ import annotations

import llm

_BASE = (
    "你在帮用户本人回复微信。根据对话上下文、下面的人设与对该联系人的记忆,"
    "以用户的身份生成下一条要发给对方的回复。\n"
    "要求:只输出回复正文;简短、口语化、像真人微信聊天;"
    "不要加引号、不要解释、不要署名;除非人设要求,否则不加表情符号。"
)


def render(messages, last_n: int) -> str:
    """把消息列表渲染成 '发送者: 内容' 的多行文本。"""
    rows = []
    for m in messages[-last_n:]:
        rows.append(f"{m.get('sender', '?')}: {m.get('text', '')}")
    return "\n".join(rows)


def draft_reply(messages, persona_text: str, memory_text: str, model: str, last_n: int = 8) -> str:
    convo = render(messages, last_n)
    system = (
        f"{_BASE}\n\n## 当前人设\n{persona_text}\n\n"
        f"## 关于该联系人的记忆\n{memory_text or '(暂无)'}"
    )
    user = f"## 当前对话(最后一条是对方刚发的)\n{convo}\n\n请直接给出你要发送的回复:"
    return llm.call_text(model, system, user, max_tokens=400, temperature=0.7)
