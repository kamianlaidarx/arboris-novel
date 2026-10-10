# AIMETA P=小说服务_小说管理业务逻辑|R=小说CRUD_章节管理|NR=不含内容生成|E=NovelService|X=internal|A=服务类|D=sqlalchemy|S=db|RD=./README.ai
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence

logger = logging.getLogger(__name__)

_PREFERRED_CONTENT_KEYS: tuple[str, ...] = (
    "content",
    "chapter_content",
    "chapter_text",
    "full_content",
    "text",
    "body",
    "story",
    "chapter",
    "real_summary",
    "summary",
)


def _normalize_version_content(raw_content: Any, metadata: Any) -> str:
    # 优先使用原始内容
    text = _coerce_text(raw_content)
    if text:
        return text
    
    # 如果没有原始内容，尝试从元数据提取（兼容旧逻辑）
    text = _coerce_text(metadata)
    return text or ""


def _coerce_text(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        return _clean_string(value)
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        for key in _PREFERRED_CONTENT_KEYS:
            if key in value and value[key]:
                nested = _coerce_text(value[key])
                if nested:
                    return nested
        return _clean_string(json.dumps(value, ensure_ascii=False), parse_json=False)
    if isinstance(value, (list, tuple, set)):
        parts = [text for text in (_coerce_text(item) for item in value) if text]
        if parts:
            return "\n".join(parts)
        return None
    return _clean_string(str(value))


def _clean_string(text: str, parse_json: bool = True) -> str:
    stripped = text.strip()
    if not stripped:
        return stripped
    if parse_json and (
        (stripped.startswith("{") and stripped.endswith("}"))
        or (stripped.startswith("[") and stripped.endswith("]"))
    ):
        try:
            parsed = json.loads(stripped)
            coerced = _coerce_text(parsed)
            if coerced:
                return coerced
        except json.JSONDecodeError:
            pass
    if stripped.startswith('"') and stripped.endswith('"') and len(stripped) >= 2:
        stripped = stripped[1:-1]
    return (
        stripped.replace("\\n", "\n")
        .replace("\\t", "\t")
        .replace('\\"', '"')
        .replace("\\\\", "\\")
    )

from fastapi import HTTPException, status
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import (
    BlueprintCharacter,
    BlueprintRelationship,
    Chapter,
    ChapterEvaluation,
    ChapterOutline,
    ChapterVersion,
    NovelBlueprint,
    NovelConversation,
    NovelProject,
)
from ..repositories.novel_repository import NovelRepository
from ..schemas.admin import AdminNovelSummary
from ..schemas.novel import (
    Blueprint,
    Chapter as ChapterSchema,
    ChapterGenerationStatus,
    ChapterOutline as ChapterOutlineSchema,
    NovelProject as NovelProjectSchema,
    NovelProjectSummary,
    NovelSectionResponse,
    NovelSectionType,
)


class NovelService:
    """小说项目服务，基于拆表后的结构提供聚合与业务操作。"""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = NovelRepository(session)

    # ------------------------------------------------------------------
    # 项目与摘要
    # ------------------------------------------------------------------
    async def create_project(self, user_id: int, title: str, initial_prompt: str) -> NovelProject:
        project = NovelProject(
            id=str(uuid.uuid4()),
            user_id=user_id,
            title=title,
            initial_prompt=initial_prompt,
        )
        blueprint = NovelBlueprint(project=project)
        self.session.add_all([project, blueprint])
        await self.session.commit()
        await self.session.refresh(project)
        return project

    async def ensure_project_owner(self, project_id: str, user_id: int) -> NovelProject:
        project = await self.repo.get_by_id(project_id)
        if not project:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
        if project.user_id != user_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="无权访问该项目")
        return project

    async def get_project_schema(self, project_id: str, user_id: int) -> NovelProjectSchema:
        project = await self.ensure_project_owner(project_id, user_id)
        return await self._serialize_project(project)

    async def get_section_data(
        self,
        project_id: str,
        user_id: int,
        section: NovelSectionType,
    ) -> NovelSectionResponse:
        project = await self.ensure_project_owner(project_id, user_id)
        return self._build_section_response(project, section)

    async def get_chapter_schema(
        self,
        project_id: str,
        user_id: int,
        chapter_number: int,
    ) -> ChapterSchema:
        project = await self.ensure_project_owner(project_id, user_id)
        return self._build_chapter_schema(project, chapter_number)

    async def list_projects_for_user(self, user_id: int) -> List[NovelProjectSummary]:
        projects = await self.repo.list_by_user(user_id)
        summaries: List[NovelProjectSummary] = []
        for project in projects:
            blueprint = project.blueprint
            genre = blueprint.genre if blueprint and blueprint.genre else "未知"
            outlines = project.outlines
            chapters = project.chapters
            total = len(outlines) or len(chapters)
            completed = sum(1 for chapter in chapters if chapter.selected_version_id)
            summaries.append(
                NovelProjectSummary(
                    id=project.id,
                    title=project.title,
                    genre=genre,
                    last_edited=project.updated_at.isoformat() if project.updated_at else "未知",
                    completed_chapters=completed,
                    total_chapters=total,
                )
            )
        return summaries

    async def list_projects_for_admin(self) -> List[AdminNovelSummary]:
        projects = await self.repo.list_all()
        summaries: List[AdminNovelSummary] = []
        for project in projects:
            blueprint = project.blueprint
            genre = blueprint.genre if blueprint and blueprint.genre else "未知"
            outlines = project.outlines
            chapters = project.chapters
            total = len(outlines) or len(chapters)
            completed = sum(1 for chapter in chapters if chapter.selected_version_id)
            owner = project.owner
            summaries.append(
                AdminNovelSummary(
                    id=project.id,
                    title=project.title,
                    owner_id=owner.id if owner else 0,
                    owner_username=owner.username if owner else "未知",
                    genre=genre,
                    last_edited=project.updated_at.isoformat() if project.updated_at else "",
                    completed_chapters=completed,
                    total_chapters=total,
                )
            )
        return summaries

    async def delete_projects(self, project_ids: List[str], user_id: int) -> None:
        for pid in project_ids:
            project = await self.ensure_project_owner(pid, user_id)
            await self.repo.delete(project)
        await self.session.commit()

    async def count_projects(self) -> int:
        result = await self.session.execute(select(func.count(NovelProject.id)))
        return result.scalar_one()

    # ------------------------------------------------------------------
    # 对话管理
    # ------------------------------------------------------------------
    async def list_conversations(self, project_id: str) -> List[NovelConversation]:
        stmt = (
            select(NovelConversation)
            .where(NovelConversation.project_id == project_id)
            .order_by(NovelConversation.seq.asc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars())

    async def append_conversation(self, project_id: str, role: str, content: str, metadata: Optional[Dict] = None) -> None:
        result = await self.session.execute(
            select(func.max(NovelConversation.seq)).where(NovelConversation.project_id == project_id)
        )
        current_max = result.scalar()
        next_seq = (current_max or 0) + 1
        convo = NovelConversation(
            project_id=project_id,
            seq=next_seq,
            role=role,
            content=content,
            metadata=metadata,
        )
        self.session.add(convo)
        await self.session.commit()
        await self._touch_project(project_id)

    # ------------------------------------------------------------------
    # 蓝图管理
    # ------------------------------------------------------------------
    async def replace_blueprint(self, project_id: str, blueprint: Blueprint) -> None:
        record = await self.session.get(NovelBlueprint, project_id)
        if not record:
            record = NovelBlueprint(project_id=project_id)
            self.session.add(record)
        record.title = blueprint.title
        record.target_audience = blueprint.target_audience
        record.genre = blueprint.genre
        record.style = blueprint.style
        record.tone = blueprint.tone
        record.one_sentence_summary = blueprint.one_sentence_summary
        record.full_synopsis = blueprint.full_synopsis
        record.world_setting = blueprint.world_setting

        await self.session.execute(delete(BlueprintCharacter).where(BlueprintCharacter.project_id == project_id))
        for index, data in enumerate(blueprint.characters):
            self.session.add(
                BlueprintCharacter(
                    project_id=project_id,
                    name=data.get("name", ""),
                    identity=data.get("identity"),
                    personality=data.get("personality"),
                    goals=data.get("goals"),
                    abilities=data.get("abilities"),
                    relationship_to_protagonist=data.get("relationship_to_protagonist"),
                    extra={k: v for k, v in data.items() if k not in {
                        "name",
                        "identity",
                        "personality",
                        "goals",
                        "abilities",
                        "relationship_to_protagonist",
                    }},
                    position=index,
                )
            )

        await self.session.execute(delete(BlueprintRelationship).where(BlueprintRelationship.project_id == project_id))
        for index, relation in enumerate(blueprint.relationships):
            self.session.add(
                BlueprintRelationship(
                    project_id=project_id,
                    character_from=relation.character_from,
                    character_to=relation.character_to,
                    description=relation.description,
                    position=index,
                )
            )

        await self.session.execute(delete(ChapterOutline).where(ChapterOutline.project_id == project_id))
        for outline in blueprint.chapter_outline:
            self.session.add(
                ChapterOutline(
                    project_id=project_id,
                    chapter_number=outline.chapter_number,
                    title=outline.title,
                    summary=outline.summary,
                )
            )

        await self.session.commit()
        await self._touch_project(project_id)

    async def _sync_relationship_names(
        self,
        project_id: str,
        old_characters: Sequence[Any],
        new_characters: Sequence[Dict[str, Any]],
    ) -> None:
        """把角色改名同步到关系表。

        为什么需要：``BlueprintRelationship.character_from/to`` 存的是
        **角色名字符串**，不是外键。角色被改名后，旧关系会指向一个
        不存在的角色——界面照常显示，不会报任何错，但关系实际上失效了。

        如何识别「同一个角色被改名」：前后端都没有稳定的角色 ID
        （保存时整批删除重建），所以只能靠位置推断。这里用两条规则：

        1. **按位置配对**：第 i 个旧角色对应第 i 个新角色。
           编辑器是列表形式，改名不会改变顺序，这条覆盖绝大多数情况。
        2. **名字仍然存在的视为未改名**：避免「中间删了一个角色」
           导致后续位置整体错位、把 A 的名字安到 B 头上。

        只在旧名确实消失、且新名确实新增时才替换，宁可少改也不错改。
        """
        old_names = [(c.name or "").strip() for c in old_characters]
        new_names = [(c.get("name") or "").strip() for c in new_characters]
        if not old_names or not new_names:
            return

        new_name_set = set(new_names)
        old_name_set = set(old_names)
        # 未改名 = 新旧名单里都还在的名字
        unchanged = old_name_set & new_name_set

        rename_map: Dict[str, str] = {}
        for index, old_name in enumerate(old_names):
            if not old_name or old_name in unchanged:
                continue
            if index >= len(new_names):
                break
            new_name = new_names[index]
            if not new_name or new_name in old_name_set:
                # 新位置上的名字本来就存在（说明是顺序变动而非改名），跳过
                continue
            rename_map[old_name] = new_name

        if not rename_map:
            return

        relationships = (
            await self.session.execute(
                select(BlueprintRelationship).where(
                    BlueprintRelationship.project_id == project_id
                )
            )
        ).scalars().all()

        changed = 0
        for relation in relationships:
            if relation.character_from in rename_map:
                relation.character_from = rename_map[relation.character_from]
                changed += 1
            if relation.character_to in rename_map:
                relation.character_to = rename_map[relation.character_to]
                changed += 1

        if changed:
            logger.info(
                "项目 %s 角色改名，已同步 %d 处关系引用: %s",
                project_id,
                changed,
                rename_map,
            )

    async def patch_blueprint(self, project_id: str, patch: Dict) -> None:
        blueprint = await self.session.get(NovelBlueprint, project_id)
        if not blueprint:
            blueprint = NovelBlueprint(project_id=project_id)
            self.session.add(blueprint)

        if "one_sentence_summary" in patch:
            blueprint.one_sentence_summary = patch["one_sentence_summary"]
        if "full_synopsis" in patch:
            blueprint.full_synopsis = patch["full_synopsis"]
        if "world_setting" in patch and patch["world_setting"] is not None:
            # 创建新字典对象以触发 SQLAlchemy 的变更检测
            existing = blueprint.world_setting or {}
            blueprint.world_setting = {**existing, **patch["world_setting"]}
        if "characters" in patch and patch["characters"] is not None:
            # 保存前先取旧名单：关系是按【角色名】关联的
            # （BlueprintRelationship.character_from/to 都是字符串），
            # 角色改名后旧关系会指向一个不存在的角色，而且不会报错。
            # 所以先算出「旧名 → 新名」的映射，回头同步关系表。
            old_characters = (
                await self.session.execute(
                    select(BlueprintCharacter)
                    .where(BlueprintCharacter.project_id == project_id)
                    .order_by(BlueprintCharacter.position)
                )
            ).scalars().all()

            await self.session.execute(delete(BlueprintCharacter).where(BlueprintCharacter.project_id == project_id))
            for index, data in enumerate(patch["characters"]):
                self.session.add(
                    BlueprintCharacter(
                        project_id=project_id,
                        name=data.get("name", ""),
                        identity=data.get("identity"),
                        personality=data.get("personality"),
                        goals=data.get("goals"),
                        abilities=data.get("abilities"),
                        relationship_to_protagonist=data.get("relationship_to_protagonist"),
                        extra={k: v for k, v in data.items() if k not in {
                            "name",
                            "identity",
                            "personality",
                            "goals",
                            "abilities",
                            "relationship_to_protagonist",
                        }},
                        position=index,
                    )
                )

            # 本次请求没带关系数据 → 用户只改了角色，
            # 需要把改名同步到已存的关系上，否则关系会静默失效。
            if patch.get("relationships") is None:
                await self._sync_relationship_names(
                    project_id, old_characters, patch["characters"]
                )
        if "relationships" in patch and patch["relationships"] is not None:
            await self.session.execute(delete(BlueprintRelationship).where(BlueprintRelationship.project_id == project_id))
            for index, relation in enumerate(patch["relationships"]):
                self.session.add(
                    BlueprintRelationship(
                        project_id=project_id,
                        character_from=relation.get("character_from"),
                        character_to=relation.get("character_to"),
                        description=relation.get("description"),
                        position=index,
                    )
                )
        if "chapter_outline" in patch and patch["chapter_outline"] is not None:
            await self.session.execute(delete(ChapterOutline).where(ChapterOutline.project_id == project_id))
            for outline in patch["chapter_outline"]:
                self.session.add(
                    ChapterOutline(
                        project_id=project_id,
                        chapter_number=outline.get("chapter_number"),
                        title=outline.get("title", ""),
                        summary=outline.get("summary"),
                    )
                )
        await self.session.commit()
        await self._touch_project(project_id)

    # ------------------------------------------------------------------
    # 章节与版本
    # ------------------------------------------------------------------
    async def get_outline(self, project_id: str, chapter_number: int) -> Optional[ChapterOutline]:
        stmt = (
            select(ChapterOutline)
            .where(
                ChapterOutline.project_id == project_id,
                ChapterOutline.chapter_number == chapter_number,
            )
        )
        result = await self.session.execute(stmt)
        return result.scalars().first()

    async def update_or_create_outline(
        self,
        project_id: str,
        chapter_number: int,
        title: str,
        summary: str,
        metadata: Optional[dict] = None,
    ) -> ChapterOutline:
        """更新或创建章节大纲，支持 metadata 存储导演脚本等信息。"""
        stmt = select(ChapterOutline).where(
            ChapterOutline.project_id == project_id,
            ChapterOutline.chapter_number == chapter_number,
        )
        result = await self.session.execute(stmt)
        outline = result.scalars().first()
        if outline:
            outline.title = title
            outline.summary = summary
            if metadata is not None:
                outline.metadata = metadata
        else:
            outline = ChapterOutline(
                project_id=project_id,
                chapter_number=chapter_number,
                title=title,
                summary=summary,
                metadata=metadata,
            )
            self.session.add(outline)
        await self.session.flush()
        return outline

    async def get_or_create_chapter(self, project_id: str, chapter_number: int) -> Chapter:
        stmt = (
            select(Chapter)
            .options(selectinload(Chapter.selected_version))
            .where(
                Chapter.project_id == project_id,
                Chapter.chapter_number == chapter_number,
            )
        )
        result = await self.session.execute(stmt)
        chapter = result.scalars().first()
        if chapter:
            return chapter
        chapter = Chapter(project_id=project_id, chapter_number=chapter_number)
        self.session.add(chapter)
        await self.session.commit()
        await self.session.refresh(chapter)
        return chapter

    async def replace_chapter_versions(self, chapter: Chapter, contents: List[str], metadata: Optional[List[Dict]] = None) -> List[ChapterVersion]:
        await self.session.execute(delete(ChapterVersion).where(ChapterVersion.chapter_id == chapter.id))
        versions: List[ChapterVersion] = []
        for index, content in enumerate(contents):
            extra = metadata[index] if metadata and index < len(metadata) else None
            text_content = _normalize_version_content(content, extra)
            version = ChapterVersion(
                chapter_id=chapter.id,
                content=text_content,
                metadata=extra,  # ✅ 落盘 metadata
                version_label=f"v{index+1}",
            )
            self.session.add(version)
            versions.append(version)
        chapter.status = ChapterGenerationStatus.WAITING_FOR_CONFIRM.value
        await self.session.commit()
        await self.session.refresh(chapter)
        await self._touch_project(chapter.project_id)
        return versions

    async def select_chapter_version(self, chapter: Chapter, version_index: int) -> ChapterVersion:
        stmt = select(ChapterVersion).where(ChapterVersion.chapter_id == chapter.id).order_by(ChapterVersion.created_at)
        result = await self.session.execute(stmt)
        versions = result.scalars().all()
        
        if not versions or version_index < 0 or version_index >= len(versions):
            raise HTTPException(status_code=400, detail="版本索引无效")
        selected = versions[version_index]
        
        # 校验内容是否为空
        if not selected.content or len(selected.content.strip()) == 0:
            raise HTTPException(status_code=400, detail="选中的版本内容为空，无法确认为最终版")
        
        chapter.selected_version_id = selected.id
        chapter.status = ChapterGenerationStatus.SUCCESSFUL.value
        chapter.word_count = len(selected.content or "")
        await self.session.commit()
        await self.session.refresh(chapter)
        await self._touch_project(chapter.project_id)
        return selected

    async def add_chapter_evaluation(self, chapter: Chapter, version: Optional[ChapterVersion], feedback: str, decision: Optional[str] = None) -> None:
        evaluation = ChapterEvaluation(
            chapter_id=chapter.id,
            version_id=version.id if version else None,
            feedback=feedback,
            decision=decision,
        )
        self.session.add(evaluation)
        chapter.status = ChapterGenerationStatus.WAITING_FOR_CONFIRM.value
        await self.session.commit()
        await self.session.refresh(chapter)
        await self._touch_project(chapter.project_id)

    async def delete_chapters(self, project_id: str, chapter_numbers: Iterable[int]) -> None:
        await self.session.execute(
            delete(Chapter).where(
                Chapter.project_id == project_id,
                Chapter.chapter_number.in_(list(chapter_numbers)),
            )
        )
        await self.session.execute(
            delete(ChapterOutline).where(
                ChapterOutline.project_id == project_id,
                ChapterOutline.chapter_number.in_(list(chapter_numbers)),
            )
        )
        await self.session.commit()
        await self._touch_project(project_id)

    # ------------------------------------------------------------------
    # 序列化辅助
    # ------------------------------------------------------------------
    async def get_project_schema_for_admin(self, project_id: str) -> NovelProjectSchema:
        project = await self.repo.get_by_id(project_id)
        if not project:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
        return await self._serialize_project(project)

    async def get_section_data_for_admin(
        self,
        project_id: str,
        section: NovelSectionType,
    ) -> NovelSectionResponse:
        project = await self.repo.get_by_id(project_id)
        if not project:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
        return self._build_section_response(project, section)

    async def get_chapter_schema_for_admin(
        self,
        project_id: str,
        chapter_number: int,
    ) -> ChapterSchema:
        project = await self.repo.get_by_id(project_id)
        if not project:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="项目不存在")
        return self._build_chapter_schema(project, chapter_number)

    async def _serialize_project(self, project: NovelProject) -> NovelProjectSchema:
        conversations = [
            {"role": convo.role, "content": convo.content}
            for convo in sorted(project.conversations, key=lambda c: c.seq)
        ]

        blueprint_schema = self._build_blueprint_schema(project)

        outlines_map = {outline.chapter_number: outline for outline in project.outlines}
        chapters_map = {chapter.chapter_number: chapter for chapter in project.chapters}
        chapter_numbers = sorted(set(outlines_map.keys()) | set(chapters_map.keys()))
        chapters_schema: List[ChapterSchema] = [
            self._build_chapter_schema(
                project,
                number,
                outlines_map=outlines_map,
                chapters_map=chapters_map,
            )
            for number in chapter_numbers
        ]

        return NovelProjectSchema(
            id=project.id,
            user_id=project.user_id,
            title=project.title,
            initial_prompt=project.initial_prompt or "",
            conversation_history=conversations,
            blueprint=blueprint_schema,
            chapters=chapters_schema,
        )

    async def _touch_project(self, project_id: str) -> None:
        await self.session.execute(
            update(NovelProject)
            .where(NovelProject.id == project_id)
            .values(updated_at=datetime.now(timezone.utc))
        )
        await self.session.commit()

    def _build_blueprint_schema(self, project: NovelProject) -> Blueprint:
        blueprint_obj = project.blueprint
        if blueprint_obj:
            return Blueprint(
                title=blueprint_obj.title or "",
                target_audience=blueprint_obj.target_audience or "",
                genre=blueprint_obj.genre or "",
                style=blueprint_obj.style or "",
                tone=blueprint_obj.tone or "",
                one_sentence_summary=blueprint_obj.one_sentence_summary or "",
                full_synopsis=blueprint_obj.full_synopsis or "",
                world_setting=blueprint_obj.world_setting or {},
                characters=[
                    {
                        "name": character.name,
                        "identity": character.identity,
                        "personality": character.personality,
                        "goals": character.goals,
                        "abilities": character.abilities,
                        "relationship_to_protagonist": character.relationship_to_protagonist,
                        **(character.extra or {}),
                    }
                    for character in sorted(project.characters, key=lambda c: c.position)
                ],
                relationships=[
                    {
                        "character_from": relation.character_from,
                        "character_to": relation.character_to,
                        "description": relation.description or "",
                        "relationship_type": getattr(relation, "relationship_type", None),
                    }
                    for relation in sorted(project.relationships_, key=lambda r: r.position)
                ],
                chapter_outline=[
                    ChapterOutlineSchema(
                        chapter_number=outline.chapter_number,
                        title=outline.title,
                        summary=outline.summary or "",
                    )
                    for outline in sorted(project.outlines, key=lambda o: o.chapter_number)
                ],
            )
        return Blueprint(
            title="",
            target_audience="",
            genre="",
            style="",
            tone="",
            one_sentence_summary="",
            full_synopsis="",
            world_setting={},
            characters=[],
            relationships=[],
            chapter_outline=[],
        )

    def _build_section_response(
        self,
        project: NovelProject,
        section: NovelSectionType,
    ) -> NovelSectionResponse:
        blueprint = self._build_blueprint_schema(project)

        if section == NovelSectionType.OVERVIEW:
            data = {
                "title": project.title,
                "initial_prompt": project.initial_prompt or "",
                "status": project.status,
                "one_sentence_summary": blueprint.one_sentence_summary,
                "target_audience": blueprint.target_audience,
                "genre": blueprint.genre,
                "style": blueprint.style,
                "tone": blueprint.tone,
                "full_synopsis": blueprint.full_synopsis,
                "updated_at": project.updated_at.isoformat() if project.updated_at else None,
            }
        elif section == NovelSectionType.WORLD_SETTING:
            data = {
                "world_setting": blueprint.world_setting or {},
            }
        elif section == NovelSectionType.CHARACTERS:
            data = {
                "characters": blueprint.characters,
            }
        elif section == NovelSectionType.RELATIONSHIPS:
            data = {
                "relationships": blueprint.relationships,
            }
        elif section == NovelSectionType.CHAPTER_OUTLINE:
            data = {
                "chapter_outline": [outline.model_dump() for outline in blueprint.chapter_outline],
            }
        elif section == NovelSectionType.CHAPTERS:
            outlines_map = {outline.chapter_number: outline for outline in project.outlines}
            chapters_map = {chapter.chapter_number: chapter for chapter in project.chapters}
            chapter_numbers = sorted(set(outlines_map.keys()) | set(chapters_map.keys()))
            # 章节列表只返回元数据，不包含完整内容
            chapters = [
                self._build_chapter_schema(
                    project,
                    number,
                    outlines_map=outlines_map,
                    chapters_map=chapters_map,
                    include_content=False,
                ).model_dump()
                for number in chapter_numbers
            ]
            data = {
                "chapters": chapters,
                "total": len(chapters),
            }
        else:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="未知的章节类型")

        return NovelSectionResponse(section=section, data=data)

    def _build_chapter_schema(
        self,
        project: NovelProject,
        chapter_number: int,
        *,
        outlines_map: Optional[Dict[int, ChapterOutline]] = None,
        chapters_map: Optional[Dict[int, Chapter]] = None,
        include_content: bool = True,
    ) -> ChapterSchema:
        outlines = outlines_map or {outline.chapter_number: outline for outline in project.outlines}
        chapters = chapters_map or {chapter.chapter_number: chapter for chapter in project.chapters}
        outline = outlines.get(chapter_number)
        chapter = chapters.get(chapter_number)

        if not outline and not chapter:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="章节不存在")

        title = outline.title if outline else f"第{chapter_number}章"
        summary = outline.summary if outline else ""
        real_summary = chapter.real_summary if chapter else None
        content = None
        versions: Optional[List[str]] = None
        evaluation_text: Optional[str] = None
        status_value = ChapterGenerationStatus.NOT_GENERATED.value
        word_count = 0

        if chapter:
            status_value = chapter.status or ChapterGenerationStatus.NOT_GENERATED.value
            word_count = chapter.word_count or 0

            # 只有在 include_content=True 时才包含完整内容
            if include_content:
                if chapter.selected_version:
                    content = chapter.selected_version.content
                if chapter.versions:
                    versions = [
                        v.content
                        for v in sorted(chapter.versions, key=lambda item: item.created_at)
                    ]
                if chapter.evaluations:
                    latest = sorted(chapter.evaluations, key=lambda item: item.created_at)[-1]
                    evaluation_text = latest.feedback or latest.decision

        return ChapterSchema(
            chapter_number=chapter_number,
            title=title,
            summary=summary,
            real_summary=real_summary,
            content=content,
            versions=versions,
            evaluation=evaluation_text,
            generation_status=ChapterGenerationStatus(status_value),
            word_count=word_count,
        )
