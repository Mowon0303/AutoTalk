"""把聊天截图读成结构化消息。

发言人判定不让模型直接猜"谁说的"(小视觉模型常把左右判反),而是让它只给出
每条消息的水平位置百分比 cx,再用几何规则映射:贴右=我、贴左=对方、居中=系统。
"""
from __future__ import annotations

import base64
import json
import os
import re
import tempfile
from pathlib import Path

import llm

# 读取模式:vlm(纯视觉模型,默认) 或 ocr(本地 OCR + 头像/几何判定,复用 vendored chat_ocr.py)
_MODE = {"read_mode": "vlm", "ocr_backend": "auto", "me_side": "right",
         "crop_left": 0.0, "crop_bottom": 0.0}


def configure(read_mode: str = "vlm", ocr_backend: str = "auto", me_side: str = "right",
              crop_left: float = 0.0, crop_bottom: float = 0.0) -> None:
    _MODE["read_mode"] = (read_mode or "vlm").lower()
    _MODE["ocr_backend"] = ocr_backend or "auto"
    _MODE["me_side"] = me_side or "right"
    _MODE["crop_left"] = float(crop_left or 0.0)
    _MODE["crop_bottom"] = float(crop_bottom or 0.0)


_OCR_LABEL = {"me": "我", "other": "对方", "system": "系统", "unknown": "unknown"}

_SYS = "你是解析聊天截图的助手。只输出 JSON,不要任何解释或多余文字。"


def _prompt(last_n: int) -> str:
    return f"""这是一张聊天截图。从上到下列出最近的消息(最多 {last_n} 条)。
严格只输出 JSON(不要 markdown 代码块、不要解释):
{{"chat_title": "顶部标题栏里的聊天名;看不到就填 null", "messages": [{{"text": "消息文字", "cx": 整数}}]}}

要点:
- cx = 该消息气泡(或图片)水平中心占图片总宽度的百分比,0=最左,100=最右;贴左的小、贴右的大、居中约 50。
- **不要判断谁发的**,只如实给出位置 cx。
- 图片或表情包:text 写成 "〔图片〕" 或 "〔表情〕",也要给 cx。
- 时间戳、日期、"撤回了一条消息" 等居中灰字也照常列出(cx 约 50)。"""


def _apply_crop(png_path: str):
    """裁掉左侧会话列表(crop_left)和底部输入框(crop_bottom)。返回 (使用路径, 需清理的临时路径或None)。"""
    left = _MODE.get("crop_left", 0.0)
    bottom = _MODE.get("crop_bottom", 0.0)
    if left <= 0 and bottom <= 0:
        return png_path, None
    try:
        from PIL import Image
        with Image.open(png_path) as im:
            w, h = im.size
            x0 = int(w * left) if left > 0 else 0
            y1 = int(h * (1 - bottom)) if bottom > 0 else h
            if x0 >= w or y1 <= 0:
                return png_path, None
            fd, tmp = tempfile.mkstemp(suffix=".png", prefix="draftmate_crop_")
            os.close(fd)
            im.crop((x0, 0, w, y1)).save(tmp)
            return tmp, tmp
    except Exception:
        return png_path, None


def read_messages(png_path: str, model: str, last_n: int = 8) -> dict:
    use_path, tmp = _apply_crop(png_path)
    try:
        if _MODE["read_mode"] == "ocr":
            try:
                return _read_via_ocr(use_path, last_n)
            except Exception as e:
                print(f"  [OCR 读取失败,回退到视觉模型] {e}")
        data = base64.b64encode(Path(use_path).read_bytes()).decode()
        raw = llm.call_vision(model, _SYS, _prompt(last_n), data, max_tokens=1200, temperature=0.1)
        return _parse(raw)
    finally:
        if tmp:
            try:
                os.remove(tmp)
            except OSError:
                pass


def _is_image_ph(t: str) -> bool:
    t = (t or "").strip()
    return t.startswith("〔图片〕") or t.startswith("〔表情〕")


def _y_overlap(a, b) -> bool:
    """两个 [x0,y0,x1,y1] 框是否纵向重叠。"""
    return not (a[3] < b[1] or b[3] < a[1])


def _is_ui_noise(t: str) -> bool:
    """非消息 UI 文本:"N条新消息" / "以下为新消息" / 纯符号(如 •••、···)。"""
    t = (t or "").strip()
    if not t:
        return True
    if re.fullmatch(r"\d+\s*条新消息", t) or "以下为新消息" in t:
        return True
    if not re.search(r"[A-Za-z0-9一-鿿]", t):   # 只有符号/标点,无字母数字汉字
        return True
    return False


def _extract_group_names(items: list):
    """群聊:识别"昵称小字"行并绑到后续消息;另支持"昵称:正文"前缀。
    返回 (items, is_group, title):
    - ≥2 个不同昵称 → 真群聊,应用昵称;
    - 只有 1 个且在最顶上 → 桌面版会话标题栏,当作 title 摘掉(非群聊);
    - 1v1(无此版面)→ 原样返回。"""
    if len(items) < 2:
        return items, False, None
    hs = sorted(b["box"][3] - b["box"][1] for b in items if b["box"][3] > b["box"][1])
    med_h = hs[len(hs) // 2] if hs else 24
    is_name = [False] * len(items)
    for i in range(len(items) - 1):
        a, b = items[i], items[i + 1]
        if a["sender"] != "对方" or b["sender"] != "对方":
            continue
        if (len(a["text"]) <= 12
                and (b["box"][0] - a["box"][0]) > max(8, 0.4 * med_h)   # 下一条气泡更靠右(缩进)
                and 0 <= (b["box"][1] - a["box"][3]) < 2.2 * med_h):     # 紧贴上方(同一轮)
            is_name[i] = True
    name_idx = [i for i, v in enumerate(is_name) if v]
    distinct = {items[i]["text"] for i in name_idx}
    if not name_idx:
        return items, False, None
    if len(distinct) < 2:
        # 只有一个"昵称":若就在最顶上,基本是桌面会话标题栏 → 当 title 摘掉,不算群聊
        if name_idx == [0]:
            return items[1:], False, items[0]["text"]
        return items, False, None      # 信号太弱,不当群聊也不乱改
    out, cur = [], None
    for i, it in enumerate(items):
        if is_name[i]:
            cur = it["text"]
            continue
        if it["sender"] == "对方":
            m = re.match(r"^([A-Za-z一-鿿]{1,8})[:：]\s*(.+)$", it["text"], re.DOTALL)
            if m:
                it = {**it, "sender": m.group(1), "text": m.group(2).strip()}
            elif cur:
                it = {**it, "sender": cur}
        out.append(it)
    return out, True, None


def _read_via_ocr(png_path: str, last_n: int) -> dict:
    """复用 vendored chat_ocr.py:本地 OCR + 头像/几何判定发言人(比让模型猜更稳)。"""
    import chat_ocr  # 同目录 vendored 脚本

    raw = chat_ocr.process_image(png_path, _MODE["ocr_backend"], _MODE["me_side"])
    if any((m.get("text") or "").startswith("⚠️") for m in raw):
        raise RuntimeError("OCR 未读出文字")
    _, img_h = chat_ocr.image_size(png_path)   # 截图高度,用于判定顶部标题栏

    # 顶部第一条若是居中短文本(非时间/日期)→ 当作聊天标题(手机版居中标题)
    title = None
    if raw and raw[0].get("speaker") == "system":
        t0 = (raw[0].get("text") or "").strip()
        if t0 and len(t0) <= 20 and not re.search(r"\d{1,2}:\d{2}|\d{4}|[年月日]", t0):
            title = t0
            raw = raw[1:]

    items = []
    for m in raw:
        t = (m.get("text") or "").strip()
        if not t or _is_ui_noise(t):
            continue
        items.append({
            "sender": _OCR_LABEL.get(m.get("speaker"), "unknown"),
            "text": t,
            "box": m.get("bbox") or [0, 0, 0, 0],
            "ocr": float(m.get("ocr_confidence", 1.0)),
        })

    # 桌面整窗截图(crop_left>0):最顶上、落在顶部 header 带内的短文本(非时间)= 会话名
    if not title and _MODE.get("crop_left", 0) > 0 and items:
        f = items[0]
        if (len(f["text"]) <= 20
                and not re.search(r"\d{1,2}:\d{2}|\d{4}|[年月日]", f["text"])
                and f["box"][1] < img_h * 0.15):
            title = f["text"]
            items = items[1:]

    # 群聊:识别昵称行并绑定发言人(1v1/桌面标题已先摘出,无影响)
    items, is_group, gtitle = _extract_group_names(items)
    if gtitle and not title:
        title = gtitle

    # 图片占位符 + 同发言人且纵向重叠的文字(表情包/截图上的字)→ 合并成一条
    merged: list[dict] = []
    for it in items:
        if merged:
            prev = merged[-1]
            if (prev["sender"] == it["sender"]
                    and (_is_image_ph(prev["text"]) ^ _is_image_ph(it["text"]))
                    and _y_overlap(prev["box"], it["box"])):
                img, txt = (prev, it) if _is_image_ph(prev["text"]) else (it, prev)
                ph = img["text"].split("〕", 1)[0] + "〕"   # 〔图片〕 / 〔表情〕
                prev["text"] = ph + txt["text"]
                prev["box"] = [min(prev["box"][0], it["box"][0]), min(prev["box"][1], it["box"][1]),
                               max(prev["box"][2], it["box"][2]), max(prev["box"][3], it["box"][3])]
                continue
        merged.append(dict(it))

    out = []
    for it in merged:
        # 短文本 + OCR 极不确定、且非图片占位 → 多为头像/图标误读(如 "6只""8~"),丢弃
        if len(it["text"]) <= 4 and it.get("ocr", 1.0) < 0.4 and not _is_image_ph(it["text"]):
            continue
        out.append({"sender": it["sender"], "text": it["text"]})
    return {"chat_title": title, "is_group": is_group, "messages": out[-last_n:]}


def _sender_from_cx(cx) -> str:
    """几何规则:贴右=我,贴左=对方,居中=系统;无法解析=unknown。"""
    if isinstance(cx, str):
        m = re.search(r"-?\d+(?:\.\d+)?", cx)
        cx = m.group(0) if m else None
    try:
        v = float(cx)
    except (TypeError, ValueError):
        return "unknown"
    if v >= 60:
        return "我"
    if v <= 40:
        return "对方"
    return "系统"


def _empty() -> dict:
    return {"chat_title": None, "is_group": False, "messages": []}


def _parse(raw: str) -> dict:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if not m:
            return _empty()
        try:
            obj = json.loads(m.group(0))
        except json.JSONDecodeError:
            return _empty()
    if not isinstance(obj, dict):
        return _empty()

    out = []
    for m in obj.get("messages", []) or []:
        if not isinstance(m, dict):
            continue
        t = (m.get("text") or "").strip()
        if not t:
            continue
        item = {"sender": _sender_from_cx(m.get("cx")), "text": t}
        if not (out and out[-1] == item):  # 去掉相邻完全重复
            out.append(item)
    return {
        "chat_title": obj.get("chat_title") or None,
        "is_group": bool(obj.get("is_group", False)),
        "messages": out,
    }
