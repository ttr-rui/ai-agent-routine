# TaskMate · 能说会做的待办智能助理（MCP + Python）

> 课程作业：基于 **Model Context Protocol (MCP)** 构建一个具备「自然语言交互（能说）+ 工具调用执行（会做）」能力的 AI Agent。
> 场景：**帮用户整理任务、拆解目标、生成并维护待办清单**。

---

## 1. 它到底做了什么

| 能力 | 用户说什么 | Agent 做什么（真的会做） |
| --- | --- | --- |
| 加任务 | 「提醒我明天交智能体作业」 | 调 `add_task`，日期自动换算成 2026-10-25，写入 SQLite |
| 拆目标 | 「把课程设计拆成 5 个可执行步骤」 | 调 `batch_add_tasks`，一次性落 5 条子任务并返回 ID |
| 查进度 | 「我今天该干嘛」 | 调 `daily_briefing`，把逾期/今日到期/高优任务汇总成清单 |
| 改任务 | 「把 3 号任务提前到今天，优先级拉满」 | 先 `list_tasks` 确认，再 `update_task(id=3, ...)` |
| 完成/删除 | 「作业做完了」 | 调 `complete_task`，状态落库为 done |
| 看统计 | 「我还有多少事没做」 | 调 `get_stats`，返回各状态数量与逾期数 |

**「会做」的证据**：每次回复下方的「🔧 执行轨迹」会展示 Agent 实际调用了哪个 MCP 工具、传了什么参数、返回了什么；同时侧栏任务看板实时刷新，数据存在 `data/tasks.db`，关掉程序也不会丢。

**看板不止能看**：统计卡片 + 完成率进度条、按状态/逾期筛选、关键字搜索、四种排序、逾期与今日到期高亮、
看板上直接完成/重开/删除（删除需二次确认），以及**一键导出 Markdown 清单和 CSV**（Excel 可直接打开）。

---

## 2. 技术架构

```
┌──────────────────────────────────────────────────────────┐
│  用户（Streamlit 网页 / 命令行 / 语音）                     │
└───────────────┬──────────────────────────────────────────┘
                │  自然语言
┌───────────────▼──────────────────────────────────────────┐
│  Agent 大脑  agent/agent.py                               │
│  · 系统提示词（日期换算 / 先做再说 / 模糊删除先确认）        │
│  · Tool-Calling 循环（最多 8 步，防死循环）                 │
│  · 多轮记忆（SQLite，跨会话持久化）                         │
└───────┬──────────────────────────────┬───────────────────┘
        │ OpenAI 兼容协议（决策）        │ MCP 协议 stdio（执行）
┌───────▼──────────┐        ┌──────────▼───────────────────┐
│  LLM             │        │  MCP Server  server/          │
│  DeepSeek/GPT/   │        │  task_mcp_server.py           │
│  Qwen 任选       │        │  8 个工具 + 1 资源 + 1 提示词  │
└──────────────────┘        └──────────┬───────────────────┘
                                       │
                            ┌──────────▼──────────┐
                            │  SQLite data/tasks.db│
                            │  tasks + messages   │
                            └─────────────────────┘
```

**为什么用 MCP**：能力层（Server）与大脑层（Agent）解耦。Server 一旦写完，除了本项目的 Agent，还能直接挂到 Claude Desktop / Cursor / Cherry Studio 上（见 `mcp_config_example.json`），不用改一行 Python。这就是「推荐用 MCP 框架」的实际收益。

业务流程图源码（Mermaid，可在 GitHub 直接渲染）见 [`docs/workflow.mmd`](docs/workflow.mmd)。

---

## 3. 目录结构

```
taskmate-agent/
├── server/                     【成员 A】后端 · 能力层
│   ├── storage.py              SQLite 数据层（任务 + 记忆），纯逻辑可单测
│   └── task_mcp_server.py      MCP Server：8 个工具 / 1 资源 / 1 提示词
├── agent/                      【成员 A】后端 · 大脑层
│   ├── config.py               统一配置（.env）
│   ├── llm.py                  OpenAI 兼容 LLM 客户端 + 摘要
│   ├── mcp_client.py           MCP 客户端，工具 schema 动态下发
│   ├── memory.py               多轮对话记忆
│   ├── prompts.py              系统提示词
│   └── agent.py                Tool-Calling 循环 + 同步 Runtime 包装
├── ui/                         【成员 B】前端
│   ├── app.py                  Streamlit：聊天 + 看板 + 语音
│   ├── task_views.py           看板视图层：筛选/排序/导出（纯函数可单测）
│   └── voice.py                ASR(Whisper) + TTS(edge-tts)
├── tests/                      【成员 C】测试
│   ├── test_storage.py         pytest 单测
│   ├── selftest.py             数据层零依赖自测
│   ├── test_static_checks.py   代码与文档一致性
│   ├── test_mcp_integration.py 真起子进程跑 MCP 协议
│   ├── test_agent_loop_mock.py 假 LLM 驱动决策循环
│   ├── test_task_views.py      看板视图层单测（筛选/排序/导出 22 项）
│   ├── test_e2e.py             8 条端到端回归
│   ├── test_ui_smoke.py        网页首屏 + CLI 边界
│   └── e2e_checklist.md        8 条用例清单（联调回归标准）
├── docs/                       环境配置指南 + workflow.mmd 业务流程图
├── .github/workflows/tests.yml CI：push/PR 自动跑全部离线测试
├── CONTRIBUTING.md             分支、PR、契约变更与安全红线
├── LICENSE                     MIT
├── INTERFACE.md                模块间接口契约（三方协作以此为准）
├── 交付清单.md                  三人交付物总清单（验收依据，C 维护）
├── main.py                     命令行入口
├── run.ps1                     Windows 一键启动脚本（demo/web/live/test）
├── mcp_config_example.json     挂到 Claude Desktop / Cursor 的配置示例
├── requirements.txt
└── .env.example                → 复制为 .env 填 key
```

---

## 4. 快速开始

### 方式一：一键脚本（推荐，已在本机验证）

项目配好了开箱即用的 Python 环境（含 mcp/openai/streamlit 全部依赖），
用 `run.ps1` 启动，**不需要自己装 Python**（系统里那个 `python` 是微软商店占位符，没有 pip）：

```powershell
cd taskmate-agent
powershell -ExecutionPolicy Bypass -File .\run.ps1 demo   # 离线演示 CLI（无需 API key）
powershell -ExecutionPolicy Bypass -File .\run.ps1 web    # 网页版（离线模式）
powershell -ExecutionPolicy Bypass -File .\run.ps1 live   # 接真实大模型（需 .env）
powershell -ExecutionPolicy Bypass -File .\run.ps1 test   # 跑全部 7 套 81 项验证
```

> 直接 `.\run.ps1` 若报「在此系统上禁止运行脚本」，是 Windows 执行策略限制，
> 按上面带 `-ExecutionPolicy Bypass` 的写法调用即可（不改系统设置）。

### 方式二：手动安装（自己有 Python 3.10+ 时）

```bash
# 0) 前置：Python 3.10+（推荐 3.11）
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate

# 1) 装依赖
pip install -r requirements.txt

# 2) 配置 LLM（二选一：DeepSeek 最便宜，通义/智谱/OpenAI 都行，都是 OpenAI 兼容格式）
cp .env.example .env        # Windows 手动复制改名即可
# 编辑 .env，填 LLM_API_KEY

# 3) 一键验证（推荐，全部不花钱、不联网、不需要 API key）
python tests/selftest.py            # 数据层 6 项
python tests/test_static_checks.py  # 静态一致性 10 项
python tests/test_mcp_integration.py# 真跑 MCP 协议 17 项
python tests/test_agent_loop_mock.py# 用假 LLM 跑决策循环 11 项
python tests/test_task_views.py     # 看板筛选/排序/导出 22 项
python tests/test_ui_smoke.py       # Streamlit 首屏 + CLI 边界 6 项（需装 streamlit）
# 装了 pytest 的小组也可以用：pytest -q

# 4) 命令行体验
python main.py

# 5) 网页体验（加分项：前端界面）
streamlit run ui/app.py

# 6) 单独调试 MCP Server（官方调试器，需本机可用 npx）
mcp dev server/task_mcp_server.py
```

> ⚠️ **依赖版本硬约束**：必须 `mcp<2.0.0`。MCP 2.x 把 `FastMCP` 重命名为 `MCPServer`，
> 装成 2.x 会在 Server 启动时报 `ModuleNotFoundError: mcp.server.fastmcp`。
> `requirements.txt` 已锁定，自己装时别手改成 `mcp>=1.9`。

---

## 4.5 实际运行与验证（照着做就行）

### 路线 A：零成本离线跑通（不需要 API key，推荐先做这个）

项目内置了一个「规则假大脑」`agent/mock_llm.py`，它会按关键词决定调哪个工具，
从而把**整条链路**（说话 → Agent 决策 → 调 MCP 工具 → 写 SQLite → 自然语言回复）完整跑通，
用来验证架构是否搭对、录制演示视频，完全不花钱。

```bash
# Windows PowerShell
$env:USE_MOCK_LLM="1"
python main.py
```

实测输入 → 真实输出（数据库为 `data/tasks.db`）：

```
🧑 你：帮我添加任务：明天交智能体作业，很急
   ── 执行轨迹 ──
   1. 🔧 add_task ← {'title': '明天交智能体作业，很急', 'priority': 1, 'due_date': '明天'}
🤖 TaskMate：新增任务成功：[1] 明天交智能体作业，很急（紧急，截止 2026-10-25）

🧑 你：把大作业拆成3个步骤
   1. 🔧 batch_add_tasks ← {'items': [...]}
🤖 TaskMate：批量拆解成功，共 3 条：- [2] …步骤1 - [3] …步骤2 - [4] …步骤3

🧑 你：我今天该干嘛
   1. 🔧 daily_briefing ← {}
🤖 TaskMate：今天是 2026-10-24，你共有 4 条任务，其中逾期 0 条、今天到期 0 条。
   🔥 高优先级：[1] 明天交智能体作业，很急

🧑 你：1号做完了
   1. 🔧 complete_task ← {'task_id': 1}
🤖 TaskMate：✅ 已标记完成：明天交智能体作业，很急

🧑 你：统计一下还有多少事
   1. 🔧 get_stats ← {}
🤖 TaskMate：统计：共 4 条，待办 3，进行中 0，已完成 1，逾期 0，今天到期 0。
```

网页端同样支持离线模式：`$env:USE_MOCK_LLM="1"; streamlit run ui/app.py`

> ⚠️ 假大脑只会机械匹配关键词，**不能用来判断 Agent 智能程度**。正式演示必须走路线 B。

### 路线 B：接真实大模型（正式演示）

```bash
cp .env.example .env      # 填入 LLM_API_KEY，并把 USE_MOCK_LLM 改回 0
python main.py            # 或 streamlit run ui/app.py
```

常见现象与解释：
- 模型**不调工具、只聊天** → 换支持 function calling 的模型（DeepSeek-V3 / gpt-4o-mini / qwen-plus）
- 回复里出现**编造的任务** → 检查系统提示词 `agent/prompts.py` 是否被改动
- 改了 `.env` 没生效 → 重启进程（`Config` 在 import 时读取）

### 路线 C：跑自动化验证（7 套，81 项断言）

```bash
python tests/selftest.py              # 数据层 7 项（含同名任务去重）
python tests/test_static_checks.py    # 静态一致性 10 项
python tests/test_mcp_integration.py  # 真起子进程跑 MCP 协议 17 项
python tests/test_agent_loop_mock.py  # 假 LLM 驱动决策循环 11 项
python tests/test_task_views.py       # 看板筛选/排序/导出 22 项
python tests/test_e2e.py              # 8 条端到端回归
python tests/test_ui_smoke.py         # Streamlit 首屏 + CLI 边界 6 项
```

合计 7 + 10 + 17 + 11 + 22 + 8 + 6 = **81 项**，全部不需要 API key、不联网，退出码 0 即通过；GitHub 上 push / PR 会由
`.github/workflows/tests.yml` 自动再跑一遍（CI）。

### 路线 D：push 前的仓库体检（可选但推荐）

```bash
python scripts/check_repo_ready.py   # 8 项：138MB 语音模型是否已被忽略、.env/*.db 是否漏进索引、关键文件是否齐全
```

> 语音模型 `models/whisper-base/model.bin` 有 138MB，超过 GitHub 单文件 100MB 上限，**故意不入库**：
> 用 `python scripts/fetch_asr_model.py` 按需重建（详见 `models/README.md` 与 `demo/提交次序.md`）。

## 5. MCP 工具清单（Server 对外契约）

| 工具 | 作用 | 关键参数 |
| --- | --- | --- |
| `add_task` | 新增任务（同名未完成任务自动去重，返回 duplicate 标记） | title, priority(1-4), due_date（支持"明天"/"11-01"）, tags, parent_id |
| `batch_add_tasks` | 批量新增（目标拆解） | items[] |
| `list_tasks` | 查询过滤 | status, keyword, max_priority, tag, limit |
| `update_task` | 改标题/优先级/截止日/状态/标签 | task_id + 待改字段 |
| `complete_task` | 标记完成 | task_id |
| `delete_task` | 删除 | task_id |
| `get_stats` | 统计（总数/各状态/逾期/今日到期） | — |
| `daily_briefing` | 今日简报（逾期+今日到期+高优+未来7天） | — |

资源：`tasks://all`（纯文本全量任务）　提示词模板：`plan_my_day(focus)`

---

## 6. 加分项覆盖情况

| 加分项 | 实现方式 | 代码位置 | 证据 |
| --- | --- | --- | --- |
| 多轮对话记忆 | 对话历史落 SQLite，按 session 隔离，重启可恢复，超长自动摘要 | `agent/memory.py` | 端到端用例 6、7 |
| 语音输入/输出 | 🎤 faster-whisper 本地 ASR（模型默认读 `models/whisper-base/`，缺失时用 `python scripts/fetch_asr_model.py` 拉取）+ 🔊 edge-tts 播报，缺失依赖自动降级、未听清有提示；**同名任务自动去重**防重复录入 | `ui/voice.py`、`ui/app.py`、`server/storage.py` | 端到端用例 8；`tests/test_voice_pipeline.py`（TTS→ASR→建任务管道）；`demo/语音实测清单.md`（麦克风级人工） |
| 同名任务去重 | `add_task` 对 pending/doing 中同标题任务（忽略空白/大小写）不再重复插入，返回 `duplicate=true`；任务完成后允许重建 | `server/storage.py`、`tests/test_storage.py::test_duplicate_add` | `tests/selftest.py` 第 7 项 |
| 与外部 API / 数据库交互 | 外部 LLM API（OpenAI 兼容）+ 经 MCP 跨进程读写 SQLite | `agent/llm.py`、`server/storage.py` | 端到端用例 1~7 |
| 简洁前端界面 | Streamlit 聊天窗 + 实时任务看板 + 执行轨迹面板 | `ui/app.py` | 演示 GIF |

---

## 7. 小组分工

| 成员 | 角色 | 负责模块 | 主要交付物 |
| --- | --- | --- | --- |
| A | 后端 | MCP Server + 数据层 + 大脑层 | `server/*`、`agent/*`（决策循环/记忆/Client）、`main.py`、配置文件、冒烟自测 |
| B | 前端 | 界面 + 语音 + 素材 | `ui/app.py`、`ui/task_views.py`（看板筛选/排序/导出）、`ui/voice.py`、界面收尾与演示截图 |
| C | 测试 + 文档 + 发布 | 测试、契约、文档、演示 | `INTERFACE.md`、`tests/*`（含 8 条 e2e）、`docs/*`、`demo/*`、`blog/*`、`README.md`、CI、仓库管理与发布 |

> 协作方式：契约先行（以 `INTERFACE.md` 为准），A/B 并行不互相等待；C 持有契约与验收权，
> A/B 走 feature 分支提 PR。分工审阅记录见 `demo/分工优化审阅.md`。

---

## 8. 常见坑

1. **`mcp` 包装不上**：必须用 Python ≥3.10；Windows 上建议先在 venv 里 `pip install --upgrade pip`。
2. **Server 起不来（ImportError）**：`task_mcp_server.py` 里已 `sys.path.insert` 了自身目录，别用 `python -m` 方式启动，直接 `python server/task_mcp_server.py`。
3. **中文乱码**：client 启动时已注入 `PYTHONIOENCODING=utf-8`；Windows 命令行乱码时先执行 `chcp 65001`。
4. **LLM 不调工具**：确认模型支持 function calling（DeepSeek-V3 / GPT-4o-mini / qwen-plus 都支持；某些小模型不支持，换模型即可）。
5. **日期算错**：系统提示词里注入了当前日期，且 Server 侧 `_norm_date` 兜底换算「今天/明天/后天」。
6. **Token 爆炸**：`AGENT_HISTORY_TURNS` 控制记忆长度，`AGENT_MAX_STEPS` 控制单次最大工具轮数。
7. **装了 mcp 2.x 起不来**：必须锁 `mcp<2.0.0`（2.x 已把 FastMCP 改名）。
8. **本机没有可用 Python**：用 `run.ps1`（内置环境），别被微软商店占位符的 `python` 误导。

---

## 9. 协作文档索引（联调期常用）

| 文档 | 用途 | 谁要看 |
| --- | --- | --- |
| `INTERFACE.md` | 接口契约：签名、返回格式、history 格式、环境变量、变更流程 | A、B（改接口前必读） |
| `交付清单.md` | 三人交付物总清单，发布当天的验收依据 | 全员 |
| `docs/环境配置.md` | key 申请、.env 配置、报错对照表（组员装环境看这个） | 全员 |
| `docs/workflow.mmd` | 业务流程图 Mermaid 源码（README / 博客可引用渲染） | 演示答辩 |
| `CONTRIBUTING.md` | 分支与 PR 约定、契约变更顺序、合并前自检、安全红线 | A、B |
| `tests/e2e_checklist.md` | 8 条端到端用例 + 联调当天填结果 | C 主导，A/B 配合修 |
| `demo/bug_log.md` | 问题记录（现象 / 复现 / 归属 / 严重级） | 全员 |
| `demo/recording_guide.md` | 90 秒演示 GIF 分镜与录制要点 | C（录）、B（出素材） |
| `demo/release_checklist.md` | 发布日逐项打勾清单 | C |
