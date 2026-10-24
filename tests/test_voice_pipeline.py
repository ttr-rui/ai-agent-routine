"""语音全链路测试（在线测试，不进 run.ps1 test 的离线套件）。

验证闭环：edge-tts 把一句话合成 mp3 → faster-whisper 转写回文字 →
拿转写结果去真实调 Agent → 任务真的写进 SQLite。

运行：  python tests/test_voice_pipeline.py
前提：  pip install edge-tts faster-whisper；首次运行需联网下载 whisper 模型（约 145MB）
"""
from __future__ import annotations

import os
import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

results: list[bool] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append(bool(ok))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  → {detail}" if detail else ""))


def main() -> int:
    from ui.voice import asr_ready, speak, transcribe

    check("前置：faster-whisper 已安装", asr_ready())

    # ---------- 1. TTS 合成 ----------
    said = "帮我添加任务：后天交智能体大作业"
    mp3 = speak(said)
    check("TTS 合成音频", bool(mp3) and len(mp3) > 1000, f"{len(mp3) if mp3 else 0} bytes")

    # ---------- 2. ASR 转写 ----------
    heard = transcribe(mp3, suffix=".mp3") if mp3 else ""
    check("ASR 转写出非空文字", bool(heard.strip()), f"听到：{heard}")
    hit = any(k in heard for k in ("智能体", "作业", "任务", "添加"))
    check("转写内容与原句语义一致（关键词命中）", hit, heard)

    # ---------- 3. 转写结果喂给真实 Agent（Mock 大脑，离线可跑） ----------
    if heard:
        os.environ["USE_MOCK_LLM"] = "1"
        # ignore_cleanup_errors：Windows 下 MCP 会话关闭后 SQLite 句柄释放有延迟，
        # 临时目录清理会偶发 PermissionError，与功能正确性无关
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            os.environ["TASK_DB_PATH"] = str(Path(tmp) / "voice.db")
            # Config 在 import 时读取，必须重新加载模块
            for mod in [m for m in list(sys.modules) if m.startswith(("agent", "server", "storage"))]:
                del sys.modules[mod]
            from agent.agent import AgentRuntime

            rt = AgentRuntime()
            out = rt.chat(heard, "voice-test")
            tools = [t["tool"] for t in out["trace"]]
            check("Agent 收到语音转写文本后调用了工具", "add_task" in tools, f"trace={tools}")
            conn = sqlite3.connect(os.environ["TASK_DB_PATH"])
            titles = [r[0] for r in conn.execute("SELECT title FROM tasks").fetchall()]
            conn.close()
            check("任务真实落库", len(titles) > 0, f"titles={titles}")
            rt.close()
    else:
        check("Agent 收到语音转写文本后调用了工具", False, "转写为空，跳过")
        check("任务真实落库", False, "转写为空，跳过")

    passed = sum(results)
    print(f"\n{passed}/{len(results)} 通过")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
