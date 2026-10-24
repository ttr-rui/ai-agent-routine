"""Agent 决策循环验证：用假 LLM（打桩）驱动真实 MCP 链路，不花一分钱 API 费用。

覆盖：工具调用闭环、多轮记忆、步数上限回退、工具不存在时的容错。
运行：  python tests/test_agent_loop_mock.py
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "server"))

import agent.config as cfg  # noqa: E402

# 用临时库 + 假 key，避免污染真实数据、也避免因为没有 key 而无法构造
_tmp = tempfile.mkdtemp(prefix="taskmate_agent_")
cfg.Config.API_KEY = "test-key-not-real"
cfg.Config.DB_PATH = os.path.join(_tmp, "agent.db")
cfg.Config.MAX_STEPS = 8

from agent.agent import TaskMateAgent  # noqa: E402
from storage import TaskStore  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    results.append((name, bool(cond), detail))
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  → {detail}" if detail else ""))


class FakeLLM:
    """按脚本依次返回预设响应，模拟 LLM 的决策过程。"""

    def __init__(self, script: list[dict]):
        self.script = script
        self.n = 0
        self.seen_tools: list[list[str]] = []

    async def chat(self, messages, tools=None, temperature=0.2):
        self.seen_tools.append([t["function"]["name"] for t in (tools or [])])
        resp = self.script[min(self.n, len(self.script) - 1)]
        self.n += 1
        return resp

    async def summarize(self, text: str) -> str:
        return "摘要"


def tc(name: str, args: dict) -> dict:
    return {"role": "assistant", "content": "",
            "tool_calls": [{"id": f"c{name}", "name": name, "arguments": json.dumps(args, ensure_ascii=False)}]}


async def main() -> int:
    agent = TaskMateAgent()
    tools = await agent.astart()
    check("MCP 连接成功并拿到工具", len(tools) == 8, f"{len(tools)} 个")

    # ---------- 用例 1：工具调用闭环（真的写库） ----------
    agent.llm = FakeLLM([
        tc("add_task", {"title": "写验证报告", "due_date": "明天", "priority": 2}),
        {"role": "assistant", "content": "已添加「写验证报告」", "tool_calls": []},
    ])
    out = await agent.achat("帮我加个任务：明天前写验证报告", "s1")
    check("trace 记录了真实工具调用",
          out["trace"] and out["trace"][0]["tool"] == "add_task")
    check("返回自然语言答案", "写验证报告" in out["answer"], out["answer"][:40])

    store = TaskStore(cfg.Config.DB_PATH)
    rows = store.list_tasks(keyword="写验证报告")
    check("任务真的落到了数据库", len(rows) == 1, f"{len(rows)} 条")

    # ---------- 用例 2：Agent 侧与 Server 侧用的是同一个库 ----------
    # 若 DB 路径注入失效，Server 会写到「cwd 下的 data/tasks.db」，这里该文件就不会出现
    check("Server 写库位置 = Config.DB_PATH",
          os.path.exists(cfg.Config.DB_PATH), cfg.Config.DB_PATH)
    check("多轮记忆已写入", len(agent.memory.history("s1")) >= 2,
          f"{len(agent.memory.history('s1'))} 条")

    # ---------- 用例 3：多轮上下文（第二轮能看到第一轮） ----------
    agent.llm = FakeLLM([
        tc("list_tasks", {}),
        {"role": "assistant", "content": "当前有 1 条任务", "tool_calls": []},
    ])
    ctx = agent.memory.history("s1")
    check("历史里包含上一轮用户原话",
          any("写验证报告" in m["content"] for m in ctx))

    # ---------- 用例 4：工具不存在时的容错（不崩，回传 error 给 LLM） ----------
    r = await agent.hub.call("no_such_tool", {})
    check("调用不存在的工具返回 error 字段", "error" in r, str(r)[:60])

    r2 = await agent.hub.call("add_task", {"title": "参数非法测试", "priority": "abc"})
    check("参数类型非法时不崩溃", isinstance(r2, dict), str(r2)[:60])

    # ---------- 用例 5：步数耗尽时的兜底回复 ----------
    cfg.Config.MAX_STEPS = 2
    agent2 = TaskMateAgent()
    await agent2.astart()
    agent2.llm = FakeLLM([tc("list_tasks", {}), tc("list_tasks", {}),
                          {"role": "assistant", "content": "步数用尽后的总结", "tool_calls": []}])
    out2 = await agent2.achat("一直查个不停", "s2")
    check("步数耗尽仍能给出总结", "步数用尽后的总结" in out2["answer"], out2["answer"][:40])
    check("步数耗尽不再无限调用", len(out2["trace"]) <= 4, f"{len(out2['trace'])} 次")
    cfg.Config.MAX_STEPS = 8

    await agent.aclose()
    await agent2.aclose()

    import shutil

    shutil.rmtree(_tmp, ignore_errors=True)

    passed = sum(1 for _, ok, _ in results if ok)
    print(f"\n{passed}/{len(results)} 通过")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
