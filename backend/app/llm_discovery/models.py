# AIMETA P=模型发现数据结构|R=模型信息与结果结构|NR=不含IO逻辑|E=ModelInfo,ModelListResult|X=internal|A=数据类|D=dataclasses|S=none|RD=./README.ai
"""与传输层无关的模型发现数据结构。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, Iterable, List, Optional, Sequence


class Capability(str, Enum):
    """模型能力标签。

    能力标签由模型 ID 的命名特征推断，仅用于界面上分组/过滤，
    不代表对模型能力的权威判定，用户可以手动输入任意模型名。
    """

    CHAT = "chat"
    REASONING = "reasoning"
    VISION = "vision"
    EMBEDDING = "embedding"
    RERANK = "rerank"
    IMAGE = "image"
    AUDIO = "audio"
    MODERATION = "moderation"
    CODE = "code"
    OTHER = "other"


# 单个模型最多保留的能力标签数量，避免标签噪声
MAX_CAPABILITIES_PER_MODEL = 4


@dataclass(frozen=True)
class ModelInfo:
    """单个模型条目。"""

    id: str
    owned_by: Optional[str] = None
    created: Optional[int] = None
    capabilities: Sequence[Capability] = ()
    description: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "id": self.id,
            "capabilities": [item.value for item in self.capabilities],
        }
        if self.owned_by:
            payload["owned_by"] = self.owned_by
        if self.created is not None:
            payload["created"] = self.created
        if self.description:
            payload["description"] = self.description
        return payload


@dataclass
class ModelListResult:
    """一次模型发现的结果。

    即使 discovery 部分失败（例如某个候选端点 404），只要最终拿到模型列表，
    也会把过程中的问题记录在 ``warnings`` 中返回，而不是静默吞掉。
    """

    provider: str
    provider_label: str
    base_url: Optional[str]
    endpoint: Optional[str]
    models: List[ModelInfo] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    attempts: List[str] = field(default_factory=list)
    elapsed_ms: int = 0
    cached: bool = False
    expires_in: int = 0
    truncated: bool = False
    limited: bool = False
    total: int = 0
    latency_ms: Optional[int] = None

    def capability_counts(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for model in self.models:
            for capability in model.capabilities:
                counts[capability.value] = counts.get(capability.value, 0) + 1
        return counts

    def model_ids(self) -> List[str]:
        return [model.id for model in self.models]


def dedupe_models(models: Iterable[ModelInfo]) -> List[ModelInfo]:
    """按模型 ID 去重并按名称排序，去重时保留先出现（优先级更高）的条目。"""

    seen: Dict[str, ModelInfo] = {}
    for model in models:
        key = model.id.strip()
        if not key:
            continue
        if key not in seen:
            seen[key] = model if key == model.id else ModelInfo(
                id=key,
                owned_by=model.owned_by,
                created=model.created,
                capabilities=model.capabilities,
                description=model.description,
            )
    return sorted(seen.values(), key=lambda item: item.id.lower())
