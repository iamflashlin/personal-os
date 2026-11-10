# Personal OS — Claude Code 项目交接文档

2026-11-10

## 0. 使用方式（给你本人看）

这份文档是交给 Claude Code 的执行基线：它在你的两份设计稿（V1.1 设计方案、V1.2 交接指令）之上做了架构审查和取舍，Claude Code 读完就知道做什么、先做什么、用什么现成工具。

**你是新手，直接跳到第 9 节「新手逐步操作指南」，从第 1 步开始照做。** 第 1–8 节主要写给 Claude Code 看，你现在读不懂也没关系，以后每合并一个功能就会慢慢对应上。

整体流程是：

1. 照第 9 节装好软件、建好仓库，把本文档存成 `docs/HANDOFF.md`，两份原始设计稿放进 `docs/source/`。
2. 在仓库文件夹里启动 Claude Code，粘贴第 10 节的开场提示词。
3. Claude Code 第一轮只搭 D0 骨架、写计划和任务卡，不写业务功能；你看过同意后再进入 V0.1。

优先级规则：原始设计稿是“功能全集”，本文档是“执行版”。两者冲突时以本文档为准，除非你明确改决定。文中 Claude Code、pstack 的细节查证于 2026-11-10，工具更新很快，动手前以官方文档为准。

## 1. Claude Code：你的角色与工作规则

你是这个项目的技术负责人兼主力开发 Agent。用户负责产品方向、关键决策和真实体验验收；你负责设计落地、实现、测试和验证。用户是社区大学工程方向学生，数学好、正在学 C++、软件工程经验有限，只有一台 Windows 笔记本，没有 Mac。他希望理解自己的系统，所以每个 PR 都要附 3–5 句“这次学到什么”的通俗说明。

### 每个任务的固定循环

1. 读任务卡和相关代码，用自己的话复述任务、约束、依赖。
2. 写出可观察的验收标准（命令 + 预期输出，或真实界面上的状态）。
3. 判断能否独立完成；触发下方“必须问用户”条件就停下来问。
4. 实现：能先写失败测试就先写；Bug 必须先复现再修。
5. 验证：`uv run python -m tools.check` 全绿，再跑该模块的真实行为验证脚本，证据存入 `.evidence/<任务ID>/`。
6. 由只读的 reviewer 子 Agent 审查后开 PR，PR 里附验收对照表和证据。
7. 记录：重要决定写 `docs/decisions/`，重复犯的错写 `docs/lessons.md` 并优先转成 lint / 类型 / 测试 / skill。

### 硬约束

- 不把自己的口头报告当作通过证据；“编译通过 / 单测通过”不等于功能可用。
- 不假设用户已装任何工具，不假设有 Mac，不假设 iOS 第三方 App 能读写其他 App。
- 不加智能家居功能；不碰用户的另一个项目“定风台”的数据、凭据和自动化。
- 凭据不进仓库；日志不写敏感信息。
- 安装依赖、改系统设置、联网下载前先说明要做什么和影响。
- 未经审核不合并高风险改动、不部署。
- 优先复用成熟工具（第 5 节）；现成工具达不到验收标准时才自研，并写决策记录。
- 给耗时或成本估计时说明假设，不承诺日期。
- 不确定的技术能力要标注“未验证”，并给出验证方法（一个半天以内的 spike）。
- 默认用中文跟用户沟通；代码、注释、提交信息用英文。

### 必须问用户的情况

- 会改变架构边界、数据模型或安全模型的决定。
- 需要花钱、注册账号、授权第三方服务。
- 涉及删除数据、对外发送、不可逆操作。
- 验收标准本身有歧义。

其余细节自己决定并在 PR 里说明，不要频繁打断用户。多种方案时给一个默认推荐。

## 2. 项目是什么

Personal OS 是一套个人 AI 操作与执行系统：用户说出意图，系统在授权范围内检索个人记忆、制定计划、操作电脑把工作准备好或直接做掉，再用可观察的证据验证结果、更新进度。

**和普通任务管理器的区别**：任务管理器记录“要做什么”；Personal OS 要把“决定开始”到“真正在做”的距离压到一句话，并替用户完成可授权、可验证的工作。用户的核心痛点是启动门槛高、容易沉迷设计而迟迟不执行，所以“一键开始 + 断点恢复 + 明确的下一步”比任何分析功能都重要。

**为什么这几点是核心**

- 电脑执行能力：用户的实际工作（编程、学习、文档）都发生在电脑上；不能执行，就只是另一个聊天机器人。
- 个人记忆：“上次做到哪、下一步是什么”是降低启动成本的关键，而且必须独立于任何模型和聊天窗口。
- 手机轻量：iOS 对第三方 App 限制很多，手机只当入口和通知端，计算和执行放在电脑与后台。
- 可迁移：用户将来会换 Mac、加服务器、换模型供应商，记忆和配置丢了就前功尽弃。
- 先建开发工厂：用户一个人加 AI 开发，后续所有功能都从“Agent 可靠地写出并验证代码”里来。但工厂只是手段，见第 3 节的修正。

**范围**

| 包含 | 排除 |
| --- | --- |
| 手机、电脑、浏览器、语音与耳机、未来可穿戴设备 | 全屋智能、家电、家庭传感器、安防 |
| 个人位置与通勤、学习与工作工具、第三方服务 | “定风台”交易研究项目的数据与权限（可复用开发工具，业务隔离） |
| 个人数据与记忆、多 Agent 执行、多 Agent 开发 |  |

长期目标是推广给其他用户，所以单用户假设可以写在配置里，但不要写死在代码里（例如所有表都带 `owner_id`）。

## 3. 架构审查结论（已作用到后文的方案里）

原设计方向正确，但有三个会拖垮进度的问题：D0 工厂本身容易变成一个产品；“后台持续运行”和“只有一台笔记本”冲突；手机到电脑的网络通路没有设计。Claude Code 可以对下表结论提出异议，但要带证据和替代方案。

| # | 问题 | 影响 | 处理方式 |
| --- | --- | --- | --- |
| 1 | D0 列了 17 项能力，等于另一个产品 | 可能数周没有一行 Personal OS 代码 | D0 = 配置 + 约定 + 少量脚本。并行、隔离、子 Agent、skills 由 Claude Code 自带，不自写调度器。D0 的验收需求就是 V0.1 的第一个真实切片 |
| 2 | 后台需要常开，但只有一台会合盖的笔记本 | 电脑睡眠时手机指令没人接 | V0.1 的 Hub 跑在同一台 PC，但是独立进程、走网络接口。桌面 Agent 主动连向 Hub，以后把 Hub 搬到小 VPS 只改配置。手机端必须显示“电脑离线” |
| 3 | 手机如何连到家里电脑没有设计 | 公网暴露端口有安全风险 | 用 Tailscale 私有网络，Hub 只监听本机和 Tailscale 网卡 |
| 4 | V0.1 把“屏幕理解 + 鼠标键盘”列为 P0 | 最大技术风险被放在第一版 | “打开网页和编程环境”用命令行就能做（`start <url>`、`code <folder>`）。GUI 自动化推到 P1，V0.1 只用 UIA 做“窗口是否已打开”的验证 |
| 5 | “任务完成验证”没有定义证据 | AI 自称完成就更新成果 | 引入 Evidence 实体：编译/测试结果、git 提交、文件、用户确认。代码层面禁止仅凭模型输出把任务标为完成 |
| 6 | 学习任务里 AI 代做与学会冲突 | 学术诚信风险，也违背“增强真实能力” | CIS 课程任务默认 Human-led：解释、提示、查错，不生成可直接提交的作业答案 |
| 7 | 遗漏的基础能力 | 后期补很痛 | 从第一天就做：统一审计日志、幂等键、设备配对 token、数据库 schema 迁移、凭据安全存储、紧急停止、每次模型调用的成本记录、时区处理 |
| 8 | 19 个逻辑模块里多数在 V0.1 不需要独立存在 | 过度工程 | 模块化单体。Event Bus、Workflow Engine、Sync Service、向量库、PostgreSQL、Tauri 在 V0.1 都不做；事件日志和任务队列用 SQLite 表实现 |
| 9 | 候选技术里的 Docker | 容器控制不了宿主 Windows 桌面，反而增加复杂度 | 本地开发用 uv 锁版本即可。Docker 只在把 Hub 部署到服务器时使用 |
| 10 | 情境感知会采集位置、活动等敏感数据 | 隐私与维护成本 | V0.1 只用时间、日程、设备在线状态，不采集位置。所有情境数据带来源和失效时间 |
| 11 | 原生 Windows 版 Claude Code 没有沙箱 | Agent 运行的命令直接作用在你的电脑上 | 保持默认的逐条确认模式，只给 lint、测试等安全命令设免确认；用 deny 规则禁止读 .env、强推和递归删除；永不使用跳过权限的模式。好处是真实 GUI 验证可以直接在本机跑 |
| 12 | 用户自述“容易花大量时间设计迟迟不执行” | 这个项目本身也可能变成设计陷阱 | 每个切片都用用户当天能真实使用的场景验收。运行指标只追踪“通过验证并被用户用起来的功能” |

**关于购买 Mac**：同意推迟。Hub、Windows 桌面 Agent、PWA 都不需要 Mac。真正需要 Mac 的时点是开发原生 SwiftUI、App Intents、锁屏小组件或发 TestFlight；或者想开始做 macOS 适配器。提前买不会降低迁移成本，因为迁移成本由架构（适配器分层 + 数据导出）决定。过渡期如需短暂使用 Xcode，可评估云 Mac 租用（价格未核实）。

## 4. 默认技术架构

默认方案是一个 Python 模块化单体 Hub + 一个独立的 Windows 桌面 Agent 进程 + 一个 PWA 手机网页，数据全部在 SQLite 和一个文件目录里。这是能跑通手机到电脑闭环的最少部件，同时保留了所有将来拆分的接缝。

```text
 iPhone (PWA / iOS 快捷指令 / ntfy)
    │  HTTPS over Tailscale  ▲ ntfy 推送
    ▼                        │
 ┌──────────────── Hub (FastAPI 模块化单体) ────────────────┐
 │ 任务与会话 · 记忆 · 意图与规划 · 运行与队列 · 权限与审计 · 设备与推送 │
 │ [ SQLite + FTS5 · 文件目录 ]  ← 唯一的状态所有者          │
 └───────▲──────────────────────────────┬─────────────┘
         │ 结果与证据 (WebSocket，        │ 结构化调用
         │ 由桌面 Agent 主动连接)          ▼
 ┌───────┴──────────────┐        模型供应商（经 ModelProvider 适配层，可替换）
 │ 桌面 Agent (Windows)  │
 │ 动作白名单 + 执行后验证 │ ── 打开并检查 ──▶ Windows 应用（VS Code、浏览器）
 └──────────────────────┘
```

桌面 Agent 主动连向 Hub，所以 Hub 以后搬到服务器时电脑不需要开放任何入站端口；所有状态只在 Hub 的 SQLite 与文件目录里。

### 4.1 组件与边界

- **Hub**（`apps/hub`，FastAPI）：唯一的状态所有者。内部按包分模块：`tasks`（目标/项目/任务/Workspace）、`sessions`（工作会话与状态快照）、`memory`、`planner`（意图理解与拆解）、`runs`（Agent 运行与步骤）、`jobs`（SQLite 任务队列）、`permissions`、`audit`、`devices`、`notify`、`backup`、`models`（模型适配层）。模块之间只通过各自的 `service.py` 公开函数和 Pydantic 类型交互，用 import-linter 类工具在 CI 里强制。
- **桌面 Agent**（`apps/desktop_agent`）：只执行、不思考。主动用 WebSocket 连接 Hub，接收 ActionRequest，在白名单内执行并自带验证，返回 ActionResult。通过 `DesktopController` 接口访问系统，实现类为 `WindowsAdapter`，将来加 `MacOSAdapter`。
- **PWA**（`apps/web`，React + TypeScript + Vite）：今日任务、一键开始、文字命令框、运行状态、确认按钮。手机和电脑浏览器共用。
- **共享契约**（`packages/contracts`）：ActionRequest/ActionResult、命令、事件的 Pydantic 模型，导出 JSON Schema 并生成 TypeScript 类型。任何跨进程接口先改这里。

### 4.2 动作契约（执行层的核心）

每个动作都必须声明：`name`、参数 schema、`risk_level`（P0–P4）、是否可逆、`timeout`、`verify()`。请求带 `idempotency_key`，Agent 对同一 key 只执行一次。结果包含 `status`（succeeded / failed / needs\_user / cancelled）和 `evidence[]`（进程列表、窗口标题、截图路径、命令输出）。执行方式优先级：官方 API → 命令行 / 系统接口 → Playwright → UIA 控件操作 → 视觉 + 鼠标键盘。

V0.1 动作清单：`open_url`、`open_folder_in_editor`、`launch_app`（白名单）、`read_file`（限定目录）、`run_command`（白名单命令，如 `g++`、测试）、`capture_workspace_state`、`screenshot`。

### 4.3 数据模型

所有表都有：`id`（ULID）、`owner_id`、`created_at`/`updated_at`（UTC）、`source`、`version`。记忆类记录加 `provenance`（raw / user\_confirmed / ai\_inferred / verified）、`confidence`、`expires_at`、`sensitivity`。

| 实体 | 关键字段 | V0.1 |
| --- | --- | --- |
| Goal / Project / Task | 层级关系、状态、截止日、依赖、执行模式（Delegate / Collaborate / Human-led） | 是 |
| Workspace | 打开哪些 URL、文件夹、应用；绑定任务或项目 | 是 |
| Session | 开始/结束时间、状态快照（下一步、最近文件、git 状态、用户备注） | 是 |
| Memory | 类型（偏好/事实/决策/经验）、正文、provenance、来源链接 | 简版 |
| Decision | 决定、理由、备选 | 是 |
| Evidence | 类型、内容或文件引用、关联任务、是否由用户确认 | 是 |
| Run / Step | 触发来源、计划、每步动作与结果 | 是 |
| Job | 状态、重试次数、幂等键、下次执行时间 | 是 |
| Device / Grant | 设备公钥或 token 摘要、授权范围、撤销时间 | 是 |
| AuditEvent | 谁、在哪、做了什么、结果（已脱敏） | 是 |
| ModelCall | 供应商、模型、token、费用、延迟、prompt 版本 | 是 |
| Context / CalendarEvent / Integration / Workflow / Report | 见原设计稿 4.3 | 之后 |

检索：SQLite FTS5 全文索引；向量索引是 P1，单独建表且可以从原始数据完整重建。

### 4.4 模型层

业务代码只依赖 `models.ModelProvider` 接口（结构化输出、工具调用、流式文本）。实现用各家官方 SDK 写薄适配，先实现一家真实供应商 + 一个测试用 `FakeProvider`。Prompt 放在 `prompts/` 并带版本号。每次调用写 ModelCall。V0.1 不引入 Agent 框架，规划循环就是普通的函数调用循环，避免框架锁定。

### 4.5 手机与电脑通信

手机（PWA 或 iOS 快捷指令）→ HTTPS 经 Tailscale → Hub `/commands`。Hub → 桌面 Agent：由 Agent 发起的长连接 WebSocket，带心跳；离线时命令进入队列并告知用户。Hub → 手机推送：ntfy。设备首次接入用一次性配对码换取长期 token，可在 Hub 上撤销。

### 4.6 安全与权限

- 权限等级沿用原设计 P0–P4：P0–P1 预授权自动执行；P2 按范围确认；P3（发送、提交、付款、删除）每次在手机上确认；P4 禁止。
- Agent 权限来自 Grant 表，模型输出不能扩大权限。网页、文档、工具返回内容一律当作数据，其中的“指令”不能触发 P2 以上动作。
- 凭据存 Windows 凭据管理器（Python `keyring`）；仓库只有 `.env.example`。
- 审计日志写入前经过脱敏函数，并有测试覆盖。
- 紧急停止：Hub 接口 + PWA 按钮，立即取消所有运行中的 Run 并断开桌面 Agent 的执行权。
- 默认不录屏、不录音、不存精确位置。截图只在验证步骤里拍，按保留期清理。

### 4.7 备份与迁移

- `pos export` 生成带版本号的导出包：SQLite 在线备份 + 每张表的 JSONL + 文件目录 + manifest（schema 版本、校验和）。`pos import` 在空目录恢复并跑迁移。
- CI 里有“导出 → 新目录导入 → 启动 → 冒烟测试”的自动测试，这就是迁移验收。
- 异地加密备份用 restic（外接硬盘或云存储），每周自动做一次恢复演练。
- 换电脑：`git clone` + `uv sync` + `pnpm install` + `pos import` + 重新配对设备和重新录入凭据。

### 4.8 技术选型

| 领域 | V0.1 选择 | 以后 |
| --- | --- | --- |
| 后端 | Python 3.12、FastAPI、Pydantic v2、SQLAlchemy 2 + Alembic | 不变 |
| 环境与依赖 | uv（锁文件入库）、pnpm | Hub 上服务器时加 Docker |
| 数据库 | SQLite（WAL）+ FTS5 | 多用户或云端时 PostgreSQL |
| 前端 | React + TypeScript + Vite，PWA | 原生 iOS（SwiftUI） |
| 桌面执行 | Python、psutil、pywinauto（UIA） | Playwright、更多 GUI 动作、托盘程序 |
| 质量 | ruff、pyright（核心模块 strict）、pytest、Vitest、Playwright 端到端 | 不变 |
| CI | GitHub Actions，windows-latest + ubuntu-latest | 不变 |
| 网络与推送 | Tailscale、ntfy | 对外推广时换成云端 Hub + 正式推送 |
| 模型 | 官方 SDK + 自写适配层 | 按需评估网关库 |

## 5. 借力清单：复用什么、自研什么

原则：现成工具能满足 80% 以上需求就集成；只自研本项目独有的东西（记忆模型、动作契约、权限与验证）。对一个候选项目有疑问时，先做一个不超过半天的 spike，带可运行的验收脚本，结论写进 `docs/decisions/`。下表“改为自研的条件”就是触发重新评估的信号。

| 能力 | 直接复用 | 自研部分 | 改为自研或换工具的条件 |
| --- | --- | --- | --- |
| 编码 Agent、并行、隔离 | Claude Code 自带的子 Agent、`claude --worktree` 并行会话、权限系统、plan mode | 无 | 不自写调度器。只有当 Claude Code 无法表达某种必要流程时，才写小脚本补上 |
| 工程方法 | pstack 官方 Claude Code 插件（MIT） | 本项目的验证 skill、任务卡 skill | 见第 6 节 |
| 给 Claude Code 的浏览器验证 | Playwright MCP（微软官方） | 无 | — |
| 手机入口 | PWA + iOS 快捷指令（听写 → POST） | 页面本身 | 需要锁屏小组件、App Intents、后台定位时 → 原生 iOS（那时再考虑 Mac） |
| 网络通路 | Tailscale | 无 | 推广给其他用户时，改为云端 Hub + 桌面 Agent 主动连接 |
| 手机推送 | ntfy（开源，可自建） | 通知策略（低打扰、合并） | 做原生 App 时换 APNs |
| 打开工作环境 | Windows `start`、VS Code `code` CLI、psutil | Workspace 定义、状态快照与恢复逻辑 | — |
| Windows 控件操作 | pywinauto（UIA 后端）作为库 | 动作契约、权限、验证、审计的包装 | — |
| 通用 Windows 电脑操控 | Windows-MCP（MIT）只作开发期参考和实验工具 | 产品执行层自己包装 | 它给 Agent 很宽的系统权限，没有我们需要的授权与审计，所以不直接暴露给产品里的模型 |
| 复杂多应用 GUI 任务 | 微软 UFO2（MIT，UIA + 视觉混合）列为 P1 评估对象 | — | P1 spike：在 5 个固定任务上的成功率和耗时达标，就作为可选后端接入；不达标就继续用自己的 UIA 动作 |
| 浏览器自动化 | Playwright（Python） | 登录态管理、网页内容当数据的隔离 | — |
| 数据库与检索 | SQLite、FTS5；P1 用 sqlite-vec 做向量 | 数据 schema | 云端多用户时换 PostgreSQL + pgvector |
| 长期记忆框架 | mem0、Letta 只参考设计，不作核心存储 | 记忆模型（来源、可信度、用户确认、导出） | “记忆独立于模型且可导出”是硬需求，第三方框架可以作为可替换的检索或提取组件接入 |
| 模型调用 | 各家官方 SDK | 薄适配层 + 成本记录 | 接入第 3 家供应商时评估网关库（锁版本、审查供应链） |
| 任务队列 | — | SQLite job 表 + worker（约百行） | 出现多机、长周期工作流时评估 Temporal / DBOS 等 |
| 自动化工作流 | V0.1 不做 | — | V0.3 对比 n8n 与自研 Trigger→…→Update 引擎 |
| 异地备份 | restic | 备份调度与恢复演练脚本 | — |
| 对外工具接口 | MCP 官方 Python SDK（P1） | 把 Personal OS 的任务和记忆暴露为 MCP server，让 Claude Code 等 Agent 也能读写 | — |
| Canvas 课程 | Canvas LMS REST API（P1） | 同步逻辑 | 未验证：学校是否允许学生生成个人访问 token。不允许就改为日历订阅或手动导入 |

## 6. 开发方法：直接用官方 pstack 插件

结论：pstack 官方支持 Claude Code，直接安装官方插件，不自己重造。依赖 Cursor 的步骤在 Claude Code 里会自动跳过。本项目只在它之上补充自己的验证 skill 和任务卡规范。

### 6.1 pstack 是什么（据官方 README 与指南）

- MIT 开源的 skills、子 Agent 和 playbook 集合，作者 Lauren Tan（poteto）。主旨是写更少但更高质量的代码，并把验证做到足以让多个 Agent 放心并行。
- 入口 `/poteto-mode`：根据目标选一个 playbook（共 23 个，如 investigation、bug fix、feature、refactoring、prototype、orchestrate），把步骤写成待办清单，按需调用其他 skill。在 Claude Code 里命令带前缀：`/pstack:poteto-mode`。
- 24 条短原则，如 laziness-protocol、prove-it-works、fix-root-causes、type-system-discipline。
- 使用方式强调“别微管”：只描述目标和“怎样算完成”。例如：`/pstack:poteto-mode 给 Hub 加任务 CRUD 接口，验收是 T-0003 任务卡里的命令全部通过`。
- Claude Code 安装方式（官方 README）：`/plugin marketplace add cursor/plugins` → `/plugin install pstack@cursor-plugins` → `/pstack:setup-pstack`。第三方市场默认不自动更新，这正好等于锁定版本。
- 依赖 Cursor 的部分（Claude Code 里用不了）：`/loop` 长任务、自定义模式、agents 窗口、Bugbot、automations。README 说这些步骤在 Claude Code 里会被跳过并留一行说明。`control-cli`、`control-ui` 在另一个插件 cursor-team-kit 里，暂不安装。
- 模型分配：pstack 默认把委派工作给 grok、难题给 opus。`/pstack:setup-pstack` 会把你的选择写进 `~/.claude/rules/pstack-models.md`。在 Claude Code 里只选 Claude 模型（如 sonnet 做委派、opus 做难题和审查）；grok 是否可选以 setup 的提示为准。这个文件在用户目录不在仓库里，换电脑时重新跑一次 setup。

### 6.2 在本项目里怎么用

常用 skill（安装后都带 `pstack:` 前缀）：

| skill | 什么时候用 |
| --- | --- |
| poteto-mode | 每张任务卡的默认入口 |
| architect、interrogate、blast-radius | 改接口、改数据模型、动核心模块前 |
| tdd | 写新功能、修 Bug |
| create-verification-skill、maintain-verification-skill | 为 Hub、桌面 Agent、PWA 各写一个“真实行为验证”skill，放进 `.claude/skills/` |
| reflect、correct | 同类错误第二次出现时，输出写 `docs/lessons.md` |
| show-me-your-work | 较长的自主运行，留下决策记录 |
| unslop、no-comments | 提交前清理 |
| how、why、teach、in-your-own-words | 你想弄懂某段代码时，直接自己用：`/pstack:teach Hub 的任务队列是怎么工作的` |

### 6.3 值得借鉴的原则 → 本项目的可执行版本

- 目标 + 完成标准 → 每张任务卡必须有 `acceptance`（可运行的命令或可观察状态），没有就不开工。
- 先复现、修根因 → Bug 类 PR 必须包含一个先失败后通过的测试。
- 在真实界面上证明 → 每个模块一个 `scripts/verify/<module>.py`，真的启动 Hub、真的让桌面 Agent 打开窗口，然后检查状态并截图。原生 Windows 版 Claude Code 没有沙箱，可以直接跑（会弹权限确认）。
- 类型纪律 → 核心模块 pyright strict；跨进程数据只用 contracts 里的类型。
- 写更少的代码 → 审查时先问“能否删掉或用现成库替代”。
- 纠正重复错误 → 同类错误第二次出现，必须转成 lint 规则、测试、类型约束、hook 或 skill 之一，并在 lessons 里记录。
- 验证可靠后再并行 → 见 6.4。

### 6.4 并行度与自治程度的升级门槛

| 阶段 | 配置 | 升到下一阶段的条件 |
| --- | --- | --- |
| 1（现在） | 1 个 Claude Code 会话；只读 reviewer 子 Agent；你审每个 PR | `tools.check` 与至少 2 个模块的 verify 脚本稳定可用 |
| 2 | 主会话 + 2–3 个 `claude --worktree <名字>` 会话（各开一个终端窗口），各自只改 `allowed_paths` | 连续 10 个 PR 无人工返工、无合并冲突过夜 |
| 3 | 低风险任务（文档、测试、内部重构）可自主完成到 PR | 连续 4 周的验证通过率与返工率达标（标准由你定） |
| 4 | 经严格验证的低风险流程可自动合并 | 你明确批准 |

并行规则：核心文件（contracts、数据库迁移、CLAUDE.md）同一时间只有一个会话能改；接口先合并，再并行写两端；每个会话对应一张任务卡，防止重复开发。衡量指标是“每周通过验证并合并的任务数”和“返工时间”，不是 PR 数、代码行数或 token。

## 7. D0 开发工厂（最小可行版）

D0 是一个带规矩的仓库，不是一个系统：CLAUDE.md + `.claude/` 里的权限、子 Agent 和 skills + pstack 插件 + 一条 `tools.check` 命令 + CI + 任务卡模板。时间盒：如果 2 个工作日的搭建后仍未开始写 V0.1 的第一个切片，就停下来砍范围。

### 7.1 仓库结构

```text
personal-os/
  CLAUDE.md                 # 全仓规则（短，指向 docs/）
  .mcp.json                 # 项目级 MCP（Playwright）
  .claude/
    settings.json           # 权限规则、启用的插件（入库）
    agents/                 # architect.md / reviewer.md / tester.md
    skills/
      task-card/            # 写任务卡、拆任务
      verify-hub/           # 如何真实验证 Hub
      verify-desktop-agent/ # 如何真实验证桌面 Agent
      evidence/             # 证据包格式与 PR 模板
  apps/
    hub/                    # FastAPI，模块化单体
    desktop_agent/          # Windows 执行进程
    web/                    # PWA
  packages/contracts/       # 跨进程类型 + JSON Schema
  prompts/                  # 产品内的模型 prompt（带版本）
  tools/                    # check.py、report.py、导入导出 CLI
  scripts/verify/           # 真实行为验证脚本
  tests/
  docs/
    HANDOFF.md              # 本文档
    source/                 # 两份原始设计稿 + course-policy.md
    ARCHITECTURE.md
    SETUP.md                # 新电脑从零搭建步骤
    decisions/              # ADR：0001-xxx.md
    tasks/                  # 任务卡 T-0001.md …
    lessons.md
    progress.md             # 由 tools/report.py 生成
    backlog.md              # V0.1 期间出现的新想法
  .evidence/                # 验证证据（不入库，PR 里附摘要）
  .github/workflows/ci.yml
  pyproject.toml  uv.lock  package.json  pnpm-lock.yaml  .env.example  .gitignore
```

### 7.2 主要配置

下面是示意，写入前对照 Claude Code 官方文档（code.claude.com/docs）核对。设置文件是严格 JSON，不能写注释。

```json
{
  "$schema": "https://json.schemastore.org/claude-code-settings.json",
  "permissions": {
    "allow": [
      "Bash(uv run python -m tools.check)",
      "Bash(uv run pytest *)",
      "Bash(git status)",
      "Bash(git diff *)",
      "Bash(git log *)"
    ],
    "deny": [
      "Read(./.env)",
      "Read(./.env.*)",
      "Bash(git push --force *)",
      "Bash(rm -rf *)"
    ]
  }
}
```

上面是 `.claude/settings.json`。pstack 插件是否也写进这个文件（`enabledPlugins` / `extraKnownMarketplaces`，让换电脑时自动提示安装），由 Claude Code 在 D0-03 核对官方写法后决定。

```markdown
---
name: reviewer
description: Read-only reviewer. Use before opening any PR to check correctness, security, missing tests and scope creep against the task card.
tools: Read, Glob, Grep, Bash
model: opus
---
Review the diff against the task card's acceptance criteria and docs/ARCHITECTURE.md.
Do not edit files. Reject if: no evidence bundle, acceptance not demonstrated,
files changed outside allowed_paths, new dependency without a decision record,
secrets or personal data in logs. Report findings as a checklist.
```

上面是 `.claude/agents/reviewer.md`。另建 `architect.md`（只读，输出接口与任务拆分）和 `tester.md`（负责写测试和 `scripts/verify/`，跑真实验证）。

```json
{
  "mcpServers": {
    "playwright": {
      "command": "npx",
      "args": ["@playwright/mcp@latest"]
    }
  }
}
```

上面是 `.mcp.json`，用 `claude mcp add --scope project playwright -- npx @playwright/mcp@latest` 生成。Windows 上如果启动失败，试把 command 改成 `cmd`、args 改成 `["/c", "npx", "@playwright/mcp@latest"]`（未验证）。

CLAUDE.md 保持简短（建议 100 行以内），内容提纲：项目一句话 + 需要全局背景时读 `docs/HANDOFF.md`（不要用 `@` 整篇导入，太长）；常用命令；模块边界规则；任务循环（第 1 节）；完成定义；禁止事项；用户是新手，给用户的操作步骤要具体到每条命令。

### 7.3 任务卡格式

```markdown
---
id: T-0007
title: Desktop agent opens a URL and verifies the browser window
status: todo            # todo | in_progress | review | done | blocked
risk: low               # low | medium | high
depends_on: [T-0005]
allowed_paths: [apps/desktop_agent/**, packages/contracts/**, tests/desktop_agent/**]
needs_user_decision: false
---
## Goal
## Context / inputs
## Out of scope
## Acceptance (runnable)
- `uv run pytest tests/desktop_agent -q` passes
- `uv run python scripts/verify/desktop_agent.py open_url` exits 0 and saves a screenshot
## Verification evidence
(.evidence/T-0007/ 文件清单)
## Errors & lessons
```

### 7.4 质量门禁与证据

- `uv run python -m tools.check`：ruff → pyright → 模块边界检查 → pytest → 前端 lint/类型/测试。本地和 CI 跑同一条命令。
- CI 在 windows-latest 和 ubuntu-latest 上都跑；桌面 Agent 的 GUI 验证只在本机跑，结果进证据包。
- 证据包 `.evidence/<任务ID>/`：命令及输出、截图、相关日志片段、`summary.md`（逐条对应验收标准）。PR 描述贴 summary。
- D0 稳定后可加 hook（例如每次改完 Python 文件自动跑 ruff format），把“提醒”变成自动执行。

### 7.5 版本管理、成本与进度

- `main` 受保护；每张任务卡一个分支 `t/0007-open-url`，squash 合并；提交信息用 Conventional Commits。
- 成本：Claude Code 用量含在 Pro / Max 订阅里，有使用上限。主会话用默认模型，只在架构设计、疑难 Bug、审查时用 opus；一个任务结束后用 `/clear` 清空上下文再开始下一个；同时不超过 3 个会话。产品自身的模型费用看 ModelCall 表。
- 进度：`tools/report.py` 从任务卡和 git log 生成 `docs/progress.md`（完成 / 进行中 / 阻塞 / 本周合并 / 返工）。
- 模型切换：开发侧用 `/model`；产品侧用模型适配层。
- 开发环境迁移：项目配置全在仓库（CLAUDE.md、`.claude/`、`.mcp.json`）；用户级的 `~/.claude/` 只放个人偏好。`docs/SETUP.md` + `scripts/bootstrap.ps1` 能在新电脑上一次搭好。

### 7.6 D0 任务清单

- [ ] D0-01 仓库骨架、pyproject、package.json、`tools.check`、CI 全绿（含一个占位测试）
- [ ] D0-02 确认用户已装好 pstack 插件（第 9 节第 9 步），读一遍 poteto-mode 的原则索引，把和本项目冲突的地方写进 CLAUDE.md
- [ ] D0-03 CLAUDE.md、`.claude/settings.json`、3 个子 Agent、`.mcp.json`
- [ ] D0-04 用 `/pstack:create-verification-skill` 和手写，得到 task-card / evidence / verify skills 初版；PR 模板
- [ ] D0-05 小实验：用脚本打开记事本并截图、用 pywinauto 读到它的窗口标题，证明本机真实验证可行；结论写入 decisions
- [ ] D0-06 ARCHITECTURE.md（从本文档第 4 节精简）与前 3 个 ADR：模块化单体、SQLite、桌面 Agent 主动连接
- [ ] D0-07 `tools/report.py` + `docs/progress.md`

**D0 验收**：用 V0.1 的 S1 作为真实需求跑一遍完整流程：理解需求 → 拆任务卡 → 选择子 Agent → 写代码 → 自动测试 → 真实验证 → PR 附证据 → 用户审核 → lessons / decisions 更新。全部步骤在 git 和任务卡里可追溯。

## 8. V0.1 实施路线

V0.1 只交付一个纵向闭环：用户在 iPhone 上说“开始今天的 CIS 编程学习”，Windows 电脑打开对应网页和 VS Code 项目并显示上次的下一步，结束时保存状态，完成时凭证据更新进度。拆成 8 个切片，每个切片单独可演示。

### 8.1 第一条手机到电脑的真实闭环

1. iPhone 快捷指令“开始学习”：听写文本 → `POST https://<pc>.<tailnet>.ts.net/commands`（带设备 token）。PWA 的输入框走同一接口。
2. Hub 记录 Command，调用 planner：意图 = start\_task，匹配任务“CIS 编程学习”（置信度低就通过 ntfy 反问一句）。
3. Hub 创建 Run 和 Session，读取该任务的 Workspace 与上次快照，生成动作列表（open\_url × n、open\_folder\_in\_editor）。
4. 动作经已连接的 WebSocket 发给桌面 Agent；桌面离线 → 进队列 + 推送“电脑离线”。
5. 桌面 Agent 逐个执行并验证（进程存在、窗口标题匹配），回传 ActionResult 与证据。
6. Hub 更新 Run，在电脑上弹出 PWA 会话页（下一步 + 上次备注），并推送手机“已就绪：下一步是 …”。
7. 结束时用户点“暂停”或说“今天先到这”：保存快照（用户一句话备注 + 项目目录 git 状态 + 最近修改的文件）。
8. 完成时：运行白名单内的编译/测试命令得到证据，用户确认后任务标为完成、进度更新。

### 8.2 切片

| 切片 | 内容 | 依赖 | 可并行 | 难度 | 验收标准 |
| --- | --- | --- | --- | --- | --- |
| S1 Hub 核心 | FastAPI + SQLite + Alembic；Goal/Project/Task/Workspace CRUD；审计日志；`pos export/import` v0 | D0 | — | 低 | API 测试通过；导出到新目录导入后数据一致（自动测试） |
| S2 桌面 Agent 骨架 | 主动 WebSocket、配对 token、心跳、动作注册表与白名单；open\_url、open\_folder\_in\_editor、launch\_app 及其 verify | S1 的 contracts | 与 S4 并行 | 中 | 本机真实运行：打开测试 URL 和临时文件夹，verify 识别到窗口，存截图；重复发送同一幂等键只执行一次 |
| S3 启动与恢复 | Session 模型；start\_session / pause\_session；快照保存与恢复 | S1、S2 | 与 S5 并行 | 中 | 开始 → 暂停 → 再开始，打开同样的资源并显示同样的下一步 |
| S4 手机入口 | PWA（今日、一键开始、命令框、运行状态、确认）；Tailscale 访问；iOS 快捷指令；ntfy 推送 | S1 | 与 S2 并行 | 低 | iPhone 在蜂窝网络下经 Tailscale 触发 S3；电脑离线时手机显示离线 |
| S5 意图理解 | 命令 → 意图（start\_task / create\_task / add\_note / pause）+ 任务匹配；模型适配层 + FakeProvider；ModelCall 成本记录 | S1 | 与 S3 并行 | 中 | 约 30 条中英文说法的评测集达到用户认可的准确率；低置信度时反问而不是猜 |
| S6 编程辅助与完成验证 | Human-led 辅导面板（解释报错、给提示）；白名单编译/测试命令；Evidence 与完成确认 | S3、S5 | — | 中 | 用一道真实 C++ 练习走完全程；测试证明仅有模型输出无法把任务标为完成 |
| S7 记忆、进度、备份 | Memory 表（含 provenance、用户纠错）；每日看板；定时备份 + restic + 恢复演练 | S1 | 可从 S1 后开始 | 低 | 在空目录恢复后冒烟测试通过；用户修改的记忆在下次会话中生效 |
| S8 权限与审计加固 | 风险等级与手机确认流；紧急停止；日志脱敏测试；prompt injection 测试 | S2、S4 | 可与 S6 并行 | 中 | 含恶意指令的网页文本不会触发动作；紧急停止后所有 Run 取消；日志里无 token |

推荐顺序：S1 →（S2 ‖ S4）→（S3 ‖ S5）→ S6，S7 与 S8 穿插。并行前先合并 contracts 里的接口定义。阶段 1 单线程时就按这个顺序串行做。

### 8.3 主要风险

| 风险 | 应对 |
| --- | --- |
| 笔记本睡眠时桌面 Agent 和 Hub 都离线 | V0.1 接受并明确显示；V0.2 把 Hub 搬到常开设备。Wi-Fi 笔记本的远程唤醒不可靠，不作为方案 |
| Windows 的前台窗口保护会阻止程序把窗口切到最前 | verify 只检查窗口存在，不强求前台；在 S2 里实测 |
| iPhone 需要保持 Tailscale 连接 | 在 S4 实测耗电与重连；必要时用快捷指令先启用 VPN（未验证） |
| Claude Code 直接在本机执行，可能误操作 | deny 规则 + 每个 PR 合并前你看一眼改动；所有代码在 git 里，出错可以回退 |
| AI 辅导变成代写作业 | S6 的 prompt 与测试明确限制为讲解和提示；按课程学术诚信规定执行 |
| 范围蔓延 | 新想法一律进 `docs/backlog.md`，V0.1 期间不开新切片 |

## 9. 新手逐步操作指南（你本人照做）

照着第 1 步到第 12 步做完，你的电脑就能让 Claude Code 开始开发这个项目。预计 1.5–3 小时（假设网络正常、电脑没有学校或公司的管理限制）。每一步都写了“做什么、为什么、成功的样子”。卡住时看本节最后的「遇到问题怎么办」。

现在不要装 Docker、PostgreSQL，也不要为此买 Mac。

### 开始前：5 个概念

| 词 | 意思 |
| --- | --- |
| 终端 / PowerShell | 一个打字下命令的窗口。你输入一行命令，按回车，电脑执行并显示结果 |
| 命令 | 下面灰色代码框里的每一行。一次复制一行，粘贴进终端，按回车 |
| 路径 | 文件在电脑里的地址，例如 `C:\dev\personal-os` |
| Git / 仓库 | Git 记录代码的每一次修改，可以随时回到以前的版本。“仓库”就是被 Git 管理的项目文件夹；GitHub 是存仓库的网站 |
| Claude Code | 在终端里运行的 AI 编程助手。它能读写你项目里的文件、运行命令，每次要做有风险的事会先问你 |

### 第 1 步：打开 PowerShell

1. 按键盘上的 Windows 键，输入 `terminal`，打开“终端”（Windows Terminal）。找不到就输入 `PowerShell`。
2. 不需要“以管理员身份运行”。
3. 窗口里出现类似 `PS C:\Users\你的用户名>` 的一行，说明打开的是 PowerShell。
4. 粘贴命令：按 Ctrl+V，或在窗口里点右键。粘贴后按回车执行。

### 第 2 步：允许运行脚本（只做一次）

Windows 默认禁止运行脚本，之后装的 pnpm 等工具会因此报错。运行：

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned
```

如果问你是否更改，输入 `Y` 再回车。这只影响你自己的账户，允许运行本机脚本和有签名的下载脚本。

### 第 3 步：安装基础软件

先检查 winget（Windows 自带的软件安装器）能不能用：

```powershell
winget --version
```

显示版本号就继续。显示“无法识别”：打开 Microsoft Store，搜索“应用安装程序”（App Installer），点更新，然后重开终端。

然后一行一行运行下面的命令（每行装一个软件，等它结束再运行下一行）。第一次可能要你输入 `Y` 同意条款；弹出“是否允许此应用对你的设备进行更改”时点“是”。

```powershell
winget install --id Git.Git -e
winget install --id GitHub.cli -e
winget install --id OpenJS.NodeJS.LTS -e
winget install --id astral-sh.uv -e
winget install --id Microsoft.VisualStudioCode -e
```

各是什么：Git 管理代码版本；GitHub CLI（`gh`）在终端里操作 GitHub；Node.js 运行前端工具；uv 管理 Python；VS Code 是写代码的编辑器。

**全部装完后，关掉终端窗口，重新打开一个**（新装的命令要重开才认得）。再运行：

```powershell
npm install -g pnpm
uv python install 3.12
```

检查是否都装好了，每行都应该显示一个版本号：

```powershell
git --version
gh --version
node --version
pnpm --version
uv --version
code --version
```

- [ ] 6 个命令都显示了版本号
- [ ] 已装好 CIS 课程要求的 C++ 编译器（先问清课程用 MSVC、MinGW 还是在线环境；不确定可以之后让 Claude Code 帮你装）

### 第 4 步：告诉 Git 你是谁

把引号里换成你的名字和 GitHub 注册邮箱：

```powershell
git config --global user.name "Your Name"
git config --global user.email "you@example.com"
git config --global init.defaultBranch main
```

### 第 5 步：注册并登录 GitHub

1. 浏览器打开 github.com，注册账号（已有就跳过）。
2. 终端运行 `gh auth login`，按提示用方向键选择、回车确认：
   1. Where do you use GitHub? → `GitHub.com`
   2. Preferred protocol → `HTTPS`
   3. Authenticate Git with your GitHub credentials? → `Yes`
   4. How would you like to authenticate? → `Login with a web browser`
3. 终端会显示一个 8 位验证码。按回车打开浏览器，粘贴验证码，点授权。
4. 运行 `gh auth status`，显示 `Logged in to github.com` 就成功了。

### 第 6 步：安装并登录 Claude Code

Claude Code 需要付费的 Claude 订阅（Pro 或 Max；免费版不含 Claude Code）。先在 claude.ai 开通订阅。Pro 有使用上限，开发多了可能需要升级到 Max，以官方说明为准。

```powershell
irm https://claude.ai/install.ps1 | iex
```

这是官方安装命令，不需要管理员权限，装好后会自动更新。装完**关掉终端重新打开**，检查：

```powershell
claude --version
claude doctor
```

`claude doctor` 会检查安装是否正常。如果安装命令失败，可以改用 `winget install Anthropic.ClaudeCode`（这种方式不会自动更新，要定期运行 `winget upgrade Anthropic.ClaudeCode`）。

### 第 7 步：建项目文件夹和 GitHub 仓库

```powershell
mkdir C:\dev
cd C:\dev
gh repo create personal-os --private --clone
cd personal-os
```

这四行分别是：建一个 `C:\dev` 文件夹；进入它；在 GitHub 上建私有仓库 `personal-os` 并下载到本地；进入项目文件夹。

为什么放 `C:\dev`：路径里没有空格和中文，也不在 OneDrive 同步的“桌面”“文档”里。OneDrive 同步会锁住文件、拖慢工具，经常造成奇怪的错误。

### 第 8 步：放入文档并做第一次提交

```powershell
mkdir docs\source
explorer .
```

`explorer .` 会用文件资源管理器打开当前文件夹。然后：

1. 先让 Windows 显示扩展名：资源管理器顶部“查看” → “显示” → 勾选“文件扩展名”。
2. 把我发给你的 `HANDOFF.md` 放进 `docs` 文件夹。
3. 把两份原始设计稿放进 `docs\source`，改名为 `design-v1.1.md` 和 `handoff-v1.2.md`（确认扩展名是 `.md`，不是 `.md.txt`）。

回到终端，做第一次提交并上传：

```powershell
git add .
git commit -m "docs: add handoff and design documents"
git push
```

成功的样子：浏览器打开 `github.com/你的用户名/personal-os`，能看到 docs 文件夹。这次提交也很重要：Claude Code 的并行会话（worktree）要求仓库里至少有一次提交。

### 第 9 步：第一次启动 Claude Code，学会基本操作

```powershell
cd C:\dev\personal-os
claude
```

第一次启动会打开浏览器让你登录 Claude 账号。回到终端后，它会问是否信任这个文件夹，选 Yes。

| 操作 | 怎么做 |
| --- | --- |
| 给它下指令 | 直接用中文打字，按回车 |
| 打断它 | 按 Esc |
| 切换模式 | 按 Shift+Tab。底部显示 `plan mode on` 时，它只读文件、出计划，不改任何东西 |
| 清空对话，开始新任务 | 输入 `/clear` |
| 看帮助 | 输入 `/help` |
| 粘贴截图 | 按 Alt+V |
| 退出 | 输入 `/exit` |
| 下次接着上次的对话 | 在项目文件夹里运行 `claude --continue` |

**权限确认是你最重要的安全阀。** 它要运行命令或改文件时会问你：

- `Yes`：只允许这一次。
- `Yes, and don't ask again`：以后同类命令不再问。只对查看、测试这类无害命令选它。
- `No`：拒绝，并告诉它你想怎么做。
- 看不懂这条命令时，选 No，然后问它：“这条命令会做什么？有什么风险？”
- 永远不要用跳过权限确认的启动参数（名字里带 `dangerously` 的那个）。

### 第 10 步：安装 pstack 插件

在 Claude Code 里（不是 PowerShell 里）依次输入：

```text
/plugin marketplace add cursor/plugins
/plugin install pstack@cursor-plugins
```

然后输入 `/exit` 退出，再运行 `claude` 重新进入，输入：

```text
/pstack:setup-pstack
```

它会问你给不同工作用哪个模型。只选 Claude 的模型：日常委派选 sonnet，难题和审查选 opus。选完输入 `/pstack`，能看到一串 `pstack:` 开头的命令就装好了。

### 第 11 步：安装 Playwright MCP（让 Claude Code 能操作浏览器做验证）

先在 Claude Code 里输入 `/exit` 退出，回到 PowerShell，确认还在 `C:\dev\personal-os`，运行：

```powershell
claude mcp add --scope project playwright -- npx @playwright/mcp@latest
claude mcp list
```

列表里出现 `playwright` 就成功了。第一次使用时 Claude Code 会问你是否允许这个服务器，选 Yes。这一步失败也没关系，可以留给 Claude Code 在 D0-03 里替你配置。

### 第 12 步：让 Claude Code 开工

1. 运行 `claude` 进入，按 Shift+Tab 直到底部显示 `plan mode on`。
2. 粘贴第 10 节的开场提示词，回车。
3. 它会读文档、检查环境，然后给出计划。认真读计划，有不同意的地方直接打字告诉它。
4. 同意后批准计划，它退出 plan mode 开始干活。之后每次要运行命令或改文件都会问你。
5. 它完成后会开一个 PR（合并请求）。去 GitHub 仓库页面点 Pull requests 查看。

### 之后再做（不急）

- [ ] 做到 V0.1 的 S4 时：电脑运行 `winget install --id tailscale.tailscale -e`，iPhone 从 App Store 装 Tailscale，两边登录同一个账号；iPhone 再装 ntfy App。Claude Code 会告诉你具体怎么配。
- [ ] 做到 S5 时：申请一个产品运行时用的模型 API key（Anthropic Console 或 OpenAI），在后台设月度花费上限。这笔钱和 Claude 订阅是分开的。不要把 key 粘贴到对话里，Claude Code 会给你一条命令把它存进 Windows 凭据管理器。
- [ ] 准备验收材料：一个真实的 CIS 课程文件夹和 1–2 道练习题；“开始 CIS 学习”时要打开的网址清单；一句话写下课程对使用 AI 的规定，存成 `docs/source/course-policy.md`。

### 需要你拍板的决定

- [ ] 产品运行时首选哪家模型，每月预算上限多少。
- [ ] CIS 任务的辅导边界（默认：只讲解和提示，不生成可提交的答案）。
- [ ] 意图理解准确率的及格线（建议先定 90%，低于置信度阈值就反问）。

### 每天怎么用（10–20 分钟）

1. 打开终端，`cd C:\dev\personal-os`，运行 `claude`。
2. 输入 `/pstack:poteto-mode 完成 docs/tasks/T-0003.md`（换成当前的任务卡编号）。
3. 处理它弹出的权限确认和问题。
4. 在 GitHub 上看 PR：读“证据摘要”和“这次学到什么”，点 Files changed 大致看改了哪些文件。
5. 满意就点 Squash and merge 合并。然后在终端运行 `git checkout main` 和 `git pull` 同步到本地。
6. 任务之间输入 `/clear`，让下一个任务从干净的上下文开始。

### 遇到问题怎么办

| 现象 | 处理 |
| --- | --- |
| “无法将 xxx 项识别为 cmdlet” 或 “不是内部或外部命令” | 关掉终端重新打开。还不行，就重新运行那个软件的安装命令 |
| “因为在此系统上禁止运行脚本” | 做第 2 步 |
| winget 无法识别 | 在 Microsoft Store 更新“应用安装程序” |
| Claude Code 登录失败或行为异常 | 运行 `claude doctor`；确认订阅是 Pro 或 Max |
| `git push` 被拒绝 | 不要加 `--force`。把整段输出复制给 Claude Code，问它怎么办 |
| 看不懂任何报错 | 整段复制给 Claude Code：“这是什么意思？下一步我该做什么？” |
| 担心它改坏了东西 | 所有改动都在 git 里。问它：“列出这次改了哪些文件，怎么撤销？” |

### 你和 Claude Code 的分工

| 你做 | Claude Code 做 |
| --- | --- |
| 本节第 1–12 步、订阅和账号、手机上的操作 | 写代码、写测试、配置项目、运行检查和验证 |
| 回答它标出的“需要用户决定”的问题 | 拆任务卡、写文档和决策记录 |
| 在真实场景里试用新功能，说哪里不顺手 | 开 PR，附证据和“这次学到什么” |
| 合并 PR | 记录重复犯的错，并把它变成自动检查 |

## 10. Claude Code 第一次会话

第一次会话的产出是：D0-01 骨架跑绿、D0-03 配置、一份 D0 计划、本机真实验证小实验的结论、接下来的任务卡。不写业务功能。先按 Shift+Tab 进入 plan mode，再把下面这段粘贴给 Claude Code：

```text
你是 Personal OS 项目的技术负责人。先完整阅读 docs/HANDOFF.md，再浏览 docs/source/ 里的两份原始设计稿。
两者冲突时以 HANDOFF.md 为准。用中文和我沟通。我是编程新手：需要我亲自操作时，给我具体到每条命令的步骤，
并说明每条命令是做什么的。

本次会话只做下面这些，不要开始写 V0.1 业务代码：

1. 用 10 行以内复述你对项目和第一阶段目标的理解，列出你不同意或认为有风险的点（每条带理由和替代方案）。
2. 核对本机环境：git、gh、node、pnpm、uv、Python 3.12、code 命令是否可用，pstack 插件和 Playwright MCP 是否已装。
   缺什么就列出来并告诉我怎么装，不要自己装系统软件。
3. 对照 Claude Code 官方文档核对 HANDOFF.md 7.2 节中 CLAUDE.md、.claude/settings.json、.claude/agents、.mcp.json 的写法，指出需要修正的地方。
4. 完成 D0-01：仓库骨架、pyproject + uv、package.json + pnpm、tools/check.py（ruff、pyright、pytest、前端检查）、
   GitHub Actions（windows-latest + ubuntu-latest）。用 `uv run python -m tools.check` 证明本地全绿，输出放进 .evidence/D0-01/。
5. 完成 D0-03：CLAUDE.md、.claude/settings.json（权限规则）、architect / reviewer / tester 三个子 Agent。
6. D0-05 小实验：用脚本打开记事本、截图、用 pywinauto 读到它的窗口标题再关掉，证明本机真实验证可行。结论写入 docs/decisions/。
7. 写出 D0-02、D0-04、D0-06、D0-07 以及 V0.1 S1 的任务卡（按 HANDOFF.md 7.3 格式），放进 docs/tasks/。
8. 提交前让 reviewer 子 Agent 审查。然后开一个 PR，描述里包含：做了什么、证据摘要、需要我决定的问题、
   “这次学到什么”（3–5 句通俗解释），以及我在 GitHub 上审核和合并这个 PR 的具体步骤。

先给我计划，我同意后再动手。安装任何依赖或联网下载前先告诉我。不要把你自己的口头报告当作通过证据。
```

**之后的节奏**：每次会话以一张任务卡为单位（见第 9 节「每天怎么用」）。S4 完成后，从第二天起就用手机启动真实的 CIS 学习，把不顺手的地方直接让 Claude Code 写成新任务卡。

## 参考资料

已打开并读取：

- [Claude Code：在 Windows 上安装](https://code.claude.com/docs/en/setup)
- [Claude Code：设置文件与权限规则](https://code.claude.com/docs/en/settings)
- [Claude Code：子 Agent](https://code.claude.com/docs/en/sub-agents)
- [Claude Code：Skills](https://code.claude.com/docs/en/skills)
- [Claude Code：MCP](https://code.claude.com/docs/en/mcp)
- [Claude Code：常用工作流（worktree、plan mode、恢复会话）](https://code.claude.com/docs/en/common-workflows)
- [pstack 指南 README（cursor/plugins）](https://github.com/cursor/plugins/blob/main/pstack/docs/guide/README.md)
- [pstack README（安装、skills、playbooks、Cursor 依赖）](https://raw.githubusercontent.com/cursor/plugins/main/pstack/README.md)

检索到、未逐页核对：

- [UFO2: The Desktop AgentOS（微软，arXiv）](https://arxiv.org/html/2504.14603v2)
- [Windows-MCP（CursorTouch）概况](https://dev.co/ai/mcp/windows-mcp)
