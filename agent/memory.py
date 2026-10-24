"""多轮对话记忆（成员 B 负责）：落 SQLite，重启不丢；超长自动摘要压缩。"""
from __future__ import annotations

import sys
import os
from typing import Any

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "server"))
from storage import TaskStore  # noqa: E402

from .config import Config  # noqa: E402


class ConversationMemory:
    """以 session_id 为单位保存对话；不同会话互不干扰。"""

    def __init__(self, store: TaskStore | None = None, max_turns: int | None = None):
        self.store = store or TaskStore(Config.DB_PATH)
        self.max_turns = max_turns or Config.HISTORY_TURNS

    def add(self, session_id: str, role: str, content: str) -> None:
        if not content:
            return
        self.store.add_message(session_id, role, content)

    def history(self, session_id: str) -> list[dict[str, str]]:
        """取出最近 N 条，作为 LLM 上下文。"""
        return self.store.get_messages(session_id, self.max_turns)

    def compact(self, session_id: str, summary: str) -> None:
        """把历史替换成一条 system 摘要（长对话防爆 token）。"""
        self.store.clear_messages(session_id)
        self.store.add_message(session_id, "system", f"【此前对话摘要】{summary}")

    def clear(self, session_id: str) -> None:
        self.store.clear_messages(session_id)

    def sessions(self) -> list[str]:
        rows = self.store.conn.execute("SELECT DISTINCT session_id FROM messages").fetchall()
        return [r[0] for r in rows]

    def export_markdown(self, session_id: str) -> str:
        msgs = self.store.get_messages(session_id, 200)
        return "\n\n".join(f"**{m['role']}**：{m['content']}" for m in msgs)


def dump_trace(trace: list[dict[str, Any]]) -> str:
    """把工具调用轨迹渲染成 UI 上可展示的文本。"""
    if not trace:
        return ""
    lines = []
    for i, t in enumerate(trace, 1):
        lines.append(f"{i}. 🔧 `{t['tool']}` ← `{t['args']}`")
    return "\n".join(lines)
