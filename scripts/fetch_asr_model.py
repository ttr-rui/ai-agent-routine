# -*- coding: utf-8 -*-
"""一键下载 faster-whisper 语音模型到 models/whisper-<size>/。

为什么需要这个脚本：model.bin 单文件约 138MB，超过 GitHub 单文件 100MB 上限，
所以模型文件不能进仓库（已在 .gitignore 里排除），换机器后靠本脚本重建。

用法：
    python scripts/fetch_asr_model.py              # 默认 base（约 145MB，推荐）
    python scripts/fetch_asr_model.py --size tiny  # 约 75MB，最快但准确率略低
    python scripts/fetch_asr_model.py --size small # 约 480MB，更准

国内网络默认走 hf-mirror 镜像；可用 --endpoint 或环境变量 HF_ENDPOINT 覆盖。
"""
from __future__ import annotations

import argparse
import os
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILES = ["config.json", "model.bin", "tokenizer.json", "vocabulary.txt"]
DEFAULT_ENDPOINT = "https://hf-mirror.com"


def human(n: int) -> str:
    return f"{n / 1024 / 1024:.1f}MB" if n >= 1024 * 1024 else f"{n / 1024:.0f}KB"


def download(url: str, dst: Path, retries: int = 3) -> None:
    """单个文件下载 + 断点无关的简单重试（镜像偶尔 429 限流）。"""
    if dst.exists() and dst.stat().st_size > 0:
        print(f"  已存在，跳过：{dst.name}（{human(dst.stat().st_size)}）")
        return
    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "taskmate-agent"})
            with urllib.request.urlopen(req, timeout=120) as resp, open(dst, "wb") as f:
                total = int(resp.headers.get("Content-Length") or 0)
                got = 0
                while True:
                    chunk = resp.read(256 * 1024)
                    if not chunk:
                        break
                    f.write(chunk)
                    got += len(chunk)
                    if total:
                        print(
                            f"\r  {dst.name}：{got * 100 // total}%（{human(got)}/{human(total)}）",
                            end="", flush=True,
                        )
            print(f"\r  {dst.name} 下载完成（{human(dst.stat().st_size)}）        ")
            return
        except Exception as e:  # noqa: BLE001 - 网络类错误统一重试
            last_err = e
            print(f"\n  第 {attempt} 次失败：{e}，3 秒后重试…")
            time.sleep(3)
    raise RuntimeError(f"{dst.name} 下载失败：{last_err}")


def main() -> int:
    ap = argparse.ArgumentParser(description="下载 faster-whisper 模型（不入库，按需获取）")
    ap.add_argument("--size", default="base", choices=["tiny", "base", "small", "medium"])
    ap.add_argument("--endpoint", default=os.getenv("HF_ENDPOINT", DEFAULT_ENDPOINT))
    args = ap.parse_args()

    out_dir = ROOT / "models" / f"whisper-{args.size}"
    out_dir.mkdir(parents=True, exist_ok=True)
    base = f"{args.endpoint.rstrip('/')}/Systran/faster-whisper-{args.size}/resolve/main"
    print(f"下载 whisper-{args.size} 到 {out_dir}\n镜像源：{args.endpoint}")

    for name in FILES:
        download(f"{base}/{name}", out_dir / name)
    print(f"\n完成。模型目录：{out_dir}")
    print("提示：本机用 tiny 可在 ui/voice.py 用环境变量 VOICE_ASR_MODEL=tiny 指定。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
