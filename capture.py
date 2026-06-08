"""屏幕截图与窗口定位(macOS)。"""
from __future__ import annotations

import hashlib
import os
import subprocess
import tempfile
from pathlib import Path


def _osascript(script: str) -> str:
    r = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


def window_bounds(process_name: str):
    """返回聊天软件主窗口的 (x, y, w, h);拿不到时返回 None(改为全屏截图)。"""
    script = f'''
    set _info to ""
    tell application "System Events"
        if exists process "{process_name}" then
            tell process "{process_name}"
                set _p to position of window 1
                set _s to size of window 1
                set _info to ((item 1 of _p) as string) & "," & ((item 2 of _p) as string) & "," & ((item 1 of _s) as string) & "," & ((item 2 of _s) as string)
            end tell
        end if
    end tell
    return _info
    '''
    out = _osascript(script)
    if "," not in out:
        return None
    try:
        x, y, w, h = (int(v) for v in out.split(","))
    except ValueError:
        return None
    if w <= 0 or h <= 0:
        return None
    return (x, y, w, h)


_ALIASES = []   # 目标应用的窗口属主名别名(本地化名等),由 configure() 从配置注入


def configure(aliases=None) -> None:
    global _ALIASES
    _ALIASES = [str(a).lower() for a in (aliases or []) if a]


def _is_target_owner(owner, process_name: str) -> bool:
    o = (owner or "").lower()
    if not o:
        return False
    cands = ([process_name.lower()] if process_name else []) + _ALIASES
    return any(c and (o == c or c in o) for c in cands)


def window_id(process_name: str):
    """用 Quartz 找目标应用主窗口的 CGWindowID(按窗口抓取,被遮挡也只截它自己)。
    注意:有些应用窗口 owner 名是本地化名,不一定等于进程名,可在配置 app_aliases 里补。"""
    try:
        import Quartz
    except Exception:
        return None
    # 先 OnScreenOnly(最适合截图);权限/沙箱拿不到时退到 All
    for opt in (Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGWindowListOptionAll):
        wins = Quartz.CGWindowListCopyWindowInfo(opt, Quartz.kCGNullWindowID) or []
        best_id, best_area = None, 0.0
        for w in wins:
            if not _is_target_owner(w.get("kCGWindowOwnerName"), process_name):
                continue
            if w.get("kCGWindowLayer", 0) != 0:        # 只要普通窗口层(排除菜单/悬浮层)
                continue
            b = w.get("kCGWindowBounds", {})
            area = float(b.get("Width", 0)) * float(b.get("Height", 0))
            if area > best_area:
                best_area, best_id = area, int(w.get("kCGWindowNumber", 0))
        if best_id:
            return best_id
    return None


def list_window_owners() -> list:
    """列出当前所有窗口的 owner 名(诊断用:确认聊天软件到底叫什么)。"""
    try:
        import Quartz
    except Exception:
        return []
    wins = Quartz.CGWindowListCopyWindowInfo(Quartz.kCGWindowListOptionAll, Quartz.kCGNullWindowID) or []
    return sorted({(w.get("kCGWindowOwnerName") or "?") for w in wins})


def grab(process_name: str) -> str:
    """截图(只截聊天软件窗口本身,即使被别的窗口挡住),返回临时 png 路径。调用方负责删除。"""
    fd, path = tempfile.mkstemp(suffix=".png", prefix="draftmate_")
    os.close(fd)
    wid = window_id(process_name)
    if wid:
        # -l 按窗口 ID 抓该窗口自身内容(不受遮挡影响);-o 去掉窗口阴影
        subprocess.run(["screencapture", "-x", "-o", "-l", str(wid), path], check=False)
    else:
        bounds = window_bounds(process_name)
        if bounds:
            x, y, w, h = bounds
            subprocess.run(["screencapture", "-x", "-R", f"{x},{y},{w},{h}", path], check=False)
        else:
            subprocess.run(["screencapture", "-x", path], check=False)
    # 截图无效(没权限时 screencapture 会失败/产出空文件)→ 明确报错,别把空图喂给模型
    if not os.path.exists(path) or os.path.getsize(path) < 1024:
        try:
            os.remove(path)
        except OSError:
            pass
        raise RuntimeError(
            "截图失败:多半是终端没有「屏幕录制」权限。"
            "去 系统设置→隐私与安全性→屏幕录制 勾上你的终端,重启终端后再试。"
        )
    return path


def file_hash(path: str) -> str:
    return hashlib.sha1(Path(path).read_bytes()).hexdigest()
