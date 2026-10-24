"""离线演示用的「假大脑」：用规则模拟 LLM 的工具调用决策。

用途：在没有 API key 的情况下，也能把「用户说话 → Agent 决策 → 调 MCP 工具 → 写库 →
自然语言回复」这条链路完整跑一遍，方便验证架构、录制演示、以及 CI 自测。

开启方式（二选一）：
    USE_MOCK_LLM=1 python main.py
    在 .env 里写 USE_MOCK_LLM=1

注意：它只会按关键词机械匹配，不具备真实语义理解，不能用来判断 Agent 的智能程度。
"""
from __future__ import annotations

import json
import re
import uuid
from typing import Any

TOOL_TITLES = {
    "add_task": "新增任务",
    "batch_add_tasks": "批量拆解",
    "list_tasks": "查询任务",
    "update_task": "修改任务",
    "complete_task": "完成任务",
    "delete_task": "删除任务",
    "get_stats": "统计",
    "daily_briefing": "今日简报",
}

STOP_WORDS = [
    "帮我", "请", "麻烦", "给我", "我想", "我要", "需要", "记得", "提醒我", "提醒",
    "添加", "新增", "加一个", "加个", "加", "创建", "记录一下", "记一下",
    "到待办", "到清单", "进清单", "加到", "任务", "一下", "一下儿",
]


def _clean_title(text: str) -> str:
    t = text.strip()
    for w in sorted(STOP_WORDS, key=len, reverse=True):
        t = t.replace(w, "")
    t = re.sub(r"[，,。！!？?、]+$", "", t.strip())
    return t.strip(" ：:") or "未命名任务"


def _pick_priority(text: str) -> int:
    if any(k in text for k in ("紧急", "很急", "最优先", "马上", "立刻")):
        return 1
    if any(k in text for k in ("重要", "优先", "尽快")):
        return 2
    return 3


def _pick_due(text: str) -> str:
    m = re.search(r"(今天|明天|后天|大后天|昨天)", text)
    if m:
        return m.group(1)
    m = re.search(r"(\d{4}-\d{1,2}-\d{1,2}|\d{1,2}[/-]\d{1,2})", text)
    return m.group(1) if m else ""


def _pick_id(text: str) -> int | None:
    m = re.search(r"(\d+)\s*(号|条)?", text)
    return int(m.group(1)) if m else None


class MockLLM:
    """接口与 agent.llm.LLM 完全一致，可直接替换。"""

    model = "mock-rule-based"

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        has_result = any(m.get("role") == "tool" for m in messages)
        if has_result:
            return {"role": "assistant", "content": self._summarize(messages), "tool_calls": []}

        user_text = ""
        for m in reversed(messages):
            if m.get("role") == "user":
                user_text = str(m.get("content", ""))
                break
        return self._decide(user_text)

    async def summarize(self, text: str) -> str:
        return text[:200]

    # ---------------- 决策 ----------------
    def _decide(self, text: str) -> dict[str, Any]:
        t = text.strip()

        if any(k in t for k in ("拆", "分成", "步骤", "分解")):
            n_match = re.search(r"(\d+)\s*(个|步|条)", t)
            n = int(n_match.group(1)) if n_match else 3
            n = max(1, min(n, 8))
            base = _clean_title(t)
            items = [{"title": f"{base} - 步骤{i+1}", "priority": 3} for i in range(n)]
            return self._call("batch_add_tasks", {"items": items})

        if any(k in t for k in ("今天该", "该干嘛", "干啥", "简报", "总结", "进度", "安排", "计划")):
            return self._call("daily_briefing", {})

        if any(k in t for k in ("多少", "几件", "统计", "还剩", "完成率")):
            return self._call("get_stats", {})

        if any(k in t for k in ("完成", "做完了", "搞定了", "结束了", "搞定")):
            tid = _pick_id(t)
            if tid is not None:
                return self._call("complete_task", {"task_id": tid})
            return self._call("list_tasks", {"status": "pending"})

        if any(k in t for k in ("删除", "去掉", "移除")):
            tid = _pick_id(t)
            if tid is not None:
                return self._call("delete_task", {"task_id": tid})
            return self._call("list_tasks", {"status": "pending"})

        if any(k in t for k in ("改", "推迟", "提前", "调整", "延期")):
            tid = _pick_id(t)
            if tid is not None:
                return self._call("update_task", {
                    "task_id": tid,
                    "due_date": _pick_due(t) or "明天",
                    "priority": _pick_priority(t),
                })
            return self._call("list_tasks", {})

        if any(k in t for k in ("添加", "新增", "加", "提醒", "记得", "创建", "记录")):
            return self._call("add_task", {
                "title": _clean_title(t),
                "priority": _pick_priority(t),
                "due_date": _pick_due(t),
            })

        # 兜底：查任务
        return self._call("list_tasks", {"status": "pending", "limit": 20})

    @staticmethod
    def _call(name: str, args: dict[str, Any]) -> dict[str, Any]:
        return {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_" + uuid.uuid4().hex[:8],
                    "name": name,
                    "arguments": json.dumps(args, ensure_ascii=False),
                }
            ],
        }

    # ---------------- 结果整理 ----------------
    def _summarize(self, messages: list[dict[str, Any]]) -> str:
        last_tool = ""
        for m in reversed(messages):
            if m.get("role") == "tool":
                last_tool = str(m.get("content", ""))
                break
        tool_name = ""
        for m in reversed(messages):
            if m.get("role") == "assistant" and m.get("tool_calls"):
                tool_name = m["tool_calls"][0]["function"]["name"]
                break

        try:
            data = json.loads(last_tool)
        except (json.JSONDecodeError, ValueError):
            return "操作已完成。"

        prefix = TOOL_TITLES.get(tool_name, "操作")

        if isinstance(data, dict) and "error" in data:
            return f"{prefix}失败：{data['error']}。请先查一下任务列表确认编号。"

        if tool_name == "daily_briefing":
            stats = data.get("stats", {})
            lines = [
                f"今天是 {data.get('today','')}，你共有 {stats.get('total',0)} 条任务，"
                f"其中逾期 {stats.get('overdue',0)} 条、今天到期 {stats.get('due_today',0)} 条。",
            ]
            if data.get("overdue"):
                lines.append("⚠️ 逾期：" + "；".join(f"[{t['id']}] {t['title']}" for t in data["overdue"]))
            if data.get("due_today"):
                lines.append("🎯 今日到期：" + "；".join(f"[{t['id']}] {t['title']}" for t in data["due_today"]))
            if data.get("urgent"):
                lines.append("🔥 高优先级：" + "；".join(f"[{t['id']}] {t['title']}" for t in data["urgent"]))
            return "\n".join(lines)

        if tool_name == "get_stats":
            return (f"统计：共 {data.get('total',0)} 条，待办 {data.get('pending',0)}，"
                    f"进行中 {data.get('doing',0)}，已完成 {data.get('done',0)}，"
                    f"逾期 {data.get('overdue',0)}，今天到期 {data.get('due_today',0)}。")

        if tool_name == "complete_task":
            return f"✅ 已标记完成：{data.get('task',{}).get('title','')}"

        if tool_name == "delete_task":
            return f"🗑️ 已删除 id={data.get('task_id')}" if data.get("deleted") else "没找到要删除的任务。"

        tasks = data.get("tasks") if isinstance(data, dict) else None
        if tasks is not None:
            if not tasks:
                return "当前没有符合条件的任务。"
            head = f"{prefix}成功，共 {data.get('count', len(tasks))} 条："
            rows = [f"- [{t['id']}] {t['title']}（{t['priority_name']}"
                    + (f"，截止 {t['due_date']}" if t.get("due_date") else "") + "）" for t in tasks]
            return "\n".join([head] + rows)

        if isinstance(data, dict) and "id" in data:
            return (f"{prefix}成功：[{data['id']}] {data.get('title','')}"
                    f"（{data.get('priority_name','')}"
                    + (f"，截止 {data.get('due_date')}" if data.get("due_date") else "") + "）")

        return f"{prefix}已完成。"
