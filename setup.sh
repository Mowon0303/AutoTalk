#!/usr/bin/env bash
# DraftMate 一键安装:建 venv + 装依赖 + 自检。可重复运行。
set -euo pipefail
cd "$(dirname "$0")"

PY=.venv/bin/python

echo "==> 1/3 创建虚拟环境 .venv"
python3 -m venv .venv
"$PY" -m pip install -q --upgrade pip

echo "==> 2/3 安装依赖"
"$PY" -m pip install -q pyyaml            # 读配置(必装)
"$PY" -m pip install -q pillow numpy      # OCR 模式(read_mode=ocr)
if [ "$(uname)" = "Darwin" ]; then
    "$PY" -m pip install -q pyobjc-framework-Vision pyobjc-framework-Quartz  # macOS 原生 OCR,轻量免下模型
    OCR_BACKEND="vision(macOS 原生)"
else
    echo "    非 macOS:跳过 vision 后端;如需 OCR 请手动: $PY -m pip install easyocr (较重)"
    OCR_BACKEND="未装(需手动)"
fi
# 云端 Claude 模式才需要(本地 ollama 不需要),需要时取消注释:
# "$PY" -m pip install -q anthropic

echo "==> 3/3 自检"
echo "    Python  : $("$PY" --version 2>&1)"
echo "    OCR 后端: ${OCR_BACKEND}"
if command -v ollama >/dev/null 2>&1; then
    echo "    ollama  : 已安装"
    if curl -s -m 2 http://localhost:11434/api/tags >/dev/null 2>&1; then
        echo "    服务    : 在线"
    else
        echo "    服务    : 未响应(用前先启动 ollama)"
    fi
    if ollama list 2>/dev/null | grep -qi "qwen2.5vl"; then
        echo "    视觉模型: qwen2.5vl 已就绪"
    else
        echo "    视觉模型: 未发现 → 运行  ollama pull qwen2.5vl:7b"
    fi
else
    echo "    ollama  : 未安装(本地模式需要) → https://ollama.com"
fi

cat <<'EOF'

✅ 安装完成。接着:
   1) 若还没有视觉模型:  ollama pull qwen2.5vl:7b
   2) 确认 config.yaml:  provider: ollama / model: qwen2.5vl:7b / read_mode: ocr
   3) 运行:
        source .venv/bin/activate
        python main.py --once       # 截图→OCR→草稿→确认框(dry_run 不真发)
        # 验证 OK 后:python main.py --send   才会真正发送(先用小号)
EOF
