"""语音输入/输出（成员 B 负责，加分项）。

链路：
- 语音 → 文字（ASR）：faster-whisper 本地模型（离线、免费、中文可用）
  → 云端 /audio/transcriptions 兜底（仅当 LLM 服务商提供该接口，如 OpenAI；DeepSeek 不提供）
  → 都失败返回空串，UI 提示改用打字
- 文字 → 语音（TTS）：edge-tts（微软 Edge 在线 TTS，免费、无需 key、中文音色自然）

设计要点：
- ASR 模型全局只加载一次；仓库自带本地模型文件（models/whisper-base/），
  首次即可离线使用，无需联网下载
- 模型缺失时自动回退 HuggingFace 在线下载（国内默认走 hf-mirror 镜像）
- 任何一步失败都不抛异常——语音是加分项，绝不能拖垮主流程
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"
# tiny≈75MB 最快 / base≈145MB 推荐 / small≈480MB 更准；课程演示用 base 足够
ASR_MODEL = os.getenv("VOICE_ASR_MODEL", "base")
# 仓库自带模型目录（curl 从 hf-mirror 下载的离线文件，开箱即用）
LOCAL_MODEL_DIR = ROOT / "models" / f"whisper-{ASR_MODEL}"

# 模型缺失需联网下载时的兜底配置；国内网络默认用 hf-mirror 下载模型
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
# 禁用 xet 存储协议：镜像站无法转发 xet CAS 会返回 401，导致模型大文件永远下载失败。
# 关掉后走普通 HTTP 从镜像下载，国内网络才能下成功。
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

_whisper_model = None  # 进程级单例


def _get_whisper():
    """懒加载并复用 faster-whisper 模型（优先仓库自带本地文件，缺失则在线下载）。"""
    global _whisper_model
    if _whisper_model is None:
        from faster_whisper import WhisperModel

        model_path = str(LOCAL_MODEL_DIR) if LOCAL_MODEL_DIR.exists() else ASR_MODEL
        _whisper_model = WhisperModel(model_path, device="cpu", compute_type="int8")
    return _whisper_model


# ---------------------------------------------------------------- 语音识别
def transcribe(audio_bytes: bytes, suffix: str = ".wav") -> str:
    """把一段音频转成中文文字；失败返回空串（不抛异常）。

    audio_bytes: 浏览器 st.audio_input 录到的 WAV，或任意 mp3/wav 字节流
    """
    if not audio_bytes:
        return ""
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as f:
        f.write(audio_bytes)
        path = f.name
    try:
        # 1) 本地 faster-whisper（推荐路径：离线、免费）
        try:
            model = _get_whisper()
            segments, _ = model.transcribe(path, language="zh", vad_filter=True)
            text = "".join(s.text for s in segments).strip()
            if text:
                return text
            print("[voice] 本地 ASR 未识别出内容", file=sys.stderr)
        except Exception as e:
            print(f"[voice] faster-whisper 不可用（{e}），尝试云端接口", file=sys.stderr)

        # 2) 云端兜底：只有 LLM 服务商提供 /audio/transcriptions 才可用（DeepSeek 无此接口）
        try:
            from openai import OpenAI
            from dotenv import load_dotenv

            load_dotenv(ROOT / ".env")
            base_url = os.getenv("LLM_BASE_URL", "")
            if "api.openai.com" not in base_url:
                print("[voice] 当前 LLM 服务商不提供语音接口，跳过云端兜底", file=sys.stderr)
                return ""
            client = OpenAI(api_key=os.getenv("LLM_API_KEY"), base_url=base_url)
            with open(path, "rb") as fh:
                return client.audio.transcriptions.create(
                    model="whisper-1", file=fh, language="zh"
                ).text
        except Exception as e:
            print(f"[voice] 云端 ASR 也不可用：{e}", file=sys.stderr)
            return ""
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


# ---------------------------------------------------------------- 语音合成
async def _tts_to_file(text: str, out_path: str, voice: str = DEFAULT_VOICE) -> None:
    import edge_tts

    comm = edge_tts.Communicate(text, voice)
    await comm.save(out_path)


def speak(text: str, voice: str = DEFAULT_VOICE) -> bytes | None:
    """把文字合成成 mp3 字节流，失败返回 None。"""
    if not text:
        return None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as f:
            path = f.name
        asyncio.run(_tts_to_file(text[:500], path, voice))
        data = Path(path).read_bytes()
        os.unlink(path)
        return data
    except Exception as e:
        print(f"[voice] TTS 失败：{e}", file=sys.stderr)
        return None


def asr_ready() -> bool:
    """ASR 是否可用（UI 据此决定是否展示语音按钮的提示文案）。"""
    try:
        import faster_whisper  # noqa: F401

        return True
    except ImportError:
        return False


if __name__ == "__main__":
    print("测试 TTS + ASR 闭环…")
    mp3 = speak("你好，我是 TaskMate，帮我添加任务：明天交智能体作业")
    print("TTS 生成字节数：", len(mp3) if mp3 else 0)
    if mp3:
        text = transcribe(mp3, suffix=".mp3")
        print("ASR 转写结果：", text)
