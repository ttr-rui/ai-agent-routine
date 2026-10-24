"""LLM 客户端封装（成员 B 负责）：只用 OpenAI 兼容协议，换模型只改 .env。"""
from __future__ import annotations

import json
from typing import Any

from openai import AsyncOpenAI

from .config import Config


class LLM:
    def __init__(self) -> None:
        if not Config.API_KEY:
            raise RuntimeError("未配置 LLM_API_KEY，请先填写 .env")
        self.client = AsyncOpenAI(api_key=Config.API_KEY, base_url=Config.BASE_URL)
        self.model = Config.MODEL

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        temperature: float = 0.2,
    ) -> dict[str, Any]:
        """返回统一的 dict：{role, content, tool_calls:[{id,name,arguments}]}"""
        kwargs: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        resp = await self.client.chat.completions.create(**kwargs)
        msg = resp.choices[0].message

        tool_calls = []
        if msg.tool_calls:
            for tc in msg.tool_calls:
                tool_calls.append(
                    {
                        "id": tc.id,
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    }
                )
        return {"role": "assistant", "content": msg.content or "", "tool_calls": tool_calls}

    async def summarize(self, text: str) -> str:
        """把超长的历史对话压成一段摘要，用于长程记忆。"""
        resp = await self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": "你是对话摘要器，用中文 200 字以内压缩下面的对话，"
                                              "必须保留：用户已确定的任务、截止时间、偏好设置。"},
                {"role": "user", "content": text},
            ],
            temperature=0.1,
        )
        return resp.choices[0].message.content or ""

    @staticmethod
    def safe_json(raw: str) -> dict:
        try:
            return json.loads(raw or "{}")
        except json.JSONDecodeError:
            return {"_raw": raw}
