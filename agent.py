"""根据上下文 + 人设 + 记忆生成回复草稿。"""
from __future__ import annotations

import llm

_ROLE = (
    "你在替用户本人在聊天软件里回消息。下面的「人设」就是你的说话方式,"
    "人设里的示例是语感参照——模仿那个味道,但禁止照抄原句、禁止套用到不贴合的语境。"
)

_RULES = (
    "- 你在替「我」说话:别把对方的处境、情绪、待办安到自己头上。\n"
    "- 只输出一条回复正文:不加引号、不解释、不署名。\n"
    "- 像真人打字:短句、口语,一般 1~2 句,最多 3 句。\n"
    "- 对方最后一句若是提问、二选一或求确认,先正面回应它。\n"
    "- 不反问对方已问过的问题,不复述对方刚说的话,不编造没发生的事。\n"
    "- 禁止客服腔和正确废话:「多喝热水」「注意休息哦」「加油哦」「辛苦啦」「没关系的呢」这类一律不出现。\n"
    "- 一条回复最多一个问题,不查户口。\n"
    "- 如果设了「目标(阶段性)」,朝它轻推一步就够,别用力过猛;没设目标就正常接话。\n"
    "- 信息不足时给出自己的倾向或自然地问清,不要瞎编。"
)

# 各人设的采样温度:撩/走心需要变化和灵气,正式场合要稳。
_TEMPS = {"serious": 0.5, "casual": 0.75, "flirty": 0.85, "shenqing": 0.8}


def temperature_for(persona_name: str, regen: bool = False) -> float:
    """人设 → 采样温度;「换个说法」再加一点随机,避免重生成出同一句。"""
    t = _TEMPS.get(persona_name, 0.7)
    return min(1.0, t + 0.15) if regen else t


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
    temperature: float = 0.7,
) -> str:
    convo = render(messages, last_n)
    # 人设放最前定调,硬规则压轴 —— 小模型对开头和结尾的指令最敏感
    system = (
        f"{_ROLE}\n\n## 人设(你的说话方式)\n{persona_text}\n\n"
        f"## 手动上下文(优先级最高)\n{_render_manual_context(manual_context)}\n\n"
        f"## 关于该联系人的记忆\n{memory_text or '(暂无)'}\n\n"
        f"## 输出硬规则\n{_RULES}"
    )
    user = f"## 当前对话(最后一条是对方刚发的)\n{convo}\n\n请直接给出你要发送的回复:"
    return llm.call_text(model, system, user, max_tokens=300, temperature=temperature)
