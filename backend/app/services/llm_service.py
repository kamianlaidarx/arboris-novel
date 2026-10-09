# AIMETA P=LLM服务_大模型调用封装|R=API调用_流式生成|NR=不含业务逻辑|E=LLMService|X=internal|A=服务类|D=openai,httpx|S=net|RD=./README.ai
import logging
import os
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx
from fastapi import HTTPException, status
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    InternalServerError,
)

from ..core.config import settings
from ..repositories.llm_config_repository import LLMConfigRepository
from ..repositories.system_config_repository import SystemConfigRepository
from ..repositories.user_repository import UserRepository
from ..services.admin_setting_service import AdminSettingService
from ..services.prompt_service import PromptService
from ..services.usage_service import UsageService
from ..utils.llm_tool import ChatMessage, LLMClient

logger = logging.getLogger(__name__)

try:  # pragma: no cover - 运行环境未安装时兼容
    from ollama import AsyncClient as OllamaAsyncClient
except ImportError:  # pragma: no cover - Ollama 为可选依赖
    OllamaAsyncClient = None


def _extract_upstream_message(exc: Exception) -> Optional[str]:
    """从上游错误响应里取出可读消息。

    优先取 ``message_zh``（部分网关会返回中文），其次 ``message``。
    取不到就返回 None，由调用方决定兜底文案。
    """
    response = getattr(exc, "response", None)
    if response is None:
        return None
    try:
        payload = response.json()
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    error_data = payload.get("error")
    if not isinstance(error_data, dict):
        # 有些网关直接把 message 放在顶层
        top = payload.get("message")
        return top if isinstance(top, str) and top else None
    for key in ("message_zh", "message"):
        value = error_data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _classify_upstream_status(
    exc: APIStatusError, model: Optional[str]
) -> tuple[int, str]:
    """把上游 HTTP 状态码翻译成「可操作」的中文提示。

    返回 ``(对前端暴露的状态码, 提示文案)``。

    重点是把**配置类错误**（模型名写错、key 无效、余额不足）与
    真正的服务端故障区分开——前者用户自己就能修，后者只能等。
    以前这两类都变成 500，用户完全看不出该做什么。
    """
    code = getattr(exc, "status_code", None)
    upstream = _extract_upstream_message(exc)
    model_hint = f"当前模型「{model}」" if model else "当前模型"

    if code == 404:
        return 400, (
            f"{model_hint}在该服务上不存在（上游返回 404）。"
            "请检查模型名是否拼写正确，或点击「从网关拉取可用模型」重新选择。"
        )
    if code == 401:
        return 401, "AI 服务的 API Key 无效或已过期，请重新配置。"
    if code == 403:
        return 403, (
            f"AI 服务拒绝了本次请求（403）{f'：{upstream}' if upstream else '，可能是 Key 权限不足或模型未开通。'}"
        )
    if code == 400:
        # 余额不足也常以 400/402 出现，这里把上游原文带出来更有用
        if upstream and ("balance" in upstream.lower() or "余额" in upstream or "quota" in upstream.lower()):
            return 402, f"AI 服务账户余额不足：{upstream}"
        return 400, (
            f"AI 服务认为请求不合法（400）{f'：{upstream}' if upstream else '，请检查模型参数配置。'}"
        )
    if code == 402:
        return 402, f"AI 服务账户余额不足{f'：{upstream}' if upstream else '，请充值后重试。'}"
    if code == 422:
        return 400, (
            f"AI 服务无法处理该请求（422）{f'：{upstream}' if upstream else '，请检查模型参数。'}"
        )
    if code == 429:
        return 429, "AI 服务限流（429），请稍后重试或降低请求频率。"
    if code is not None and code >= 500:
        return 503, f"AI 服务内部错误（{code}），请稍后重试。"

    # 其余状态码：原样透传，附上游消息
    return 502, (
        f"AI 服务返回异常状态 {code}"
        f"{f'：{upstream}' if upstream else '，请检查模型配置。'}"
    )


def _upstream_error_detail(exc: Exception, fallback: str) -> str:
    """取上游错误消息，取不到则用兜底文案。

    注意优先级：**兜底文案优先于 ``str(exc)``**。
    OpenAI SDK 的 ``str(exc)`` 通常是 ``"upstream error"`` 这类
    没有信息量的占位串，直接展示给用户还不如我们自己的中文提示。
    所以只有在既没有上游消息、也没有兜底文案时才退回 ``str(exc)``。
    """
    return _extract_upstream_message(exc) or fallback or str(exc)


class LLMService:
    """封装与大模型交互的所有逻辑，包括配额控制与配置选择。"""

    def __init__(self, session):
        self.session = session
        self.llm_repo = LLMConfigRepository(session)
        self.system_config_repo = SystemConfigRepository(session)
        self.user_repo = UserRepository(session)
        self.admin_setting_service = AdminSettingService(session)
        self.usage_service = UsageService(session)
        self._embedding_dimensions: Dict[str, int] = {}

    async def get_llm_response(
        self,
        system_prompt: str,
        conversation_history: List[Dict[str, str]],
        *,
        temperature: float = 0.7,
        user_id: Optional[int] = None,
        timeout: float = 300.0,
        response_format: Optional[str] = "json_object",
        max_tokens: Optional[int] = None,
        top_p: Optional[float] = None,
        model: Optional[str] = None,
    ) -> str:
        messages = [{"role": "system", "content": system_prompt}, *conversation_history]
        return await self._stream_and_collect(
            messages,
            temperature=temperature,
            user_id=user_id,
            timeout=timeout,
            response_format=response_format,
            max_tokens=max_tokens,
            top_p=top_p,
            model=model,
        )

    async def generate(
        self,
        prompt: str,
        *,
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
        user_id: Optional[int] = None,
        timeout: float = 300.0,
        max_tokens: Optional[int] = None,
        response_format: Optional[str] = None,
        top_p: Optional[float] = None,
        model: Optional[str] = None,
    ) -> str:
        """兼容旧版接口的文本生成入口，统一走 get_llm_response。"""
        return await self.get_llm_response(
            system_prompt=system_prompt or "你是一位专业写作助手。",
            conversation_history=[{"role": "user", "content": prompt}],
            temperature=temperature,
            user_id=user_id,
            timeout=timeout,
            response_format=response_format,
            max_tokens=max_tokens,
            top_p=top_p,
            model=model,
        )

    async def get_summary(
        self,
        chapter_content: str,
        *,
        temperature: float = 0.2,
        user_id: Optional[int] = None,
        timeout: float = 180.0,
        system_prompt: Optional[str] = None,
    ) -> str:
        if not system_prompt:
            prompt_service = PromptService(self.session)
            system_prompt = await prompt_service.get_prompt("extraction")
        if not system_prompt:
            logger.error("未配置名为 'extraction' 的摘要提示词，无法生成章节摘要")
            raise HTTPException(status_code=500, detail="未配置摘要提示词，请联系管理员配置 'extraction' 提示词")
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": chapter_content},
        ]
        return await self._stream_and_collect(messages, temperature=temperature, user_id=user_id, timeout=timeout)

    async def _stream_and_collect(
        self,
        messages: List[Dict[str, str]],
        *,
        temperature: float,
        user_id: Optional[int],
        timeout: float,
        response_format: Optional[str] = None,
        max_tokens: Optional[int] = None,
        top_p: Optional[float] = None,
        model: Optional[str] = None,
    ) -> str:
        config = await self._resolve_llm_config(user_id, model_override=model)
        client = LLMClient(api_key=config["api_key"], base_url=config.get("base_url"))

        # 把调用方给的超时收敛到全局上限。
        # 上限默认 90 秒，低于 Cloudflare 免费版的 100 秒——
        # 这样超时会由我们自己先触发，返回可读的中文提示，
        # 而不是让请求挂到被 CF 以 524 掐断（用户只看到「未返回有效内容」）。
        effective_timeout = min(float(timeout), float(settings.llm_generation_timeout))

        chat_messages = [ChatMessage(role=msg["role"], content=msg["content"]) for msg in messages]

        full_response = ""
        finish_reason = None

        logger.info(
            "Streaming LLM response: model=%s user_id=%s messages=%d",
            config.get("model"),
            user_id,
            len(messages),
        )

        try:
            async for part in client.stream_chat(
                messages=chat_messages,
                model=config.get("model"),
                temperature=temperature,
                timeout=int(effective_timeout),
                response_format=response_format,
                max_tokens=max_tokens,
                top_p=top_p,
            ):
                if part.get("content"):
                    full_response += part["content"]
                if part.get("finish_reason"):
                    finish_reason = part["finish_reason"]
        except InternalServerError as exc:
            detail = _upstream_error_detail(exc, "AI 服务内部错误，请稍后重试")
            logger.error(
                "LLM stream internal error: model=%s user_id=%s detail=%s",
                config.get("model"),
                user_id,
                detail,
                exc_info=exc,
            )
            raise HTTPException(status_code=503, detail=detail)
        except APIStatusError as exc:
            # 覆盖 400/401/403/404/409/422/429 等全部带状态码的上游错误。
            # 之前只捕获了 InternalServerError，导致「模型名写错」这类
            # 404 一路冒到 FastAPI 变成 500，用户只看到「服务器内部错误」，
            # 完全看不出真正原因是配置问题。
            status_code, detail = _classify_upstream_status(exc, config.get("model"))
            logger.error(
                "LLM stream rejected by upstream: model=%s status=%s detail=%s",
                config.get("model"),
                getattr(exc, "status_code", None),
                detail,
            )
            raise HTTPException(status_code=status_code, detail=detail) from exc
        except (httpx.RemoteProtocolError, httpx.ReadTimeout, APIConnectionError, APITimeoutError) as exc:
            if isinstance(exc, httpx.RemoteProtocolError):
                detail = "AI 服务连接被意外中断，请稍后重试"
            elif isinstance(exc, (httpx.ReadTimeout, APITimeoutError)):
                detail = "AI 服务响应超时，请稍后重试"
            else:
                detail = "无法连接到 AI 服务，请稍后重试"
            logger.error(
                "LLM stream failed: model=%s user_id=%s detail=%s",
                config.get("model"),
                user_id,
                detail,
                exc_info=exc,
            )
            raise HTTPException(status_code=503, detail=detail) from exc

        logger.debug(
            "LLM response collected: model=%s user_id=%s finish_reason=%s preview=%s",
            config.get("model"),
            user_id,
            finish_reason,
            full_response[:500],
        )

        if finish_reason == "length":
            logger.warning(
                "LLM response truncated: model=%s user_id=%s response_length=%d",
                config.get("model"),
                user_id,
                len(full_response),
            )
            raise HTTPException(
                status_code=500,
                detail=f"AI 响应因长度限制被截断（已生成 {len(full_response)} 字符），请缩短输入内容或调整模型参数"
            )

        if not full_response:
            logger.error(
                "LLM returned empty response: model=%s user_id=%s finish_reason=%s",
                config.get("model"),
                user_id,
                finish_reason,
            )
            raise HTTPException(
                status_code=500,
                detail=f"AI 未返回有效内容（结束原因: {finish_reason or '未知'}），请稍后重试或联系管理员"
            )

        await self.usage_service.increment("api_request_count")
        logger.info(
            "LLM response success: model=%s user_id=%s chars=%d",
            config.get("model"),
            user_id,
            len(full_response),
        )
        return full_response

    async def stream_llm_response(
        self,
        *,
        system_prompt: str,
        conversation_history: List[Dict[str, str]],
        temperature: float = 0.7,
        user_id: Optional[int] = None,
        timeout: float = 300.0,
        response_format: Optional[str] = None,
        max_tokens: Optional[int] = None,
        model: Optional[str] = None,
    ) -> AsyncIterator[str]:
        """逐块产出模型输出，而不是攒完再返回。

        用途：让 HTTP 层能边生成边推给客户端（SSE），使首字节在
        1~2 秒内发出。这样反向代理针对「静默连接」的超时（例如
        Cloudflare 免费版的 100 秒）就不会掐断长生成。

        与 ``_stream_and_collect`` 仅差在「是否累积」，错误处理完全一致。
        """
        config = await self._resolve_llm_config(user_id, model_override=model)
        client = LLMClient(api_key=config["api_key"], base_url=config.get("base_url"))
        effective_timeout = min(float(timeout), float(settings.llm_generation_timeout))
        chat_messages = [
            ChatMessage(role="system", content=system_prompt),
            *[ChatMessage(role=m["role"], content=m["content"]) for m in conversation_history],
        ]

        logger.info(
            "Streaming LLM response (incremental): model=%s user_id=%s messages=%d",
            config.get("model"),
            user_id,
            len(chat_messages),
        )

        try:
            async for part in client.stream_chat(
                messages=chat_messages,
                model=config.get("model"),
                temperature=temperature,
                timeout=int(effective_timeout),
                response_format=response_format,
                max_tokens=max_tokens,
            ):
                content = part.get("content")
                if content:
                    yield content
        except InternalServerError as exc:
            detail = _upstream_error_detail(exc, "AI 服务内部错误，请稍后重试")
            logger.error("LLM stream internal error: model=%s detail=%s",
                         config.get("model"), detail, exc_info=exc)
            raise HTTPException(status_code=503, detail=detail)
        except APIStatusError as exc:
            status_code, detail = _classify_upstream_status(exc, config.get("model"))
            logger.error("LLM stream rejected: model=%s status=%s detail=%s",
                         config.get("model"), getattr(exc, "status_code", None), detail)
            raise HTTPException(status_code=status_code, detail=detail) from exc
        except (httpx.RemoteProtocolError, httpx.ReadTimeout, APIConnectionError, APITimeoutError) as exc:
            if isinstance(exc, httpx.RemoteProtocolError):
                detail = "AI 服务连接被意外中断，请稍后重试"
            elif isinstance(exc, (httpx.ReadTimeout, APITimeoutError)):
                detail = "AI 服务响应超时，请稍后重试"
            else:
                detail = "无法连接到 AI 服务，请稍后重试"
            logger.error("LLM stream failed: model=%s detail=%s",
                         config.get("model"), detail, exc_info=exc)
            raise HTTPException(status_code=503, detail=detail) from exc

        await self.usage_service.increment("api_request_count")

    async def _resolve_llm_config(
        self,
        user_id: Optional[int],
        model_override: Optional[str] = None,
    ) -> Dict[str, Optional[str]]:
        """解析本次调用要用的凭据与模型。

        优先级（``model_override`` 只影响 model 字段，不影响凭据来源）：
            1. ``model_override``       —— 前端切换器指定的模型
            2. 用户活跃模型             —— user_llm_models 里 is_active=1
            3. 旧单模型配置             —— llm_configs.llm_provider_model
            4. 系统默认                 —— system_configs 的 llm.model

        凭据（url + api_key）始终取自 llm_configs（用户级）或系统配置，
        因为同一网关下的多个模型共用一套凭据。
        """
        requested = (model_override or "").strip() or None

        if user_id:
            config = await self.llm_repo.get_by_user(user_id)
            if config and config.llm_provider_api_key:
                model = requested or await self._active_model_for(user_id)
                if not model:
                    model = config.llm_provider_model
                return {
                    "api_key": config.llm_provider_api_key,
                    "base_url": config.llm_provider_url,
                    "model": model,
                }

        # 检查每日使用次数限制
        if user_id:
            await self._enforce_daily_limit(user_id)

        api_key = await self._get_config_value("llm.api_key")
        base_url = await self._get_config_value("llm.base_url")
        model = requested
        if not model and user_id:
            model = await self._active_model_for(user_id)
        if not model:
            model = await self._get_config_value("llm.model")

        if not api_key:
            logger.error("未配置默认 LLM API Key，且用户 %s 未设置自定义 API Key", user_id)
            raise HTTPException(
                status_code=500,
                detail="未配置默认 LLM API Key，请联系管理员配置系统默认 API Key 或在个人设置中配置自定义 API Key"
            )

        return {"api_key": api_key, "base_url": base_url, "model": model}

    async def _active_model_for(self, user_id: int) -> Optional[str]:
        """取用户当前活跃模型；出错时返回 None 让调用方走回退链。"""
        try:
            from .user_model_service import UserModelService

            return await UserModelService(self.session).get_active_model(user_id)
        except Exception as exc:  # 多模型表不可用不应阻断生成
            logger.warning("读取活跃模型失败，回退到默认: user=%s error=%s", user_id, exc)
            return None

    async def get_embedding(
        self,
        text: str,
        *,
        user_id: Optional[int] = None,
        model: Optional[str] = None,
    ) -> List[float]:
        """生成文本向量，用于章节 RAG 检索，支持 openai 与 ollama 双提供方。"""
        provider = await self._get_config_value("embedding.provider") or "openai"
        default_model = (
            await self._get_config_value("ollama.embedding_model") or "nomic-embed-text:latest"
            if provider == "ollama"
            else await self._get_config_value("embedding.model") or "text-embedding-3-large"
        )
        target_model = model or default_model

        if provider == "ollama":
            if OllamaAsyncClient is None:
                logger.error("未安装 ollama 依赖，无法调用本地嵌入模型。")
                raise HTTPException(status_code=500, detail="缺少 Ollama 依赖，请先安装 ollama 包。")

            base_url = (
                await self._get_config_value("ollama.embedding_base_url")
                or await self._get_config_value("embedding.base_url")
            )
            client = OllamaAsyncClient(host=base_url)
            try:
                response = await client.embeddings(model=target_model, prompt=text)
            except Exception as exc:  # pragma: no cover - 本地服务调用失败
                logger.error(
                    "Ollama 嵌入请求失败: model=%s base_url=%s error=%s",
                    target_model,
                    base_url,
                    exc,
                    exc_info=True,
                )
                return []
            embedding: Optional[List[float]]
            if isinstance(response, dict):
                embedding = response.get("embedding")
            else:
                embedding = getattr(response, "embedding", None)
            if not embedding:
                logger.warning("Ollama 返回空向量: model=%s", target_model)
                return []
            if not isinstance(embedding, list):
                embedding = list(embedding)
        else:
            config = await self._resolve_llm_config(user_id)
            api_key = await self._get_config_value("embedding.api_key") or config["api_key"]
            base_url = await self._get_config_value("embedding.base_url") or config.get("base_url")
            client = AsyncOpenAI(api_key=api_key, base_url=base_url)
            try:
                response = await client.embeddings.create(
                    input=text,
                    model=target_model,
                )
            except Exception as exc:  # pragma: no cover - 网络或鉴权失败
                logger.error(
                    "OpenAI 嵌入请求失败: model=%s base_url=%s user_id=%s error=%s",
                    target_model,
                    base_url,
                    user_id,
                    exc,
                    exc_info=True,
                )
                return []
            if not response.data:
                logger.warning("OpenAI 嵌入请求返回空数据: model=%s user_id=%s", target_model, user_id)
                return []
            embedding = response.data[0].embedding

        if not isinstance(embedding, list):
            embedding = list(embedding)

        dimension = len(embedding)
        if not dimension:
            vector_size_str = await self._get_config_value("embedding.model_vector_size")
            if vector_size_str:
                dimension = int(vector_size_str)
        if dimension:
            self._embedding_dimensions[target_model] = dimension
        return embedding

    async def get_embedding_dimension(self, model: Optional[str] = None) -> Optional[int]:
        """获取嵌入向量维度，优先返回缓存结果，其次读取配置。"""
        provider = await self._get_config_value("embedding.provider") or "openai"
        default_model = (
            await self._get_config_value("ollama.embedding_model") or "nomic-embed-text:latest"
            if provider == "ollama"
            else await self._get_config_value("embedding.model") or "text-embedding-3-large"
        )
        target_model = model or default_model
        if target_model in self._embedding_dimensions:
            return self._embedding_dimensions[target_model]
        vector_size_str = await self._get_config_value("embedding.model_vector_size")
        return int(vector_size_str) if vector_size_str else None

    async def _enforce_daily_limit(self, user_id: int) -> None:
        limit_str = await self.admin_setting_service.get("daily_request_limit", "100")
        limit = int(limit_str or 10)
        used = await self.user_repo.get_daily_request(user_id)
        if used >= limit:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="今日请求次数已达上限，请明日再试或设置自定义 API Key。",
            )
        await self.user_repo.increment_daily_request(user_id)
        await self.session.commit()

    async def _get_config_value(self, key: str) -> Optional[str]:
        record = await self.system_config_repo.get_by_key(key)
        if record:
            return record.value
        # 兼容环境变量，首次迁移时无需立即写入数据库
        env_key = key.upper().replace(".", "_")
        return os.getenv(env_key)
