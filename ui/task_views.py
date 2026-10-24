"""看板视图层（纯函数，不依赖 Streamlit，方便单测）。

负责：任务筛选 / 排序 / 逾期判定 / 完成率 / Markdown 与 CSV 导出。
UI（app.py）只负责渲染，所有数据处理都收敛在这里，避免"逻辑写在页面里没法测"。
"""
from __future__ import annotations

import csv
import io
from datetime import date
from typing import Any

# 优先级：文案 + 徽章配色（与 app.py 的 CSS 变量保持一致）
PRIORITY_STYLE: dict[int, tuple[str, str]] = {
    1: ("紧急", "#C92A2A"),
    2: ("高", "#E8590C"),
    3: ("中", "#1971C2"),
    4: ("低", "#868E96"),
}

VIEW_OPTIONS = ["全部", "待办", "进行中", "已完成", "已逾期"]
_VIEW_TO_STATUS = {"待办": "pending", "进行中": "doing", "已完成": "done"}
SORT_OPTIONS = ["智能排序", "截止日最近", "优先级最高", "最新创建"]


def is_overdue(task: dict[str, Any], today: str | None = None) -> bool:
    """未完成且截止日严格早于今天（今天到期不算逾期，与统计口径一致）。"""
    today = today or date.today().isoformat()
    due = task.get("due_date") or ""
    return bool(due) and due < today and task.get("status") not in ("done", "cancelled")


def is_due_today(task: dict[str, Any], today: str | None = None) -> bool:
    today = today or date.today().isoformat()
    return (task.get("due_date") or "") == today and task.get("status") not in ("done", "cancelled")


def filter_tasks(
    tasks: list[dict[str, Any]], view: str = "全部", keyword: str = ""
) -> list[dict[str, Any]]:
    """按视图 + 关键字过滤；未知视图按「全部」处理，不抛异常。"""
    kw = (keyword or "").strip().lower()
    out = []
    for t in tasks:
        if view in _VIEW_TO_STATUS and t.get("status") != _VIEW_TO_STATUS[view]:
            continue
        if view == "已逾期" and not is_overdue(t):
            continue
        if kw:
            haystack = " ".join(
                [str(t.get("title", "")), str(t.get("description", "")),
                 " ".join(t.get("tags") or [])]
            ).lower()
            if kw not in haystack:
                continue
        out.append(t)
    return out


def sort_tasks(tasks: list[dict[str, Any]], mode: str = "智能排序") -> list[dict[str, Any]]:
    """返回新列表，不改原列表。逾期 > 今日到期 > 其他，组内按优先级与截止日。"""
    if mode == "截止日最近":
        return sorted(tasks, key=lambda t: ((t.get("due_date") or "9999-12-31"), t.get("priority", 3)))
    if mode == "优先级最高":
        return sorted(tasks, key=lambda t: (t.get("priority", 3), t.get("due_date") or "9999-12-31"))
    if mode == "最新创建":
        return sorted(tasks, key=lambda t: str(t.get("created_at", "")), reverse=True)
    return sorted(
        tasks,
        key=lambda t: (
            t.get("status") == "done",                 # 已完成沉底
            0 if is_overdue(t) else 1,                 # 逾期最前
            0 if is_due_today(t) else 1,               # 今日到期其次
            t.get("priority", 3),
            t.get("due_date") or "9999-12-31",
        ),
    )


def completion_rate(stats: dict[str, Any]) -> float:
    """完成率 0.0~1.0；没有任务时返回 0 而不是除零。"""
    total = int(stats.get("total", 0) or 0)
    return round(int(stats.get("done", 0) or 0) / total, 4) if total else 0.0


def to_markdown(tasks: list[dict[str, Any]], today: str | None = None) -> str:
    """导出为 Markdown 清单（GitHub 任务列表语法），按逾期/今日/待办/已完成分组。"""
    today = today or date.today().isoformat()
    lines = [f"# TaskMate 待办清单（{today}）", ""]
    groups = [
        ("⚠️ 已逾期", [t for t in tasks if is_overdue(t, today)]),
        ("🎯 今日到期", [t for t in tasks if is_due_today(t, today)]),
        ("📌 待办", [t for t in tasks
                    if t.get("status") not in ("done", "cancelled")
                    and not is_overdue(t, today) and not is_due_today(t, today)]),
        ("✅ 已完成", [t for t in tasks if t.get("status") == "done"]),
    ]
    for name, items in groups:
        if not items:
            continue
        lines.append(f"## {name}（{len(items)}）")
        for t in items:
            box = "x" if t.get("status") == "done" else " "
            pname = PRIORITY_STYLE.get(t.get("priority", 3), ("中", ""))[0]
            due = f" · 截止 {t['due_date']}" if t.get("due_date") else ""
            tags = "".join(f" #{tag}" for tag in (t.get("tags") or []))
            lines.append(f"- [{box}] **#{t['id']} {t['title']}**（{pname}）{due}{tags}")
        lines.append("")
    if len(lines) == 2:
        lines.append("（暂无任务）")
    return "\n".join(lines).strip() + "\n"


def to_csv(tasks: list[dict[str, Any]]) -> str:
    """导出 CSV（带 BOM，Excel 直接打开不乱码）。"""
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["ID", "标题", "描述", "优先级", "状态", "截止日", "标签", "创建时间", "更新时间"])
    for t in tasks:
        writer.writerow([
            t.get("id", ""), t.get("title", ""), t.get("description", ""),
            t.get("priority_name") or PRIORITY_STYLE.get(t.get("priority", 3), ("中", ""))[0],
            t.get("status_name") or t.get("status", ""), t.get("due_date", ""),
            "|".join(t.get("tags") or []), t.get("created_at", ""), t.get("updated_at", ""),
        ])
    return "﻿" + buf.getvalue()
