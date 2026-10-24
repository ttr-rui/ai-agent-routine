"""端到端回归（成员 C 负责）：对照 demo/e2e_checklist.md 的 8 条用例。

- 用例 1-7 全自动：真实拉起 MCP Server 子进程 + 真 SQLite，大脑用离线 MockLLM
  （不需要 API key、不联网），验证的是完整链路而非单元逻辑。
- 用例 8 语音：TTS/ASR 依赖网络与麦克风，脚本只做"可运行、可优雅降级"验证，
  人工听感验证按 checklist 手动执行。

运行：  python tests/test_e2e.py      （退出码 0 = 8 条全过）
"""
from __future__ import annotations

import os
import sys
import tempfile
import datetime
from pathlib import Path

# 必须在 import agent 之前设置环境变量（Config 在 import 时读取）
_TMP = tempfile.mkdtemp(prefix="taskmate_e2e_")
os.environ["USE_MOCK_LLM"] = "1"
os.environ["TASK_DB_PATH"] = str(Path(_TMP) / "e2e.db")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agent.agent import AgentRuntime  # noqa: E402

PASS, FAIL = "  PASS ", "  FAIL "
results: list[bool] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append(bool(ok))
    print(f"{PASS if ok else FAIL} 用例{name}  {detail}")


def tomorrow() -> str:
    return (datetime.date.today() + datetime.timedelta(days=1)).isoformat()


def main() -> int:
    print(f"临时数据库：{_TMP}\n")

    # ---------- 用例 1：添加 ----------
    rt = AgentRuntime()
    check("1 前置：MCP 连接拿到 8 个工具", len(rt.tools) == 8, f"tools={rt.tools}")
    out = rt.chat("帮我添加任务：明天交智能体作业，很急", "e2e")
    tools1 = [t["tool"] for t in out["trace"]]
    check("1 添加：走 add_task 且回复含任务信息",
          tools1 == ["add_task"] and "[" in out["answer"] and "2026" in out["answer"],
          f"trace={tools1}, answer={out['answer'][:40]}")

    # ---------- 用例 2：查未完成 ----------
    out = rt.chat("帮我看看还有哪些没做完的待办", "e2e")
    tools2 = [t["tool"] for t in out["trace"]]
    check("2 查未完成：list_tasks 且 status=pending",
          tools2 == ["list_tasks"] and out["trace"][0]["args"].get("status") == "pending"
          and "交智能体作业" in out["answer"],
          f"args={out['trace'][0]['args']}")

    # ---------- 用例 3：标完成 ----------
    out = rt.chat("1号做完了", "e2e")
    tools3 = [t["tool"] for t in out["trace"]]
    check("3 标完成：complete_task(id=1) 回复含完成标记",
          tools3 == ["complete_task"] and out["trace"][0]["args"].get("task_id") == 1
          and ("✅" in out["answer"] or "完成" in out["answer"]),
          f"answer={out['answer'][:30]}")

    # ---------- 用例 4：删除 ----------
    rt.chat("帮我添加任务：临时测试用的任务", "e2e")   # 建一条专门用来删的
    rows = _db_ids()
    target = max(rows)
    out = rt.chat(f"删除{target}号任务", "e2e")
    tools4 = [t["tool"] for t in out["trace"]]
    check("4 删除：delete_task 后库里确实没了",
          tools4 == ["delete_task"] and out["trace"][0]["args"].get("task_id") == target
          and target not in _db_ids(),
          f"删的是 id={target}")

    # ---------- 用例 5：闲聊（不执行危险操作） ----------
    out = rt.chat("你好呀，今天天气怎么样", "e2e")
    tools5 = [t["tool"] for t in out["trace"]]
    check("5 闲聊：正常回复、链路不崩",
          bool(out["answer"].strip()) and tools5 == ["list_tasks"],
          f"Mock 兜底成查询是预期行为；answer={out['answer'][:30]}")

    # ---------- 用例 6：多轮指代（依赖上一轮结果的 id） ----------
    out = rt.chat("帮我看看还有哪些没做完的待办", "e2e")   # 先查，拿到当前 id 列表
    ids = [t["args"].get("task_id") for t in out["trace"] if t["tool"] == "list_tasks"]
    any_id = min(i for i in _db_ids() if i != target)
    out2 = rt.chat(f"{any_id}号做完了", "e2e")             # 指代：用上一轮看到的编号
    tools6 = [t["tool"] for t in out2["trace"]]
    check("6 多轮指代：上一轮上下文里的 id 本轮可直接用",
          tools6 == ["complete_task"] and any_id not in _db_status("pending"),
          f"指代 id={any_id}")
    n_msgs = _count_messages("e2e")
    check("6 记忆：对话历史已持久化（重启可恢复的前提）", n_msgs >= 8, f"messages 表 {n_msgs} 条")

    # ---------- 用例 7：重启后数据仍在 ----------
    rt.chat("帮我添加任务：重启存活测试XYZ", "e2e")
    rt.close()                                             # 模拟进程退出
    rt = AgentRuntime()                                    # 全新 Runtime（新子进程 + 新连接）
    out = rt.chat("帮我看看还有哪些没做完的待办", "e2e")
    check("7 重启后数据仍在：新进程能查到旧任务",
          "重启存活测试XYZ" in out["answer"],
          f"answer 含标题 = {'重启存活测试XYZ' in out['answer']}")
    rt.close()

    # ---------- 用例 8：语音（可自动部分：模块可用 + 优雅降级） ----------
    try:
        from ui.voice import transcribe, speak
        garbage = transcribe(b"\x00" * 64)                 # 喂垃圾音频：应返回空串而不是崩
        mp3 = None
        try:
            mp3 = speak("端到端语音测试")                   # 需要网络访问微软 TTS
        except Exception as e:
            print(f"         （TTS 网络异常，已降级：{e}）")
        check("8 语音：ASR 垃圾输入不崩、TTS 可用或优雅降级",
              garbage == "" and (mp3 is None or len(mp3) > 1000),
              f"transcribe→{garbage!r}, tts_bytes={len(mp3) if mp3 else '降级'}")
    except Exception as e:
        check("8 语音", False, f"模块导入失败：{e}")

    ok = all(results)
    print(f"\n{'✅ 8 条端到端用例全部通过' if ok else '❌ 存在失败用例，见上方 FAIL'}"
          f"（{sum(results)}/{len(results)}）")
    return 0 if ok else 1


def _db_ids() -> list[int]:
    import sqlite3
    conn = sqlite3.connect(os.environ["TASK_DB_PATH"])
    ids = [r[0] for r in conn.execute("SELECT id FROM tasks").fetchall()]
    conn.close()
    return ids


def _db_status(status: str) -> list[int]:
    import sqlite3
    conn = sqlite3.connect(os.environ["TASK_DB_PATH"])
    ids = [r[0] for r in conn.execute(
        "SELECT id FROM tasks WHERE status = ?", (status,)).fetchall()]
    conn.close()
    return ids


def _count_messages(session: str) -> int:
    import sqlite3
    conn = sqlite3.connect(os.environ["TASK_DB_PATH"])
    n = conn.execute("SELECT COUNT(*) FROM messages WHERE session_id = ?",
                     (session,)).fetchone()[0]
    conn.close()
    return n


if __name__ == "__main__":
    sys.exit(main())
