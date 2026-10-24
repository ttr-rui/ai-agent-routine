"""Streamlit 前端（成员 B 负责）：聊天窗 + 任务看板 + 语音 I/O。

运行：  streamlit run ui/app.py
设计：  高级简约 · 自然有机配色（主绿 #2D6A4F / 强调橙 #F4A261 / 米白底 #FEFDF8）
        数据处理全部放在 ui/task_views.py（纯函数，可单测），本文件只做渲染与交互。
"""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "server"))

from agent.config import Config, check_config  # noqa: E402
from storage import TaskStore  # noqa: E402
from ui.task_views import (  # noqa: E402
    PRIORITY_STYLE, SORT_OPTIONS, VIEW_OPTIONS,
    completion_rate, filter_tasks, is_due_today, is_overdue,
    sort_tasks, to_csv, to_markdown,
)

st.set_page_config(page_title="TaskMate · 待办智能助理", page_icon="✅",
                   layout="wide", initial_sidebar_state="expanded")

CSS = """
<style>
:root {
  --brand: #2D6A4F; --accent: #F4A261; --ink: #1B2A22;
  --muted: #6B7A70; --line: #E4E9E2; --card: #FFFFFF;
}
.stApp { background: #FEFDF8; }
h1, h2, h3 { color: var(--ink); letter-spacing: -0.02em; }
.tm-hero {
  padding: 20px 24px; border: 1px solid var(--line); border-radius: 18px;
  background: linear-gradient(135deg, #FFFFFF 0%, #F3F7F0 100%);
  box-shadow: 0 1px 2px rgba(27,42,34,.04), 0 8px 24px rgba(27,42,34,.05);
  margin-bottom: 18px;
}
.tm-hero .sub { color: var(--muted); font-size: 15px; margin-top: 6px; }
.tm-badge {
  display: inline-block; padding: 2px 10px; border-radius: 999px;
  font-size: 12px; font-weight: 600; line-height: 20px; margin-right: 6px;
  border: 1px solid transparent;
}
.tm-badge.mode { background: #E8F2EA; color: var(--brand); border-color: #CBE0CF; }
.tm-badge.mock { background: #FFF3E4; color: #A35A12; border-color: #F2D8B4; }
.tm-pill {
  display: inline-block; min-width: 34px; text-align: center;
  padding: 1px 8px; border-radius: 6px; font-size: 12px; font-weight: 600;
  color: #fff; margin-right: 6px;
}
.tm-overdue { color: #C92A2A; font-weight: 600; }
.tm-today { color: #A35A12; font-weight: 600; }
.tm-done { color: var(--muted); text-decoration: line-through; }
.tm-meta { color: var(--muted); font-size: 12.5px; }
.tm-empty {
  padding: 26px; text-align: center; color: var(--muted);
  border: 1px dashed var(--line); border-radius: 16px; background: #fff;
}
.stButton > button { border-radius: 10px; transition: all .15s ease; }
.stButton > button:hover { transform: translateY(-1px); }
section[data-testid="stSidebar"] { background: #FFFFFF; border-right: 1px solid var(--line); }
</style>
"""


@st.cache_resource
def get_store() -> TaskStore:
    return TaskStore(Config.DB_PATH)


@st.cache_resource
def get_runtime():
    """懒加载：只有用户真的发消息时才实例化（避免缺 key 时首屏白屏）。"""
    from agent.agent import AgentRuntime

    return AgentRuntime()


# ---------------------------------------------------------------- 看板
def render_task_card(store: TaskStore, t: dict) -> None:
    overdue, due_today = is_overdue(t), is_due_today(t)
    pname, pcolor = PRIORITY_STYLE.get(t["priority"], ("中", "#868E96"))
    done = t["status"] == "done"

    with st.container(border=True):
        title_cls = "tm-done" if done else ("tm-overdue" if overdue else "")
        st.markdown(
            f'<span class="tm-pill" style="background:{pcolor}">{pname}</span>'
            f'<span class="{title_cls}"><b>#{t["id"]} {t["title"]}</b></span>',
            unsafe_allow_html=True,
        )
        meta = []
        if t.get("due_date"):
            flag = "（已逾期）" if overdue else ("（今天到期）" if due_today else "")
            meta.append(f'截止 {t["due_date"]}{flag}')
        if t.get("tags"):
            meta.append(" ".join(f"#{x}" for x in t["tags"]))
        if t.get("description"):
            meta.append(str(t["description"])[:40])
        if meta:
            st.markdown(f'<div class="tm-meta">{" · ".join(meta)}</div>', unsafe_allow_html=True)

        c1, c2, c3 = st.columns([1, 1, 2])
        if not done:
            if c1.button("✅ 完成", key=f"done_{t['id']}", use_container_width=True):
                store.complete_task(t["id"])
                st.rerun()
        else:
            if c1.button("↩️ 重开", key=f"reopen_{t['id']}", use_container_width=True):
                store.update_task(t["id"], status="pending")
                st.rerun()
        if c2.button("🗑 删除", key=f"del_{t['id']}", use_container_width=True):
            st.session_state[f"confirm_del_{t['id']}"] = True
        if st.session_state.get(f"confirm_del_{t['id']}"):
            st.warning(f"确认删除 #{t['id']}？此操作不可恢复")
            if c3.button("确认删除", key=f"del_ok_{t['id']}"):
                store.delete_task(t["id"])
                st.session_state.pop(f"confirm_del_{t['id']}", None)
                st.rerun()


def render_board(store: TaskStore) -> None:
    s = store.stats()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("总任务", s["total"])
    c2.metric("待办", s["pending"] + s.get("doing", 0))
    c3.metric("今日到期", s["due_today"])
    c4.metric("已逾期", s["overdue"])
    rate = completion_rate(s)
    st.progress(rate, text=f"完成率 {rate:.0%}（{s['done']}/{s['total']}）")

    view = st.radio("筛选", VIEW_OPTIONS, horizontal=True, label_visibility="collapsed")
    kw = st.text_input("🔎 搜索任务", placeholder="标题 / 描述 / 标签", label_visibility="collapsed")
    order = st.selectbox("排序", SORT_OPTIONS, label_visibility="collapsed")

    tasks = sort_tasks(filter_tasks(store.list_tasks(limit=500), view, kw), order)
    st.caption(f"显示 {len(tasks)} 条")
    if not tasks:
        st.markdown('<div class="tm-empty">这里还空空如也<br>跟右边聊聊，让 Agent 帮你建第一条任务</div>',
                    unsafe_allow_html=True)
    for t in tasks[:50]:
        render_task_card(store, t)
    if len(tasks) > 50:
        st.caption("仅显示前 50 条，可用搜索缩小范围")

    all_tasks = store.list_tasks(limit=1000)
    d1, d2 = st.columns(2)
    d1.download_button("⬇️ 导出 Markdown", to_markdown(all_tasks),
                       file_name="taskmate-todos.md", mime="text/markdown",
                       use_container_width=True)
    d2.download_button("⬇️ 导出 CSV", to_csv(all_tasks),
                       file_name="taskmate-todos.csv", mime="text/csv",
                       use_container_width=True)


# ---------------------------------------------------------------- 主区
def show_trace(trace: list[dict]) -> None:
    with st.expander(f"🔧 执行轨迹 · 调用了 {len(trace)} 次 MCP 工具"):
        for i, t in enumerate(trace, 1):
            st.code(f'{i}. {t["tool"]}({t["args"]})', language="python")
            with st.popover("查看返回"):
                st.json(t["result"])


EXAMPLES = [
    ("➕ 加任务", "帮我添加任务：明天交智能体作业，很急"),
    ("🧩 拆目标", "把智能体大作业拆成3个可执行步骤"),
    ("📋 今日安排", "我今天该干嘛？"),
    ("📊 看统计", "统计一下还有多少事没做"),
]


def main() -> None:
    st.markdown(CSS, unsafe_allow_html=True)
    mock = Config.USE_MOCK_LLM
    mode_txt = "离线演示模式 · Mock 大脑" if mock else f"真实大模型 · {Config.MODEL}"
    st.markdown(
        f'<div class="tm-hero">'
        f'<div class="sub">能说会做的待办智能助理 · 自然语言对话 × MCP 工具调用读写 SQLite</div>'
        f'<div style="margin-top:10px"><span class="tm-badge {"mock" if mock else "mode"}">{mode_txt}</span>'
        f'<span class="tm-badge mode">MCP Server · 8 工具</span>'
        f'<span class="tm-badge mode">记忆持久化</span></div></div>',
        unsafe_allow_html=True,
    )
    st.title("✅ TaskMate · 能说会做的待办智能助理")  # 供无障碍/测试读取的主标题
    st.caption("输入自然语言即可增删查改任务；点回复下方的「执行轨迹」可以看到 Agent 真的调用了哪些工具。")

    with st.sidebar:
        st.header("📋 任务看板")
        try:
            render_board(get_store())
        except Exception as e:
            st.error(f"看板加载失败：{type(e).__name__}: {e}")

        st.divider()
        st.subheader("⚙️ 会话与设置")
        tts_on = st.toggle("🔊 语音播报回复（edge-tts）", value=False)
        if st.button("🧹 清空本轮对话记忆", use_container_width=True):
            st.session_state.messages = []
            try:
                get_runtime().reset("web")
            except Exception:
                pass
            st.rerun()
        problems = check_config()
        if problems:
            st.warning("；".join(problems) + "。也可先用离线模式：设置 USE_MOCK_LLM=1")
        with st.expander("🧰 当前 MCP 工具（8）"):
            st.markdown("\n".join(
                f"- `{n}`" for n in ["add_task", "batch_add_tasks", "list_tasks", "update_task",
                                     "complete_task", "delete_task", "get_stats", "daily_briefing"]))
        st.caption(f"数据库：{Path(Config.DB_PATH).name} · 历史 {Config.HISTORY_TURNS} 轮 · 单轮最多 {Config.MAX_STEPS} 步")

    if "messages" not in st.session_state:
        st.session_state.messages = []

    if not st.session_state.messages:
        st.markdown("**试试这样问（点一下即可发送）：**")
        cols = st.columns(4)
        for col, (label, text) in zip(cols, EXAMPLES):
            if col.button(label, use_container_width=True, help=text):
                st.session_state.pending_input = text

    for m in st.session_state.messages:
        with st.chat_message(m["role"]):
            st.markdown(m["content"])
            if m.get("trace"):
                show_trace(m["trace"])

    prompt = st.chat_input("说点什么，比如：提醒我后天交实验报告，优先级最高")
    if st.session_state.get("pending_input"):
        prompt = st.session_state.pop("pending_input")

    audio = None
    try:
        # BUG-13：录音被消费后必须在下一轮「组件实例化之前」清空它的值——
        # 实例化之后再改 st.session_state["voice_rec"] 会抛
        # StreamlitWidgetAlreadyInstantiatedError（组件态 key 实例化后只读）
        if st.session_state.get("voice_consumed"):
            st.session_state.voice_rec = None
            st.session_state.voice_consumed = False
        audio = st.audio_input("🎤 或直接说话（语音输入）", key="voice_rec")
    except Exception:
        pass
    if audio:
        from ui.voice import asr_ready, transcribe

        if not asr_ready():
            st.warning("语音识别组件未安装：pip install faster-whisper（装好后重启页面）")
        else:
            with st.spinner("语音识别中…（首次需下载模型，请稍候）"):
                heard = transcribe(audio.getvalue())
            # 只标记「已消费」：下一轮 rerun 时在组件实例化前清空录音，
            # 防止同一段录音被再次转写发送（无限重复录入 BUG-13）
            st.session_state.voice_consumed = True
            if heard:
                st.toast(f"🎤 听到你说：{heard}")
                prompt = heard
            else:
                st.warning("没听清，请靠近麦克风再说一次，或改用打字。")

    if prompt:
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        with st.chat_message("assistant"):
            try:
                with st.spinner("思考并调用工具中…"):
                    out = get_runtime().chat(prompt, session_id="web")
                st.markdown(out["answer"])
                if out["trace"]:
                    show_trace(out["trace"])
                st.session_state.messages.append(
                    {"role": "assistant", "content": out["answer"], "trace": out["trace"]})
                if tts_on:
                    try:
                        from ui.voice import speak

                        mp3 = speak(out["answer"])
                        if mp3:
                            st.audio(mp3, format="audio/mp3")
                    except Exception:
                        st.caption("（语音播报不可用，已忽略）")
                st.rerun()  # 让看板立即反映最新数据
            except Exception as e:
                msg = f"❌ 出错了：{type(e).__name__}: {e}。可检查 .env 配置，或改用离线模式（USE_MOCK_LLM=1）。"
                st.error(msg)
                st.session_state.messages.append({"role": "assistant", "content": msg})


if __name__ == "__main__":
    main()
