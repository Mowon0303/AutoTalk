# Changelog

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
- 项目更名 **AutoTalk → DraftMate**:GitHub 仓库、README/界面文案、打包(`CFBundleName`、bundle id `local.draftmate.copilot`、`DraftMate.app`)、数据目录(`~/Library/Application Support/DraftMate`)、本地文件夹一并更新;内部记忆标记(`autotalk:manual-context`)保持不变以兼容已存档案。README 简介改为更中性的表述。
- Copilot UI 重做为暖黑 + 琥珀金的「Focus」设计:三层布局(标题栏 / 状态栏 / 左截图 + 右建议)、AI 分析卡、带语气标签与「★推荐」的回复卡;加载 Bricolage Grotesque / IBM Plex 字体(离线回退系统字体)。
- 手动上下文用持续的「目标(阶段性)」(`goal`)取代逐条输入的「我这次想表达」(`reply_intent`):设一次长期生效,agent 朝该阶段性目标循序渐进地给建议,不再要求每条都手填意图。同步更新 `agent` 回复策略、`copilot` UI 标签/占位与前后端字段。

### Fixed
- `memory.load()` 现在剥掉手动上下文块,避免它在 prompt 里重复(该块已单独以最高优先级注入)。

### Removed
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
