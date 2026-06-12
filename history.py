"""历史导入:自动滚动当前对话 + 多屏截图 OCR 去重拼接 → 一段连续历史。

红线:这里的键鼠模拟**仅限只读导航(滚动浏览)**,绝不模拟输入文字或点击发送
(copilot-only 身份不变)。自动滚动需要「辅助功能」权限;截图沿用「屏幕录制」权限。
"""
from __future__ import annotations

import os
import re
import time

import vision

# 滚轮方向:正值=向上看更早的历史。macOS「自然滚动」开关会影响实际方向,
# 实测若反了把这个改成 -1。
SCROLL_DIR = 1


# ════════════════════ 自动滚动(M3,只读导航)════════════════════
def accessibility_ok() -> bool:
    """是否已授予「辅助功能」权限(合成鼠标/滚轮事件需要)。检测不到时放行,让实际滚动去试。"""
    for mod in ("ApplicationServices", "HIServices"):
        try:
            m = __import__(mod, fromlist=["AXIsProcessTrusted"])
            return bool(m.AXIsProcessTrusted())
        except Exception:
            continue
    return True


def activate(process_name: str) -> bool:
    """把目标 App 窗口带到前台。自动滚动要求窗口可见且在最上层,否则滚轮会落到别的窗口。
    优先 Cocoa NSRunningApplication(绕开 AppleScript;后者需 Apple Events 权限,实测常废),退路 AppleScript。"""
    pid = vision.window_pid(process_name)
    if pid:
        try:
            import AppKit
            ra = AppKit.NSRunningApplication.runningApplicationWithProcessIdentifier_(pid)
            if ra and ra.activateWithOptions_(AppKit.NSApplicationActivateIgnoringOtherApps):
                return True
        except Exception:
            pass
    names = [process_name] + [a for a in vision._ALIASES if a]
    for name in names:
        if vision._osascript(f'tell application "System Events" to set frontmost of process "{name}" to true'):
            return True
    if process_name:
        vision._osascript(f'tell application "{process_name}" to activate')
    return False


def scroll_up(process_name: str, lines: int = 8, direction: int = SCROLL_DIR) -> bool:
    """把鼠标移到目标窗口聊天区,向 direction 方向滚 lines 行。成功发出事件返回 True。"""
    bounds = vision.window_box(process_name) or vision.window_bounds(process_name)
    if not bounds:
        return False
    x, y, w, h = bounds
    cx, cy = x + int(w * 0.6), y + int(h * 0.5)   # 偏右,避开桌面版左侧会话列表
    try:
        import Quartz
    except Exception:
        return False
    Quartz.CGEventPost(
        Quartz.kCGHIDEventTap,
        Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventMouseMoved, (cx, cy), 0),
    )
    time.sleep(0.05)
    for _ in range(max(1, lines)):
        ev = Quartz.CGEventCreateScrollWheelEvent(None, Quartz.kCGScrollEventUnitLine, 1, direction)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, ev)
        time.sleep(0.04)
    return True


# ════════════════════ 去重拼接(M2)════════════════════
def _key(m: dict) -> str:
    """消息归一化指纹:发言人 + 文本去空白后前 24 字。容忍 OCR 末尾抖动。"""
    sender = (m.get("sender") or "")[:6]
    text = re.sub(r"\s+", "", m.get("text") or "")
    return sender + "|" + text[:24]


def _overlap_len(earlier: list, known: list, max_probe: int = 14) -> int:
    """earlier(更早一屏)的「后缀」与 known(已知较早段)的「前缀」最长重叠条数。
    earlier 底部应与 known 顶部是同几条消息。"""
    cap = min(len(earlier), len(known), max_probe)
    for k in range(cap, 0, -1):
        if all(_key(earlier[-k + i]) == _key(known[i]) for i in range(k)):
            return k
    return 0


def stitch(known: list, earlier: list) -> tuple[list, int]:
    """把更早的一屏 earlier 拼到 known 前面,去掉重叠。返回(新列表, 本屏新增条数)。
    known/earlier 均按时间从早到晚排列。"""
    if not earlier:
        return known, 0
    if not known:
        return list(earlier), len(earlier)
    k = _overlap_len(earlier, known)
    added = earlier if k == 0 else earlier[: len(earlier) - k]
    return added + known, len(added)


# ════════════════════ 采集编排(M3 + M2)════════════════════
def import_history(process_name: str, model: str, *, max_screens: int = 25,
                   scroll_lines: int = 8, settle: float = 0.7, on_progress=None) -> dict:
    """自动往上滚到顶并拼出完整历史。返回 {title, messages, screens, reached_top}。
    on_progress(dict) 每屏回调一次,用于 UI 进度。"""
    if not accessibility_ok():
        raise RuntimeError(
            "自动滚动需要「辅助功能」权限:系统设置→隐私与安全性→辅助功能,"
            "勾上 DraftMate(开发态勾你的终端),重开后再试。"
        )
    activate(process_name)
    time.sleep(0.3)
    known: list = []
    title = None
    no_gain = 0
    screens = 0
    direction = SCROLL_DIR
    flipped = False           # 方向自适应:先试一个方向,没采到新内容就翻转(应对「自然滚动」开关)
    for i in range(max(1, max_screens)):
        png = vision.grab(process_name)
        try:
            data = vision.read_messages(png, model, 9999)   # 大 last_n = 拿整屏全部
        finally:
            try:
                os.remove(png)
            except OSError:
                pass
        msgs = data.get("messages") or []
        title = title or data.get("chat_title")
        screens += 1
        if i == 0:
            known, added = msgs, len(msgs)
        else:
            known, added = stitch(known, msgs)
        if on_progress:
            on_progress({"screens": screens, "messages": len(known), "added": added})
        if added == 0:
            no_gain += 1
            if no_gain >= 2:
                if not flipped:           # 可能方向反了(往下滚到底了)→ 翻转再试
                    direction, flipped, no_gain = -direction, True, 0
                else:                     # 翻转后仍没新增 = 真到顶
                    return {"title": title, "messages": known, "screens": screens, "reached_top": True}
        else:
            no_gain = 0
        if not scroll_up(process_name, scroll_lines, direction):
            return {"title": title, "messages": known, "screens": screens, "reached_top": False}
        time.sleep(settle)        # 等微信渲染稳定再截下一屏
    return {"title": title, "messages": known, "screens": screens, "reached_top": False}
