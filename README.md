# AutoTalk

桌面聊天软件（macOS）自动回复助手 —— 截图读对话、套人设+记忆生成草稿、**人工确认后**发送。可全程跑在本地（Ollama），数据不出本机。

**流程**：
```
定时截图目标 App 窗口
  → 读出最近对话(谁说了什么)      [两种方式:OCR 几何判定 / 视觉模型直读]
  → 套「人设 + 联系人记忆」生成草稿  [本地 Ollama 或 云端 Claude]
  → 弹原生确认框,你过目/编辑       [核心安全闸门]
  → 剪贴板粘贴 + 回车发送           [dry_run 下只打印]
```

> **人工确认是核心设计**：防止发错话、防止被消息里的内容注入劫持,也让发送节奏保持人类速度。目前不做全自动发送。

---

## 一键安装

```bash
cd AutoTalk
bash setup.sh                     # 建 .venv、装依赖、自检
cp config.example.yaml config.yaml   # 复制配置模板,然后按下面填好 app_name
```

`setup.sh` 在 macOS 上会装最轻量的本地 OCR 后端(系统原生 Vision,免下模型)。

**授权**(系统设置 → 隐私与安全性)——把你运行命令的**终端**加进:
- **屏幕录制**:截图需要。
- **辅助功能**:粘贴、回车、读取窗口位置需要。

## 配置目标应用(必填)

在 `config.yaml` 里填目标 App:
```yaml
app_name: "你的App应用名"      # 系统里显示的应用名/进程名
app_aliases: []               # 若该 App 窗口属主名是本地化名(和应用名不同),在此补上
```
不确定属主名时,先 `python main.py --snap`,定位不到会打印出当前所有窗口的 owner 名,照着填。

## 两种后端(`provider`)

| | 本地 Ollama(默认) | 云端 Claude |
|---|---|---|
| 配置 | `provider: ollama` / `model: qwen2.5vl:7b` | `provider: anthropic` / `model: claude-sonnet-4-6` |
| 需要 | `ollama pull qwen2.5vl:7b` | `export ANTHROPIC_API_KEY=...` + `pip install anthropic` |
| 隐私 | **截图不出本机** | 截图发往云端 |
| 质量 | 够用 | 更强 |

## 两种读取模式(`read_mode`)

- **`ocr`(推荐)**:本地 OCR 拿到每个文字的精确坐标 + 检测头像,用**几何规则**判定发言人——贴右=我、贴左=对方、居中=系统。比让模型"猜"更稳。需 OCR 后端(macOS 原生 `vision` 最轻量,`setup.sh` 已装)。复用了自带的 `chat_ocr.py`(自包含)。
- **`vlm`**:直接让视觉模型读整张图。最简单、不用装 OCR 后端,但小模型对左右气泡的发言人判定容易出错。OCR 读不出时会自动回退到 `vlm`。

## 能力

- **1v1 发言人判定**:我 / 对方 / 系统(时间戳),几何判定。
- **群聊多人区分**:识别气泡上方的昵称小字,把每条消息绑到对应的人。
- **图片/表情**:标成 `〔图片〕`/`〔表情〕`;表情包上的字会和图合并成一条。
- **会话名**:从标题栏提取,用于按联系人绑人设/记忆。

## 运行

```bash
source .venv/bin/activate
python main.py --check     # 体检:依赖/权限/后端/目标App 是否就绪
python main.py --snap      # 抓一张:存「实际分析区域」+预览打开+打印解析(看它读到啥)
python main.py --once      # 真机一轮:读对话→草稿→确认框(dry_run 不真发)
python main.py             # 持续监听
python main.py --send      # 真正发送(务必先用不重要的会话测)
python copilot.py          # 本地副驾 UI:截图预览 + 建议回复 + 复制
python copilot.py --window # 原生窗口模式(需 pywebview)
```

`selftest.py` 可对一张静态截图离线跑「读取→草稿」(不截屏、零权限),最适合调参:
```bash
python selftest.py 某张聊天截图.png
```

## 目录结构

```
AutoTalk/
  setup.sh           一键建环境 + 自检
  main.py            入口(--once / --send / --check / --snap)
  watcher.py         主循环:轮询 + 新消息检测 + 串起流程
  capture.py         截图 + 按窗口ID定位目标App(不受遮挡)
  vision.py          截图 -> 结构化消息(ocr 几何判定 或 vlm 直读)
  chat_ocr.py        自带:OCR + 头像/几何发言人判定(ocr 模式用)
  llm.py             模型调用层(ollama / anthropic 双后端)
  agent.py           拼 prompt(人设 + 记忆 + 对话)-> 草稿
  memory.py          联系人记忆:人工档案 + 自动摘要
  persona.py         人设加载与按联系人绑定
  confirm.py/.applescript  原生确认框
  sender.py          剪贴板粘贴 + 回车发送(dry_run 只打印)
  doctor.py          体检(--check)
  snap.py            抓图查看(--snap)
  selftest.py        离线自检
  config.example.yaml  配置模板(复制为 config.yaml)
  skills/
    personas/        人设:serious / flirty / casual / tongjincheng
    memory/          每个联系人一个档案 + 自动摘要(运行时生成,不入库)
```

## 加 skill

- **加人设**:在 `skills/personas/` 丢个 `xxx.md`(写清"什么语气")。生效:全局 `default_persona: xxx`,或按联系人 `contacts: {会话名: xxx}`,或在 `skills/memory/<名字>.md` 写 `人设: xxx`。
- **调记忆**:联系人首次出现自动生成 `skills/memory/<名字>.md`,手填关系/偏好,代码不覆盖;对话摘要存同名 `.summary.md` 由程序维护。

## 已知限制 & 风险

- 读取靠 OCR/视觉,复杂排版/异形表情/深色截图可能识别不全。
- 截图按窗口 ID 抓取,请保持目标窗口未最小化;`crop_left/crop_bottom` 按你的窗口尺寸微调。
- 对没有官方开放接口的 App 做自动化可能违反其用户协议、并有账号风险:请用非主力账号、保持低频、**逐条人工确认**、不要群发。
- 隐私:`vlm`+云端会把截图发往云端;`ocr`+本地全程不出本机。本地生成的截图/联系人记忆/状态文件都不会进仓库(见 `.gitignore`)。
