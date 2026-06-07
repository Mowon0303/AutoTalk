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


def _public_status() -> dict:
    """Return non-secret runtime facts for the local UI."""
    return {
        "app_name": cfg.get("app_name") or "未配置",
        "provider": cfg.get("provider", ""),
        "read_mode": cfg.get("read_mode", ""),
        "ocr_backend": cfg.get("ocr_backend", ""),
        "vision_model": cfg.get("vision_model", ""),
        "reply_model": cfg.get("reply_model", ""),
        "default_persona": cfg.get("default_persona", ""),
        "read_last_n": cfg.get("read_last_n", 0),
        "copy_only": True,
    }


def _error_text(exc: BaseException) -> str:
    code = getattr(exc, "code", None)
    if code not in (None, 0):
        return str(code)
    text = str(exc)
    return text or exc.__class__.__name__


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
    profile_was_missing = not memory.profile_exists(title)
    mem = memory.load(title)
    manual = memory.manual_context(title)
    suggestions = []
    if msgs and msgs[-1].get("sender") not in ("我", "系统", "unknown"):
        for name in _suggest_personas(title):
            try:
                text = agent.draft_reply(msgs, persona.load(name), mem,
                                         cfg["reply_model"], cfg["read_last_n"], manual)
            except SystemExit as e:
                text = f"(生成失败: {_error_text(e)})"
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
        "status": _public_status(),
        "profile": {
            "title": title,
            "manual": manual,
            "needs_input": profile_was_missing or not memory.has_manual_context(manual),
        },
    }


def regenerate_one(title: str, persona_name: str, messages: list) -> str:
    """对已显示的对话,用指定人设重新生成一条建议(复用已读消息,不重新截图)。"""
    mem = memory.load(title)
    manual = memory.manual_context(title)
    name = persona_name or cfg.get("default_persona", "serious")
    return agent.draft_reply(messages, persona.load(name), mem,
                             cfg["reply_model"], cfg["read_last_n"], manual)


PAGE = """<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AutoTalk Copilot</title>
<style>
  :root{
    --bg:#f4f7f9;
    --panel:#ffffff;
    --panel-soft:#f9fbfc;
    --ink:#18232c;
    --muted:#647385;
    --faint:#8a96a6;
    --line:#dbe3ea;
    --line-strong:#c5d1db;
    --accent:#126c73;
    --accent-ink:#ffffff;
    --accent-soft:#dff4f1;
    --warm:#b85c38;
    --warm-soft:#fff0e8;
    --ok:#2d7a46;
    --me:#dff5e9;
    --other:#eef2f6;
    --system:#fff5d8;
    --shadow:0 18px 45px rgba(24,35,44,.08);
  }
  *{box-sizing:border-box}
  html,body{height:100%}
  body{
    margin:0;
    font:14px/1.5 -apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI",sans-serif;
    color:var(--ink);
    background:
      linear-gradient(180deg,#ffffff 0,#f4f7f9 48%,#eef3f6 100%);
  }
  button,input{font:inherit}
  button{
    border:0;
    border-radius:8px;
    cursor:pointer;
    transition:transform .12s ease,box-shadow .12s ease,background .12s ease,opacity .12s ease;
  }
  button:hover{transform:translateY(-1px)}
  button:active{transform:translateY(0)}
  button:disabled{cursor:default;opacity:.58;transform:none}
  .app{min-height:100%;display:grid;grid-template-rows:auto minmax(0,1fr)}
  .topbar{
    display:flex;
    align-items:center;
    justify-content:space-between;
    gap:16px;
    padding:14px 18px;
    background:rgba(255,255,255,.9);
    border-bottom:1px solid var(--line);
    backdrop-filter:saturate(1.3) blur(18px);
    position:sticky;
    top:0;
    z-index:5;
  }
  .brand{display:flex;align-items:center;gap:12px;min-width:0}
  .brand-mark{
    width:34px;height:34px;border-radius:8px;
    display:grid;place-items:center;
    color:#fff;background:linear-gradient(135deg,#126c73,#243b53);
    font-weight:800;letter-spacing:0;
    box-shadow:0 10px 22px rgba(18,108,115,.25);
  }
  .brand h1{margin:0;font-size:16px;line-height:1.15;letter-spacing:0}
  .brand .sub{margin-top:2px;color:var(--muted);font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:52vw}
  .top-actions{display:flex;align-items:center;gap:10px;flex-wrap:wrap;justify-content:flex-end}
  .pill-row{display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end}
  .pill{
    display:inline-flex;align-items:center;gap:6px;
    min-height:28px;padding:4px 9px;border-radius:999px;
    background:var(--panel-soft);border:1px solid var(--line);
    color:var(--muted);font-size:12px;white-space:nowrap;
  }
  .pill strong{color:var(--ink);font-weight:650}
  .primary{
    display:inline-flex;align-items:center;gap:8px;
    min-height:36px;padding:8px 14px;
    color:var(--accent-ink);background:var(--accent);
    box-shadow:0 10px 20px rgba(18,108,115,.2);
    font-weight:650;
  }
  .primary .spin{display:none;width:13px;height:13px;border:2px solid rgba(255,255,255,.45);border-top-color:#fff;border-radius:50%}
  .primary.loading .spin{display:block;animation:spin .72s linear infinite}
  @keyframes spin{to{transform:rotate(360deg)}}
  .workspace{
    min-height:0;
    display:grid;
    grid-template-columns:minmax(420px,1.12fr) minmax(360px,.88fr);
    gap:16px;
    padding:16px;
  }
  .panel{
    min-width:0;
    min-height:0;
    background:rgba(255,255,255,.9);
    border:1px solid var(--line);
    border-radius:8px;
    box-shadow:var(--shadow);
    overflow:hidden;
  }
  .panel-head{
    display:flex;align-items:center;justify-content:space-between;gap:12px;
    min-height:52px;padding:12px 14px;border-bottom:1px solid var(--line);
    background:linear-gradient(180deg,#fff,#fbfcfd);
  }
  .panel-title{min-width:0}
  .panel-title h2{margin:0;font-size:13px;line-height:1.2;letter-spacing:0;color:#2b3946}
  .meta{color:var(--muted);font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .preview{display:grid;grid-template-rows:auto minmax(0,1fr)}
  .preview-stage{
    min-height:0;height:calc(100vh - 154px);
    background:
      linear-gradient(135deg,rgba(18,108,115,.08),transparent 32%),
      #1f2830;
    display:grid;
    place-items:center;
    padding:14px;
    position:relative;
  }
  #shot{
    display:none;
    width:100%;
    height:100%;
    object-fit:contain;
    border-radius:6px;
    background:#111820;
    border:1px solid rgba(255,255,255,.12);
    box-shadow:0 16px 38px rgba(0,0,0,.26);
  }
  .empty-preview{
    width:min(520px,86%);
    aspect-ratio:4/3;
    border:1px solid rgba(255,255,255,.16);
    border-radius:8px;
    background:
      linear-gradient(90deg,rgba(255,255,255,.09) 0 18%,transparent 18% 100%),
      linear-gradient(180deg,rgba(255,255,255,.08),rgba(255,255,255,.03));
    display:grid;
    grid-template-columns:31% 1fr;
    overflow:hidden;
  }
  .mock-list{border-right:1px solid rgba(255,255,255,.12);padding:16px 12px}
  .mock-chat{padding:26px 20px;display:flex;flex-direction:column;gap:12px}
  .skel{height:10px;border-radius:999px;background:rgba(255,255,255,.14);margin-bottom:12px}
  .skel.short{width:55%}.skel.mid{width:74%}.skel.long{width:92%}
  .empty-copy{position:absolute;left:24px;bottom:20px;color:rgba(255,255,255,.72);font-size:12px}
  .inspector{
    display:grid;
    grid-template-rows:auto auto auto minmax(0,1fr);
    min-height:0;
  }
  .summary{
    display:grid;
    grid-template-columns:1fr auto;
    gap:10px;
    padding:12px 14px;
    border-bottom:1px solid var(--line);
    background:var(--panel-soft);
  }
  .chat-title{font-size:18px;font-weight:750;letter-spacing:0;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
  .badge{
    align-self:start;
    padding:4px 8px;
    border-radius:999px;
    color:var(--warm);
    background:var(--warm-soft);
    border:1px solid #ffd8c7;
    font-size:12px;
    white-space:nowrap;
  }
  .statusline{
    padding:8px 14px;
    min-height:35px;
    display:flex;
    align-items:center;
    gap:8px;
    color:var(--muted);
    border-bottom:1px solid var(--line);
    background:#fff;
    font-size:12px;
  }
  .dot{width:7px;height:7px;border-radius:50%;background:var(--faint);flex:0 0 auto}
  .dot.ok{background:var(--ok)}.dot.busy{background:var(--warm)}
  .context-panel{
    padding:12px 14px;
    border-bottom:1px solid var(--line);
    background:#fbfcfd;
  }
  .context-head{
    display:flex;
    align-items:center;
    justify-content:space-between;
    gap:10px;
    margin-bottom:10px;
  }
  .context-head strong{font-size:12px;color:#2b3946}
  .context-state{font-size:12px;color:var(--muted);white-space:nowrap}
  .context-state.need{color:var(--warm);font-weight:700}
  .context-grid{display:grid;grid-template-columns:1fr 1fr;gap:9px}
  .context-field.full{grid-column:1 / -1}
  .context-field label{
    display:block;
    color:var(--muted);
    font-size:12px;
    font-weight:650;
    margin-bottom:5px;
  }
  .context-field textarea{
    width:100%;
    min-height:58px;
    resize:vertical;
    border:1px solid var(--line-strong);
    border-radius:8px;
    background:#fff;
    color:var(--ink);
    padding:8px 9px;
    outline:none;
  }
  .context-field textarea:focus{
    border-color:var(--accent);
    box-shadow:0 0 0 3px rgba(18,108,115,.12);
  }
  .context-actions{display:flex;align-items:center;gap:8px;margin-top:9px}
  .secondary{
    min-height:32px;
    padding:6px 10px;
    color:#24313c;
    background:#fff;
    border:1px solid var(--line-strong);
    font-weight:650;
  }
  .save-note{color:var(--muted);font-size:12px}
  .content{
    min-height:0;
    display:grid;
    grid-template-rows:minmax(0,1fr) auto;
  }
  .messages{
    min-height:190px;
    overflow:auto;
    padding:14px;
    display:flex;
    flex-direction:column;
    gap:9px;
  }
  .message-row{display:flex;align-items:flex-end;gap:8px}
  .message-row.me{justify-content:flex-end}
  .message-row.system{justify-content:center}
  .sender{
    color:var(--muted);
    font-size:12px;
    max-width:86px;
    overflow:hidden;
    text-overflow:ellipsis;
    white-space:nowrap;
    flex:0 1 auto;
  }
  .bubble{
    max-width:min(78%,560px);
    padding:9px 11px;
    border-radius:8px;
    border:1px solid transparent;
    white-space:pre-wrap;
    word-break:break-word;
    overflow-wrap:anywhere;
    color:#202b34;
  }
  .message-row.other .bubble{background:var(--other);border-color:#e2e8ef}
  .message-row.me .bubble{background:var(--me);border-color:#c3ead7}
  .message-row.system .bubble{
    max-width:92%;
    background:var(--system);
    border-color:#f0dfaa;
    color:#776333;
    font-size:12px;
    text-align:center;
  }
  .suggestions{
    border-top:1px solid var(--line);
    background:linear-gradient(180deg,#fbfcfd,#fff);
    padding:12px 14px 14px;
  }
  .section-label{
    display:flex;align-items:center;justify-content:space-between;gap:8px;
    color:#2b3946;font-size:12px;font-weight:750;letter-spacing:0;margin-bottom:10px;
  }
  .suggestion-list{display:grid;gap:9px}
  .suggestion{
    border:1px solid var(--line);
    border-radius:8px;
    background:#fff;
    padding:11px;
  }
  .suggestion-top{
    display:flex;align-items:center;justify-content:space-between;gap:10px;margin-bottom:8px;
  }
  .tone{font-size:12px;color:var(--muted);font-weight:700}
  .copy{
    min-width:34px;min-height:30px;
    padding:6px 9px;
    border:1px solid var(--line-strong);
    background:#f8fafb;
    color:#24313c;
    font-weight:650;
  }
  .copy.copied{color:#fff;background:var(--ok);border-color:var(--ok)}
  .suggestion-text{
    width:100%;
    min-height:50px;
    resize:vertical;
    border:1px solid transparent;
    border-radius:6px;
    background:#fdfefe;
    color:#202b34;
    font:inherit;
    font-size:15px;
    line-height:1.58;
    padding:7px 9px;
    outline:none;
  }
  .suggestion:hover .suggestion-text{border-color:var(--line)}
  .suggestion-text:focus{border-color:var(--accent);box-shadow:0 0 0 3px rgba(18,108,115,.10);background:#fff}
  .suggestion-actions{display:flex;gap:6px}
  .regen{
    min-width:34px;min-height:30px;padding:6px 9px;
    border:1px solid var(--line-strong);background:#f8fafb;color:#24313c;font-weight:650;
  }
  .regen:disabled{opacity:.55}
  .goal-presets{display:flex;flex-wrap:wrap;gap:6px;margin-top:6px}
  .preset{
    padding:4px 9px;border-radius:999px;
    border:1px solid var(--line-strong);background:#f8fafb;color:#24313c;font-size:12px;
  }
  .preset:hover{background:var(--accent-soft);border-color:var(--accent)}
  .empty-state{
    min-height:120px;
    display:grid;
    place-items:center;
    color:var(--muted);
    text-align:center;
    border:1px dashed var(--line-strong);
    border-radius:8px;
    background:#fbfcfd;
    padding:18px;
  }
  .error{
    display:none;
    margin:0 14px 12px;
    padding:10px 12px;
    border:1px solid #f1b8a1;
    border-radius:8px;
    background:#fff0e8;
    color:#7e351e;
    word-break:break-word;
  }
  @media (max-width:980px){
    .topbar{align-items:flex-start;flex-direction:column}
    .top-actions{width:100%;justify-content:space-between}
    .pill-row{justify-content:flex-start}
    .workspace{grid-template-columns:1fr}
    .preview-stage{height:min(62vh,620px)}
  }
  @media (max-width:620px){
    .workspace{padding:10px;gap:10px}
    .topbar{padding:12px}
    .top-actions{align-items:stretch;flex-direction:column}
    .primary{justify-content:center;width:100%}
    .pill-row{display:grid;grid-template-columns:1fr 1fr}
    .pill{justify-content:center;min-width:0}
    .summary{grid-template-columns:1fr}
    .context-grid{grid-template-columns:1fr}
    .context-field.full{grid-column:auto}
    .context-actions{align-items:stretch;flex-direction:column}
    .secondary{width:100%}
    .bubble{max-width:88%}
  }
</style>
</head>
<body>
<main class="app">
  <header class="topbar">
    <div class="brand">
      <div class="brand-mark">AT</div>
      <div>
        <h1>AutoTalk Copilot</h1>
        <div class="sub" id="appSub">副驾工作台</div>
      </div>
    </div>
    <div class="top-actions">
      <div class="pill-row" id="runtimePills">
        <span class="pill">目标 <strong>读取中</strong></span>
        <span class="pill">模式 <strong>读取中</strong></span>
        <span class="pill">输出 <strong>复制</strong></span>
      </div>
      <button class="primary" id="readBtn" onclick="readNow()"><span class="spin"></span><span id="readLabel">读取</span></button>
    </div>
  </header>
  <section class="workspace">
    <section class="panel preview">
      <div class="panel-head">
        <div class="panel-title">
          <h2>分析区域</h2>
          <div class="meta" id="shotMeta">等待读取</div>
        </div>
        <div class="meta" id="imageState">未载入</div>
      </div>
      <div class="preview-stage">
        <img id="shot" alt="">
        <div class="empty-preview" id="emptyPreview">
          <div class="mock-list">
            <div class="skel long"></div><div class="skel mid"></div><div class="skel short"></div>
            <div class="skel long"></div><div class="skel mid"></div>
          </div>
          <div class="mock-chat">
            <div class="skel mid"></div><div class="skel long"></div><div class="skel short"></div>
            <div class="skel long"></div><div class="skel mid"></div>
          </div>
        </div>
        <div class="empty-copy" id="previewHint">No capture loaded</div>
      </div>
    </section>
    <section class="panel inspector">
      <div class="summary">
        <div>
          <div class="chat-title" id="chatTitle">当前对话</div>
          <div class="meta" id="chatMeta">0 条消息</div>
        </div>
        <div class="badge" id="groupBadge">1v1</div>
      </div>
      <div class="statusline"><span class="dot" id="statusDot"></span><span id="statusText">就绪</span></div>
      <div class="context-panel">
        <div class="context-head">
          <strong>给 agent 的上下文</strong>
          <span class="context-state" id="contextState">先读取对话</span>
        </div>
        <div class="context-grid">
          <div class="context-field">
            <label for="personInfo">对方信息</label>
            <textarea id="personInfo" placeholder="例如: 刚加的租房中介 / USC 同学 / 朋友介绍的人"></textarea>
          </div>
          <div class="context-field">
            <label for="replyIntent">目标(阶段性)</label>
            <textarea id="replyIntent" placeholder="例如: 从认识推进到暧昧 / 约对方出来 / 维持朋友别越界"></textarea>
            <div class="goal-presets">
              <button type="button" class="preset" onclick="setGoal('从认识慢慢推进到暧昧')">认识→暧昧</button>
              <button type="button" class="preset" onclick="setGoal('找个自然的由头约对方出来')">约出来</button>
              <button type="button" class="preset" onclick="setGoal('推进到确定关系')">确定关系</button>
              <button type="button" class="preset" onclick="setGoal('维持朋友关系,别越界')">维持朋友</button>
            </div>
          </div>
          <div class="context-field">
            <label for="replyAvoid">不要提/边界</label>
            <textarea id="replyAvoid" placeholder="例如: 不要透露太多个人信息 / 不要暧昧"></textarea>
          </div>
          <div class="context-field">
            <label for="contextNotes">备注</label>
            <textarea id="contextNotes" placeholder="例如: 语气自然一点,先确认对方能不能帮忙"></textarea>
          </div>
        </div>
        <div class="context-actions">
          <button class="secondary" id="saveContextBtn" onclick="saveContext()">保存上下文</button>
          <button class="secondary" id="saveReadBtn" onclick="saveContext(true)">保存并重生</button>
          <span class="save-note" id="saveNote"></span>
        </div>
      </div>
      <div class="content">
        <div class="messages" id="messages">
          <div class="empty-state">等待对话内容</div>
        </div>
        <div>
          <div class="error" id="errorBox"></div>
          <div class="suggestions">
            <div class="section-label">
              <span>建议回复</span>
              <span class="meta" id="suggestionMeta">0 条</span>
            </div>
            <div class="suggestion-list" id="suggestions">
              <div class="empty-state">等待生成</div>
            </div>
          </div>
        </div>
      </div>
    </section>
  </section>
</main>
<script>
const els={
  readBtn:document.getElementById('readBtn'),
  readLabel:document.getElementById('readLabel'),
  runtimePills:document.getElementById('runtimePills'),
  appSub:document.getElementById('appSub'),
  shot:document.getElementById('shot'),
  emptyPreview:document.getElementById('emptyPreview'),
  previewHint:document.getElementById('previewHint'),
  shotMeta:document.getElementById('shotMeta'),
  imageState:document.getElementById('imageState'),
  chatTitle:document.getElementById('chatTitle'),
  chatMeta:document.getElementById('chatMeta'),
  groupBadge:document.getElementById('groupBadge'),
  statusDot:document.getElementById('statusDot'),
  statusText:document.getElementById('statusText'),
  contextState:document.getElementById('contextState'),
  personInfo:document.getElementById('personInfo'),
  replyIntent:document.getElementById('replyIntent'),
  replyAvoid:document.getElementById('replyAvoid'),
  contextNotes:document.getElementById('contextNotes'),
  saveContextBtn:document.getElementById('saveContextBtn'),
  saveReadBtn:document.getElementById('saveReadBtn'),
  saveNote:document.getElementById('saveNote'),
  messages:document.getElementById('messages'),
  suggestions:document.getElementById('suggestions'),
  suggestionMeta:document.getElementById('suggestionMeta'),
  errorBox:document.getElementById('errorBox')
};
let currentProfileTitle='';
let lastMessages=[];
let lastTitle='';
function esc(value){
  return String(value ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
}
function setBusy(isBusy){
  els.readBtn.disabled=isBusy;
  els.readBtn.classList.toggle('loading',isBusy);
  els.readLabel.textContent=isBusy?'读取中':'读取';
  els.statusDot.className='dot '+(isBusy?'busy':'ok');
}
function setStatus(text,kind='ok'){
  els.statusText.textContent=text;
  els.statusDot.className='dot '+kind;
}
function showError(text){
  els.errorBox.style.display=text?'block':'none';
  els.errorBox.textContent=text || '';
}
function renderRuntime(status){
  if(!status)return;
  const mode=status.read_mode==='ocr' ? `ocr/${status.ocr_backend || 'auto'}` : (status.read_mode || 'vlm');
  els.appSub.textContent=`${status.provider || 'provider'} · ${status.default_persona || 'persona'} · ${status.read_last_n || 0} 条上下文`;
  els.runtimePills.innerHTML=[
    ['目标',status.app_name || '未配置'],
    ['模式',mode],
    ['回复',status.reply_model || '未配置'],
    ['输出',status.copy_only ? '复制' : '发送']
  ].map(([k,v])=>`<span class="pill">${esc(k)} <strong>${esc(v)}</strong></span>`).join('');
}
function manualValues(){
  return {
    person_info:els.personInfo.value.trim(),
    goal:els.replyIntent.value.trim(),
    avoid:els.replyAvoid.value.trim(),
    notes:els.contextNotes.value.trim()
  };
}
function renderProfile(profile){
  if(!profile){
    currentProfileTitle='';
    els.contextState.textContent='先读取对话';
    els.contextState.className='context-state';
    return;
  }
  currentProfileTitle=profile.title || '';
  const manual=profile.manual || {};
  els.personInfo.value=manual.person_info || '';
  els.replyIntent.value=manual.goal || '';
  els.replyAvoid.value=manual.avoid || '';
  els.contextNotes.value=manual.notes || '';
  els.contextState.textContent=profile.needs_input ? '信息不足,建议手动补充' : `已加载 ${currentProfileTitle}`;
  els.contextState.className='context-state '+(profile.needs_input ? 'need' : '');
  els.saveNote.textContent='';
}
function renderMessages(messages){
  if(!messages.length){
    els.messages.innerHTML='<div class="empty-state">没有读到消息</div>';
    return;
  }
  els.messages.innerHTML=messages.map(m=>{
    const sender=m.sender || 'unknown';
    const cls=sender==='我'?'me':(sender==='系统'?'system':'other');
    const label=(cls==='other') ? `<div class="sender">${esc(sender)}</div>` : '';
    return `<div class="message-row ${cls}">${label}<div class="bubble">${esc(m.text)}</div></div>`;
  }).join('');
  els.messages.scrollTop=els.messages.scrollHeight;
}
function renderSuggestions(items,note){
  els.suggestionMeta.textContent=`${items.length} 条`;
  if(!items.length){
    els.suggestions.innerHTML=`<div class="empty-state">${esc(note || '暂无建议')}</div>`;
    return;
  }
  els.suggestions.innerHTML=items.map((item,index)=>`
    <article class="suggestion">
      <div class="suggestion-top">
        <div class="tone">${esc(item.persona || 'persona')}</div>
        <div class="suggestion-actions">
          <button class="regen" title="换个说法再生成这条" data-persona="${esc(item.persona || '')}" onclick="regenOne(${index},this)">↻</button>
          <button class="copy" title="复制(可先编辑)" onclick="copySuggestion(${index},this)">复制</button>
        </div>
      </div>
      <textarea class="suggestion-text" id="suggestion-${index}" spellcheck="false">${esc(item.text)}</textarea>
    </article>
  `).join('');
}
function renderPayload(data){
  renderRuntime(data.status);
  const messages=Array.isArray(data.messages)?data.messages:[];
  const suggestions=Array.isArray(data.suggestions)?data.suggestions:[];
  lastMessages=messages;
  lastTitle=data.title || '';
  els.chatTitle.textContent=data.title || '当前对话';
  els.chatMeta.textContent=`${messages.length} 条消息 · ${new Date().toLocaleTimeString()}`;
  els.groupBadge.textContent=data.is_group?'群聊':'1v1';
  renderProfile(data.profile);
  renderMessages(messages);
  renderSuggestions(suggestions,data.note);
  if(data.image){
    els.shot.src='data:image/png;base64,'+data.image;
    els.shot.style.display='block';
    els.emptyPreview.style.display='none';
    els.previewHint.style.display='none';
    els.shotMeta.textContent='已载入实际分析区域';
    els.imageState.textContent='PNG';
  }
}
async function saveContext(thenRead=false){
  if(!currentProfileTitle){
    showError('请先读取一次对话,让 AutoTalk 知道要保存到哪个联系人。');
    return;
  }
  els.saveContextBtn.disabled=true;
  els.saveReadBtn.disabled=true;
  els.saveNote.textContent='保存中';
  try{
    const res=await fetch('/api/context',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({title:currentProfileTitle,manual:manualValues()})
    });
    const data=await res.json();
    if(!data.ok){
      showError(data.error || '保存失败');
      els.saveNote.textContent='保存失败';
      return;
    }
    els.contextState.textContent=`已保存 ${currentProfileTitle}`;
    els.contextState.className='context-state';
    els.saveNote.textContent='已保存';
    showError('');
    if(thenRead) await readNow();
  }catch(err){
    showError('保存失败: '+String(err));
    els.saveNote.textContent='保存失败';
  }finally{
    els.saveContextBtn.disabled=false;
    els.saveReadBtn.disabled=false;
    setTimeout(()=>{ if(els.saveNote.textContent==='已保存') els.saveNote.textContent=''; },1600);
  }
}
async function readNow(){
  setBusy(true);
  showError('');
  setStatus('读取和生成中','busy');
  try{
    const res=await fetch('/api/read',{cache:'no-store'});
    const data=await res.json();
    if(data.error){
      renderRuntime(data.status);
      showError(data.error);
      setStatus('读取失败','busy');
      return;
    }
    renderPayload(data);
    setStatus('读取完成','ok');
  }catch(err){
    showError(String(err));
    setStatus('请求失败','busy');
  }finally{
    setBusy(false);
  }
}
function fallbackCopy(text){
  const t=document.createElement('textarea');
  t.value=text;
  t.setAttribute('readonly','');
  t.style.position='fixed';
  t.style.left='-9999px';
  document.body.appendChild(t);
  t.select();
  document.execCommand('copy');
  document.body.removeChild(t);
}
async function copySuggestion(index,button){
  const el=document.getElementById(`suggestion-${index}`);
  const text=('value' in el)?el.value:el.textContent;
  try{
    if(navigator.clipboard && window.isSecureContext) await navigator.clipboard.writeText(text);
    else fallbackCopy(text);
    button.textContent='已复制';
    button.classList.add('copied');
    setTimeout(()=>{button.textContent='复制';button.classList.remove('copied');},1400);
  }catch(err){
    showError('复制失败: '+String(err));
  }
}
function setGoal(text){
  els.replyIntent.value=text;
  els.replyIntent.focus();
}
async function regenOne(index,button){
  if(!lastMessages.length){showError('先读取一次对话,再用 ↻ 重生成。');return;}
  const persona=button.getAttribute('data-persona')||'';
  const ta=document.getElementById(`suggestion-${index}`);
  button.disabled=true;
  try{
    const res=await fetch('/api/regenerate',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({title:lastTitle,persona:persona,messages:lastMessages})
    });
    const data=await res.json();
    if(data.error){showError('再生成失败: '+data.error);}
    else if(typeof data.text==='string'){ta.value=data.text;showError('');}
  }catch(err){showError('再生成失败: '+String(err));}
  finally{button.disabled=false;}
}
document.addEventListener('keydown',e=>{
  if((e.metaKey||e.ctrlKey)&&(e.key==='r'||e.key==='R')){
    e.preventDefault();
    if(!els.readBtn.disabled)readNow();
  }
});
async function boot(){
  try{
    const res=await fetch('/api/status',{cache:'no-store'});
    renderRuntime(await res.json());
  }catch(_){
    els.appSub.textContent='本地服务';
  }
}
boot();
</script>
</body>
</html>"""


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
        elif self.path == "/api/status":
            self._send(200, "application/json; charset=utf-8",
                       json.dumps(_public_status(), ensure_ascii=False).encode("utf-8"))
        elif self.path == "/api/read":
            try:
                payload = read_and_suggest()
            except SystemExit as e:
                payload = {"error": _error_text(e), "status": _public_status()}
            except Exception as e:
                payload = {"error": str(e), "status": _public_status()}
            self._send(200, "application/json; charset=utf-8",
                       json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        else:
            self._send(404, "text/plain", b"not found")

    def do_POST(self):
        if self.path not in ("/api/context", "/api/regenerate"):
            self._send(404, "text/plain", b"not found")
            return
        try:
            n = int(self.headers.get("Content-Length", "0") or "0")
            data = json.loads(self.rfile.read(n).decode("utf-8")) if n else {}
            if self.path == "/api/context":
                title = data.get("title")
                saved = memory.save_manual_context(title, data.get("manual") or {})
                payload = {"ok": True, "profile": {"title": title, "manual": saved}}
            else:  # /api/regenerate
                text = regenerate_one(data.get("title") or "unknown",
                                      data.get("persona") or "", data.get("messages") or [])
                payload = {"text": text}
        except SystemExit as e:
            payload = {"ok": False, "error": _error_text(e)}
        except Exception as e:
            payload = {"ok": False, "error": str(e)}
        self._send(200, "application/json; charset=utf-8",
                   json.dumps(payload, ensure_ascii=False).encode("utf-8"))


def _serve_forever() -> None:
    HTTPServer((HOST, PORT), Handler).serve_forever()


def main() -> None:
    import sys

    url = f"http://{HOST}:{PORT}"
    if "--window" in sys.argv or getattr(sys, "frozen", False):   # 打包后默认走原生窗口
        import webview
        threading.Thread(target=_serve_forever, daemon=True).start()
        webview.create_window("AutoTalk 副驾", url, width=1120, height=740, min_size=(820, 520))
        webview.start()                 # 阻塞,直到关闭窗口
    else:                               # 浏览器模式
        print(f"AutoTalk 副驾 → {url}(只读屏 + 复制,不自动发送)。Ctrl+C 退出。")
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
        _serve_forever()


if __name__ == "__main__":
    main()
