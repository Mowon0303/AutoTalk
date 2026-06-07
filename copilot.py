"""AutoTalk 副驾(本地网页 UI)。

看截图 + 旁边给几条建议回复,点「复制」自己粘贴 —— 全程只读屏 + 剪贴板,
不模拟键鼠、不自动发送,把封号风险降到最低。

运行: source .venv/bin/activate && python copilot.py
然后浏览器打开 http://127.0.0.1:8765(会自动弹)。点「读取当前对话」即可。
仅监听本机 127.0.0.1,不对外暴露。
"""
from __future__ import annotations

import base64
import json
import os
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

import agent
import capture
import config
import llm
import memory
import persona
import vision

HOST, PORT = "127.0.0.1", 8765

cfg = config.load()
llm.configure(cfg.get("provider", "anthropic"), cfg.get("ollama_host", "http://localhost:11434"))
vision.configure(cfg.get("read_mode", "vlm"), cfg.get("ocr_backend", "auto"),
                 cfg.get("me_side", "right"), cfg.get("crop_left", 0.0), cfg.get("crop_bottom", 0.0))
capture.configure(cfg.get("app_aliases", []))


def _suggest_personas(title: str) -> list[str]:
    """给哪几种语气出建议:该联系人绑定的(或默认)+ casual + flirty,去重取前 3。"""
    bound = (cfg.get("contacts") or {}).get(title) or cfg.get("default_persona", "serious")
    out = []
    for name in [bound, "casual", "flirty", "serious"]:
        if name and name not in out and os.path.exists(os.path.join(persona.PERSONA_DIR, f"{name}.md")):
            out.append(name)
    return out[:3]


def read_and_suggest() -> dict:
    """截图 → 读取 → 生成多条建议。返回给前端的数据。"""
    png = capture.grab(cfg["app_name"])  # 失败会抛(权限/没装后端)
    try:
        view, tmp = vision._apply_crop(png)
        img_b64 = base64.b64encode(open(view, "rb").read()).decode()
        data = vision.read_messages(png, cfg["vision_model"], cfg["read_last_n"])
    finally:
        for p in {png, locals().get("tmp")}:
            if p:
                try:
                    os.remove(p)
                except OSError:
                    pass

    title = data.get("chat_title") or "unknown"
    msgs = data.get("messages") or []
    mem = memory.load(title)
    suggestions = []
    if msgs and msgs[-1].get("sender") not in ("我", "系统", "unknown"):
        for name in _suggest_personas(title):
            try:
                text = agent.draft_reply(msgs, persona.load(name), mem,
                                         cfg["reply_model"], cfg["read_last_n"])
            except Exception as e:
                text = f"(生成失败: {e})"
            suggestions.append({"persona": name, "text": text})
    return {
        "image": img_b64,
        "title": title,
        "is_group": bool(data.get("is_group")),
        "messages": msgs,
        "suggestions": suggestions,
        "note": "" if suggestions else "最后一条不是对方发的(或没读到对方消息),不出建议。",
    }


PAGE = """<!doctype html><html lang="zh"><head><meta charset="utf-8">
<title>AutoTalk 副驾</title>
<style>
  body{margin:0;font:14px/1.5 -apple-system,system-ui,sans-serif;background:#1e1f22;color:#e6e6e6}
  header{padding:10px 16px;background:#2b2d31;display:flex;align-items:center;gap:12px;position:sticky;top:0}
  header b{font-size:15px}
  #status{color:#9aa0a6;font-size:12px}
  button{background:#5865f2;color:#fff;border:0;border-radius:8px;padding:8px 14px;cursor:pointer;font-size:14px}
  button:hover{filter:brightness(1.1)} button:disabled{opacity:.5;cursor:default}
  .wrap{display:flex;gap:16px;padding:16px;align-items:flex-start}
  .col{flex:1;min-width:0}
  #shot{max-width:100%;border-radius:10px;border:1px solid #3a3c40;background:#111}
  .meta{color:#9aa0a6;font-size:12px;margin:4px 0 10px}
  .msg{padding:6px 10px;border-radius:8px;margin:4px 0;max-width:90%;white-space:pre-wrap;word-break:break-word}
  .me{background:#2f6f3e;margin-left:auto;text-align:right}
  .other{background:#33363c}
  .sys{color:#80848e;font-size:12px;text-align:center;background:none}
  .card{background:#2b2d31;border:1px solid #3a3c40;border-radius:10px;padding:12px;margin:10px 0}
  .card .tone{color:#9aa0a6;font-size:12px;margin-bottom:6px}
  .card .txt{font-size:15px;white-space:pre-wrap;word-break:break-word}
  .copy{margin-top:8px;background:#3a3c40}
  h3{margin:6px 0;font-size:13px;color:#9aa0a6;font-weight:600}
</style></head><body>
<header>
  <b>💬 AutoTalk 副驾</b>
  <button id="go" onclick="load()">🔄 读取当前对话</button>
  <span id="status">点上面按钮读取(只读屏 · 不自动发送)</span>
</header>
<div class="wrap">
  <div class="col"><h3>截图(实际分析区域)</h3><img id="shot" alt="(还没读取)"></div>
  <div class="col">
    <h3 id="title">对话</h3><div class="meta" id="meta"></div>
    <div id="msgs"></div>
    <h3>建议回复(点复制,自己粘贴)</h3>
    <div id="sugs"></div>
  </div>
</div>
<script>
function esc(s){return (s||"").replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]))}
async function load(){
  const btn=document.getElementById('go'); btn.disabled=true;
  document.getElementById('status').textContent='读取+生成中…(本地模型可能要几秒)';
  try{
    const r=await fetch('/api/read'); const d=await r.json();
    if(d.error){document.getElementById('status').textContent='出错: '+d.error; btn.disabled=false; return;}
    document.getElementById('shot').src='data:image/png;base64,'+d.image;
    document.getElementById('title').textContent=(d.is_group?'[群] ':'')+(d.title||'对话');
    document.getElementById('meta').textContent=d.messages.length+' 条消息';
    document.getElementById('msgs').innerHTML=d.messages.map(m=>{
      const cls=m.sender==='我'?'me':(m.sender==='系统'?'sys':'other');
      const who=(m.sender==='我'||m.sender==='系统')?'':esc(m.sender)+': ';
      return '<div class="msg '+cls+'">'+who+esc(m.text)+'</div>';
    }).join('');
    const sugs=document.getElementById('sugs');
    if(!d.suggestions.length){sugs.innerHTML='<div class="meta">'+esc(d.note||'无建议')+'</div>';}
    else{sugs.innerHTML=d.suggestions.map((s,i)=>
      '<div class="card"><div class="tone">'+esc(s.persona)+'</div>'+
      '<div class="txt" id="t'+i+'">'+esc(s.text)+'</div>'+
      '<button class="copy" onclick="cp('+i+',this)">复制</button></div>').join('');}
    document.getElementById('status').textContent='读取完成 '+new Date().toLocaleTimeString();
  }catch(e){document.getElementById('status').textContent='请求失败: '+e;}
  btn.disabled=false;
}
function cp(i,b){const t=document.getElementById('t'+i).textContent;
  navigator.clipboard.writeText(t).then(()=>{b.textContent='已复制 ✓';setTimeout(()=>b.textContent='复制',1500);});}
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # 静音访问日志
        pass

    def _send(self, code, ctype, body: bytes):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/":
            self._send(200, "text/html; charset=utf-8", PAGE.encode("utf-8"))
        elif self.path == "/api/read":
            try:
                payload = read_and_suggest()
            except Exception as e:
                payload = {"error": str(e)}
            self._send(200, "application/json; charset=utf-8",
                       json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        else:
            self._send(404, "text/plain", b"not found")


def main() -> None:
    url = f"http://{HOST}:{PORT}"
    print(f"AutoTalk 副驾 → {url}(只读屏 + 复制,不自动发送)。Ctrl+C 退出。")
    threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    HTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
