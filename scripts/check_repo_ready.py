# -*- coding: utf-8 -*-
"""提交前的仓库体检：不要把 GitHub 装不下的东西推上去。

检查四件事（任一项不通过即退出码 1）：
1. 超大文件：GitHub 单文件上限 100MB，超过它 push 会直接失败
2. 敏感文件：.env / *.db 等不应入库的文件
3. 忽略有效性：上面两类文件是否真的被 .gitignore 覆盖
4. 必需文件：README / 测试 / CI / 源码是否齐全

用法：python scripts/check_repo_ready.py     （push 前跑一次，全绿再 push）
"""
from __future__ import annotations

import fnmatch
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GITHUB_FILE_LIMIT_MB = 100
BIG_FILE_WARN_MB = 50

# 相对路径会被跳过的目录（本质不算仓库内容）
SKIP_DIRS = {".git", "__pycache__", ".pytest_cache", ".mypy_cache", ".idea", ".vscode"}

# 必须存在的关键文件（缺了说明提交漏了东西）
REQUIRED = [
    "README.md", "INTERFACE.md", "LICENSE", "CONTRIBUTING.md", ".gitignore",
    ".gitattributes", "requirements.txt", "run.ps1", "main.py",
    ".github/workflows/tests.yml",
    "server/storage.py", "server/task_mcp_server.py",
    "ui/app.py", "ui/task_views.py", "ui/voice.py",
    "tests/selftest.py", "tests/test_e2e.py", "tests/test_ui_smoke.py",
    "docs/环境配置.md", "demo/bug_log.md", "交付清单.md",
]

results: list[bool] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append(bool(ok))
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  → {detail}" if detail else ""))


def load_ignore_patterns() -> list[str]:
    gi = ROOT / ".gitignore"
    if not gi.exists():
        return []
    out = []
    for line in gi.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            out.append(line)
    return out


def is_ignored(rel: str, patterns: list[str]) -> bool:
    """用简化规则判断路径是否被 .gitignore 覆盖（够用即可，不追求 100% 复刻 git 语义）。"""
    rel = rel.replace("\\", "/")
    parts = rel.split("/")
    for pat in patterns:
        p = pat.strip("/")
        if not p:
            continue
        if fnmatch.fnmatch(rel, p) or fnmatch.fnmatch(parts[-1], p):
            return True
        # 目录型规则：models/whisper-*/ → 覆盖该目录下所有文件
        if pat.endswith("/") or p.endswith("*"):
            for i in range(len(parts)):
                prefix = "/".join(parts[: i + 1])
                if fnmatch.fnmatch(prefix, p) or fnmatch.fnmatch(prefix + "/", pat):
                    return True
    return False


def main() -> int:
    patterns = load_ignore_patterns()
    check(".gitignore 存在且有规则", bool(patterns), f"{len(patterns)} 条规则")

    files: list[Path] = []
    ignored_files: list[Path] = []
    for f in ROOT.rglob("*"):
        if f.is_file() and not any(part in SKIP_DIRS for part in f.parts):
            rel_all = str(f.relative_to(ROOT)).replace("\\", "/")
            (ignored_files if is_ignored(rel_all, patterns) else files).append(f)

    # 1. 超大文件：已经被 .gitignore 忽略的不算待提交内容，只看真正会入库的
    big = [(f, f.stat().st_size) for f in files if f.stat().st_size > BIG_FILE_WARN_MB * 1024 * 1024]
    oversize = [(f, s) for f, s in big if s > GITHUB_FILE_LIMIT_MB * 1024 * 1024]
    check(f"待提交文件中没有超过 GitHub 单文件上限（{GITHUB_FILE_LIMIT_MB}MB）的",
          not oversize,
          "; ".join(f"{f.relative_to(ROOT)} {s/1024/1024:.0f}MB" for f, s in oversize) or "无")
    # 被忽略的超大文件也要显式确认，防止改 .gitignore 时误删规则
    big_ignored = [f for f in ignored_files if f.stat().st_size > GITHUB_FILE_LIMIT_MB * 1024 * 1024]
    for f in big_ignored:
        rel = str(f.relative_to(ROOT)).replace("\\", "/")
        check(f"超大文件仍被 .gitignore 忽略：{rel}", is_ignored(rel, patterns),
              f"{f.stat().st_size/1024/1024:.0f}MB（不入 Git，靠 scripts/fetch_asr_model.py 重建）")
    if big and not oversize:
        print(f"  INFO  {len(big)} 个体积较大但未超限的文件（可正常提交）："
              f"{', '.join(str(f.relative_to(ROOT)) for f, _ in big)[:120]}")

    # 2. 敏感文件是否会被误提交：要看磁盘上「所有」文件，
    #    它们被判为已忽略正是我们要显式确认的事
    sensitive = []
    for f in files + ignored_files:
        rel = str(f.relative_to(ROOT)).replace("\\", "/")
        if rel == ".env" or rel.endswith("/.env") or rel.endswith(".db"):
            sensitive.append(rel)
    check("敏感文件均被 .gitignore 忽略", bool(sensitive) and all(is_ignored(r, patterns) for r in sensitive)
          or not sensitive,
          "; ".join(sensitive) or "磁盘上没有 .env / *.db")
    for rel in sensitive:
        check(f"敏感文件被忽略：{rel}", is_ignored(rel, patterns))

    # 3. 必需文件齐全
    missing = [r for r in REQUIRED if not (ROOT / r).exists()]
    check("关键文件齐全", not missing, f"缺失：{missing}" if missing else f"{len(REQUIRED)} 个关键文件都在")

    # 4. 别把临时调试文件混进来（排除 __init__.py 这类双下划线文件）
    stray = [str(f.relative_to(ROOT)).replace("\\", "/") for f in files
             if re.match(r"^_(?!_)[^/]*\.(py|txt|md)$", f.name)]
    check("没有 _ 开头的临时调试文件", not stray, "; ".join(stray) or "干净（临时脚本已清理）")

    passed = sum(results)
    print(f"\n{passed}/{len(results)} 通过" + ("" if passed == len(results) else "  ← 先修再 push！"))
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
