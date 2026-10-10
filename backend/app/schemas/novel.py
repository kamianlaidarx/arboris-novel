# AIMETA P=小说模式_小说和章节请求响应|R=小说结构_章节结构|NR=不含业务逻辑|E=NovelSchema_ChapterSchema|X=internal|A=Pydantic模式|D=pydantic|S=none|RD=./README.ai
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ChoiceOption(BaseModel):
    """前端选择项描述，用于动态 UI 控件。"""

    id: str
    label: str


class UIControl(BaseModel):
    """描述前端应渲染的组件类型与配置。"""

    type: str = Field(..., description="控件类型，如 single_choice/text_input")
    options: Optional[List[ChoiceOption]] = Field(default=None, description="可选项列表")
    placeholder: Optional[str] = Field(default=None, description="输入提示文案")


class ConverseResponse(BaseModel):
    """概念对话接口的统一返回体。"""

    ai_message: str
    ui_control: UIControl
    conversation_state: Dict[str, Any]
    is_complete: bool = False
    ready_for_blueprint: Optional[bool] = None


class ConverseRequest(BaseModel):
    """概念对话接口的请求体。"""

    user_input: Dict[str, Any]
    conversation_state: Dict[str, Any]
    #: 可选：本次对话使用的模型。不传则用用户的活跃模型。
    model: Optional[str] = Field(
        default=None, description="本次请求使用的模型名；留空则用当前活跃模型"
    )


class ChapterGenerationStatus(str, Enum):
    NOT_GENERATED = "not_generated"
    GENERATING = "generating"
    EVALUATING = "evaluating"
    SELECTING = "selecting"
    FAILED = "failed"
    EVALUATION_FAILED = "evaluation_failed"
    WAITING_FOR_CONFIRM = "waiting_for_confirm"
    SUCCESSFUL = "successful"


class ChapterOutline(BaseModel):
    chapter_number: int
    # title / summary 给默认值而不是必填：模型偶尔会漏掉某个字段，
    # 而一次蓝图生成要 40 秒以上，因为一个缺失的标题就让整次生成失败
    # 并不划算（实测 gemini 输出的 10 个章节里全都漏了 title）。
    # 界面会展示空标题，用户可以手动补，比整份蓝图丢掉好。
    title: str = ""
    summary: str = ""


class Chapter(ChapterOutline):
    real_summary: Optional[str] = None
    content: Optional[str] = None
    versions: Optional[List[str]] = None
    evaluation: Optional[str] = None
    generation_status: ChapterGenerationStatus = ChapterGenerationStatus.NOT_GENERATED


class Relationship(BaseModel):
    character_from: str
    character_to: str
    description: str


class Blueprint(BaseModel):
    title: str
    target_audience: str = ""
    genre: str = ""
    style: str = ""
    tone: str = ""
    one_sentence_summary: str = ""
    full_synopsis: str = ""
    world_setting: Dict[str, Any] = {}
    characters: List[Dict[str, Any]] = []
    relationships: List[Relationship] = []
    chapter_outline: List[ChapterOutline] = []
    
    class Config:
        from_attributes = True


class NovelProject(BaseModel):
    id: str
    user_id: int
    title: str
    initial_prompt: str
    conversation_history: List[Dict[str, Any]] = []
    blueprint: Optional[Blueprint] = None
    chapters: List[Chapter] = []

    class Config:
        from_attributes = True


class NovelProjectSummary(BaseModel):
    id: str
    title: str
    genre: str
    last_edited: str
    completed_chapters: int
    total_chapters: int


class BlueprintGenerateRequest(BaseModel):
    """蓝图生成的可选用户输入。

    背景：蓝图原本只依据「概念对话历史」生成，用户对角色命名等细节
    没有任何直接输入通道，只能反复对话去间接影响，且模型每次取名
    都趋同（同一套提示词下分布收敛）。这里补一个显式通道。
    """

    #: 候选主角名。模型从中挑一个作为主角；留空则自由发挥。
    #: 做成列表而非单值：用户常想给几个风格相近的名字让模型选。
    protagonist_names: List[str] = Field(
        default_factory=list,
        description="候选主角名，模型从中选一个；留空则由模型自行命名",
    )
    #: 自由修改意见。可写任何要求，例如「主角是女性」「不要系统流」
    #: 「世界观偏硬科幻」。会作为高优先级指令拼进提示词。
    instructions: str = Field(
        default="",
        description="用户对蓝图的额外要求，会作为高优先级指令传给模型",
    )


class BlueprintGenerationResponse(BaseModel):
    blueprint: Blueprint
    ai_message: str


class ChapterGenerationResponse(BaseModel):
    ai_message: str
    chapter_versions: List[Dict[str, Any]]


class NovelSectionType(str, Enum):
    OVERVIEW = "overview"
    WORLD_SETTING = "world_setting"
    CHARACTERS = "characters"
    RELATIONSHIPS = "relationships"
    CHAPTER_OUTLINE = "chapter_outline"
    CHAPTERS = "chapters"


class NovelSectionResponse(BaseModel):
    section: NovelSectionType
    data: Dict[str, Any]


class GenerateChapterRequest(BaseModel):
    chapter_number: int
    writing_notes: Optional[str] = Field(default=None, description="章节额外写作指令")


class FlowConfig(BaseModel):
    preset: str = Field(default="basic", description="basic|enhanced|ultimate|custom")
    versions: Optional[int] = Field(default=None, description="生成版本数量")
    enable_preview: Optional[bool] = Field(default=None, description="是否启用预演生成")
    enable_optimizer: Optional[bool] = Field(default=None, description="是否启用优化器")
    enable_consistency: Optional[bool] = Field(default=None, description="是否启用一致性检查")
    enable_enrichment: Optional[bool] = Field(default=None, description="是否启用字数扩写")
    async_finalize: Optional[bool] = Field(default=None, description="是否异步定稿")
    enable_rag: Optional[bool] = Field(default=None, description="是否启用 RAG")
    rag_mode: Optional[str] = Field(default=None, description="simple|two_stage")


class AdvancedGenerateRequest(BaseModel):
    project_id: str
    chapter_number: int
    writing_notes: Optional[str] = Field(default=None, description="章节额外写作指令")
    flow_config: FlowConfig = Field(default_factory=FlowConfig)


class AdvancedGenerateVariant(BaseModel):
    index: int
    version_id: int
    content: str
    metadata: Optional[Dict[str, Any]] = None


class AdvancedGenerateResponse(BaseModel):
    project_id: str
    chapter_number: int
    preset: str
    best_version_index: int
    variants: List[AdvancedGenerateVariant]
    review_summaries: Dict[str, Any] = Field(default_factory=dict)
    debug_metadata: Optional[Dict[str, Any]] = None


class FinalizeChapterRequest(BaseModel):
    project_id: str
    selected_version_id: int
    skip_vector_update: Optional[bool] = Field(default=False, description="是否跳过向量库更新")


class FinalizeChapterResponse(BaseModel):
    project_id: str
    chapter_number: int
    selected_version_id: int
    result: Dict[str, Any]


class SelectVersionRequest(BaseModel):
    chapter_number: int
    version_index: int


class EvaluateChapterRequest(BaseModel):
    chapter_number: int


class UpdateChapterOutlineRequest(BaseModel):
    chapter_number: int
    title: str
    summary: str


class DeleteChapterRequest(BaseModel):
    chapter_numbers: List[int]


class GenerateOutlineRequest(BaseModel):
    start_chapter: int
    num_chapters: int


class BlueprintPatch(BaseModel):
    one_sentence_summary: Optional[str] = None
    full_synopsis: Optional[str] = None
    world_setting: Optional[Dict[str, Any]] = None
    characters: Optional[List[Dict[str, Any]]] = None
    relationships: Optional[List[Relationship]] = None
    chapter_outline: Optional[List[ChapterOutline]] = None


class EditChapterRequest(BaseModel):
    chapter_number: int
    content: str


class CharacterRenameRequest(BaseModel):
    """角色改名的映射。

    只做**全名精确替换**，不猜简称：中文简称（「陆行舟」→「行舟」/「陆兄」）
    需要用户明确指定，程序猜错会改坏正文。
    """

    #: {旧名: 新名}
    mapping: Dict[str, str] = Field(
        default_factory=dict,
        description="旧名到新名的映射，如 {'陆行舟': '李明'}",
    )
    #: 是否同时替换章节正文。False 时只改大纲。
    include_prose: bool = Field(
        default=True,
        description="是否替换正文；false 表示只改大纲",
    )


class IgnoreNamesRequest(BaseModel):
    """忽略/取消忽略某些名字。

    ``names`` 为空表示对**全部**当前可疑名字生效——用于一键关闭对比页面。
    """

    names: List[str] = Field(default_factory=list)


class OutlineRegenRequest(BaseModel):
    """章节大纲重生成请求。

    与原有 ``GenerateOutlineRequest`` 的区别：那个只能从末尾追加
    （``start_chapter`` 由前端算成「现有数量+1」），这个可以指定任意范围
    重做，并带上用户的优化建议。
    """

    start_chapter: int = Field(ge=1, description="起始章节号（含）")
    num_chapters: int = Field(
        ge=1, le=30,
        description="生成章节数；上限 30，一次生成过多会变慢且后半段容易丢失一致性",
    )
    instructions: str = Field(
        default="",
        description="优化建议与限制，如「节奏再快些」「每章结尾留悬念」",
    )
    keep_existing: bool = Field(
        default=True,
        description="是否参考已有大纲的情节走向；false 表示可以完全重新设计",
    )


class OutlineDraftPayload(BaseModel):
    """一条确认后的大纲草稿。"""

    chapter_number: int
    title: str = ""
    summary: str = ""


class OutlineApplyRequest(BaseModel):
    drafts: List[OutlineDraftPayload] = Field(default_factory=list)


class ApplyOptimizationRequest(BaseModel):
    """应用优化结果。

    为什么用请求体而不是查询参数：优化后的正文动辄上万字，
    放进 URL 会超出 nginx 的 ``large_client_header_buffers`` 限制
    （默认 8k），服务端直接返回 **414 URI Too Long**。
    正文本来就该走请求体。
    """

    project_id: str
    chapter_number: int
    optimized_content: str
