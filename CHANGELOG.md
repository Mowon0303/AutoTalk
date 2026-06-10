# Changelog

## Unreleased - 2026-06-10 (军师层:关系阶段判定)

### Added
- **`agent.assess_stage()` 军师判定**:每次读取先用回复模型做一次低温短输出的关系阶段估计——L0–L5/D1/D2 八等级 + 判定规则(两类独立证据才升级、拿不准取更低、只引用真实对话、秒回/表情=弱证据),蒸馏自 13 项研究的阶段判定法(本地 skill 资产去名化入 App);非恋爱语境(同事/事务)自动输出「不适用」。输出三行:阶段(置信度)/依据(引用片段)/策略(只给方向,禁示例句)。
- 判定结果接入两处:①「AI 分析」卡显示真判定(原为 4 条写死的 JS 规则,降级为兜底);②作为 `stage_hint` 喂给每条草稿与「换个说法」——按阶段校准火候,不越级推进(实测 L1 判定下三个人设都不再直接约饭)。
- 判定失败不挡草稿生成;`/api/regenerate` 接受前端回传的 `analysis` 复用判定,不重复计算。

### Verified
- 暧昧语境 → L1(中置信)+真实片段引用;同事语境 → 「不适用(非恋爱语境)」(高置信)。
- 修掉一个真实坑:判定策略行写了示例句导致 7B 草稿整句照抄、三候选趋同——规则禁台词 + 草稿侧声明"方向非措辞"后,三人设输出重新分化。

## Unreleased - 2026-06-10 (UI 交互修复 + 真·监控)

### Added
- **「监控」开关(用户拍板把 Backlog 提前)**:开启后每 `poll_interval_seconds`(默认 5s,重新入册到配置默认值)秒调用新的 `GET /api/peek`——只截屏+OCR 取最后一条非系统消息指纹,**不生成**;指纹变化且新消息来自对方时,才触发一次完整读取+生成。仍只读屏、不模拟输入、不发送(红线 3 不动)。开启时 REC 指示与 run-pill 显示「监控中」,tooltip 写明行为。
- **模型下拉改为真正的选择器**(原来点开是一堆运行信息):`GET /api/models` 列出本地 Ollama 全部已 pull 模型(当前值不在列表也带上,如 claude-*),点选即 `POST /api/model` 切换——内存立即生效,并只改写 config.yaml 的 `reply_model` 一行(行尾注释保留)。运行信息网格移入设置(⚙)面板的「运行信息」区。
- 用量计数拆分手动/自动:`usage.auto_reads` 单独记监控触发的读取,角标显示「已读取 N 次 (自动 M)」——周留存指标只认手动,防挂机刷数。

### Fixed
- 左侧「待命」指示器现在接入真实生命周期:读取中 REC「读取中」、监控开启「监控中」、空闲「待命」(原来只挂在装饰开关上,点读取毫无反应)。
- `/api/read` 支持 `?auto=1` 标记监控触发;Handler 路由统一拆 query。
- **监控开启后 30s 无反应(用户实测)**:原逻辑只对开启之后的新消息反应且全程静默——预期不符 + 不可观测。改为:①开启时若屏幕上最后一条是对方的未回消息,立刻先出一版草稿;②每次探测在状态栏打心跳(`监控中 · HH:MM:SS 已探测,无新消息`);③探测失败不再吞掉,显示具体错误。
- 模型选择器实测正常(用户点击已把 reply_model 切到 qwen2.5vl:7b 并正确写回配置)——已把配置恢复为 qwen2.5:7b 文本模型,VL 模型聊天质量明显更平。
- 监控范围据实重写文案(用户实测指出):只盯**当前打开的对话**——微信不点开会话不渲染内容,平台物理限制;tooltip/状态栏/分发说明同步说清。侧栏红点检测与多窗口监控列为「明确不做」(见 PLAN Backlog)。

## Unreleased - 2026-06-10 (回复质量:去同质化 + 撩感)

> 问题:三条候选一个味、全是客服安慰腔、零撩感。病因三个,全部修掉。

### Changed
- **回复模型切到文本模型**:`reply_model: qwen2.5:7b`(config.yaml 与 example 均默认),原来回退到 `qwen2.5vl:7b`——7B 视觉模型客串中文聊天是同质化首因。视觉模型只管读图。
- **人设从"形容词"改成"少样本示例"**:四个 persona 全部重写为「定位 + 语气 + 4–6 条示例对话 + 禁忌」结构——7B 模型无法从"语气:亲和幽默"演出人设,只能模仿示例。flirty/shenqing 的技法蒸馏自深情流方法论(推拉、给台阶式邀约、给确定感不舔、点到为止、反鸡汤),已去名化。示例刻意避开高频输入句,防止小模型整句照抄(测试中实际发生过)。
- **按人设分采样温度**:`agent.temperature_for()`——serious 0.5 / casual 0.75 / shenqing 0.8 / flirty 0.85(原来统一 0.4,低温+同 prompt 是同质化次因);「换个说法」再 +0.15 防重生成出同一句。
- **prompt 重排**:人设放 system 最前定调、硬规则压轴(小模型对开头结尾最敏感);新增反客服腔黑名单(「多喝热水/注意休息哦/加油哦/辛苦啦」禁用)、角色锚定(别把对方处境安自己头上)、一条回复最多一个问题;删掉"默认不加表情符号"(交由人设决定)。
- **llm 按模型名路由后端**:`reply_model` 填 `claude-*` 可单独让"回复生成"上云(只传对话文字、不传截图,读图仍全本地),质量天花板留口子;默认配置仍全本地,需自带 ANTHROPIC_API_KEY。
- `分发说明.md` 安装步骤补上 Ollama 安装与模型拉取(原"三步"漏了整个模型环节,种子用户装完必卡)。

### Verified
- 固定对话 × 4 人设 × 3 轮对比:改前四条几乎同句型、零邀约;改后人设分化明显(serious 落到事/casual 接梗怼/flirty 邀约带暧昧/shenqing 接情绪给确定感),客服腔消失。7B 仍偶发嘴瓢与双问句,属模型上限,升级路已留(qwen2.5:14b 本地 / claude-* 文字上云)。
- 同步打包态数据目录(~/Library/Application Support/DraftMate):reply_model、四个新人设;真名人设按约定改 `.local.md`(seed 只在首装拷贝,不同步会导致 .app 用旧人设)。

## Unreleased - 2026-06-10 (Phase 0 产品侧)

### Added
- 仅本地的用量计数(隐私承诺内的最低成本度量):`usage.json` 记累计「读取」次数 + 最近使用日期,状态栏角标展示(title 注明"仅本地统计,不上传");`/api/status` 与读取返回的 `status` 均带 `usage`。无任何遥测,周报靠用户自愿截图角标。
- `分发说明.md`:给种子用户的一页说明(是什么 / 隐私承诺 / 安装三步 / 已知限制 / 反馈方式)。
- `指标记录.md`(含真名,不入库):用户总表 + W1–W7 周记录 + Gate 1 判据与结论页,定义复制自 PLAN.md。

### Changed
- **去名化(变现前红线)**:`skills/personas/tongjincheng.md` 改为本地私有 `tongjincheng.local.md`(已 `git rm --cached`,不入库、不入分发包),对外改为抽象流派 `shenqing.md`(深情流);copilot UI 标签映射、README、config.example 同步替换。建立 `*.local.md` = 本地私有人设约定:`load_persona` 先找 `<名>.md` 再回退 `<名>.local.md`,`setup_app.py` 打包过滤 `*.local.md`,.gitignore 同步。
- `config.example.yaml` 默认 `app_name: "WeChat"` + 常见别名(原默认空值会让打包态首跑必报"未配置",是种子用户第一个卡点)。
- 状态栏诚实化:隐藏纯装饰的「监听」开关(原 `toggleRunning` 只改样式、无轮询逻辑,会误导隐私预期),去掉假的「自动截图 5s」字样(改"手动读取",运行时被实际读取模式覆盖),「监听」标签改「当前」;新增用量角标。

### Verified
- `py_compile` 全部源文件通过;计数器/人设加载/页面内容单测通过;8766 端口 Handler 冒烟 + 打包后 App 实际启动并响应 `/api/status`、页面含角标。
- 打包产物全包扫描无「童锦程/tongjincheng」字样;bundle 内 personas 仅 serious/casual/flirty/shenqing 四个。

### Dev note
- 项目目录改名(AutoTalk→DraftMate)导致 `.venv/bin/pip` 等脚本 shebang 指向死路径;包本体完好,用 `.venv/bin/python -m pip` 绕过,后续可重建 venv。

## Unreleased - 2026-06-07 (后续)

### Added
- Copilot UI 打磨:
  - 「目标(阶段性)」快捷预设按钮(认识→暧昧 / 约出来 / 确定关系 / 维持朋友),一键填入。
  - 建议回复改为可编辑文本框,可先改后复制(复制的是改后的内容)。
  - 每条建议加 ↻「再生成」按钮:复用当前对话、同人设单独重出一条,无需整页重读。
  - 快捷键 ⌘R / Ctrl+R 触发「读取」。
  - 新增 `/api/regenerate` 接口(POST `{title, persona, messages}` → 单条建议)。
- py2app 打包:新增 `setup_app.py` + `appdirs.py`,可构建自包含的 `DraftMate.app`(`python setup_app.py py2app`)。打包态把用户数据(config / 记忆 / 截图)移到 `~/Library/Application Support/DraftMate`,开发态路径不变。

### Changed
- 文件合并(功能不变,仅整理结构):`appdirs`→`config`、`capture`+`chat_ocr`→`vision`、`persona`+`memory`→`skills`;每个合并文件内用区域注释分段。源码模块 11 → 7 个。
- 项目更名 **AutoTalk → DraftMate**:GitHub 仓库、README/界面文案、打包(`CFBundleName`、bundle id `local.draftmate.copilot`、`DraftMate.app`)、数据目录(`~/Library/Application Support/DraftMate`)、本地文件夹一并更新;内部记忆标记(`autotalk:manual-context`)保持不变以兼容已存档案。README 简介改为更中性的表述。
- Copilot UI 重做为暖黑 + 琥珀金的「Focus」设计:三层布局(标题栏 / 状态栏 / 左截图 + 右建议)、AI 分析卡、带语气标签与「★推荐」的回复卡;加载 Bricolage Grotesque / IBM Plex 字体(离线回退系统字体)。
- 手动上下文用持续的「目标(阶段性)」(`goal`)取代逐条输入的「我这次想表达」(`reply_intent`):设一次长期生效,agent 朝该阶段性目标循序渐进地给建议,不再要求每条都手填意图。同步更新 `agent` 回复策略、`copilot` UI 标签/占位与前后端字段。

### Fixed
- `memory.load()` 现在剥掉手动上下文块,避免它在 prompt 里重复(该块已单独以最高优先级注入)。

### Removed
- 精简为 copilot-only:删除自动发送链路与多余入口/界面 —— `main.py` / `watcher.py` / `sender.py` / `confirm.py` / `confirm.applescript`(自动发送流程)、`menubar.py`(菜单栏 App)、`doctor.py` / `snap.py` / `selftest.py`(排错/测试工具);均不被 copilot app 依赖。同步精简 `setup.sh` / `setup_app.py` / README,删除旧打包产物。
- 清理随之失效的死代码与配置:`memory.update()`(发送后自动摘要)、`capture.file_hash()`,以及配置项 `poll_interval_seconds` / `dry_run` / `send_with` / `update_memory` / `summary_model`。
- 去掉 profile 模板里多余的「当前目标」一行(由结构化的目标字段取代,避免两个"目标")。

## Unreleased - 2026-06-07

### Added

- Added the local copy-only Copilot UI in `copilot.py`.
  - Shows the actual analyzed screenshot/crop on the left.
  - Shows parsed conversation messages and 2-3 suggested replies on the right.
  - Provides copy buttons instead of automatic send actions.
  - Exposes runtime status for target app, provider, read mode, reply model, persona, and copy-only mode.
- Added `/api/status` for non-secret UI runtime metadata.
- Added `/api/context` for saving per-contact manual context locally.
- Added per-contact manual context storage in `skills/memory/<contact>.md`.
  - `对方信息`
  - `我这次想表达`
  - `不要提/边界`
  - `备注`
- Added UI controls for saving contact context and regenerating suggestions.
- Added README run commands for:
  - `python copilot.py`
  - `python copilot.py --window`

### Changed

- Improved reply-generation strategy in `agent.py`.
  - Manual context now has highest priority.
  - The agent is instructed to answer the other person's latest question first.
  - The agent is instructed not to repeat or re-ask questions the other person already asked.
  - Temperature and token budget were tightened for shorter, more direct replies.
- Kept the safer product direction as a reply copilot:
  - read screen
  - show analyzed context
  - generate draft
  - user copies manually
  - no keyboard simulation or automatic send from Copilot UI

### Confirmed Behavior

- The reading pipeline already crops before OCR:
  - `capture.grab()` captures the target app window.
  - `vision.read_messages()` calls `_apply_crop()`.
  - OCR runs on the cropped image path.
- The Copilot UI also renders the cropped analysis preview, so the user can inspect what the agent actually read.
- Local memory files remain under `skills/memory/`, which is ignored by git for private `.md` and `.summary.md` files.

### Verified

- Python syntax check passed:
  - `.venv/bin/python -m py_compile copilot.py agent.py memory.py watcher.py selftest.py`
- Manual-context save/load was tested against a temporary memory directory.
- Temporary local UI verification passed on:
  - desktop viewport
  - mobile viewport
- Browser console showed no errors or warnings during UI verification.

### Notes

- If the analyzed preview still includes the bottom input toolbar, tune `crop_bottom` in `config.yaml`.
- If the contact title is read as `unknown`, context can still be saved, but the better fix is to improve title detection or set per-contact memory after a reliable title is available.
- The next quality step is to let the user choose or type the current intent before generation, so the agent stops guessing between paths such as rental, green card, or general small talk.
