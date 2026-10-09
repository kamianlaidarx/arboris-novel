# AIMETA P=定稿服务_章节定稿和记忆更新|R=定稿流程_摘要更新_状态更新_向量库写入|NR=不含生成逻辑|E=FinalizeService|X=internal|A=定稿_记忆更新|D=llm_service_vector_store_service|S=none|RD=./README.ai
"""
定稿服务 (FinalizeService)

融合自 AI_NovelGenerator 的 finalization.py 设计理念，提供章节定稿后的一系列处理：
1. 更新全局摘要 (global_summary)
2. 更新角色状态 (character_state)
3. 更新剧情线追踪 (plot_arcs)
4. 写入向量库 (vectorstore)
5. 创建章节快照 (chapter_snapshot)

这是"生成后闭环"的核心服务，确保长程一致性。
"""
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.project_memory import ProjectMemory, ChapterSnapshot
from ..models.memory_layer import CharacterState
from ..models.novel import Chapter, ChapterVersion, NovelProject
from ..models.chapter_blueprint import ChapterBlueprint
from .llm_service import LLMService
from .vector_store_service import VectorStoreService
from .fact_store import backfill_from_character_state


def _parse_character_state_payload(text: Optional[str]) -> Optional[List[Dict[str, Any]]]:
    """把角色状态更新解析为结构化列表。

    返回：
      - ``None`` 表示无法解析（调用方应回退到文本记录）
      - ``[]``   表示解析成功但本章没有角色状态变更
      - ``[{...}]`` 每个元素是一个角色的状态更新
    """
    if not text or not text.strip():
        return None

    import json

    candidate = text.strip()
    # 剥掉 markdown 代码围栏
    if candidate.startswith("```"):
        parts = candidate.split("```")
        if len(parts) >= 2:
            candidate = parts[1]
            if candidate.lstrip().lower().startswith("json"):
                candidate = candidate.lstrip()[4:]

    # 截取最外层 JSON
    start = min(
        (i for i in (candidate.find("["), candidate.find("{")) if i >= 0),
        default=-1,
    )
    if start < 0:
        return None
    end = max(candidate.rfind("]"), candidate.rfind("}"))
    if end <= start:
        return None

    try:
        data = json.loads(candidate[start : end + 1])
    except (json.JSONDecodeError, ValueError):
        return None

    if isinstance(data, dict):
        # 容忍 {"characters": [...]} 或单个角色对象
        for key in ("characters", "character_states", "states", "items"):
            if isinstance(data.get(key), list):
                data = data[key]
                break
        else:
            data = [data]

    if not isinstance(data, list):
        return None

    cleaned: List[Dict[str, Any]] = []
    for item in data:
        if isinstance(item, dict):
            cleaned.append(item)
    return cleaned

logger = logging.getLogger(__name__)


# ==================== 提示词模板 ====================

UPDATE_GLOBAL_SUMMARY_PROMPT = """\
以下是新完成的章节文本：
{chapter_text}

这是当前的前文摘要（可为空）：
{global_summary}

请根据本章新增内容，更新前文摘要。
要求：
- 保留既有重要信息，同时融入新剧情要点
- 以简洁、连贯的语言描述全书进展
- 客观描绘，不展开联想或解释
- 突出关键转折、人物关系变化、伏笔进展
- 总字数控制在2000字以内

仅返回前文摘要文本，不要解释任何内容。
"""

UPDATE_CHARACTER_STATE_PROMPT = """\
以下是新完成的章节文本：
{chapter_text}

这是当前的角色状态记录（上一章结束时）：
{old_state}

请提取本章中【发生变化的】主要角色状态，用于结构化存储。

要求：
- 只输出本章【确实发生变化】的角色；没变化的角色不要输出。
- 没变化的字段可以省略，系统会自动继承上一章的值。
- 只依据本章正文，不要推测或补全正文没有的信息。
- 严格输出 JSON 数组，不要输出任何解释文字、不要用 markdown 代码围栏。

输出格式：
[
  {{
    "name": "角色名",
    "location": "当前位置（变化时填写）",
    "health_status": "healthy|injured|critical|dead（变化时填写）",
    "injuries": ["受伤描述（变化时填写）"],
    "emotion": "主要情绪（变化时填写）",
    "emotion_intensity": 1到10的整数,
    "emotion_reason": "情绪原因（变化时填写）",
    "inventory": ["当前持有物品（变化时填写）"],
    "inventory_changes": {{"gained": [], "lost": []}},
    "power_level": "实力等级（变化时填写）",
    "power_changes": {{"gained": [], "lost": []}},
    "relationship_changes": {{"角色名": "关系变化描述"}}
  }}
]

如果本章没有任何角色状态变化，输出空数组 []。
"""

UPDATE_PLOT_ARCS_PROMPT = """\
以下是新完成的章节文本：
{chapter_text}

当前章节号：第{chapter_number}章

这是当前的剧情线追踪（JSON格式）：
{plot_arcs}

请分析本章内容，更新剧情线追踪：

1. 未回收伏笔 (unresolved_hooks):
   - 检查是否有新埋设的伏笔
   - 检查是否有伏笔被回收（标记为resolved）
   - 检查是否有伏笔被强化

2. 主线矛盾 (main_conflicts):
   - 检查是否有新的主线矛盾出现
   - 检查现有矛盾的进展状态

3. 角色弧线 (character_arcs):
   - 检查角色的成长/变化阶段
   - 更新下一个里程碑

请以JSON格式返回更新后的剧情线追踪，结构如下：
{{
  "unresolved_hooks": [
    {{"id": "hook_1", "description": "描述", "planted_chapter": 1, "expected_payoff": 10, "status": "active/reinforced/resolved"}}
  ],
  "main_conflicts": [
    {{"id": "conflict_1", "description": "描述", "status": "active/escalating/resolved"}}
  ],
  "character_arcs": [
    {{"character": "角色名", "current_stage": "当前阶段", "next_milestone": "下一里程碑"}}
  ]
}}

仅返回JSON，不要解释任何内容。
"""

GENERATE_CHAPTER_SUMMARY_PROMPT = """\
请为以下章节内容生成一个简洁的摘要（100-200字）：

章节标题：第{chapter_number}章
章节内容：
{chapter_text}

要求：
- 概括本章的主要事件和关键转折
- 突出人物行动和情感变化
- 保持客观，不做评价

仅返回摘要文本，不要解释任何内容。
"""


class FinalizeService:
    """
    定稿服务
    
    负责章节定稿后的一系列处理，包括更新记忆、状态和向量库。
    """
    
    def __init__(
        self,
        db: AsyncSession,
        llm_service: LLMService,
        vector_store_service: Optional[VectorStoreService] = None
    ):
        self.db = db
        self.llm_service = llm_service
        self.vector_store_service = vector_store_service
    
    async def finalize_chapter(
        self,
        project_id: str,
        chapter_number: int,
        chapter_text: str,
        user_id: int,
        skip_vector_update: bool = False
    ) -> Dict[str, Any]:
        """
        对指定章节执行定稿处理
        
        Args:
            project_id: 项目ID
            chapter_number: 章节号
            chapter_text: 章节正文
            user_id: 用户ID
            skip_vector_update: 是否跳过向量库更新
            
        Returns:
            包含更新结果的字典
        """
        logger.info(f"开始定稿处理: project={project_id}, chapter={chapter_number}")
        
        result = {
            "success": True,
            "chapter_number": chapter_number,
            "updates": {}
        }
        
        try:
            # 1. 获取或创建项目记忆
            project_memory = await self._get_or_create_project_memory(project_id)
            
            # 2. 更新全局摘要
            new_summary = await self._update_global_summary(
                chapter_text=chapter_text,
                old_summary=project_memory.global_summary or "",
                user_id=user_id
            )
            if new_summary:
                project_memory.global_summary = new_summary
                result["updates"]["global_summary"] = "updated"
            
            # 3. 更新角色状态
            old_state = await self._get_character_state_text(project_id)
            new_state = await self._update_character_state(
                chapter_text=chapter_text,
                old_state=old_state,
                user_id=user_id
            )
            if new_state:
                await self._save_character_state(project_id, chapter_number, new_state)
                result["updates"]["character_state"] = "updated"
            
            # 4. 更新剧情线追踪
            new_plot_arcs = await self._update_plot_arcs(
                chapter_text=chapter_text,
                chapter_number=chapter_number,
                old_plot_arcs=project_memory.plot_arcs or {},
                user_id=user_id
            )
            if new_plot_arcs:
                project_memory.plot_arcs = new_plot_arcs
                result["updates"]["plot_arcs"] = "updated"
            
            # 4.5 从结构化角色状态派生时序事实（零额外 LLM 调用）
            # 这一步把「角色当前状态」翻译成带有效期区间的原子事实，
            # 供后续章节按「第 N 章时该事实是否成立」精确查询。
            try:
                derived = await backfill_from_character_state(
                    self.db, project_id, chapter_number
                )
                if derived:
                    result["updates"]["narrative_facts"] = derived
            except Exception as exc:
                # 事实派生失败不应让整次定稿失败——摘要/状态/快照都已经写好了
                logger.error("派生时序事实失败: project=%s chapter=%s error=%s",
                             project_id, chapter_number, exc, exc_info=True)
                result["updates"]["narrative_facts_error"] = str(exc)[:500]

            # 4.6 提取章间交接契约（章末瞬时状态）
            # 事实库记录跨章持久事实，但表达不了「章节结束那一刻他在哪、在做什么」。
            # 这正是「上一章刚睡着、下一章醒着发呆」这类 bug 的来源。
            try:
                from .chapter_contract_service import ChapterContractService

                contract_service = ChapterContractService(self.db, self.llm_service)
                contract = await contract_service.extract_and_save(
                    project_id=project_id,
                    chapter_number=chapter_number,
                    chapter_text=chapter_text,
                    user_id=user_id,
                )
                if contract is not None:
                    result["updates"]["chapter_contract"] = "saved"

                    # 立刻与上一章契约做确定性比对，把矛盾记进结果
                    check = await contract_service.check_transition(
                        project_id, chapter_number - 1, chapter_number
                    )
                    if not check.is_clean:
                        result["updates"]["transition_violations"] = [
                            {
                                "kind": v.kind,
                                "severity": v.severity,
                                "message": v.message,
                            }
                            for v in check.violations
                        ]
            except Exception as exc:
                logger.error("提取章间契约失败: project=%s chapter=%s error=%s",
                             project_id, chapter_number, exc, exc_info=True)
                result["updates"]["chapter_contract_error"] = str(exc)[:500]

            # 5. 更新向量库
            if not skip_vector_update and self.vector_store_service:
                await self._update_vector_store(
                    project_id=project_id,
                    chapter_number=chapter_number,
                    chapter_text=chapter_text
                )
                result["updates"]["vector_store"] = "updated"
            
            # 6. 创建章节快照
            chapter_summary = await self._generate_chapter_summary(
                chapter_text=chapter_text,
                chapter_number=chapter_number,
                user_id=user_id
            )
            await self._create_chapter_snapshot(
                project_id=project_id,
                chapter_number=chapter_number,
                global_summary=new_summary or project_memory.global_summary,
                character_states=new_state,
                plot_arcs=new_plot_arcs or project_memory.plot_arcs,
                chapter_summary=chapter_summary,
                word_count=len(chapter_text)
            )
            result["updates"]["snapshot"] = "created"
            
            # 7. 更新项目记忆的最后更新章节
            project_memory.last_updated_chapter = chapter_number
            project_memory.version += 1
            
            # 8. 更新章节蓝图状态
            await self._update_blueprint_status(project_id, chapter_number)
            
            await self.db.commit()
            logger.info(f"定稿处理完成: project={project_id}, chapter={chapter_number}")
            
        except Exception as e:
            logger.error(f"定稿处理失败: {e}", exc_info=True)
            await self.db.rollback()
            result["success"] = False
            result["error"] = str(e)
        
        return result
    
    async def _get_or_create_project_memory(self, project_id: str) -> ProjectMemory:
        """获取或创建项目记忆"""
        result = await self.db.execute(
            select(ProjectMemory).where(ProjectMemory.project_id == project_id)
        )
        memory = result.scalars().first()
        
        if not memory:
            memory = ProjectMemory(
                project_id=project_id,
                global_summary="",
                plot_arcs={
                    "unresolved_hooks": [],
                    "main_conflicts": [],
                    "character_arcs": []
                }
            )
            self.db.add(memory)
            await self.db.flush()
        
        return memory
    
    async def _update_global_summary(
        self,
        chapter_text: str,
        old_summary: str,
        user_id: int
    ) -> Optional[str]:
        """更新全局摘要"""
        prompt = UPDATE_GLOBAL_SUMMARY_PROMPT.format(
            chapter_text=chapter_text,
            global_summary=old_summary
        )
        
        try:
            response = await self.llm_service.generate(
                prompt=prompt,
                user_id=user_id,
                max_tokens=3000,
                temperature=0.3
            )
            return response.strip() if response else None
        except Exception as e:
            logger.error(f"更新全局摘要失败: {e}")
            return None
    
    async def _get_character_state_text(self, project_id: str) -> str:
        """获取角色状态文本"""
        # 获取最新的角色状态记录
        result = await self.db.execute(
            select(CharacterState)
            .where(CharacterState.project_id == project_id)
            .order_by(CharacterState.chapter_number.desc())
        )
        states = result.scalars().all()
        
        if not states:
            return ""
        
        # 按角色分组，取每个角色的最新状态
        latest_states = {}
        for state in states:
            if state.character_name not in latest_states:
                latest_states[state.character_name] = state
        
        # 格式化为文本
        text_parts = []
        for name, state in latest_states.items():
            parts = [f"{name}："]
            if state.inventory:
                parts.append(f"├──物品: {state.inventory}")
            if state.power_level:
                parts.append(f"├──能力: {state.power_level}")
            parts.append(f"├──状态:")
            parts.append(f"│  ├──身体状态: {state.health_status or '正常'}")
            parts.append(f"│  └──心理状态: {state.emotion or '平静'}")
            if state.relationship_changes:
                parts.append(f"├──关系网: {state.relationship_changes}")
            if state.new_knowledge:
                parts.append(f"├──触发事件: {state.new_knowledge}")
            text_parts.append("\n".join(parts))
        
        return "\n\n".join(text_parts)
    
    async def _update_character_state(
        self,
        chapter_text: str,
        old_state: str,
        user_id: int
    ) -> Optional[str]:
        """更新角色状态"""
        prompt = UPDATE_CHARACTER_STATE_PROMPT.format(
            chapter_text=chapter_text,
            old_state=old_state or "（暂无角色状态记录）"
        )
        
        try:
            response = await self.llm_service.generate(
                prompt=prompt,
                user_id=user_id,
                max_tokens=4000,
                temperature=0.3
            )
            return response.strip() if response else None
        except Exception as e:
            logger.error(f"更新角色状态失败: {e}")
            return None
    
    async def _save_character_state(
        self,
        project_id: str,
        chapter_number: int,
        state_text: str
    ):
        """保存角色状态到数据库。

        解析结构化 JSON 并按角色写入 CharacterState 的真实列。
        解析失败时回退为单条 "__all__" 记录，保证不丢数据。
        """
        parsed = _parse_character_state_payload(state_text)

        if parsed is None:
            # 回退：保留原始文本，避免信息丢失（旧行为）
            logger.warning(
                "角色状态不是可解析的结构化 JSON，回退为 __all__ 文本记录: project=%s chapter=%s",
                project_id,
                chapter_number,
            )
            self.db.add(
                CharacterState(
                    project_id=project_id,
                    # NULL 而非 0：0 不是合法的 blueprint_characters.id，
                    # 在外键开启（PRAGMA foreign_keys=ON）时会被拒绝。
                    character_id=None,
                    character_name="__all__",
                    chapter_number=chapter_number,
                    extra={"raw_state_text": state_text},
                )
            )
            return

        if not parsed:
            logger.info(
                "本章未提取到角色状态变更: project=%s chapter=%s", project_id, chapter_number
            )
            return

        # 取上一章各角色状态做继承，避免每章都要模型重复输出全部字段
        existing = await self._latest_character_states(project_id, chapter_number)

        for item in parsed:
            name = (item.get("name") or "").strip()
            if not name:
                continue
            prev = existing.get(name)
            state = CharacterState(
                project_id=project_id,
                # 继承上一章的蓝图角色 id；没有就写 NULL（不能写 0，会违反外键）
                character_id=prev.character_id if prev else None,
                character_name=name,
                chapter_number=chapter_number,
                # 未提供的字段继承上一章
                location=item.get("location", prev.location if prev else None),
                location_detail=item.get("location_detail", prev.location_detail if prev else None),
                emotion=item.get("emotion", prev.emotion if prev else None),
                emotion_intensity=item.get(
                    "emotion_intensity", prev.emotion_intensity if prev else None
                ),
                emotion_reason=item.get("emotion_reason", prev.emotion_reason if prev else None),
                health_status=item.get(
                    "health_status", prev.health_status if prev else "healthy"
                ),
                injuries=item.get("injuries", prev.injuries if prev else None),
                inventory=item.get("inventory", prev.inventory if prev else None),
                inventory_changes=item.get("inventory_changes"),
                relationship_changes=item.get("relationship_changes"),
                power_level=item.get("power_level", prev.power_level if prev else None),
                power_changes=item.get("power_changes"),
            )
            self.db.add(state)

        logger.info(
            "已写入 %d 个角色的结构化状态: project=%s chapter=%s",
            len(parsed),
            project_id,
            chapter_number,
        )

    async def _latest_character_states(
        self, project_id: str, chapter_number: int
    ) -> Dict[str, CharacterState]:
        """取每个角色在 chapter_number 之前的最新一条结构化状态。"""
        result = await self.db.execute(
            select(CharacterState)
            .where(
                CharacterState.project_id == project_id,
                CharacterState.chapter_number < chapter_number,
                CharacterState.character_name != "__all__",
            )
            .order_by(CharacterState.chapter_number.desc())
        )
        latest: Dict[str, CharacterState] = {}
        for state in result.scalars().all():
            latest.setdefault(state.character_name, state)
        return latest
    
    async def _update_plot_arcs(
        self,
        chapter_text: str,
        chapter_number: int,
        old_plot_arcs: Dict,
        user_id: int
    ) -> Optional[Dict]:
        """更新剧情线追踪"""
        import json
        
        prompt = UPDATE_PLOT_ARCS_PROMPT.format(
            chapter_text=chapter_text,
            chapter_number=chapter_number,
            plot_arcs=json.dumps(old_plot_arcs, ensure_ascii=False, indent=2)
        )
        
        try:
            response = await self.llm_service.generate(
                prompt=prompt,
                user_id=user_id,
                max_tokens=2000,
                temperature=0.3
            )
            if response:
                # 尝试解析JSON
                response = response.strip()
                if response.startswith("```"):
                    response = response.split("```")[1]
                    if response.startswith("json"):
                        response = response[4:]
                return json.loads(response)
        except json.JSONDecodeError as e:
            logger.error(f"解析剧情线JSON失败: {e}")
        except Exception as e:
            logger.error(f"更新剧情线失败: {e}")
        
        return None
    
    async def _update_vector_store(
        self,
        project_id: str,
        chapter_number: int,
        chapter_text: str
    ):
        """更新向量库"""
        if not self.vector_store_service:
            return
        
        try:
            # 将章节文本分块并存入向量库
            await self.vector_store_service.add_chapter_to_store(
                project_id=project_id,
                chapter_number=chapter_number,
                content=chapter_text
            )
        except Exception as e:
            logger.error(f"更新向量库失败: {e}")
    
    async def _generate_chapter_summary(
        self,
        chapter_text: str,
        chapter_number: int,
        user_id: int
    ) -> Optional[str]:
        """生成章节摘要"""
        prompt = GENERATE_CHAPTER_SUMMARY_PROMPT.format(
            chapter_text=chapter_text[:5000],  # 限制长度
            chapter_number=chapter_number
        )
        
        try:
            response = await self.llm_service.generate(
                prompt=prompt,
                user_id=user_id,
                max_tokens=500,
                temperature=0.3
            )
            return response.strip() if response else None
        except Exception as e:
            logger.error(f"生成章节摘要失败: {e}")
            return None
    
    async def _create_chapter_snapshot(
        self,
        project_id: str,
        chapter_number: int,
        global_summary: Optional[str],
        character_states: Optional[str],
        plot_arcs: Optional[Dict],
        chapter_summary: Optional[str],
        word_count: int
    ):
        """创建章节快照"""
        snapshot = ChapterSnapshot(
            project_id=project_id,
            chapter_number=chapter_number,
            global_summary_snapshot=global_summary,
            character_states_snapshot={"raw_text": character_states} if character_states else None,
            plot_arcs_snapshot=plot_arcs,
            chapter_summary=chapter_summary,
            word_count=word_count
        )
        self.db.add(snapshot)
    
    async def _update_blueprint_status(self, project_id: str, chapter_number: int):
        """更新章节蓝图状态"""
        result = await self.db.execute(
            select(ChapterBlueprint).where(
                ChapterBlueprint.project_id == project_id,
                ChapterBlueprint.chapter_number == chapter_number,
            )
        )
        blueprint = result.scalars().first()
        
        if blueprint:
            blueprint.is_finalized = True
    
    async def get_finalize_context(
        self,
        project_id: str,
        chapter_number: int
    ) -> Dict[str, Any]:
        """
        获取定稿上下文信息
        
        用于在生成章节时提供上下文参考。
        """
        memory_result = await self.db.execute(
            select(ProjectMemory).where(ProjectMemory.project_id == project_id)
        )
        memory = memory_result.scalars().first()
        
        # 获取最近的章节快照
        snapshot_result = await self.db.execute(
            select(ChapterSnapshot)
            .where(
                ChapterSnapshot.project_id == project_id,
                ChapterSnapshot.chapter_number < chapter_number,
            )
            .order_by(ChapterSnapshot.chapter_number.desc())
            .limit(3)
        )
        recent_snapshots = snapshot_result.scalars().all()
        
        return {
            "global_summary": memory.global_summary if memory else None,
            "plot_arcs": memory.plot_arcs if memory else None,
            "recent_snapshots": [
                {
                    "chapter_number": s.chapter_number,
                    "summary": s.chapter_summary
                }
                for s in recent_snapshots
            ]
        }
