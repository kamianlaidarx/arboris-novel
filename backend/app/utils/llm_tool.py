# -*- coding: utf-8 -*-
# AIMETA P=LLM工具_大模型调用辅助|R=请求构建_响应解析|NR=不含业务逻辑|E=LLMTool|X=internal|A=工具类|D=httpx|S=net|RD=./README.ai
"""OpenAI 兼容型 LLM 工具封装，保持与旧项目一致的接口体验。"""

import os
from dataclasses import asdict, dataclass
from typing import AsyncGenerator, Dict, List, Optional

import httpx
from openai import AsyncOpenAI


@dataclass
class ChatMessage:
    role: str
    content: str

    def to_dict(self) -> Dict[str, str]:
        return asdict(self)


class LLMClient:
    """异步流式调用封装，兼容 OpenAI SDK。"""

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        key = api_key or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise ValueError("缺少 OPENAI_API_KEY 配置，请在数据库或环境变量中补全。")

        self._client = AsyncOpenAI(api_key=key, base_url=base_url or os.environ.get("OPENAI_API_BASE"))

    async def stream_chat(
        self,
        messages: List[ChatMessage],
        model: Optional[str] = None,
        response_format: Optional[str] = None,
        temperature: Optional[float] = None,
        top_p: Optional[float] = None,
        max_tokens: Optional[int] = None,
        timeout: int = 120,
        **kwargs,
    ) -> AsyncGenerator[Dict[str, str], None]:
        payload = {
            "model": model or os.environ.get("MODEL", "gpt-3.5-turbo"),
            "messages": [msg.to_dict() for msg in messages],
            "stream": True,
            **kwargs,
        }
        if response_format:
            payload["response_format"] = {"type": response_format}
        if temperature is not None:
            payload["temperature"] = temperature
        if top_p is not None:
            payload["top_p"] = top_p
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens

        # timeout 必须作为【调用参数】传给 SDK，不能塞进 payload。
        # 之前写在 payload 里有两个后果：
        #   1) 被序列化成请求体里的非法字段发给上游；
        #   2) 完全不生效——SDK 只认 create(timeout=...) 这个关键字参数。
        # 于是超时形同虚设，上游卡住时会一直挂着，直到被 Cloudflare(100s)
        # 或 nginx(600s) 掐断，表现为「AI 服务内部错误」或 524。
        #
        # 用 httpx.Timeout 拆分：连接阶段短超时（快速失败），
        # 读取阶段用调用方给的长超时（生成长文本需要时间）。
        request_timeout = httpx.Timeout(
            timeout,          # 读超时：整体允许的最大空闲等待
            connect=min(15.0, float(timeout)),
        )

        stream = await self._client.chat.completions.create(
            timeout=request_timeout, **payload
        )
        async for chunk in stream:
            if not chunk.choices:
                continue
            choice = chunk.choices[0]
            yield {
                "content": choice.delta.content,
                "finish_reason": choice.finish_reason,
            }
