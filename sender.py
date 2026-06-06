"""把回复发到微信:剪贴板粘贴 + 回车。dry_run 下只打印不发送。"""
from __future__ import annotations

import subprocess


def _pbcopy(text: str) -> None:
    subprocess.run(["pbcopy"], input=text.encode("utf-8"), check=False)


def send(text: str, app_name: str = "WeChat", dry_run: bool = True, send_with: str = "enter") -> None:
    text = (text or "").strip()
    if not text:
        return
    if dry_run:
        print(f"  [DRY_RUN] 未实际发送,内容预览:\n    {text}")
        return
    _pbcopy(text)
    enter = "key code 36 using command down" if send_with == "cmd_enter" else "key code 36"
    script = f'''
    tell application "{app_name}" to activate
    delay 0.4
    tell application "System Events"
        keystroke "v" using command down
        delay 0.2
        {enter}
    end tell
    '''
    subprocess.run(["osascript", "-e", script], check=False)
    print(f"  [已发送] {text}")
