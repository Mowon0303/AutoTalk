"""模型调用层:支持 Anthropic(云端)与 Ollama(本地)两种后端。"""
from __future__ import annotations

import json
import os
import urllib.request

_CONF = {"provider": "anthropic", "ollama_host": "http://localhost:11434"}


def configure(provider: str, ollama_host: str = "http://localhost:11434") -> None:
    _CONF["provider"] = (provider or "anthropic").lower()
    _CONF["ollama_host"] = ollama_host or "http://localhost:11434"


# ---------- 对外接口 ----------

def _backend(model: str) -> str:
    """按模型名路由:claude* 走 Anthropic,其余按全局 provider。
    这样 reply_model 可单独填 claude-* 让"回复生成"上云(只传对话文字),读图仍全本地。"""
    if (model or "").lower().startswith("claude"):
        return "anthropic"
    return _CONF["provider"]


def call_text(model: str, system: str, user: str, max_tokens: int = 1024,
              temperature: float = 0.7) -> str:
    """纯文本调用。"""
    if _backend(model) == "ollama":
        return _ollama_chat(model, system, user, None, max_tokens, temperature)
    return _anthropic(model, system, [{"role": "user", "content": user}], max_tokens, temperature)


def call_vision(model: str, system: str, user: str, image_b64: str, max_tokens: int = 1024,
                temperature: float = 0.2) -> str:
    """带一张图片的多模态调用。image_b64 为不带前缀的 base64 PNG。"""
    if _backend(model) == "ollama":
        return _ollama_chat(model, system, user, image_b64, max_tokens, temperature)
    content = [
        {"type": "image",
         "source": {"type": "base64", "media_type": "image/png", "data": image_b64}},
        {"type": "text", "text": user},
    ]
    return _anthropic(model, system, [{"role": "user", "content": content}], max_tokens, temperature)


# ---------- Anthropic 后端 ----------

_client = None


def _anthropic(model: str, system: str, messages, max_tokens: int, temperature: float) -> str:
    global _client
    if _client is None:
        try:
            import anthropic
        except ImportError:
            raise SystemExit(
                "缺少依赖 anthropic;或在 config.yaml 把 provider 改成 ollama。安装: pip install anthropic"
            )
        key = os.environ.get("ANTHROPIC_API_KEY")
        if not key:
            raise SystemExit(
                "未设置 ANTHROPIC_API_KEY;若想用本地模型,请在 config.yaml 设 provider: ollama"
            )
        _client = anthropic.Anthropic(api_key=key)
    # 把 system 包成可缓存块(仅 Anthropic 生效;Ollama 路径不会走到这里)
    sys_blocks = (
        [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
        if system else None
    )
    resp = _client.messages.create(
        model=model, max_tokens=max_tokens, temperature=temperature,
        system=sys_blocks, messages=messages,
    )
    return "".join(
        getattr(b, "text", "") for b in resp.content if getattr(b, "type", "") == "text"
    ).strip()


# ---------- Ollama 后端 ----------

def _ollama_chat(model: str, system: str, user: str, image_b64, max_tokens: int,
                 temperature: float) -> str:
    msgs = []
    if system:
        msgs.append({"role": "system", "content": system})
    um = {"role": "user", "content": user}
    if image_b64:
        um["images"] = [image_b64]  # Ollama 原生格式:图片放消息的 images 字段(不带 data: 前缀)
    msgs.append(um)
    payload = {
        "model": model,
        "messages": msgs,
        "stream": False,
        "options": {"num_predict": max_tokens, "temperature": temperature},
    }
    url = _CONF["ollama_host"].rstrip("/") + "/api/chat"
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception as e:
        raise SystemExit(f"调用 Ollama 失败({url}): {e}\n请确认 ollama 已启动、且模型已 pull。")
    return (data.get("message", {}).get("content") or "").strip()
