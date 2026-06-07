"""py2app 打包配置 —— 把副驾打成自包含的 AutoTalk.app。

构建:
    source .venv/bin/activate
    pip install py2app
    python setup_app.py py2app

产物:dist/AutoTalk.app(可拷走)。首次启动:右键→打开(未签名);
系统设置→隐私与安全性→屏幕录制 勾上 AutoTalk。
用户数据在 ~/Library/Application Support/AutoTalk(config.yaml / skills/memory / 截图)。
本包面向本地 ollama;若要云端 Claude,需另把 anthropic 加入 includes。
"""
import glob

from setuptools import setup

APP = ["copilot.py"]

DATA_FILES = [
    ("", ["config.example.yaml"]),
    ("skills/personas", glob.glob("skills/personas/*.md")),
]

OPTIONS = {
    "argv_emulation": False,
    "packages": ["PIL", "webview"],
    "includes": [
        "appdirs", "agent", "capture", "chat_ocr", "config", "llm",
        "memory", "persona", "vision", "snap",
        "yaml", "objc", "proxy_tools", "bottle", "typing_extensions",
        "Foundation", "AppKit", "WebKit", "Quartz", "Vision",
    ],
    "plist": {
        "CFBundleName": "AutoTalk",
        "CFBundleDisplayName": "AutoTalk",
        "CFBundleIdentifier": "local.autotalk.copilot",
        "CFBundleShortVersionString": "1.0",
        "CFBundleVersion": "1.0",
        "NSHighResolutionCapable": True,
        "LSUIElement": False,
    },
}

setup(
    app=APP,
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
