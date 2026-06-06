# AutoTalk

微信桌面版（macOS）自动回复助手 —— 截图读对话、套人设+记忆生成草稿、**人工确认后**发送。可全程跑在本地（Ollama），数据不出本机。

**流程**：
```
定时截图微信窗口
  → 读出最近对话(谁说了什么)      [两种方式:OCR 几何判定 / 视觉模型直读]
  → 套「人设 + 联系人记忆」生成草稿  [本地 Ollama 或 云端 Claude]
  → 弹原生确认框,你过目/编辑       [核心安全闸门]
  → 剪贴板粘贴 + 回车发送           [dry_run 下只打印]
```

> **人工确认是核心设计**：它防止发错话、防止被消息里的内容注入劫持，也让发送节奏保持人类速度（降低微信风控/封号风险）。目前不做全自动发送。

---

## 一键安装

```bash
cd AutoTalk
bash setup.sh        # 建 .venv、装依赖、自检(Python / OCR后端 / ollama / 模型)
```

`setup.sh` 在 macOS 上会装最轻量的本地 OCR 后端（系统原生 Vision，免下模型）。装完按提示拉模型即可。

**授权**（系统设置 → 隐私与安全性）——把你运行命令的**终端**加进这两项：
- **屏幕录制**：`screencapture` 截图需要。
- **辅助功能**：粘贴、回车、读取窗口位置需要。

> 手动装：`python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`，再按 requirements 注释装 OCR 后端 / 视觉模型依赖。

## 两种后端（在 `config.yaml` 切换）

| | 本地 Ollama（默认，推荐） | 云端 Claude |
|---|---|---|
| 配置 | `provider: ollama` | `provider: anthropic` |
| 模型 | `model: qwen2.5vl:7b` | `model: claude-sonnet-4-6` |
| 需要 | `ollama pull qwen2.5vl:7b` | `export ANTHROPIC_API_KEY=...` + `pip install anthropic` |
| 隐私 | **截图不出本机** | 截图发往云端 |
| 质量 | 够用 | 更强 |

## 两种读取模式（`read_mode`）

把截图变成"谁说了什么"，两种方式：

- **`ocr`（默认，推荐）**：本地 OCR 拿到每个文字的精确坐标 + 检测头像，用**几何规则**判定发言人——贴右=我、贴左=对方、居中=系统。比让模型"猜"更稳，实测 1v1 发言人判定接近满分。
  - 需要 OCR 后端：macOS 原生 `vision`（最轻量，`setup.sh` 已装）/ `easyocr` / `paddleocr` / `tesseract`，由 `ocr_backend: auto` 自动挑。
  - 复用了自带的 `wechat_ocr.py`（vendored，自包含）。
- **`vlm`**：直接让视觉模型读整张图。最简单、不用装 OCR 后端，但小模型对左右气泡的发言人判定容易出错。

> OCR 后端读不出文字时会**自动回退到 `vlm`**。

## 能力

- **1v1 发言人判定**：我 / 对方 / 系统(时间戳)，几何判定，准。
- **群聊多人区分**：自动识别气泡上方的昵称小字，把每条消息绑到对应的人；过滤"N条新消息"等 UI 文本。
- **图片 / 表情**：标成 `〔图片〕`/`〔表情〕`；表情包上的字会和图合并成一条。
- **联系人名**：1v1 能从标题栏提取 `chat_title`，用于按联系人绑人设/记忆。

## 运行

```bash
source .venv/bin/activate

# 离线自检:拿一张静态聊天截图测"读取→草稿",不截屏、零权限,最适合调参
python selftest.py ~/Desktop/某张聊天截图.png

# 实时:打开微信到某会话并保持窗口可见
python main.py --once     # 只跑一轮,验证读取+确认框
python main.py            # 持续监听(dry_run=true,不会真发)
python main.py --send     # 真正发送(务必先用小号/文件传输助手)
```

默认 `dry_run: true`：弹确认框，但点「发送」也只打印不真发。验证整条链路 OK 后再 `--send`。

## 目录结构

```
AutoTalk/
  setup.sh           一键建环境 + 自检
  main.py            入口(命令行)
  watcher.py         主循环:截图轮询 + 新消息检测 + 串起流程
  capture.py         截图 + 定位微信窗口(osascript / screencapture)
  vision.py          截图 -> 结构化消息(ocr 几何判定 或 vlm 直读)
  wechat_ocr.py      vendored:OCR + 头像/几何发言人判定(ocr 模式用)
  llm.py             模型调用层(anthropic / ollama 双后端)
  agent.py           拼 prompt(人设 + 记忆 + 对话)-> 草稿
  memory.py          联系人记忆:人工档案 + 自动摘要
  persona.py         人设 skill 加载与按联系人绑定
  confirm.py/.applescript  原生确认框
  sender.py          剪贴板粘贴 + 回车发送(dry_run 只打印)
  selftest.py        离线自检(对静态截图跑 读取->草稿)
  config.py / config.yaml   配置
  skills/
    personas/        人设:serious / flirty / casual / tongjincheng(可自行加)
    memory/          每个联系人一个档案 + 一个自动摘要(运行时生成)
```

## 加 skill（核心扩展点）

- **加人设**：在 `skills/personas/` 丢个 `xxx.md`（写清"什么语气、怎么说话"）。生效方式：
  - 全局默认：`config.yaml` 的 `default_persona: xxx`；
  - 按联系人：`config.yaml` 的 `contacts:` 写 `会话名: xxx`，或在 `skills/memory/<名字>.md` 写一行 `人设: xxx`（优先级最高）。
- **调记忆**：联系人首次出现自动生成 `skills/memory/<名字>.md`，手填关系/称呼/偏好，代码不覆盖；对话摘要存同名 `.summary.md` 由程序维护。

> 想加「查日程 / 查天气 / 记 TODO」等工具型 skill：在 `agent.py` 生成草稿前调用它们，或整体迁到 Claude Agent SDK 用其 MCP + 权限机制承载。

## 配置项（config.yaml）

| 键 | 说明 |
|---|---|
| `provider` | `ollama`(本地) 或 `anthropic`(云端) |
| `ollama_host` | Ollama 地址，默认 `http://localhost:11434` |
| `read_mode` | `ocr`(本地OCR几何判定,准) 或 `vlm`(模型直读) |
| `ocr_backend` | `auto` / `vision` / `easyocr` / `paddleocr` / `tesseract` |
| `me_side` | "我"在哪侧，微信默认 `right`；镜像布局改 `left` |
| `model` | 主模型(vlm 模式需支持视觉)；`vision_model`/`reply_model` 可分别覆盖 |
| `summary_model` | 维护记忆摘要的便宜模型 |
| `app_name` | 微信应用名，部分版本是 `微信` |
| `poll_interval_seconds` | 轮询间隔，建议 ≥3 |
| `read_last_n` | 每次读取的最近消息条数 |
| `dry_run` | true 只演练不发送 |
| `send_with` | `enter` 或 `cmd_enter`，对应你微信的发送快捷键 |
| `default_persona` / `contacts` | 默认人设 / 按会话名绑定人设 |
| `update_memory` | 发送后是否自动更新该联系人摘要 |

## 已知限制 & 风险

- **群聊**：昵称识别基于"昵称小字 + 缩进"版面的几何规则，绝大多数情况准；极端排版可能漏判，且目前会对每条新消息都尝试回复（靠确认框拦）。
- **截图范围**：按微信窗口区域抓取，请保持窗口可见、尽量放主显示器；多显示器坐标可能有偏差。
- **OCR 质量**：深色截图 / 涂鸦标注 / 异形表情可能影响识别；`ocr` 读不出会回退 `vlm`。
- **封号 / 合规**：微信无官方个人号接口，任何自动化都有**封号 / 违反用户协议**风险。请用非主力号、保持低频、**逐条人工确认**、不要群发。
- **隐私**：`vlm`+云端会把整窗截图发往云端；`ocr`+本地全程不出本机。
