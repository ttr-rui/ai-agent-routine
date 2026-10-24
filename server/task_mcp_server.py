"""TaskMate MCP Server —— 把「待办清单能力」封装成标准 MCP 工具（成员 A 负责）

对外暴露 8 个工具 + 1 个资源 + 1 个提示词模板。
任何支持 MCP 的客户端（本项目 Agent、Claude Desktop、Cursor、Cherry Studio）
都能直接挂载本 Server，实现「同一份能力、多个宿主复用」。

本地自测：
    python server/task_mcp_server.py                 # 直接用 stdio 跑起来（被 client 拉起）
    mcp dev server/task_mcp_server.py                # 官方调试器，浏览器里点着试
"""
from __future__ import annotations

import os
import sys
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcp.server.fastmcp import FastMCP  # noqa: E402
from storage import TaskStore  # noqa: E402

mcp = FastMCP("taskmate", instructions="待办任务与日程整理助手的能力服务端")

STORE = TaskStore(os.getenv("TASK_DB_PATH", "data/tasks.db"))

# 相对日期词 → 真实日期，避免 LLM 自己算错日期
RELATIVE_DAYS = {"今天": 0, "今日": 0, "明天": 1, "明日": 1, "后天": 2, "大后天": 3, "昨天": -1}


def _norm_date(text: str) -> str:
    """把 '明天' / '10-30' / '2026/10/30' 归一成 YYYY-MM-DD，失败返回原串。"""
    if not text:
        return ""
    text = text.strip()
    if text in RELATIVE_DAYS:
        return (date.today() + timedelta(days=RELATIVE_DAYS[text])).isoformat()
    for fmt_in in ("%Y-%m-%d", "%Y/%m/%d", "%m-%d", "%m/%d"):
        try:
            d = __import__("datetime").datetime.strptime(text, fmt_in).date()
            if fmt_in.startswith("%m"):  # 只给了月日，补当前年
                d = d.replace(year=date.today().year)
            return d.isoformat()
        except ValueError:
            continue
    return text


# ---------------------------------------------------------------- 工具定义
@mcp.tool()
def add_task(
    title: str,
    description: str = "",
    priority: int = 3,
    due_date: str = "",
    tags: list[str] | None = None,
    parent_id: int = 0,
) -> dict:
    """新增一条待办任务。

    Args:
        title: 任务标题，简短明确，例如「完成智能体作业第 3 节」
        description: 补充说明
        priority: 1=紧急 2=高 3=中 4=低，默认 3
        due_date: 截止日期，支持「今天/明天/后天/2026-11-01/11-01」
        tags: 标签列表，如 ["作业", "组队"]
        parent_id: 父任务 id，用于把大目标拆成子任务（没有就填 0）

    Returns:
        任务 dict，含 duplicate 字段：true 表示库里已有同名未完成任务，
        本次未重复创建（返回的是已有任务）。此时直接告知用户「已有相同任务」即可，
        不要再次调用本工具。
    """
    return STORE.add_task(
        title=title,
        description=description,
        priority=priority,
        due_date=_norm_date(due_date),
        tags=tags,
        parent_id=parent_id,
    )


@mcp.tool()
def batch_add_tasks(items: list[dict]) -> dict:
    """一次性新增多条任务，适合「帮我把一个目标拆成若干待办」的场景。

    Args:
        items: 任务数组，每项形如
               {"title": "...", "description": "...", "priority": 2,
                "due_date": "明天", "tags": ["作业"], "parent_id": 0}

    Returns:
        created_count：条目数；duplicates：其中命中同名未完成任务的个数（未重复创建）。
        每个 task 的 duplicate=true 时直接沿用已有任务，告知用户即可。
    """
    created = STORE.batch_add_tasks(items)
    duplicates = sum(1 for t in created if t.get("duplicate"))
    return {"created_count": len(created), "duplicates": duplicates, "tasks": created}


@mcp.tool()
def list_tasks(
    status: str = "",
    keyword: str = "",
    max_priority: int = 0,
    tag: str = "",
    limit: int = 30,
) -> dict:
    """查询待办任务列表。

    Args:
        status: pending(待办) / doing(进行中) / done(已完成)，留空查全部
        keyword: 标题或描述包含的关键词
        max_priority: 只返回优先级数字 <= 该值的任务（填 2 表示只要紧急和高优）
        tag: 按标签过滤
        limit: 最多返回条数
    """
    tasks = STORE.list_tasks(
        status=status or None,
        keyword=keyword,
        max_priority=max_priority or None,
        tag=tag,
        limit=limit,
    )
    return {"count": len(tasks), "tasks": tasks}


@mcp.tool()
def update_task(
    task_id: int,
    title: str = "",
    description: str = "",
    priority: int = 0,
    status: str = "",
    due_date: str = "",
    tags: list[str] | None = None,
) -> dict:
    """修改已有任务（改标题/改优先级/改截止日/改状态/改标签），传空字符串表示不修改该字段。"""
    fields: dict = {}
    if title:
        fields["title"] = title
    if description:
        fields["description"] = description
    if priority:
        fields["priority"] = priority
    if status:
        fields["status"] = status
    if due_date:
        fields["due_date"] = _norm_date(due_date)
    if tags is not None:
        fields["tags"] = tags
    updated = STORE.update_task(task_id, **fields)
    if not updated:
        return {"error": f"未找到 id={task_id} 的任务"}
    return updated


@mcp.tool()
def complete_task(task_id: int) -> dict:
    """把指定任务标记为已完成。"""
    task = STORE.complete_task(task_id)
    if not task:
        return {"error": f"未找到 id={task_id} 的任务"}
    return {"message": f"已完成：{task['title']}", "task": task}


@mcp.tool()
def delete_task(task_id: int) -> dict:
    """删除指定任务（物理删除）。如果只是做完了，请优先用 complete_task。"""
    ok = STORE.delete_task(task_id)
    return {"deleted": ok, "task_id": task_id}


@mcp.tool()
def get_stats() -> dict:
    """获取任务统计：总数、各状态数量、逾期数量、今天到期数量。"""
    return STORE.stats()


@mcp.tool()
def daily_briefing() -> dict:
    """生成今日简报：逾期任务、今天到期任务、高优先级待办、未来 7 天安排。
    当用户说「我今天该干什么」「帮我看看进度」「总结一下」时应优先调用本工具。"""
    return STORE.daily_briefing()


# ---------------------------------------------------------------- 资源 & 提示词
@mcp.resource("tasks://all")
def all_tasks_resource() -> str:
    """以纯文本形式暴露全部未完成任务，供 LLM 直接读取上下文。"""
    tasks = STORE.list_tasks(limit=100)
    lines = [f"[{t['id']}] ({t['priority_name']}/{t['status_name']}) {t['title']}"
             + (f"  截止 {t['due_date']}" if t["due_date"] else "")
             for t in tasks]
    return "\n".join(lines) or "当前没有任何任务"


@mcp.prompt()
def plan_my_day(focus: str = "效率") -> str:
    """生成「今日计划」提示词模板。"""
    return (
        f"你是我的任务助理。请先调用 daily_briefing 拿到今日简报，"
        f"再结合我今天的重点是「{focus}」，给我排出一个不超过 5 条的今日执行清单，"
        f"按优先级排序，并说明每条大概需要多久。不要新增任务，除非我明确要求。"
    )


if __name__ == "__main__":
    # stdio 传输：由 MCP 客户端以子进程方式拉起
    mcp.run(transport="stdio")
