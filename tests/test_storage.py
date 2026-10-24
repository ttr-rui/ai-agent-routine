"""数据层单测（成员 A 负责）：pytest 跑一次，保证 MCP 工具的输入输出契约稳定。

运行：  pytest -q
"""
import sys, os
from datetime import date, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "server"))

from storage import TaskStore  # noqa: E402


def test_add_and_get(tmp_path):
    s = TaskStore(str(tmp_path / "t.db"))
    t = s.add_task("写报告", priority=2, due_date="2026-11-01", tags=["作业"])
    assert t["id"] == 1
    assert t["priority_name"] == "高"
    assert s.get_task(1)["title"] == "写报告"


def test_list_filter(tmp_path):
    s = TaskStore(str(tmp_path / "t.db"))
    s.add_task("A 紧急", priority=1)
    s.add_task("B 低", priority=4)
    assert len(s.list_tasks(max_priority=2)) == 1
    assert len(s.list_tasks(keyword="低")) == 1


def test_update_complete_delete(tmp_path):
    s = TaskStore(str(tmp_path / "t.db"))
    t = s.add_task("跑步")
    s.update_task(t["id"], priority=1, status="doing")
    assert s.get_task(t["id"])["status"] == "doing"
    s.complete_task(t["id"])
    assert s.get_task(t["id"])["status"] == "done"
    assert s.delete_task(t["id"]) is True
    assert s.get_task(t["id"]) is None


def test_stats_and_briefing(tmp_path):
    s = TaskStore(str(tmp_path / "t.db"))
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    s.add_task("逾期的", priority=1, due_date=yesterday)
    s.add_task("今天的", priority=2, due_date=date.today().isoformat())
    st = s.stats()
    assert st["overdue"] == 1 and st["due_today"] == 1
    b = s.daily_briefing()
    assert len(b["overdue"]) == 1


def test_batch_add(tmp_path):
    s = TaskStore(str(tmp_path / "t.db"))
    items = [{"title": "步骤1"}, {"title": "步骤2"}, {"title": ""}]
    assert len(s.batch_add_tasks(items)) == 2


def test_duplicate_add(tmp_path):
    """同名未完成任务不重复插入（BUG-13：语音重试曾把同一句话录成一串任务）。"""
    s = TaskStore(str(tmp_path / "t.db"))
    t1 = s.add_task("提交物理作业", due_date="2026-10-26")
    assert t1["duplicate"] is False
    # 同名（含首尾空格 / 大小写差异）→ 返回已有任务，不新增
    t2 = s.add_task(" 提交物理作业 ")
    assert t2["duplicate"] is True and t2["id"] == t1["id"]
    t3 = s.add_task("提交物理作业".upper())
    assert t3["duplicate"] is True and t3["id"] == t1["id"]
    assert len(s.list_tasks()) == 1
    # 批量接口同样去重，并能看到 duplicates 计数来源
    batch = s.batch_add_tasks([{"title": "提交物理作业"}, {"title": "新任务"}])
    assert [t["duplicate"] for t in batch] == [True, False]
    assert len(s.list_tasks()) == 2
    # 已完成后允许再次创建同名任务
    s.complete_task(t1["id"])
    t4 = s.add_task("提交物理作业")
    assert t4["duplicate"] is False and t4["status"] == "pending"


def test_memory(tmp_path):
    s = TaskStore(str(tmp_path / "t.db"))
    s.add_message("s1", "user", "帮我加个任务")
    s.add_message("s1", "assistant", "好的")
    assert len(s.get_messages("s1")) == 2
    s.clear_messages("s1")
    assert s.get_messages("s1") == []
