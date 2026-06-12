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


# 军师层:关系阶段判定规则,蒸馏自 13 项研究的阶段判定法(L0–L5/D1/D2)。
# 原则:两类独立证据才升级、拿不准取更低一级、只引用对话里真实出现的内容。
_STAGE_RUBRIC = (
    "你是恋爱/暧昧聊天的军师,从对话证据估计当前关系阶段,再给下一步方向。八个等级:\n"
    "- L0 弱连接:只有问候/事务,无跟进、无记忆\n"
    "- L1 初步兴趣:背景问答(学校/工作/兴趣),双向但浅\n"
    "- L2 熟悉/轻度暧昧:双方都会主动、记得旧细节、有内梗、说过'改天约'类软计划\n"
    "- L3 情感亲近/强暧昧:一方分享脆弱(压力/不安/期望)且对方接住(理解·关心·跟进),并且双向\n"
    "- L4 约会/关系协商:有具体的一对一约会计划、直说浪漫意图、或谈'我们算什么'\n"
    "- L5 确定关系:明确身份/排他承诺,加上维护或修复行为\n"
    "- D1 降温:比之前明显变冷(主动变少/回复变短/回避情感话题和计划)\n"
    "- D2 风险:强烈情话叠加施压/控制/查岗/不接受拒绝\n"
    "判定规则:\n"
    "- 高于 L1 至少需要两类独立证据;拿不准就取更低一级并说还缺什么\n"
    "- 秒回和表情是弱证据;暖心支持不等于浪漫;随口的'我们'不等于承诺\n"
    "- 只引用对话里真实出现的内容,绝不脑补画面外的事\n"
    "- 对话明显不是恋爱/暧昧语境(同事/事务/家人)时,阶段行写「不适用(非恋爱语境)」,策略行照常给一句沟通建议\n"
    "输出格式(恰好三行,每行一句,不要标题不要多余文字):\n"
    "阶段: <标签+中文名>(置信度 低/中/高)\n"
    "依据: <引用 1-2 个对话片段说明为什么>\n"
    "策略: <与该阶段匹配的下一步方向,留有拒绝空间,别用力过猛;只描述方向,禁止写示例句、禁止引号台词>"
)


def assess_stage(messages, memory_text: str, model: str, last_n: int = 8,
                 manual_context: dict | None = None) -> str:
    """军师判定:估计关系阶段 + 下一步方向。低温短输出,供 UI 展示并喂给草稿生成校准火候。"""
    convo = render(messages, last_n)
    system = (
        f"{_STAGE_RUBRIC}\n\n## 关于对方的已知信息\n"
        f"{_render_manual_context(manual_context)}\n{(memory_text or '').strip()}"
    )
    user = f"## 当前对话(最后一条是对方刚发的)\n{convo}\n\n请按三行格式输出判定:"
    return llm.call_text(model, system, user, max_tokens=220, temperature=0.3)


# 历史导入:把长聊天蒸馏成记忆档案。
# 真实数据实测:7B 输入越长越容易①把口头梗当实体/以偏概全 ②归类错位(把球赛闲聊塞进'承诺待办')。
# 对策 = map-reduce:分块摘录(每块短→归类准)→ 合并归类去重;全程强制原文引用 [据:"原话"] 抑制编造。
_MAP_PROMPT = (
    "下面是一段聊天记录的**一个片段**(OCR,有噪声乱码,看不懂的行跳过)。\n"
    "逐条摘录**以后聊天用得上**的事实,每条一行,格式严格为:  [类型] 内容 [据:\"原话\"]\n"
    "类型只能用这五种:\n"
    "  画像 = 对方身份/处境/性格/喜好    雷区 = TA 明说过的不喜欢/敏感点\n"
    "  事件 = 聊过的话题或发生的事        承诺 = **明确约好将来要做的事**(如'下周一起吃饭')\n"
    "  氛围 = 这段聊天的语气\n"
    "铁律:只摘真实出现的,引用不出原话就不写;乱码不猜;不联想常识(别因聊到某游戏就补没出现的游戏名)。\n"
    "**特别注意**:球赛/游戏的评论、感叹、玩笑**都不是承诺**;别人聊的话题不等于 TA 的喜好。\n"
    "本段没有的类型就不写。只输出要点行,不要小标题、不要总结。"
)

# 单块/reduce 共用的结构化输出模板:只整理不推断。
_STRUCT_PROMPT = (
    "把下面的信息**整理**成一份联系人记忆档案。只做归类、去重、整理,"
    "**不新增推断、不联想常识**;矛盾时取有原文引用支撑的那条。\n"
    "按结构输出,某类没内容写「(无)」:\n"
    "## 关系背景\n一句话:怎么认识/现在算什么关系(没线索写'(无足够线索)')\n"
    "## 对方画像\n- 身份/处境/性格/喜好,每条带 [据:\"原话\"]\n"
    "## 雷区/边界\n- TA 明说过的不喜欢/敏感点 [据:\"原话\"]\n"
    "## 一起经历/聊过的大事\n- 具体话题或事件 [据:\"原话\"]\n"
    "## 承诺与待办\n- **只保留明确约好将来要做的事**;球赛/游戏评论、感叹、玩笑不算 [据:\"原话\"]\n"
    "## 最近氛围\n一句话"
)


def distill_memory(messages, model: str, manual_context: dict | None = None,
                   chunk_size: int = 35, on_progress=None) -> str:
    """长聊天蒸馏成记忆档案。短历史(≤chunk_size)单次蒸馏;长历史 map-reduce
    (分块摘录→合并归类),避免 7B 在长输入上归类错位/泛化。on_progress({phase,i,n}) 可选进度回调。"""
    msgs = list(messages or [])
    ctx = _render_manual_context(manual_context)
    if len(msgs) <= chunk_size:
        convo = render(msgs, len(msgs))
        user = (f"## 已知信息(辅助,别和聊天矛盾)\n{ctx}\n\n"
                f"## 聊天记录(OCR,有噪声)\n{convo}\n\n整理成档案:")
        return llm.call_text(model, _STRUCT_PROMPT, user, max_tokens=900, temperature=0.2)
    # map:分块摘录带类型标签的要点(每块输入短,归类准)
    chunks = [msgs[i:i + chunk_size] for i in range(0, len(msgs), chunk_size)]
    points = []
    for idx, c in enumerate(chunks):
        if on_progress:
            on_progress({"phase": "map", "i": idx + 1, "n": len(chunks)})
        convo = render(c, len(c))
        out = llm.call_text(model, _MAP_PROMPT,
                            f"## 片段({idx + 1}/{len(chunks)})\n{convo}\n\n摘录要点:",
                            max_tokens=600, temperature=0.2)
        if out.strip():
            points.append(out.strip())
    # reduce:把各块要点(已干净)归类去重成档案
    if on_progress:
        on_progress({"phase": "reduce", "i": len(chunks), "n": len(chunks)})
    allpoints = "\n".join(points)
    user = (f"## 已知信息(辅助,别和聊天矛盾)\n{ctx}\n\n"
            f"## 从长聊天分段摘录的要点(已带[类型]标签和原文引用)\n{allpoints}\n\n整理成档案:")
    return llm.call_text(model, _STRUCT_PROMPT, user, max_tokens=900, temperature=0.2)


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
    stage_hint: str = "",
) -> str:
    convo = render(messages, last_n)
    stage_block = (
        f"## 军师判定(按它的阶段校准火候,别越级推进;它给的是方向不是台词,禁止照抄它的措辞)\n{stage_hint}\n\n"
        if stage_hint else ""
    )
    # 人设放最前定调,硬规则压轴 —— 小模型对开头和结尾的指令最敏感
    system = (
        f"{_ROLE}\n\n## 人设(你的说话方式)\n{persona_text}\n\n"
        f"{stage_block}"
        f"## 手动上下文(优先级最高)\n{_render_manual_context(manual_context)}\n\n"
        f"## 关于该联系人的记忆\n{memory_text or '(暂无)'}\n\n"
        f"## 输出硬规则\n{_RULES}"
    )
    user = f"## 当前对话(最后一条是对方刚发的)\n{convo}\n\n请直接给出你要发送的回复:"
    return llm.call_text(model, system, user, max_tokens=300, temperature=temperature)
