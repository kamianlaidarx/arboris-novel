# AIMETA P=小说API_项目和章节管理|R=小说CRUD_章节管理|NR=不含内容生成|E=route:GET_POST_/api/novels/*|X=http|A=小说CRUD_章节|D=fastapi,sqlalchemy|S=db|RD=./README.ai
import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ...core.dependencies import get_current_user
from ...db.session import get_session
from ...schemas.novel import (
    Blueprint,
    BlueprintGenerateRequest,
    CharacterRenameRequest,
    IgnoreNamesRequest,
    BlueprintGenerationResponse,
    BlueprintPatch,
    Chapter as ChapterSchema,
    ConverseRequest,
    ConverseResponse,
    NovelProject as NovelProjectSchema,
    NovelProjectSummary,
    NovelSectionResponse,
    NovelSectionType,
)
from ...schemas.user import UserInDB
from ...services.import_service import ImportService
from ...services.llm_service import LLMService
from ...models.novel import NovelBlueprint
from ...services.blueprint_staleness_service import BlueprintStalenessService
from ...services.character_rename_service import CharacterRenameService
from ...services.novel_service import NovelService
from ...services.prompt_service import PromptService
from ...utils.json_utils import remove_think_tags, sanitize_json_like_text, unwrap_markdown_json
from ...utils.sse import run_with_heartbeat, sse_response

logger = logging.getLogger(__name__)


def _sse(event: str, data: dict) -> str:
    """把一个事件编码成 SSE 帧。

    ``ensure_ascii=False`` 让中文按原样发送（而不是 \\uXXXX），
    省带宽也便于调试。SSE 规范要求 data 内不能有裸换行，
    因此 JSON 序列化后统一替换成字面量 ``\\n``。
    """
    payload = json.dumps(data, ensure_ascii=False).replace("\n", "\\n")
    return f"event: {event}\ndata: {payload}\n\n"

router = APIRouter(prefix="/api/novels", tags=["Novels"])

JSON_RESPONSE_INSTRUCTION = """
IMPORTANT: 你的回复必须是合法的 JSON 对象，并严格包含以下字段：
{
  "ai_message": "string",
  "ui_control": {
    "type": "single_choice | text_input | info_display",
    "options": [
      {"id": "option_1", "label": "string"}
    ],
    "placeholder": "string"
  },
  "conversation_state": {},
  "is_complete": false
}
不要输出额外的文本或解释。
"""


def _ensure_prompt(prompt: str | None, name: str) -> str:
    if not prompt:
        raise HTTPException(status_code=500, detail=f"未配置名为 {name} 的提示词，请联系管理员")
    return prompt


@router.post("", response_model=NovelProjectSchema, status_code=status.HTTP_201_CREATED)
async def create_novel(
    title: str = Body(...),
    initial_prompt: str = Body(...),
    session: AsyncSession = Depends(get_session),
    current_user: UserInDB = Depends(get_current_user),
) -> NovelProjectSchema:
    """为当前用户创建一个新的小说项目。"""
    novel_service = NovelService(session)
    project = await novel_service.create_project(current_user.id, title, initial_prompt)
    logger.info("用户 %s 创建项目 %s", current_user.id, project.id)
    return await novel_service.get_project_schema(project.id, current_user.id)


@router.post("/import", response_model=Dict[str, str], status_code=status.HTTP_201_CREATED)
async def import_novel(
    file: UploadFile,
    session: AsyncSession = Depends(get_session),
    current_user: UserInDB = Depends(get_current_user),
) -> Dict[str, str]:
    """上传并导入小说文件。"""
    import_service = ImportService(session)
    project_id = await import_service.import_novel_from_file(current_user.id, file)
    logger.info("用户 %s 导入项目 %s", current_user.id, project_id)
    return {"id": project_id}


@router.get("", response_model=List[NovelProjectSummary])
async def list_novels(
    session: AsyncSession = Depends(get_session),
    current_user: UserInDB = Depends(get_current_user),
) -> List[NovelProjectSummary]:
    """列出用户的全部小说项目摘要信息。"""
    novel_service = NovelService(session)
    projects = await novel_service.list_projects_for_user(current_user.id)
    logger.info("用户 %s 获取项目列表，共 %s 个", current_user.id, len(projects))
    return projects


@router.get("/{project_id}", response_model=NovelProjectSchema)
async def get_novel(
    project_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: UserInDB = Depends(get_current_user),
) -> NovelProjectSchema:
    novel_service = NovelService(session)
    logger.info("用户 %s 查询项目 %s", current_user.id, project_id)
    return await novel_service.get_project_schema(project_id, current_user.id)


@router.get("/{project_id}/sections/{section}", response_model=NovelSectionResponse)
async def get_novel_section(
    project_id: str,
    section: NovelSectionType,
    session: AsyncSession = Depends(get_session),
    current_user: UserInDB = Depends(get_current_user),
) -> NovelSectionResponse:
    novel_service = NovelService(session)
    logger.info("用户 %s 获取项目 %s 的 %s 区段", current_user.id, project_id, section)
    return await novel_service.get_section_data(project_id, current_user.id, section)


@router.get("/{project_id}/chapters/{chapter_number}", response_model=ChapterSchema)
async def get_chapter(
    project_id: str,
    chapter_number: int,
    session: AsyncSession = Depends(get_session),
    current_user: UserInDB = Depends(get_current_user),
) -> ChapterSchema:
    novel_service = NovelService(session)
    logger.info("用户 %s 获取项目 %s 第 %s 章", current_user.id, project_id, chapter_number)
    return await novel_service.get_chapter_schema(project_id, current_user.id, chapter_number)


@router.delete("", status_code=status.HTTP_200_OK)
async def delete_novels(
    project_ids: List[str] = Body(...),
    session: AsyncSession = Depends(get_session),
    current_user: UserInDB = Depends(get_current_user),
) -> Dict[str, str]:
    novel_service = NovelService(session)
    await novel_service.delete_projects(project_ids, current_user.id)
    logger.info("用户 %s 删除项目 %s", current_user.id, project_ids)
    return {"status": "success", "message": f"成功删除 {len(project_ids)} 个项目"}


@router.post("/{project_id}/concept/converse", response_model=ConverseResponse)
async def converse_with_concept(
    project_id: str,
    request: ConverseRequest,
    session: AsyncSession = Depends(get_session),
    current_user: UserInDB = Depends(get_current_user),
) -> ConverseResponse:
    """与概念设计师（LLM）进行对话，引导蓝图筹备。"""
    novel_service = NovelService(session)
    prompt_service = PromptService(session)
    llm_service = LLMService(session)

    project = await novel_service.ensure_project_owner(project_id, current_user.id)

    history_records = await novel_service.list_conversations(project_id)
    logger.info(
        "项目 %s 概念对话请求，用户 %s，历史记录 %s 条",
        project_id,
        current_user.id,
        len(history_records),
    )
    conversation_history = [
        {"role": record.role, "content": record.content}
        for record in history_records
    ]
    user_content = json.dumps(request.user_input, ensure_ascii=False)
    conversation_history.append({"role": "user", "content": user_content})

    system_prompt = _ensure_prompt(await prompt_service.get_prompt("concept"), "concept")
    system_prompt = f"{system_prompt}\n{JSON_RESPONSE_INSTRUCTION}"

    llm_response = await llm_service.get_llm_response(
        system_prompt=system_prompt,
        conversation_history=conversation_history,
        temperature=0.8,
        user_id=current_user.id,
        timeout=240.0,
        model=request.model,
    )
    llm_response = remove_think_tags(llm_response)

    try:
        normalized = unwrap_markdown_json(llm_response)
        sanitized = sanitize_json_like_text(normalized)
        parsed = json.loads(sanitized)
    except json.JSONDecodeError as exc:
        logger.exception(
            "Failed to parse concept converse response: project_id=%s user_id=%s error=%s\nOriginal response: %s\nNormalized: %s\nSanitized: %s",
            project_id,
            current_user.id,
            exc,
            llm_response[:1000],
            normalized[:1000] if 'normalized' in locals() else "N/A",
            sanitized[:1000] if 'sanitized' in locals() else "N/A",
        )
        raise HTTPException(
            status_code=500,
            detail=f"概念对话失败，AI 返回的内容格式不正确。请重试或联系管理员。错误详情: {str(exc)}"
        ) from exc

    await novel_service.append_conversation(project_id, "user", user_content)
    await novel_service.append_conversation(project_id, "assistant", normalized)

    logger.info("项目 %s 概念对话完成，is_complete=%s", project_id, parsed.get("is_complete"))

    if parsed.get("is_complete"):
        parsed["ready_for_blueprint"] = True

    parsed.setdefault("conversation_state", parsed.get("conversation_state", {}))
    return ConverseResponse(**parsed)


@router.post("/{project_id}/concept/converse-stream")
async def converse_with_concept_stream(
    project_id: str,
    request: ConverseRequest,
    session: AsyncSession = Depends(get_session),
    current_user: UserInDB = Depends(get_current_user),
):
    """概念对话的流式版本（SSE）。

    与 ``converse`` 的区别只在传输方式：这里边生成边推送首字，
    而不是攒完整段再返回。原因是长生成（几十秒到几分钟）期间
    连接完全静默，反向代理会按「静默超时」掐断——Cloudflare
    免费版是 100 秒，前端只能看到 524，误以为是模型出错。

    事件类型::

        event: delta   data: {"text": "..."}      增量文本
        event: done    data: {<最终解析结果>}      完成，含 is_complete 等
        event: error   data: {"detail": "..."}    出错

    业务逻辑与 ``converse`` 完全一致，仅把「等待」换成「推送」。
    """
    novel_service = NovelService(session)
    prompt_service = PromptService(session)
    llm_service = LLMService(session)

    project = await novel_service.ensure_project_owner(project_id, current_user.id)

    history_records = await novel_service.list_conversations(project_id)
    logger.info(
        "项目 %s 概念对话(流式)请求，用户 %s，历史记录 %s 条",
        project_id,
        current_user.id,
        len(history_records),
    )
    conversation_history = [
        {"role": record.role, "content": record.content} for record in history_records
    ]
    user_content = json.dumps(request.user_input, ensure_ascii=False)
    conversation_history.append({"role": "user", "content": user_content})

    system_prompt = _ensure_prompt(await prompt_service.get_prompt("concept"), "concept")
    system_prompt = f"{system_prompt}\n{JSON_RESPONSE_INSTRUCTION}"

    async def event_stream():
        buffer: List[str] = []
        try:
            async for chunk in llm_service.stream_llm_response(
                system_prompt=system_prompt,
                conversation_history=conversation_history,
                temperature=0.8,
                user_id=current_user.id,
                timeout=240.0,
                model=request.model,
            ):
                buffer.append(chunk)
                yield _sse("delta", {"text": chunk})
        except HTTPException as exc:
            # 上游错误（模型不存在、余额不足、超时…）以事件形式下发，
            # 此时响应头已经发出，不可能再改 HTTP 状态码。
            logger.warning("概念对话(流式)失败: project=%s detail=%s", project_id, exc.detail)
            yield _sse("error", {"detail": str(exc.detail), "status": exc.status_code})
            return
        except Exception as exc:  # noqa: BLE001 - 兜底，避免中断后无提示
            logger.exception("概念对话(流式)异常: project=%s", project_id)
            yield _sse("error", {"detail": f"概念对话失败：{exc}"})
            return

        raw = remove_think_tags("".join(buffer))
        try:
            normalized = unwrap_markdown_json(raw)
            sanitized = sanitize_json_like_text(normalized)
            parsed = json.loads(sanitized)
        except json.JSONDecodeError as exc:
            logger.exception(
                "流式概念对话解析失败: project_id=%s error=%s\n原文: %s",
                project_id,
                exc,
                raw[:1000],
            )
            yield _sse("error", {"detail": f"AI 返回的内容格式不正确，请重试。错误详情: {exc}"})
            return

        try:
            await novel_service.append_conversation(project_id, "user", user_content)
            await novel_service.append_conversation(project_id, "assistant", normalized)
        except Exception as exc:  # noqa: BLE001
            logger.exception("流式概念对话落库失败: project=%s", project_id)
            yield _sse("error", {"detail": f"对话保存失败：{exc}"})
            return

        if parsed.get("is_complete"):
            parsed["ready_for_blueprint"] = True
        parsed.setdefault("conversation_state", parsed.get("conversation_state", {}))

        logger.info("项目 %s 概念对话(流式)完成，is_complete=%s",
                    project_id, parsed.get("is_complete"))
        yield _sse("done", parsed)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            # 关掉各级缓冲，确保首个字立刻到达浏览器——
            # 这是让反向代理不按「静默超时」掐断的关键。
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/{project_id}/blueprint/generate-stream")
async def generate_blueprint_stream(
    project_id: str,
    options: BlueprintGenerateRequest | None = Body(None),
    session: AsyncSession = Depends(get_session),
    current_user: UserInDB = Depends(get_current_user),
):
    """蓝图生成的流式版本（SSE）。

    蓝图实测耗时 160 秒（模型返回 15260 字符），远超 Cloudflare 免费版的
    100 秒源站等待上限，非流式必然 524。这里用「心跳帧 + 完成事件」的方式：
    即使模型长时间不出字，连接也一直有数据流动，不会被按静默超时掐断。

    请求体（可选）::

        {
          "protagonist_names": ["沈渡", "陆沉"],   // 候选主角名，模型挑一个
          "instructions": "主角是女性，不要系统流"  // 自由修改意见
        }

    事件::

        : keep-alive      注释帧（每 10 秒，客户端忽略）
        event: done       data: {...蓝图结果...}
        event: error      data: {"detail": "..."}
    """

    async def _work():
        return await _build_blueprint(project_id, session, current_user, options)

    async def _stream():
        async for frame in run_with_heartbeat(
            _work,
            on_done=lambda result: result,
            label="蓝图生成",
        ):
            yield frame

    return sse_response(_stream())


@router.post("/{project_id}/blueprint/generate", response_model=BlueprintGenerationResponse)
async def generate_blueprint(
    project_id: str,
    options: BlueprintGenerateRequest | None = Body(None),
    session: AsyncSession = Depends(get_session),
    current_user: UserInDB = Depends(get_current_user),
) -> BlueprintGenerationResponse:
    """根据完整对话生成可执行的小说蓝图（非流式，保留兼容）。

    新前端请用 ``/blueprint/generate-stream``：这个版本在慢模型下
    会超过反向代理的源站等待上限（Cloudflare 免费版 100 秒）。
    """
    result = await _build_blueprint(project_id, session, current_user, options)
    return BlueprintGenerationResponse(**result)


def _build_blueprint_constraints(options: Optional[BlueprintGenerateRequest]) -> str:
    """把用户的显式要求拼成提示词尾部的高优先级约束块。

    为什么单独成块而不是混进对话历史：这两类输入的权威性不同。
    对话历史是「聊过的内容」，可能含糊、可能被推翻；
    而这里填的是用户在生成前的最终决定，应当压过历史里的推测。
    所以明确告诉模型「以此为准」。

    没有输入时返回空串，提示词保持原样（不影响既有行为）。
    """
    if options is None:
        return ""

    names = [n.strip() for n in (options.protagonist_names or []) if n and n.strip()]
    instructions = (options.instructions or "").strip()
    if not names and not instructions:
        return ""

    lines: List[str] = [
        "",
        "---",
        "",
        "# 用户的明确要求（优先级高于以上对话历史，必须遵守）",
        "",
    ]

    if names:
        listed = "、".join(names)
        lines += [
            f"主角姓名必须从以下候选中选择**一个**：{listed}",
            "",
            "要求：",
            "- `characters` 数组里主角（第一位，或 `relationship_to_protagonist` 为「本人」的那位）的 `name` 必须是上述候选之一，原样使用，不得改写、加姓氏或加称号。",
            "- 其余角色（配角、反派、师长等）可以自行命名，但风格要与所选主角名协调。",
            "- 在 `one_sentence_summary` 或 `full_synopsis` 中自然使用该主角名。",
            "",
        ]

    if instructions:
        lines += [
            "用户对蓝图还有以下要求：",
            "",
            instructions,
            "",
            "以上要求若与对话历史冲突，以本节为准。",
            "",
        ]

    return "\n".join(lines)


async def _build_blueprint(
    project_id: str,
    session: AsyncSession,
    current_user: UserInDB,
    options: Optional[BlueprintGenerateRequest] = None,
) -> Dict[str, Any]:
    """蓝图生成的实际逻辑，供流式与非流式两个端点共用。"""
    novel_service = NovelService(session)
    prompt_service = PromptService(session)
    llm_service = LLMService(session)

    project = await novel_service.ensure_project_owner(project_id, current_user.id)
    logger.info("项目 %s 开始生成蓝图", project_id)

    history_records = await novel_service.list_conversations(project_id)
    if not history_records:
        logger.warning("项目 %s 缺少对话历史，无法生成蓝图", project_id)
        raise HTTPException(status_code=400, detail="缺少对话历史，请先完成概念对话后再生成蓝图")

    formatted_history: List[Dict[str, str]] = []
    for record in history_records:
        role = record.role
        content = record.content
        if not role or not content:
            continue
        try:
            normalized = unwrap_markdown_json(content)
            data = json.loads(normalized)
            if role == "user":
                user_value = data.get("value", data)
                if isinstance(user_value, str):
                    formatted_history.append({"role": "user", "content": user_value})
            elif role == "assistant":
                ai_message = data.get("ai_message") if isinstance(data, dict) else None
                if ai_message:
                    formatted_history.append({"role": "assistant", "content": ai_message})
        except (json.JSONDecodeError, AttributeError):
            continue

    if not formatted_history:
        logger.warning("项目 %s 对话历史格式异常，无法提取有效内容", project_id)
        raise HTTPException(
            status_code=400,
            detail="无法从历史对话中提取有效内容，请检查对话历史格式或重新进行概念对话"
        )

    system_prompt = _ensure_prompt(await prompt_service.get_prompt("screenwriting"), "screenwriting")
    system_prompt = system_prompt + _build_blueprint_constraints(options)
    blueprint_raw = await llm_service.get_llm_response(
        system_prompt=system_prompt,
        conversation_history=formatted_history,
        temperature=0.3,
        user_id=current_user.id,
        timeout=480.0,
    )
    blueprint_raw = remove_think_tags(blueprint_raw)

    blueprint_normalized = unwrap_markdown_json(blueprint_raw)
    blueprint_sanitized = sanitize_json_like_text(blueprint_normalized)
    try:
        blueprint_data = json.loads(blueprint_sanitized)
    except json.JSONDecodeError as exc:
        logger.error(
            "项目 %s 蓝图生成 JSON 解析失败: %s\n原始响应: %s\n标准化后: %s\n清洗后: %s",
            project_id,
            exc,
            blueprint_raw[:500],
            blueprint_normalized[:500],
            blueprint_sanitized[:500],
        )
        raise HTTPException(
            status_code=500,
            detail=f"蓝图生成失败，AI 返回的内容格式不正确。请重试或联系管理员。错误详情: {str(exc)}"
        ) from exc

    blueprint = Blueprint(**blueprint_data)
    await novel_service.replace_blueprint(project_id, blueprint)
    if blueprint.title:
        project.title = blueprint.title
        project.status = "blueprint_ready"
        await session.commit()
        logger.info("项目 %s 更新标题为 %s，并标记为 blueprint_ready", project_id, blueprint.title)

    ai_message = (
        "太棒了！我已经根据我们的对话整理出完整的小说蓝图。请确认是否进入写作阶段，或提出修改意见。"
    )
    # 返回 dict 而不是 Pydantic 模型：流式端点需要 JSON 序列化它，
    # 非流式端点再用它构造响应模型，一份数据两处复用。
    return {"blueprint": blueprint.model_dump(), "ai_message": ai_message}


@router.post("/{project_id}/blueprint/save", response_model=NovelProjectSchema)
async def save_blueprint(
    project_id: str,
    blueprint_data: Blueprint | None = Body(None),
    session: AsyncSession = Depends(get_session),
    current_user: UserInDB = Depends(get_current_user),
) -> NovelProjectSchema:
    """保存蓝图信息，可用于手动覆盖自动生成结果。"""
    novel_service = NovelService(session)
    project = await novel_service.ensure_project_owner(project_id, current_user.id)

    if blueprint_data:
        await novel_service.replace_blueprint(project_id, blueprint_data)
        if blueprint_data.title:
            project.title = blueprint_data.title
            await session.commit()
        logger.info("项目 %s 手动保存蓝图", project_id)
    else:
        logger.warning("项目 %s 保存蓝图时未提供蓝图数据", project_id)
        raise HTTPException(status_code=400, detail="缺少蓝图数据，请提供有效的蓝图内容")

    return await novel_service.get_project_schema(project_id, current_user.id)


@router.patch("/{project_id}/blueprint", response_model=NovelProjectSchema)
async def patch_blueprint(
    project_id: str,
    payload: BlueprintPatch,
    session: AsyncSession = Depends(get_session),
    current_user: UserInDB = Depends(get_current_user),
) -> NovelProjectSchema:
    """局部更新蓝图字段，对世界观或角色做微调。"""
    novel_service = NovelService(session)
    project = await novel_service.ensure_project_owner(project_id, current_user.id)

    update_data = payload.model_dump(exclude_unset=True)
    await novel_service.patch_blueprint(project_id, update_data)
    logger.info("项目 %s 局部更新蓝图字段：%s", project_id, list(update_data.keys()))
    return await novel_service.get_project_schema(project_id, current_user.id)


# ============================================================
# 蓝图变更的过期检测与一致性扫描（只读）
#
# 背景：蓝图改过之后，早先生成的大纲和章节正文仍是旧蓝图的产物，
# 但系统里没有地方记录这件事。实测一个项目蓝图角色是
# [沈渡/苏宛/方规/陆沉/齐延年]，而 82 条大纲和正文用的是
# 「陆行舟」「苏晚」——重叠为零，只能靠用户自己发现。
#
# 这两个接口都【只检测、不改动】：正文是几十万字的心血，
# 且名字存在歧义（「苏宛」vs「苏晚」），必须由用户决定怎么处理。
# ============================================================


@router.get("/{project_id}/staleness")
async def get_blueprint_staleness(
    project_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: UserInDB = Depends(get_current_user),
) -> Dict[str, Any]:
    """报告哪些大纲/章节是基于旧蓝图生成的。

    只做标记，不改动任何内容。``blueprint_revision`` 为空的历史数据
    归入 ``unknown_*`` 而不是 ``stale_*``——没有依据就不能当成过期，
    否则升级后所有老项目都会满屏告警。
    """
    novel_service = NovelService(session)
    await novel_service.ensure_project_owner(project_id, current_user.id)

    service = BlueprintStalenessService(session)
    return (await service.get_report(project_id)).to_dict()


@router.get("/{project_id}/consistency-report")
async def get_consistency_report(
    project_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: UserInDB = Depends(get_current_user),
) -> Dict[str, Any]:
    """扫描大纲与正文里「不在当前蓝图角色表中」的名字。

    只报告，不替换。改名场景下旧名与新名常常一字之差
    （蓝图「苏宛」vs 大纲「苏晚」），程序无法判断是笔误还是两个角色，
    只有作者知道正确答案。所以这里把可疑项连同出现位置列出来，
    由用户决定是否处理。
    """
    novel_service = NovelService(session)
    await novel_service.ensure_project_owner(project_id, current_user.id)

    service = BlueprintStalenessService(session)
    return (await service.scan_names(project_id)).to_dict()


# ============================================================
# 角色改名的预览与应用
#
# 检测（/staleness、/consistency-report）只能告诉你哪里对不上，
# 真正要改还得动手。这里提供「预览 → 确认 → 应用」三步：
#
#   POST .../rename-characters/preview   只算不改，返回每处改动+上下文
#   POST .../rename-characters/apply     真正写入
#
# 为什么必须预览：中文名字歧义极多（蓝图「苏宛」vs 大纲「苏晚」一字之差；
# 「陆行舟」可能被写作「行舟」；「陆」会出现在「陆续」里）。盲替会把
# 「改个名字」变成「悄悄改坏正文」，而正文是几十万字的心血。
#
# 正文改动新建版本而非覆盖，原版永远可回退。
# ============================================================


@router.post("/{project_id}/rename-characters/preview")
async def preview_character_rename(
    project_id: str,
    payload: CharacterRenameRequest,
    session: AsyncSession = Depends(get_session),
    current_user: UserInDB = Depends(get_current_user),
) -> Dict[str, Any]:
    """预览改名会改动哪些地方（不写入任何数据）。"""
    novel_service = NovelService(session)
    await novel_service.ensure_project_owner(project_id, current_user.id)

    service = CharacterRenameService(session)
    preview = await service.preview(project_id, payload.mapping)
    return preview.to_dict()


@router.post("/{project_id}/rename-characters/apply")
async def apply_character_rename(
    project_id: str,
    payload: CharacterRenameRequest,
    session: AsyncSession = Depends(get_session),
    current_user: UserInDB = Depends(get_current_user),
) -> Dict[str, Any]:
    """应用改名。

    正文改动会**新建版本**并把当前版本指过去，原版本完整保留，
    用户可随时在版本列表里切回。
    """
    novel_service = NovelService(session)
    await novel_service.ensure_project_owner(project_id, current_user.id)

    service = CharacterRenameService(session)
    try:
        result = await service.apply(
            project_id, payload.mapping, include_prose=payload.include_prose
        )
    except ValueError as exc:
        # 映射校验失败属于用户可修正的输入问题，返回 400 而不是 500
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result.to_dict()


@router.post("/{project_id}/consistency-report/ignore")
async def ignore_consistency_names(
    project_id: str,
    payload: IgnoreNamesRequest,
    session: AsyncSession = Depends(get_session),
    current_user: UserInDB = Depends(get_current_user),
) -> Dict[str, Any]:
    """把名字加入忽略名单，之后扫描不再报出。

    为什么需要：扫描会有少量误报（普通词恰好以姓氏字开头，如「印司」「寿数」）。
    若不能忽略，告警永远清不掉，用户最终会无视整个提示——那这个功能
    就白做了。``names`` 为空时表示「全部忽略」，用于一键关闭对比页面。
    """
    novel_service = NovelService(session)
    await novel_service.ensure_project_owner(project_id, current_user.id)

    service = BlueprintStalenessService(session)
    names = [n for n in (payload.names or []) if n and n.strip()]
    if not names:
        # 空列表 = 忽略当前所有可疑名字
        report = await service.scan_names(project_id)
        names = [n.name for n in report.unknown_names]
    ignored = await service.ignore_names(project_id, names)
    return {"ignored_names": ignored, "ignored_count": len(names)}


@router.post("/{project_id}/consistency-report/unignore")
async def unignore_consistency_names(
    project_id: str,
    payload: IgnoreNamesRequest,
    session: AsyncSession = Depends(get_session),
    current_user: UserInDB = Depends(get_current_user),
) -> Dict[str, Any]:
    """从忽略名单移除；``names`` 为空时清空整个名单。"""
    novel_service = NovelService(session)
    await novel_service.ensure_project_owner(project_id, current_user.id)

    service = BlueprintStalenessService(session)
    names = [n for n in (payload.names or []) if n and n.strip()]
    if not names:
        record = await session.get(NovelBlueprint, project_id)
        if record is not None:
            record.ignored_names = []
            await session.commit()
        return {"ignored_names": []}
    ignored = await service.unignore_names(project_id, names)
    return {"ignored_names": ignored}
