# AIMETA P=LLM配置API_模型配置与模型发现|R=LLM配置CRUD_模型列表发现|NR=不含模型调用|E=route:/api/llm-config/*|X=http|A=配置CRUD+发现|D=fastapi,sqlalchemy|S=db,net|RD=./README.ai
"""LLM 配置与模型发现接口。

错误处理是本次重构的重点之一：旧实现把所有异常都吞掉并返回空列表，
用户只能看到"未获取到模型列表"而不知道原因。现在把
:class:`~app.llm_discovery.errors.ModelDiscoveryError` 映射为带
``message`` / ``hint`` / ``attempted_endpoints`` 的结构化错误响应。
"""

from __future__ import annotations

import logging
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.dependencies import get_current_user
from ...db.session import get_session
from ...llm_discovery.errors import ModelDiscoveryError
from ...schemas.llm_config import (
    LLMConfigCreate,
    LLMConfigRead,
    ModelListRequest,
    ModelListResponse,
    ProviderInfoRead,
)
from ...schemas.user import UserInDB
from ...services.llm_config_service import LLMConfigService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/llm-config", tags=["LLM Configuration"])


def get_llm_config_service(session: AsyncSession = Depends(get_session)) -> LLMConfigService:
    return LLMConfigService(session)


def _discovery_error_response(exc: ModelDiscoveryError) -> JSONResponse:
    """把发现异常转换为结构化 JSON 响应。"""

    return JSONResponse(status_code=exc.http_status, content={"detail": exc.to_dict()})


@router.get("", response_model=LLMConfigRead)
async def read_llm_config(
    service: LLMConfigService = Depends(get_llm_config_service),
    current_user: UserInDB = Depends(get_current_user),
) -> LLMConfigRead:
    config = await service.get_config(current_user.id)
    if not config:
        logger.info("用户 %s 尚未设置 LLM 配置", current_user.id)
        raise HTTPException(status_code=404, detail="尚未设置自定义配置")
    logger.debug("用户 %s 获取 LLM 配置", current_user.id)
    return config


@router.put("", response_model=LLMConfigRead)
async def upsert_llm_config(
    payload: LLMConfigCreate,
    service: LLMConfigService = Depends(get_llm_config_service),
    current_user: UserInDB = Depends(get_current_user),
) -> LLMConfigRead:
    logger.info("用户 %s 更新 LLM 配置", current_user.id)
    return await service.upsert_config(current_user.id, payload)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT, response_model=None)
async def delete_llm_config(
    service: LLMConfigService = Depends(get_llm_config_service),
    current_user: UserInDB = Depends(get_current_user),
) -> None:
    deleted = await service.delete_config(current_user.id)
    if not deleted:
        logger.warning("用户 %s 删除 LLM 配置失败，未找到记录", current_user.id)
        raise HTTPException(status_code=404, detail="未找到配置")
    logger.info("用户 %s 删除 LLM 配置", current_user.id)


@router.get("/providers", response_model=List[ProviderInfoRead])
async def list_providers(
    service: LLMConfigService = Depends(get_llm_config_service),
    current_user: UserInDB = Depends(get_current_user),
) -> List[ProviderInfoRead]:
    """返回内置供应商预设，供前端一键填充地址。"""

    return service.list_provider_presets()


@router.get("/provider", response_model=ProviderInfoRead)
async def describe_provider(
    base_url: str | None = Query(default=None, description="要识别的服务地址"),
    provider: str | None = Query(default=None, description="显式指定供应商标识"),
    service: LLMConfigService = Depends(get_llm_config_service),
    current_user: UserInDB = Depends(get_current_user),
) -> ProviderInfoRead:
    """根据地址识别供应商，用于界面提示"已识别为 …"。"""

    return service.describe_provider(base_url, provider)


@router.post("/models", response_model=ModelListResponse)
async def list_models(
    payload: ModelListRequest,
    service: LLMConfigService = Depends(get_llm_config_service),
    current_user: UserInDB = Depends(get_current_user),
):
    """自动获取第三方大模型的可用模型列表。

    * 未传 ``llm_provider_api_key`` 时回退到当前用户已保存的配置；
    * 支持 ``refresh`` 跳过缓存强制刷新；
    * 支持 ``capabilities`` 按能力（chat / embedding / vision …）过滤；
    * 失败时返回结构化的错误说明与排查建议，而不是空列表。
    """

    try:
        result = await service.discover_models(
            user_id=current_user.id,
            api_key=payload.llm_provider_api_key,
            base_url=payload.llm_provider_url,
            provider=payload.provider,
            refresh=payload.refresh,
            capabilities=payload.capabilities,
        )
    except ModelDiscoveryError as exc:
        logger.warning(
            "用户 %s 获取模型列表失败: provider=%s error=%s message=%s",
            current_user.id,
            exc.provider,
            exc.__class__.__name__,
            exc.message,
        )
        return _discovery_error_response(exc)
    except Exception as exc:  # noqa: BLE001 - 兜底，避免 500 泄漏堆栈
        # 内部异常的原文可能包含路径、连接串等敏感信息：只记服务端日志，
        # 不放进响应体。
        logger.error("用户 %s 获取模型列表出现未预期错误: %s", current_user.id, exc, exc_info=True)
        return _discovery_error_response(
            ModelDiscoveryError(
                "获取模型列表时发生未预期错误",
                hint="请稍后重试；若持续出现请查看服务端日志。",
            )
        )

    logger.info(
        "用户 %s 获取模型列表成功: provider=%s models=%d cached=%s",
        current_user.id,
        result.provider,
        len(result.models),
        result.cached,
    )
    return service.to_response(result)
