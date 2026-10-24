"""MCP 集成验证：真起子进程、真走 stdio 协议、真调工具。

不需要 API key（不碰 LLM）。运行：
    python tests/test_mcp_integration.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402

SERVER = str(ROOT / "server" / "task_mcp_server.py")
EXPECTED_TOOLS = {
    "add_task", "batch_add_tasks", "list_tasks", "update_task",
    "complete_task", "delete_task", "get_stats", "daily_briefing",
}

results: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    results.append((name, bool(cond), detail))
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  → {detail}" if detail else ""))


async def call(session, name, args):
    res = await session.call_tool(name, args)
    texts = [c.text for c in res.content if getattr(c, "type", "") == "text"]
    raw = "\n".join(texts)
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return {"raw": raw}


async def main() -> int:
    tmpdir = tempfile.mkdtemp(prefix="taskmate_mcp_")
    db = os.path.join(tmpdir, "v.db")

    params = StdioServerParameters(
        command=sys.executable,
        args=[SERVER],
        env={**os.environ, "PYTHONIOENCODING": "utf-8", "TASK_DB_PATH": db},
    )

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # 1. 工具清单
            tools = (await session.list_tools()).tools
            names = {t.name for t in tools}
            check("列出 8 个预期工具", names == EXPECTED_TOOLS, f"实际 {sorted(names)}")
            check("每个工具都有描述(docstring)", all((t.description or "").strip() for t in tools))

            # 2. schema 可转 OpenAI function calling 格式
            ok_schema = True
            for t in tools:
                s = t.inputSchema or {}
                if s.get("type") != "object" or "properties" not in s:
                    ok_schema = False
            check("工具 schema 符合 JSON Schema object", ok_schema)

            # 3. 新增 + 相对日期归一化
            tomorrow = (date.today() + timedelta(days=1)).isoformat()
            r = await call(session, "add_task", {"title": "交作业", "due_date": "明天", "priority": 1})
            check("add_task 返回 id", isinstance(r.get("id"), int), f"id={r.get('id')}")
            check("「明天」归一化正确", r.get("due_date") == tomorrow, f"{r.get('due_date')} vs {tomorrow}")

            # 4. 非法优先级兜底
            r2 = await call(session, "add_task", {"title": "优先级非法", "priority": 99})
            check("priority=99 兜底为 3", r2.get("priority") == 3, f"priority={r2.get('priority')}")

            # 5. 批量新增（目标拆解场景）
            r3 = await call(session, "batch_add_tasks", {
                "items": [{"title": "步骤1"}, {"title": "步骤2"}, {"title": "   "}]
            })
            check("batch 过滤空标题", r3.get("created_count") == 2, f"created={r3.get('created_count')}")

            # 6. 查询过滤
            r4 = await call(session, "list_tasks", {"max_priority": 1})
            check("list_tasks 按优先级过滤", r4.get("count") == 1, f"count={r4.get('count')}")

            # 7. 更新 + 完成
            tid = r["id"]
            await call(session, "update_task", {"task_id": tid, "status": "doing"})
            r5 = await call(session, "complete_task", {"task_id": tid})
            check("complete_task 置为 done", r5.get("task", {}).get("status") == "done")

            # 8. 不存在 id 的异常处理（应返回 error，不抛异常）
            r6 = await call(session, "complete_task", {"task_id": 9999})
            check("不存在的 id 返回 error 而非崩溃", "error" in r6, str(r6)[:80])
            r7 = await call(session, "delete_task", {"task_id": 9999})
            check("删除不存在的 id 返回 deleted=False", r7.get("deleted") is False)

            # 9. 统计与简报结构
            st = await call(session, "get_stats", {})
            check("get_stats 字段完整",
                  {"total", "pending", "done", "overdue", "due_today"} <= set(st),
                  str(st))
            br = await call(session, "daily_briefing", {})
            check("daily_briefing 字段完整",
                  {"today", "stats", "overdue", "due_today", "urgent", "this_week"} <= set(br))

            # 10. 逾期判定边界：今天到期的不能算逾期
            today = date.today().isoformat()
            yesterday = (date.today() - timedelta(days=1)).isoformat()
            await call(session, "add_task", {"title": "昨天该做", "due_date": yesterday})
            await call(session, "add_task", {"title": "今天该做", "due_date": today})
            br2 = await call(session, "daily_briefing", {})
            overdue_titles = [t["title"] for t in br2["overdue"]]
            check("逾期只含昨天", overdue_titles == ["昨天该做"], str(overdue_titles))
            check("今日到期不被算逾期",
                  [t["title"] for t in br2["due_today"]] == ["今天该做"])

            # 11. 资源与提示词
            res = await session.read_resource("tasks://all")
            check("资源 tasks://all 可读", "昨天该做" in str(res))
            try:
                p = await session.get_prompt("plan_my_day", {"focus": "效率"})
                check("提示词模板可用", "效率" in str(p))
            except Exception as e:
                check("提示词模板可用", False, f"{type(e).__name__}: {e}")

    import shutil

    shutil.rmtree(tmpdir, ignore_errors=True)

    passed = sum(1 for _, ok, _ in results if ok)
    print(f"\n{passed}/{len(results)} 通过")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
