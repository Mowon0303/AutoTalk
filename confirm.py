"""弹出 macOS 原生对话框,让用户确认 / 编辑 / 跳过草稿。"""
from __future__ import annotations

import subprocess
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parent / "confirm.applescript"


def ask(incoming: str, draft: str) -> tuple[str, str]:
    """返回 (decision, text):decision 为 'send' / 'skip';text 为(可能被编辑过的)回复。"""
    context = f"对方说:\n{incoming}\n\n建议回复(可直接编辑):"
    r = subprocess.run(
        ["osascript", str(_SCRIPT), context, draft],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:  # 用户取消 / 关闭窗口
        return ("skip", "")
    out = r.stdout.strip()
    button, text = (out.split("\t", 1) + [draft])[:2] if "\t" in out else (out, draft)
    return ("send" if button == "发送" else "skip", text)
