# AIMETA P=用户多模型服务_切换与持久化|R=模型列表_活跃模型_回退链|NR=不含API路由|E=UserModelService|X=internal|A=服务类|D=sqlalchemy|S=db|RD=./README.ai
"""
用户多模型配置服务。

职责
----
1. 维护用户收藏的模型列表（增删改查、排序）。
2. 维护「当前活跃模型」——同一用户至多一个。
3. 首次使用时，把旧表 ``llm_configs`` 里的单模型配置自动迁移过来，
   保证老用户升级后不掉配置。
"""
from __future__ import annotations

import logging
from typing import List, Optional, Sequence

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.llm_config import LLMConfig
from ..models.user_llm_model import UserLLMModel

logger = logging.getLogger(__name__)


class UserModelService:
    """用户可选模型的读写。"""

    def __init__(self, session: AsyncSession):
        self.session = session

    # ------------------------------------------------------------ 读

    async def list_models(self, user_id: int) -> List[UserLLMModel]:
        """按「活跃优先、再按排序」返回用户的模型列表。

        列表为空时会尝试从旧的单模型配置播种一次。
        """
        await self.ensure_seeded(user_id)
        result = await self.session.execute(
            select(UserLLMModel)
            .where(UserLLMModel.user_id == user_id)
            .order_by(
                UserLLMModel.is_active.desc(),
                UserLLMModel.sort_order.asc(),
                UserLLMModel.id.asc(),
            )
        )
        return list(result.scalars().all())

    async def get_active_model(self, user_id: int) -> Optional[str]:
        """返回当前活跃模型名；没有则返回 None（由调用方走回退链）。"""
        await self.ensure_seeded(user_id)
        result = await self.session.execute(
            select(UserLLMModel.model_name).where(
                UserLLMModel.user_id == user_id,
                UserLLMModel.is_active.is_(True),
            )
        )
        return result.scalars().first()

    # ------------------------------------------------------------ 写

    async def ensure_seeded(self, user_id: int) -> int:
        """首次访问时，把旧单模型配置迁移进可切换列表。

        只播一次。判断依据是 ``llm_configs.llm_models_seeded`` 标记位，
        而不是「列表是否为空」——否则用户清空列表后，旧模型又会被加回来。

        返回新插入的条数（0 表示无需播种）。
        """
        legacy = await self.session.execute(
            select(LLMConfig).where(LLMConfig.user_id == user_id)
        )
        config = legacy.scalars().first()
        if config is None:
            return 0
        if getattr(config, "llm_models_seeded", False):
            return 0

        model_name = (config.llm_provider_model or "").strip()
        inserted = 0
        if model_name:
            found = await self.session.execute(
                select(UserLLMModel.id).where(
                    UserLLMModel.user_id == user_id,
                    UserLLMModel.model_name == model_name,
                )
            )
            if found.scalars().first() is None:
                self.session.add(
                    UserLLMModel(
                        user_id=user_id,
                        model_name=model_name,
                        display_name=model_name,
                        is_active=True,
                        sort_order=0,
                        note="从原有配置自动迁移",
                    )
                )
                inserted = 1

        # 无论是否插入，都打上标记：这个用户已经完成过迁移
        config.llm_models_seeded = True
        await self.session.flush()
        if inserted:
            logger.info("已为 user=%s 迁移旧模型配置: %s", user_id, model_name)
        return inserted

    async def add_model(
        self,
        user_id: int,
        model_name: str,
        *,
        display_name: Optional[str] = None,
        note: Optional[str] = None,
        make_active: bool = False,
    ) -> UserLLMModel:
        """添加一个可选模型。已存在则原样返回（幂等）。"""
        model_name = (model_name or "").strip()
        if not model_name:
            raise ValueError("模型名不能为空")

        found = await self.session.execute(
            select(UserLLMModel).where(
                UserLLMModel.user_id == user_id,
                UserLLMModel.model_name == model_name,
            )
        )
        existing = found.scalars().first()
        if existing is not None:
            if make_active:
                await self.set_active(user_id, existing.id)
            return existing

        # 第一条自动成为活跃
        has_any = await self.session.execute(
            select(UserLLMModel.id).where(UserLLMModel.user_id == user_id).limit(1)
        )
        is_first = has_any.scalars().first() is None

        record = UserLLMModel(
            user_id=user_id,
            model_name=model_name,
            display_name=(display_name or model_name).strip(),
            note=note,
            is_active=is_first or make_active,
            sort_order=0,
        )
        self.session.add(record)
        await self.session.flush()

        if make_active and not is_first:
            await self.set_active(user_id, record.id)
        return record

    async def add_models(self, user_id: int, model_names: Sequence[str]) -> int:
        """批量添加（去重）。返回实际新增条数。"""
        added = 0
        for name in model_names:
            name = (name or "").strip()
            if not name:
                continue
            found = await self.session.execute(
                select(UserLLMModel.id).where(
                    UserLLMModel.user_id == user_id,
                    UserLLMModel.model_name == name,
                )
            )
            if found.scalars().first() is not None:
                continue
            await self.add_model(user_id, name)
            added += 1
        return added

    async def set_active(self, user_id: int, model_id: int) -> bool:
        """把指定模型设为活跃（同一用户只保留一个）。

        返回 False 表示该 id 不存在或不属于这个用户。
        """
        target = await self.session.execute(
            select(UserLLMModel).where(
                UserLLMModel.id == model_id,
                UserLLMModel.user_id == user_id,
            )
        )
        record = target.scalars().first()
        if record is None:
            return False

        # 先全部置否，再置目标为真，避免出现两个活跃
        await self.session.execute(
            update(UserLLMModel)
            .where(UserLLMModel.user_id == user_id)
            .values(is_active=False)
        )
        record.is_active = True
        await self.session.flush()
        return True

    async def set_active_by_name(self, user_id: int, model_name: str) -> bool:
        """按模型名切换活跃模型；不存在时自动添加后再切换。"""
        model_name = (model_name or "").strip()
        if not model_name:
            return False
        record = await self.add_model(user_id, model_name)
        return await self.set_active(user_id, record.id)

    async def remove_model(self, user_id: int, model_id: int) -> bool:
        """删除一个模型。若删的是活跃项，自动把剩下的第一个设为活跃。"""
        target = await self.session.execute(
            select(UserLLMModel).where(
                UserLLMModel.id == model_id,
                UserLLMModel.user_id == user_id,
            )
        )
        record = target.scalars().first()
        if record is None:
            return False

        was_active = record.is_active
        await self.session.delete(record)
        await self.session.flush()

        if was_active:
            remaining = await self.session.execute(
                select(UserLLMModel)
                .where(UserLLMModel.user_id == user_id)
                .order_by(UserLLMModel.sort_order.asc(), UserLLMModel.id.asc())
                .limit(1)
            )
            nxt = remaining.scalars().first()
            if nxt is not None:
                nxt.is_active = True
                await self.session.flush()
        return True

    async def clear_all(self, user_id: int) -> int:
        result = await self.session.execute(
            delete(UserLLMModel).where(UserLLMModel.user_id == user_id)
        )
        return result.rowcount or 0
