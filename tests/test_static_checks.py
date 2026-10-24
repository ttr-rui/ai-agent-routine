"""静态一致性检查：不联网、不花钱，专抓「文档/配置/代码不一致」这类交付事故。

运行：  python tests/test_static_checks.py
"""
from __future__ import annotations

import importlib.util
import py_compile
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

results: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    results.append((name, bool(cond), detail))
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  → {detail}" if detail else ""))


def main() -> int:
    # 1. 所有 py 文件语法可编译
    py_files = [p for p in ROOT.rglob("*.py") if "_smoke" not in p.name]
    bad = []
    for p in py_files:
        try:
            py_compile.compile(str(p), doraise=True, cfile=str(p.with_suffix(".pyc_tmp")))
        except py_compile.PyCompileError as e:
            bad.append(f"{p.name}: {e}")
        finally:
            tmp = p.with_suffix(".pyc_tmp")
            if tmp.exists():
                tmp.unlink()
    check(f"全部 {len(py_files)} 个 py 文件语法正确", not bad, "; ".join(bad)[:200])

    # 2. 关键文件齐备
    required = [
        "server/storage.py", "server/task_mcp_server.py",
        "agent/config.py", "agent/llm.py", "agent/mcp_client.py",
        "agent/memory.py", "agent/prompts.py", "agent/agent.py",
        "ui/app.py", "ui/voice.py", "main.py",
        "requirements.txt", ".env.example", ".gitignore",
        "README.md", "blog/博客园随笔.md", "mcp_config_example.json",
    ]
    missing = [f for f in required if not (ROOT / f).exists()]
    check("交付文件齐备", not missing, f"缺失 {missing}")

    # 3. requirements 必须锁 mcp<2（否则 2.x 会 FastMCP 改名导致启动失败）
    req = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    check("requirements 已锁 mcp<2.0.0", "mcp>=1.9.0,<2.0.0" in req)

    # 4. .env.example 的 key 与 config.py 实际读取的一致
    env_keys = set(re.findall(r"^([A-Z_]+)=", (ROOT / ".env.example").read_text(encoding="utf-8"), re.M))
    cfg_src = (ROOT / "agent" / "config.py").read_text(encoding="utf-8")
    used_keys = set(re.findall(r'_get\("([A-Z_]+)"', cfg_src))
    check("配置 key 在 .env.example 中有说明", used_keys <= env_keys,
          f"代码用到但示例缺: {used_keys - env_keys}")

    # 5. README 里提到的命令，其入口文件真实存在
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    check("README 提到的入口文件都存在",
          all((ROOT / p).exists() for p in ["main.py", "ui/app.py", "server/task_mcp_server.py",
                                            "tests/selftest.py", "tests/test_storage.py"])
          and "streamlit run ui/app.py" in readme)

    # 6. ui 目录无 __init__.py，但 ui.voice 必须能被导入（命名空间包）
    sys.path.insert(0, str(ROOT))
    try:
        spec = importlib.util.find_spec("ui.voice")
        check("ui.voice 可被导入（命名空间包）", spec is not None)
    except Exception as e:
        check("ui.voice 可被导入（命名空间包）", False, f"{type(e).__name__}: {e}")

    # 7. MCP Server 暴露的工具数与 README 声明一致
    srv = (ROOT / "server" / "task_mcp_server.py").read_text(encoding="utf-8")
    n_tools = len(re.findall(r"@mcp\.tool\(\)", srv))
    check(f"Server 工具数量 = 8（README 声明）", n_tools == 8, f"实际 {n_tools}")

    # 7.5 MCP 客户端配置示例必须是合法 JSON
    try:
        cfg_json = __import__("json").loads((ROOT / "mcp_config_example.json").read_text(encoding="utf-8"))
        check("mcp_config_example.json 合法且含 mcpServers", "mcpServers" in cfg_json)
    except Exception as e:
        check("mcp_config_example.json 合法且含 mcpServers", False, f"{type(e).__name__}: {e}")

    # 8. 敏感信息不会被提交
    gi = (ROOT / ".gitignore").read_text(encoding="utf-8")
    check(".gitignore 已排除 .env 与 db", ".env" in gi and ".db" in gi)

    # 9. 没有把真实 key 写进仓库
    leaked = [p.name for p in ROOT.rglob("*.py")
              if re.search(r"sk-[A-Za-z0-9]{16,}", p.read_text(encoding="utf-8", errors="ignore"))]
    check("代码中无硬编码 API key", not leaked, str(leaked))

    passed = sum(1 for _, ok, _ in results if ok)
    print(f"\n{passed}/{len(results)} 通过")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
