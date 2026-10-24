"""MCP 客户端（成员 B 负责）：以 stdio 子进程方式拉起 MCP Server 并调用其工具。

关键点：
1. 工具的 schema 由 Server 动态下发（list_tools），Agent 侧不硬编码，加工具不用改代码；
2. MCP 的 inputSchema 与 OpenAI function calling 的 parameters 完全同构，可直接转换。
"""
from __future__ import annotations

import json
import os
import sys
from contextlib import AsyncExitStack
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from .config import Config


class MCPToolHub:
    def __init__(self, server_script: str) -> None:
        self.server_script = server_script
        self.session: ClientSession | None = None
        self.tools: dict[str, Any] = {}
        self._stack: AsyncExitStack | None = None

    async def connect(self) -> list[str]:
        # 关键：显式把数据库绝对路径注入 Server 子进程。
        # 否则 Server 会用相对路径 data/tasks.db，且基准目录是「启动客户端时的 cwd」，
        # 会与 Agent / UI 使用的 Config.DB_PATH 指向不同的库，出现「加了任务但看板看不到」。
        params = StdioServerParameters(
            command=sys.executable,                 # 用当前虚拟环境的 python
            args=[self.server_script],
            env={
                **os.environ,
                "PYTHONIOENCODING": "utf-8",
                "TASK_DB_PATH": Config.DB_PATH,
            },
        )
        self._stack = AsyncExitStack()
        read, write = await self._stack.enter_async_context(stdio_client(params))
        self.session = await self._stack.enter_async_context(ClientSession(read, write))
        await self.session.initialize()

        result = await self.session.list_tools()
        self.tools = {t.name: t for t in result.tools}
        return list(self.tools)

    def openai_tools(self) -> list[dict[str, Any]]:
        """MCP 工具 → OpenAI function-calling 格式。"""
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description or "",
                    "parameters": t.inputSchema or {"type": "object", "properties": {}},
                },
            }
            for t in self.tools.values()
        ]

    async def call(self, name: str, arguments: dict[str, Any]) -> Any:
        if name not in self.tools:
            return {"error": f"工具 {name} 不存在，可用工具有：{list(self.tools)}"}
        if self.session is None:
            return {"error": "MCP 会话未建立"}
        try:
            args = json.loads(arguments) if isinstance(arguments, str) else (arguments or {})
            result = await self.session.call_tool(name, args)
            texts = [c.text for c in result.content if getattr(c, "type", "") == "text"]
            raw = "\n".join(texts)
            try:
                return json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                return {"raw": raw}
        except Exception as e:  # 工具执行失败要回传给 LLM，让它自行纠错重试
            return {"error": f"{type(e).__name__}: {e}"}

    async def close(self) -> None:
        if not self._stack:
            return
        stack, self._stack, self.session = self._stack, None, None
        try:
            await stack.aclose()
        except BaseException as e:  # noqa: BLE001
            # anyio 的 task group 要求在同一 task 内进/出，跨 task / 跨事件循环关闭会抛
            # RuntimeError 或 CancelledError。CancelledError 继承自 BaseException，
            # 用 except Exception 抓不住，必须显式兜住——关闭阶段不能让异常冒泡。
            print(f"[mcp] 关闭会话时出现可忽略的异常：{type(e).__name__}: {e}", file=sys.stderr)
