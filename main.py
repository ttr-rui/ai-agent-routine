"""命令行入口（成员 B 负责）：最简交互，用来快速验证 Agent 的「能说会做」。

运行：  python main.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# 只把项目根目录加入 sys.path；agent/ 是包（含 __init__.py，内部用相对导入），
# 若把 agent/ 目录本身也加进 sys.path，会导致 "attempted relative import with no
# known parent package"，CLI 一启动就崩。
sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent.agent import AgentRuntime  # noqa: E402
from agent.memory import dump_trace  # noqa: E402

BANNER = """
╭──────────────────────────────────────────────╮
│  TaskMate · 能说会做的待办智能助理 (MCP)      │
│  输入 /quit 退出   /reset 清空记忆  /tools 查看工具 │
╰──────────────────────────────────────────────╯
"""


def main() -> None:
    print(BANNER)
    try:
        rt = AgentRuntime()
    except RuntimeError as e:
        print(f"❌ 启动失败：{e}")
        sys.exit(1)

    mode = "离线演示模式（规则假大脑，无需 API key）" if os.getenv("USE_MOCK_LLM") in ("1", "true", "yes") \
        else "真实大模型模式"
    print(f"✅ MCP 已连接，可用工具：{', '.join(rt.tools)}")
    print(f"🧠 当前模式：{mode}\n")
    session_id = "cli"

    try:
        while True:
            user = input("🧑 你：").strip()
            if not user:
                continue
            if user in ("/quit", "exit", "q"):
                break
            if user == "/reset":
                rt.reset(session_id)
                print("🧹 已清空本轮记忆\n")
                continue
            if user == "/tools":
                print("🔧 " + ", ".join(rt.tools) + "\n")
                continue

            out = rt.chat(user, session_id)
            if out["trace"]:
                print("── 执行轨迹 ──")
                print(dump_trace(out["trace"]))
            print(f"🤖 TaskMate：{out['answer']}\n")
    finally:
        rt.close()
        print("👋 已退出")


if __name__ == "__main__":
    main()
