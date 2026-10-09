# AIMETA P=模型发现异常体系|R=错误分级与用户提示|NR=不含探测逻辑|E=ModelDiscoveryError|X=internal|A=异常类|D=none|S=none|RD=./README.ai
"""模型发现过程中的分级异常。

设计目标：把「拿不到模型列表」的原因明确区分开，让 API 层能返回
可直接展示给用户的中文提示（``message``）+ 可操作的下一步建议（``hint``），
而不是像旧实现那样统一返回空列表。
"""

from __future__ import annotations

from typing import Optional


class ModelDiscoveryError(Exception):
    """模型发现异常基类。

    Attributes:
        message: 面向用户的中文说明。
        hint: 针对该错误的排查/修复建议。
        provider: 供应商标识。
        endpoint: 触发错误的请求地址。
        status_code: 第三方返回的 HTTP 状态码（若有）。
        http_status: 映射到本服务应返回的 HTTP 状态码。
        details: 第三方原始错误片段，用于"查看详情"。
    """

    default_message = "获取模型列表失败"
    default_hint = "请检查 API 地址与 API Key 是否正确。"
    http_status = 502

    def __init__(
        self,
        message: Optional[str] = None,
        *,
        hint: Optional[str] = None,
        provider: Optional[str] = None,
        endpoint: Optional[str] = None,
        status_code: Optional[int] = None,
        details: Optional[str] = None,
        attempted_endpoints: Optional[list] = None,
    ) -> None:
        self.message = message or self.default_message
        self.hint = hint or self.default_hint
        self.provider = provider
        self.endpoint = endpoint
        self.status_code = status_code
        self.details = details
        self.attempted_endpoints = list(attempted_endpoints or [])
        super().__init__(self.message)

    def to_dict(self) -> dict:
        payload = {
            "error": self.__class__.__name__,
            "message": self.message,
            "hint": self.hint,
        }
        if self.provider:
            payload["provider"] = self.provider
        if self.endpoint:
            payload["endpoint"] = self.endpoint
        if self.attempted_endpoints:
            payload["attempted_endpoints"] = self.attempted_endpoints
        if self.status_code is not None:
            payload["upstream_status"] = self.status_code
        if self.details:
            payload["details"] = self.details
        return payload


class InvalidCredentialsError(ModelDiscoveryError):
    """缺少必要的凭证。"""

    default_message = "未提供 API Key"
    default_hint = "请先填写 API Key，或保存配置后再点击刷新。"
    http_status = 400


class ProviderAuthError(ModelDiscoveryError):
    """第三方返回 401/403，凭证无效或权限不足。"""

    default_message = "认证失败：API Key 无效或没有访问模型列表的权限"
    default_hint = "请确认 API Key 未过期、未填错，并确认该 Key 所属账号有权访问此接口。"
    http_status = 401


class ProviderRateLimitError(ModelDiscoveryError):
    """第三方返回 429，触发限流。"""

    default_message = "请求过于频繁，供应商已限流"
    default_hint = "请稍后再试；若持续出现，请检查该 Key 的速率额度。"
    http_status = 429


class NoModelListEndpointError(ModelDiscoveryError):
    """第三方不提供模型列表接口（常见于部分中转站与自建网关）。"""

    default_message = "该服务未提供模型列表接口"
    default_hint = "这属于正常情况：请手动输入模型名称（例如 deepseek-chat、gpt-4o-mini）。"
    http_status = 404


class ProviderUnreachableError(ModelDiscoveryError):
    """网络层不可达、超时或地址写错。"""

    default_message = "无法连接到该 API 地址"
    default_hint = "请检查地址是否可访问（含协议与端口），以及服务器是否能访问公网。"
    http_status = 504


class ProviderServerError(ModelDiscoveryError):
    """第三方返回 5xx。"""

    default_message = "供应商服务端错误"
    default_hint = "通常是对方临时故障，请稍后重试。"
    http_status = 502


class InvalidProviderURLError(ModelDiscoveryError):
    """用户填写的地址不是合法 URL。"""

    default_message = "API 地址格式不正确"
    default_hint = "地址需要以 http:// 或 https:// 开头，例如 https://api.deepseek.com/v1。"
    http_status = 400


class LocalEndpointBlockedError(ModelDiscoveryError):
    """内网地址被安全开关拦截。"""

    default_message = "出于安全考虑，服务器拒绝访问内网地址"
    default_hint = "如需连接内网/本地的模型网关，请让管理员开启 ALLOW_PRIVATE_LLM_ENDPOINTS。"
    http_status = 403
