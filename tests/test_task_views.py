"""看板视图层单元测试（不依赖 Streamlit、不需要 API key）。

运行：  python tests/test_task_views.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ui.task_views import (  # noqa: E402
    completion_rate, filter_tasks, is_due_today, is_overdue,
    sort_tasks, to_csv, to_markdown,
)

TODAY = "2026-10-24"
TASKS = [
    {"id": 1, "title": "逾期作业", "priority": 1, "status": "pending", "due_date": "2026-10-20",
     "tags": ["作业"], "description": "", "created_at": "2026-10-19 10:00:00"},
    {"id": 2, "title": "今天到期", "priority": 2, "status": "pending", "due_date": TODAY,
     "tags": [], "description": "", "created_at": "2026-10-22 10:00:00"},
    {"id": 3, "title": "买牛奶", "priority": 4, "status": "pending", "due_date": "",
     "tags": ["生活"], "description": "超市", "created_at": "2026-10-23 10:00:00"},
    {"id": 4, "title": "已做完的事", "priority": 3, "status": "done", "due_date": "2026-10-01",
     "tags": [], "description": "", "created_at": "2026-10-01 10:00:00"},
]

results: list[bool] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append(bool(ok))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  → {detail}" if detail else ""))


def main() -> int:
    # 逾期 / 今日到期口径（与统计一致：今天到期 ≠ 逾期；已完成不算逾期）
    check("逾期判定", is_overdue(TASKS[0], TODAY) and not is_overdue(TASKS[1], TODAY)
          and not is_overdue(TASKS[3], TODAY) and not is_overdue(TASKS[2], TODAY))
    check("今日到期判定", is_due_today(TASKS[1], TODAY) and not is_due_today(TASKS[0], TODAY))

    # 筛选
    check("视图筛选·待办", len(filter_tasks(TASKS, "待办")) == 3)
    check("视图筛选·已完成", [t["id"] for t in filter_tasks(TASKS, "已完成")] == [4])
    check("视图筛选·已逾期", [t["id"] for t in filter_tasks(TASKS, "已逾期")] == [1])
    check("未知视图不崩", len(filter_tasks(TASKS, "不存在的视图")) == 4)
    check("关键字命中标题", [t["id"] for t in filter_tasks(TASKS, "全部", "牛奶")] == [3])
    check("关键字命中描述与标签",
          [t["id"] for t in filter_tasks(TASKS, "全部", "超市")] == [3]
          and [t["id"] for t in filter_tasks(TASKS, "全部", "作业")] == [1])
    check("空关键字与空白等价", len(filter_tasks(TASKS, "全部", "   ")) == 4)
    check("无匹配返回空列表", filter_tasks(TASKS, "全部", "zzz") == [])

    # 排序
    smart = [t["id"] for t in sort_tasks(TASKS)]
    check("智能排序：逾期最前、今日其次、已完成沉底",
          smart[0] == 1 and smart[1] == 2 and smart[-1] == 4, str(smart))
    check("排序不改原列表", [t["id"] for t in TASKS] == [1, 2, 3, 4])
    check("无截止日排最后", [t["id"] for t in sort_tasks(TASKS, "截止日最近")][-1] == 3)
    check("最新创建倒序", [t["id"] for t in sort_tasks(TASKS, "最新创建")][0] == 3)

    # 完成率
    check("完成率", completion_rate({"total": 4, "done": 1}) == 0.25)
    check("完成率·空任务不除零", completion_rate({"total": 0, "done": 0}) == 0.0)

    # 导出
    md = to_markdown(TASKS, TODAY)
    check("Markdown 分组与任务列表语法",
          "## ⚠️ 已逾期" in md and "## ✅ 已完成" in md
          and "- [ ] **#1 逾期作业**" in md and "- [x] **#4 已做完的事**" in md)
    check("Markdown 含截止日期与标签", "截止 2026-10-20" in md and "#作业" in md)
    check("Markdown 空列表兜底", "暂无任务" in to_markdown([], TODAY))
    csv_text = to_csv(TASKS)
    check("CSV 带 BOM 且含表头与数据",
          csv_text.startswith("﻿") and "ID,标题,描述" in csv_text and "买牛奶" in csv_text)
    check("CSV 行数 = 表头 + 任务数", len(csv_text.strip().splitlines()) == len(TASKS) + 1)
    check("CSV 空列表只有表头", len(to_csv([]).strip().splitlines()) == 1)

    passed = sum(results)
    print(f"\n{passed}/{len(results)} 通过")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
