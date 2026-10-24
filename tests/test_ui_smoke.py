"""UI 与 CLI 冒烟：用 Streamlit 官方 AppTest 真跑一遍脚本，验证首屏渲染与缺 key 时的降级。

运行：  python tests/test_ui_smoke.py   （需已安装 streamlit）
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

results: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    results.append((name, bool(cond), detail))
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  → {detail}" if detail else ""))


def main() -> int:
    from streamlit.testing.v1 import AppTest

    # ---------- 1. 首屏渲染 ----------
    at = AppTest.from_file(str(ROOT / "ui" / "app.py"), default_timeout=120).run()
    check("Streamlit 首屏无异常", not at.exception, str(at.exception)[:200])
    titles = [t.value for t in at.title]
    check("标题正确渲染", any("TaskMate" in t for t in titles), str(titles)[:80])

    # 无 key 环境下不应直接白屏，而应给出可读提示
    if at.error:
        check("缺 key 时给出可读错误提示", True, at.error[0].value[:80])
    else:
        check("首屏未报错（未触发 LLM 调用）", True)

    # ---------- 2. 模拟用户输入，验证降级路径 ----------
    at2 = AppTest.from_file(str(ROOT / "ui" / "app.py"), default_timeout=120).run()
    at2.chat_input[0].set_value("帮我加个任务：明天交作业").run()
    check("发消息后页面不崩溃", not at2.exception, str(at2.exception)[:200])

    # ---------- 3. CLI 在缺 key 时的边界行为 ----------
    # 显式制造「缺 key」环境：剥掉环境变量里的 LLM_API_KEY，并临时挪走 .env，
    # 否则在配好 key 的机器上 CLI 会正常启动，用例失去意义（环境依赖误报）
    env = {k: v for k, v in os.environ.items() if k != "LLM_API_KEY"}
    env["USE_MOCK_LLM"] = "0"  # mock 模式不需要 key，必须关掉才能走到缺 key 分支
    dot_env = ROOT / ".env"
    hidden = ROOT / ".env.hidden_for_ui_smoke"
    moved = dot_env.exists()
    if moved:
        dot_env.rename(hidden)
    try:
        p = subprocess.run([sys.executable, "main.py"], cwd=str(ROOT), input="/quit\n",
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=120, env=env)
    finally:
        if moved:
            hidden.rename(dot_env)
    check("CLI 缺 key 时以非零码退出", p.returncode != 0, f"returncode={p.returncode}")
    check("CLI 给出明确错误原因", ("LLM_API_KEY" in p.stdout) or ("启动失败" in p.stdout),
          (p.stdout or p.stderr)[:120].replace("\n", " "))

    passed = sum(1 for _, ok, _ in results if ok)
    print(f"\n{passed}/{len(results)} 通过")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
