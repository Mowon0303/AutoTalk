#!/usr/bin/env bash
# 生成一个可双击启动的 AutoTalk.app(启动器:双击 → 用本项目 .venv 跑 copilot.py --window 原生窗口)。
# 它是个轻量启动器(指向本机这个项目),不打包依赖;移动项目后重跑本脚本即可。
set -euo pipefail
DIR="$(cd "$(dirname "$0")" && pwd)"
APP="$DIR/AutoTalk.app"

if [ ! -x "$DIR/.venv/bin/python" ]; then
    echo "⚠️ 没找到 $DIR/.venv —— 先跑 bash setup.sh 建好环境"; exit 1
fi

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS"

cat > "$APP/Contents/Info.plist" <<'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>AutoTalk</string>
  <key>CFBundleDisplayName</key><string>AutoTalk</string>
  <key>CFBundleIdentifier</key><string>local.autotalk.copilot</string>
  <key>CFBundleVersion</key><string>1.0</string>
  <key>CFBundleExecutable</key><string>AutoTalk</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>NSHighResolutionCapable</key><true/>
</dict></plist>
PLIST

# 启动脚本(生成时把绝对路径烤进去)
cat > "$APP/Contents/MacOS/AutoTalk" <<LAUNCH
#!/bin/bash
exec "$DIR/.venv/bin/python" "$DIR/copilot.py" --window
LAUNCH
chmod +x "$APP/Contents/MacOS/AutoTalk"

echo "✅ 已生成 $APP"
echo "   双击启动(首次被 Gatekeeper 拦时:右键 → 打开)。"
echo "   首次会提示『屏幕录制』权限:在 系统设置→隐私与安全性→屏幕录制 勾上 AutoTalk。"
