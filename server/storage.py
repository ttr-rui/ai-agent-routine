"""TaskMate 数据层：SQLite 持久化（成员 A 负责）

只做「纯数据操作」，不含任何 MCP / LLM 逻辑，方便单测。
数据库两张表：
  - tasks    : 待办任务
  - messages : 多轮对话记忆（供 Agent 侧使用）
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, date, timedelta
from typing import Any, Iterable

# 优先级语义：数字越小越紧急
PRIORITY_NAME = {1: "紧急", 2: "高", 3: "中", 4: "低"}
STATUS_NAME = {"pending": "待办", "doing": "进行中", "done": "已完成", "cancelled": "已取消"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    title       TEXT    NOT NULL,
    description TEXT    DEFAULT '',
    priority    INTEGER DEFAULT 3,          -- 1紧急 2高 3中 4低
    status      TEXT    DEFAULT 'pending',  -- pending / doing / done / cancelled
    due_date    TEXT    DEFAULT '',         -- YYYY-MM-DD，空串表示无截止日
    tags        TEXT    DEFAULT '[]',       -- JSON 数组
    parent_id   INTEGER DEFAULT 0,          -- 0=主任务，>0 表示是某任务的子任务
    created_at  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_due    ON tasks(due_date);

CREATE TABLE IF NOT EXISTS messages (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT    NOT NULL,
    role       TEXT    NOT NULL,          -- user / assistant / system
    content    TEXT    DEFAULT '',
    created_at TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_msg_session ON messages(session_id);
"""


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _row_to_task(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "title": row["title"],
        "description": row["description"],
        "priority": row["priority"],
        "priority_name": PRIORITY_NAME.get(row["priority"], "中"),
        "status": row["status"],
        "status_name": STATUS_NAME.get(row["status"], row["status"]),
        "due_date": row["due_date"],
        "tags": json.loads(row["tags"] or "[]"),
        "parent_id": row["parent_id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _norm_title(title: str) -> str:
    """标题规范化：压缩连续空白、去首尾、忽略大小写，用于同名判断。"""
    return " ".join(str(title).split()).lower()


class TaskStore:
    """任务 + 对话记忆的持久化封装。"""

    def __init__(self, db_path: str = "data/tasks.db"):
        self.db_path = db_path
        dirname = os.path.dirname(os.path.abspath(db_path))
        if dirname:
            os.makedirs(dirname, exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # ---------------- 任务：写操作 ----------------
    def add_task(
        self,
        title: str,
        description: str = "",
        priority: int = 3,
        due_date: str = "",
        tags: Iterable[str] | None = None,
        parent_id: int = 0,
    ) -> dict[str, Any]:
        """新增任务。同名查重：pending/doing 中已存在同标题任务（忽略大小写
        与多余空白）时不重复插入，返回已有任务并带 duplicate=True；
        任务完成后允许再次创建同名任务。"""
        title = str(title).strip()
        priority = int(priority)
        if priority not in (1, 2, 3, 4):
            priority = 3
        # 防重复录入：语音重试、Agent 循环调用等场景不应产生一串同名任务
        norm = _norm_title(title)
        for row in self.conn.execute(
            "SELECT * FROM tasks WHERE status IN ('pending','doing') ORDER BY id ASC"
        ):
            if _norm_title(row["title"]) == norm:
                dup = _row_to_task(row)
                dup["duplicate"] = True
                return dup
        tags_json = json.dumps(list(tags or []), ensure_ascii=False)
        cur = self.conn.execute(
            "INSERT INTO tasks(title, description, priority, status, due_date, tags, parent_id,"
            " created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (title, description, priority, "pending", due_date, tags_json, parent_id, _now(), _now()),
        )
        self.conn.commit()
        task = self.get_task(cur.lastrowid)
        task["duplicate"] = False
        return task

    def batch_add_tasks(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """批量新增，用于「目标拆解」场景一次性落库。

        注意：标题先 strip 再判空，否则 "   " 这类纯空白标题会被当成合法任务写进去。
        沿用 add_task 的同名查重：重复项返回已有任务并带 duplicate=True，不重复插入。
        """
        return [
            self.add_task(
                title=str(i.get("title", "")).strip(),
                description=i.get("description", ""),
                priority=i.get("priority", 3),
                due_date=i.get("due_date", ""),
                tags=i.get("tags"),
                parent_id=i.get("parent_id", 0),
            )
            for i in items
            if str(i.get("title", "")).strip()
        ]

    def update_task(self, task_id: int, **fields: Any) -> dict[str, Any] | None:
        allowed = {"title", "description", "priority", "status", "due_date", "tags", "parent_id"}
        fields = {k: v for k, v in fields.items() if k in allowed and v is not None}
        if not fields:
            return self.get_task(task_id)
        if "tags" in fields and not isinstance(fields["tags"], str):
            fields["tags"] = json.dumps(list(fields["tags"]), ensure_ascii=False)
        fields["updated_at"] = _now()
        cols = ", ".join(f"{k}=?" for k in fields)
        self.conn.execute("UPDATE tasks SET " + cols + " WHERE id=?", (*fields.values(), task_id))
        self.conn.commit()
        return self.get_task(task_id)

    def delete_task(self, task_id: int) -> bool:
        cur = self.conn.execute("DELETE FROM tasks WHERE id=?", (task_id,))
        self.conn.commit()
        return cur.rowcount > 0

    def complete_task(self, task_id: int) -> dict[str, Any] | None:
        return self.update_task(task_id, status="done")

    # ---------------- 任务：读操作 ----------------
    def get_task(self, task_id: int) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        return _row_to_task(row) if row else None

    def list_tasks(
        self,
        status: str | None = None,
        keyword: str = "",
        max_priority: int | None = None,
        due_before: str = "",
        tag: str = "",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        sql = "SELECT * FROM tasks WHERE 1=1"
        args: list[Any] = []
        if status:
            sql += " AND status=?"
            args.append(status)
        if keyword:
            sql += " AND (title LIKE ? OR description LIKE ?)"
            args += [f"%{keyword}%", f"%{keyword}%"]
        if max_priority:
            sql += " AND priority<=?"
            args.append(int(max_priority))
        if due_before:
            sql += " AND due_date<>'' AND due_date<=?"
            args.append(due_before)
        if tag:
            sql += " AND tags LIKE ?"
            args.append(f"%{tag}%")
        sql += " ORDER BY priority ASC, due_date ASC, id ASC LIMIT ?"
        args.append(int(limit))
        rows = self.conn.execute(sql, args).fetchall()
        return [_row_to_task(r) for r in rows]

    def stats(self) -> dict[str, Any]:
        today = date.today().isoformat()
        total = self.conn.execute("SELECT COUNT(*) c FROM tasks WHERE status!='cancelled'").fetchone()["c"]
        by_status = {
            r["status"]: r["c"]
            for r in self.conn.execute(
                "SELECT status, COUNT(*) c FROM tasks WHERE status!='cancelled' GROUP BY status"
            ).fetchall()
        }
        overdue = self.conn.execute(
            "SELECT COUNT(*) c FROM tasks WHERE status NOT IN ('done','cancelled') AND due_date<>'' AND due_date<?",
            (today,),
        ).fetchone()["c"]
        due_today = self.conn.execute(
            "SELECT COUNT(*) c FROM tasks WHERE status NOT IN ('done','cancelled') AND due_date=?", (today,)
        ).fetchone()["c"]
        return {
            "total": total,
            "by_status": by_status,
            "pending": by_status.get("pending", 0),
            "doing": by_status.get("doing", 0),
            "done": by_status.get("done", 0),
            "overdue": overdue,
            "due_today": due_today,
            "today": today,
        }

    def daily_briefing(self) -> dict[str, Any]:
        """今日简报：逾期 + 今天到期 + 高优先级待办。"""
        today = date.today().isoformat()
        week_later = (date.today() + timedelta(days=7)).isoformat()
        # 严格小于今天才算逾期（今天到期的归到 due_today，避免重复计数）
        overdue = [
            t
            for t in self.list_tasks(due_before=today, limit=100)
            if t["status"] not in ("done", "cancelled") and t["due_date"] and t["due_date"] < today
        ][:20]
        today_tasks = [t for t in self.list_tasks() if t["due_date"] == today and t["status"] != "done"]
        urgent = [t for t in self.list_tasks(max_priority=2) if t["status"] != "done"][:10]
        week = [t for t in self.list_tasks() if today <= (t["due_date"] or "9999-12-31") <= week_later][:20]
        return {
            "today": today,
            "stats": self.stats(),
            "overdue": overdue,
            "due_today": today_tasks,
            "urgent": urgent,
            "this_week": week,
        }

    # ---------------- 多轮对话记忆 ----------------
    def add_message(self, session_id: str, role: str, content: str) -> None:
        self.conn.execute(
            "INSERT INTO messages(session_id, role, content, created_at) VALUES (?,?,?,?)",
            (session_id, role, content, _now()),
        )
        self.conn.commit()

    def get_messages(self, session_id: str, limit: int = 20) -> list[dict[str, str]]:
        rows = self.conn.execute(
            "SELECT role, content FROM messages WHERE session_id=? ORDER BY id DESC LIMIT ?",
            (session_id, limit),
        ).fetchall()
        return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]

    def clear_messages(self, session_id: str) -> None:
        self.conn.execute("DELETE FROM messages WHERE session_id=?", (session_id,))
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()


if __name__ == "__main__":
    # 自测：python server/storage.py
    s = TaskStore("data/demo.db")
    s.add_task("写智能体作业", priority=2, due_date="2026-10-30", tags=["作业"])
    s.add_task("跑步 3 公里", priority=4, tags=["健康"])
    print(s.list_tasks())
    print(s.stats())
    print(s.daily_briefing())
