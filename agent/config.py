"""全局配置（成员 B 负责）：统一从 .env 读取，避免三人各写一套。"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


def _get(key: str, default: str = "") -> str:
    return os.getenv(key, default)


class Config:
    # LLM
    API_KEY = _get("LLM_API_KEY")
    BASE_URL = _get("LLM_BASE_URL", "https://api.deepseek.com/v1")
    MODEL = _get("LLM_MODEL", "deepseek-chat")

    # 存储
    DB_PATH = _get("TASK_DB_PATH", "data/tasks.db")
    if not os.path.isabs(DB_PATH):
        DB_PATH = str(ROOT / DB_PATH)

    # Agent
    MAX_STEPS = int(_get("AGENT_MAX_STEPS", "8"))
    HISTORY_TURNS = int(_get("AGENT_HISTORY_TURNS", "20"))

    # 离线演示：用规则假大脑替代 LLM，无需 API key 也能跑通全链路
    USE_MOCK_LLM = _get("USE_MOCK_LLM", "0").strip().lower() in ("1", "true", "yes")

    # MCP Server 启动脚本
    SERVER_SCRIPT = str(ROOT / "server" / "task_mcp_server.py")


def check_config() -> list[str]:
    """启动前自检，返回问题列表（空列表表示配置 OK）。"""
    problems = []
    if Config.USE_MOCK_LLM:  # 离线演示模式不要求 key
        return problems
    if not Config.API_KEY or Config.API_KEY.startswith("sk-xxxx"):
        problems.append("未配置 LLM_API_KEY，请复制 .env.example 为 .env 并填入 key")
    if not Path(Config.SERVER_SCRIPT).exists():
        problems.append(f"找不到 MCP Server 脚本：{Config.SERVER_SCRIPT}")
    return problems
