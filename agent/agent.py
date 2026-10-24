"""Agent 大脑（成员 B 负责）：LLM 决策循环 + MCP 工具执行 + 多轮记忆。

核心是一个 ReAct / Tool-Calling 循环：
    用户说话 → LLM 判断是否需要工具
        ├─ 不需要 → 直接自然语言回复（能说）
        └─ 需要   → 调用 MCP 工具 → 把结果回填给 LLM → 再判断 ...（会做）
"""
from __future__ import annotations

import asyncio
import json
import threading
from typing import Any

from .config import Config, check_config
from .llm import LLM
from .mcp_client import MCPToolHub
from .memory import ConversationMemory
from .prompts import build_system_prompt


class TaskMateAgent:
    def __init__(self) -> None:
        problems = check_config()
        if problems:
            raise RuntimeError("；".join(problems))
        if Config.USE_MOCK_LLM:
            from .mock_llm import MockLLM

            self.llm = MockLLM()          # 离线演示：规则假大脑
        else:
            self.llm = LLM()              # 真实大模型
        self.hub = MCPToolHub(Config.SERVER_SCRIPT)
        self.memory = ConversationMemory()

    async def astart(self) -> list[str]:
        """建立 MCP 连接，返回可用工具名列表。"""
        return await self.hub.connect()

    # ---------------- 核心循环 ----------------
    async def achat(self, user_text: str, session_id: str = "default") -> dict[str, Any]:
        self.memory.add(session_id, "user", user_text)
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": build_system_prompt(list(self.hub.tools))}
        ] + self.memory.history(session_id)

        trace: list[dict[str, Any]] = []
        answer = ""

        for step in range(Config.MAX_STEPS):
            resp = await self.llm.chat(messages, tools=self.hub.openai_tools())
            if not resp["tool_calls"]:
                answer = resp["content"]
                break

            # 组装 assistant 消息（含 tool_calls）
            messages.append(
                {
                    "role": "assistant",
                    "content": resp["content"] or "",
                    "tool_calls": [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {"name": tc["name"], "arguments": tc["arguments"]},
                        }
                        for tc in resp["tool_calls"]
                    ],
                }
            )

            # 逐个执行工具并回填
            for tc in resp["tool_calls"]:
                args = LLM.safe_json(tc["arguments"])
                result = await self.hub.call(tc["name"], args)
                trace.append({"tool": tc["name"], "args": args, "result": result})
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "name": tc["name"],
                        "content": json.dumps(result, ensure_ascii=False)[:4000],
                    }
                )
        else:
            # 步数用尽：再问一次但收回工具，逼它把已拿到的信息总结成自然语言，
            # 否则用户会收到一个空回复（原实现 answer 此时仍是空串）。
            messages.append(
                {
                    "role": "system",
                    "content": "你已达到工具调用上限，请基于已获得的信息直接给出最终答复，不要再调用任何工具。",
                }
            )
            resp = await self.llm.chat(messages, tools=None)
            answer = (resp["content"] or "").strip()
            if not answer:
                # 极端情况：模型即使被收回工具仍返回 tool_calls 且无正文
                answer = "（已达到工具调用上限，未能产出最终答复，请换个说法或把需求拆小一点重试）"

        self.memory.add(session_id, "assistant", answer)
        return {"answer": answer, "trace": trace}

    async def aclose(self) -> None:
        try:
            await self.hub.close()
        except BaseException as e:  # noqa: BLE001  关闭阶段异常一律不向上抛
            print(f"[agent] 关闭时异常已忽略：{type(e).__name__}: {e}", file=sys.stderr)


class AgentRuntime:
    """同步包装：在后台线程常驻一个 event loop，供 CLI / Streamlit 直接调用。

    这样 MCP Server 子进程只启动一次，不会每次对话都重新拉起。
    """

    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()
        self._agent = TaskMateAgent()
        self.tools = self._run(self._agent.astart())

    def _run(self, coro):
        return asyncio.run_coroutine_threadsafe(coro, self._loop).result()

    def chat(self, text: str, session_id: str = "default") -> dict[str, Any]:
        return self._run(self._agent.achat(text, session_id))

    def reset(self, session_id: str = "default") -> None:
        self._agent.memory.clear(session_id)

    def close(self) -> None:
        try:
            self._run(self._agent.aclose())
        except BaseException as e:  # noqa: BLE001
            print(f"[runtime] 关闭时异常已忽略：{type(e).__name__}: {e}", file=sys.stderr)
        finally:
            self._loop.call_soon_threadsafe(self._loop.stop)
