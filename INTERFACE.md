# INTERFACE.md · TaskMate 模块间接口契约

> 维护人：成员 C。**三方协作时以本文件为准**——A 改 Server、B 改 Agent 前必须先改这里并同步群里，避免"你改了我没看到"的联调事故。

---

## 1. Agent 对外接口（UI / CLI 唯一入口）

成员 C 的 `ui/app.py` 和 `main.py` **只允许**调用下面这一个类，不直接碰 MCP。

```python
from agent.agent import AgentRuntime

rt = AgentRuntime()          # 启动时创建一次：拉起 MCP Server 子进程 + 加载记忆
rt.tools                     # -> list[str]，可用工具名，如 ["add_task", "daily_briefing", ...]

out = rt.chat(text: str, session_id: str = "default")
# 返回 dict：
# {
#   "answer": str,          # 给用户看的自然语言回复（Markdown，直接 st.markdown 渲染）
#   "trace": [              # 执行轨迹（"会做"的证据，UI 展示在回复下方）
#     {"tool": "add_task", "args": {...}, "result": {...}},
#   ],
# }

rt.reset(session_id)         # 清空某会话的对话记忆（任务数据不受影响）
rt.close()                   # 退出前调用：关闭 MCP 子进程与 event loop
```

**约定**
- `chat()` 是**同步阻塞**调用，内部已包装异步循环；UI 里直接调用即可，不要自己再开 event loop。
- `session_id`：CLI 固定用 `"cli"`；网页端用 `st.session_state` 里的随机 uuid，每个浏览器标签一个会话。
- `answer` 里不含执行轨迹，轨迹要 UI 自己用 `out["trace"]` 渲染（参考 `agent/memory.py` 的 `dump_trace`）。

## 2. MCP 工具返回格式

8 个工具均返回 **JSON 对象**（MCP `tool result` 的 text 内容是 `json.dumps(..., ensure_ascii=False)`），由 Agent 层负责转成 Markdown 给用户：

| 返回形态 | 结构 | Agent 侧处理 |
| --- | --- | --- |
| 单任务 | `{"id": 3, "title": "...", "priority_name": "紧急", "due_date": "2026-10-25", ...}` | 拼成一行 `[3] 标题（紧急，截止 2026-10-25）` |
| 任务列表 | `{"count": n, "tasks": [{...}, ...]}` | 逐行渲染；`tasks` 为空时回复「没有符合条件的任务」 |
| 统计 | `{"total": 4, "pending": 3, "done": 1, "overdue": 0, "due_today": 0, ...}` | 拼成一句话简报 |
| 今日简报 | `{"today": "2026-10-24", "stats": {...}, "overdue": [...], "due_today": [...], "urgent": [...]}` | 分组列出，空组省略 |
| **出错** | `{"error": "未找到 id=99 的任务"}` | **不抛异常**，把 error 转成提示语回给用户/LLM |

> 注：作业参考模板写的是「MCP 返回 Markdown」，本项目改为返回 **JSON**——因为工具结果要回填给 LLM 再总结，JSON 对模型更稳；Markdown 只在最终 `answer` 层生成。如老师问起，这就是设计取舍。

## 3. 对话记忆（history）格式

存储：SQLite `messages` 表（与任务同库 `data/tasks.db`），字段：

```sql
session_id TEXT, role TEXT, content TEXT, created_at TEXT
-- role 取值：user / assistant / system
```

- 进 LLM 的上下文 = system 提示词 + `get_messages(session_id, 20)`（最近 20 条，时间升序）。
- 超长时调用 `ConversationMemory.compact()` 压成一条 system 摘要，防止 token 爆炸。
- **重启不丢**：这也是端到端用例 7「重启后数据仍在」的依据。

## 4. 环境变量（.env，全部在 `.env.example` 有注释）

| 变量 | 必填 | 默认 | 说明 |
| --- | --- | --- | --- |
| `LLM_API_KEY` | 真实模式必填 | — | DeepSeek / 通义 / OpenAI 的 key（模板里的 `DEEPSEEK_API_KEY` 即它，因为默认就接 DeepSeek） |
| `LLM_BASE_URL` | 否 | `https://api.deepseek.com/v1` | 任何 OpenAI 兼容地址 |
| `LLM_MODEL` | 否 | `deepseek-chat` | 需支持 function calling |
| `TASK_DB_PATH` | 否 | `data/tasks.db` | SQLite 路径（测试时指到临时文件） |
| `AGENT_MAX_STEPS` | 否 | `8` | 单轮最大工具调用步数 |
| `AGENT_HISTORY_TURNS` | 否 | `20` | 带入上下文的历史条数 |
| `USE_MOCK_LLM` | 否 | `0` | `1` = 离线演示模式，无需 key |

**风险提示**：`.env` 已在 `.gitignore` 里，**严禁提交**；改完 `.env` 必须重启进程才生效。

## 5. 变更流程（联调期纪律）

1. 改接口前先改本文件 → 群里 @另外两人确认。
2. 改完跑 `python tests/test_e2e.py`（8 条用例）+ `run.ps1 test`（50 项断言）。
3. 全绿才能 push；红了在 `demo/bug表.md` 记一条再分派。
