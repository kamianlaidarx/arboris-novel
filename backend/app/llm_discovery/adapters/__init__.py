# AIMETA P=模型发现适配器|R=各协议模型列表获取|NR=不含缓存与识别|E=adapters|X=internal|A=适配器包|D=httpx|S=net|RD=./README.ai
"""各协议族的模型列表适配器。"""

from .anthropic import AnthropicModelAdapter
from .base import DiscoverContext, ModelListAdapter, build_async_client
from .google import GoogleModelAdapter
from .ollama import OllamaModelAdapter
from .openai_compatible import OpenAICompatibleAdapter

__all__ = [
    "AnthropicModelAdapter",
    "DiscoverContext",
    "GoogleModelAdapter",
    "ModelListAdapter",
    "OllamaModelAdapter",
    "OpenAICompatibleAdapter",
    "build_async_client",
]
