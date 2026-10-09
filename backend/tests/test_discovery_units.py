# AIMETA P=模型发现单元测试|R=端点推导_供应商识别_错误分级|NR=不含网络|E=test_discovery_units|X=internal|A=pytest|D=pytest|S=none|RD=./README.ai
"""模型发现层纯函数级测试：端点推导、能力分类、供应商识别、地址校验。"""

import pytest

from app.llm_discovery.adapters.base import classify_model
from app.llm_discovery.adapters.openai_compatible import (
    MAX_CANDIDATES,
    derive_candidates,
    parse_model_payload,
)
from app.llm_discovery.catalog import (
    ProviderKind,
    detect_provider,
    get_provider,
    is_local_or_private,
    normalize_base_url,
)
from app.llm_discovery.models import Capability, ModelInfo, dedupe_models


# --------------------------------------------------------------- 地址归一化


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("https://api.deepseek.com/v1", "https://api.deepseek.com/v1"),
        ("https://api.deepseek.com/v1/", "https://api.deepseek.com/v1"),
        ("  https://api.deepseek.com/v1  ", "https://api.deepseek.com/v1"),
        # 缺少协议时补 https
        ("api.deepseek.com/v1", "https://api.deepseek.com/v1"),
        # 本地地址补 http
        ("localhost:11434", "http://localhost:11434"),
        ("127.0.0.1:8000/v1", "http://127.0.0.1:8000/v1"),
        # # 结尾表示固定端点，归一化后保留标记
        ("https://host/custom/models#", "https://host/custom/models#"),
        # 空值
        ("", None),
        ("   ", None),
        (None, None),
    ],
)
def test_normalize_base_url(raw, expected):
    assert normalize_base_url(raw) == expected


# --------------------------------------------------------------- 供应商识别


@pytest.mark.parametrize(
    "url,expected_id,expected_kind",
    [
        ("https://api.deepseek.com/v1", "deepseek", ProviderKind.OPENAI_COMPATIBLE),
        ("https://api.moonshot.cn/v1", "moonshot", ProviderKind.OPENAI_COMPATIBLE),
        ("https://open.bigmodel.cn/api/paas/v4", "zhipu", ProviderKind.OPENAI_COMPATIBLE),
        ("https://api.siliconflow.cn/v1", "siliconflow", ProviderKind.OPENAI_COMPATIBLE),
        ("https://openrouter.ai/api/v1", "openrouter", ProviderKind.OPENAI_COMPATIBLE),
        ("https://api.openai.com/v1", "openai", ProviderKind.OPENAI_COMPATIBLE),
        ("https://api.anthropic.com/v1", "anthropic", ProviderKind.ANTHROPIC),
        ("https://generativelanguage.googleapis.com/v1beta", "google", ProviderKind.GOOGLE),
        ("http://localhost:11434", "ollama", ProviderKind.OLLAMA),
        ("https://my-proxy.example.com/v1", "openai-compatible", ProviderKind.OPENAI_COMPATIBLE),
        ("https://foo.openai.azure.com", "azure-openai", ProviderKind.AZURE_OPENAI),
    ],
)
def test_detect_provider(url, expected_id, expected_kind):
    descriptor = detect_provider(url)
    assert descriptor.id == expected_id
    assert descriptor.kind == expected_kind


def test_detect_provider_without_url_defaults_to_openai():
    assert detect_provider(None).id == "openai"
    assert detect_provider("").id == "openai"


def test_get_provider_unknown_returns_none():
    assert get_provider("no-such-provider") is None
    assert get_provider("DEEPSEEK").id == "deepseek"


# --------------------------------------------------------------- 内网判定


@pytest.mark.parametrize(
    "url,expected",
    [
        ("http://localhost:11434", True),
        ("http://127.0.0.1:8000/v1", True),
        ("http://10.0.0.5/v1", True),
        ("http://192.168.1.20/v1", True),
        ("http://172.16.5.4/v1", True),
        ("http://169.254.1.1/v1", True),
        ("https://api.deepseek.com/v1", False),
        ("https://my-proxy.example.com/v1", False),
    ],
)
def test_is_local_or_private(url, expected):
    assert is_local_or_private(url) is expected


# --------------------------------------------------------------- 端点推导


@pytest.mark.parametrize(
    "base_url,expected_first,expected_count",
    [
        # 已带版本号：只补 /models，不得拼出 /v1/v1/models
        ("https://api.siliconflow.cn/v1", "https://api.siliconflow.cn/v1/models", 1),
        ("https://open.bigmodel.cn/api/paas/v4", "https://open.bigmodel.cn/api/paas/v4/models", 1),
        # 裸域名：优先标准 /v1/models，再退回 /models
        ("https://api.deepseek.com", "https://api.deepseek.com/v1/models", 2),
        # 像 API 根路径的末段：先补 /models，再试 /v1/models
        ("https://host/openai", "https://host/openai/models", 2),
        # 已明确指定 models
        ("https://host/v1/models", "https://host/v1/models", 1),
        # # 固定端点
        ("https://host/custom/path#", "https://host/custom/path", 1),
    ],
)
def test_derive_candidates(base_url, expected_first, expected_count):
    candidates = derive_candidates(base_url)
    assert candidates[0] == expected_first
    assert len(candidates) == expected_count
    # 所有候选都必须包含在尝试上限内
    assert len(candidates) <= MAX_CANDIDATES


def test_derive_candidates_never_produces_doubled_version_segment():
    """回归测试：/v1 结尾的地址不能推导出 /v1/v1/models。"""

    for base_url in (
        "https://api.siliconflow.cn/v1",
        "https://api.deepseek.com/v1",
        "https://openrouter.ai/api/v1",
    ):
        for candidate in derive_candidates(base_url):
            assert "/v1/v1/" not in candidate
            assert "//" not in candidate.replace("://", "")


def test_derive_candidates_empty_uses_openai_default():
    assert derive_candidates(None) == ["https://api.openai.com/v1/models"]
    assert derive_candidates("") == ["https://api.openai.com/v1/models"]


def test_derive_candidates_deduplicates():
    candidates = derive_candidates("https://host/v1")
    assert len(candidates) == len(set(candidates))


# --------------------------------------------------------------- 响应解析


def test_parse_model_payload_openai_shape():
    payload = {
        "object": "list",
        "data": [
            {"id": "gpt-4o-mini", "object": "model", "created": 1700000000, "owned_by": "openai"},
            {"id": "text-embedding-3-large", "owned_by": "openai"},
        ],
    }
    parsed = parse_model_payload(payload)
    assert [item["id"] for item in parsed] == ["gpt-4o-mini", "text-embedding-3-large"]
    assert parsed[0]["owned_by"] == "openai"
    assert parsed[0]["created"] == 1700000000


def test_parse_model_payload_tolerates_variants():
    # 裸数组 + 字符串条目
    assert parse_model_payload(["a", "b"]) == [{"id": "a"}, {"id": "b"}]
    # models 键
    parsed = parse_model_payload({"models": [{"name": "m1"}]})
    assert parsed[0]["id"] == "m1"
    # data.models 嵌套
    parsed = parse_model_payload({"data": {"models": [{"id": "m2"}]}})
    assert parsed[0]["id"] == "m2"
    # 无法识别的结构
    assert parse_model_payload({"unexpected": 1}) == []
    assert parse_model_payload(None) == []


def test_parse_model_payload_skips_entries_without_id():
    parsed = parse_model_payload({"data": [{"id": ""}, {"object": "model"}, {"id": "ok"}]})
    assert [item["id"] for item in parsed] == ["ok"]


# --------------------------------------------------------------- 能力分类


@pytest.mark.parametrize(
    "model_id,expected",
    [
        ("gpt-4o-mini", Capability.CHAT),
        ("deepseek-chat", Capability.CHAT),
        ("deepseek-reasoner", Capability.REASONING),
        ("text-embedding-3-large", Capability.EMBEDDING),
        ("bge-reranker-v2-m3", Capability.RERANK),
        ("dall-e-3", Capability.IMAGE),
        ("whisper-1", Capability.AUDIO),
        ("claude-3-5-sonnet-20241022", Capability.VISION),
        ("qwen2.5-vl-72b-instruct", Capability.VISION),
        ("codestral-latest", Capability.CODE),
        ("omni-moderation-latest", Capability.MODERATION),
    ],
)
def test_classify_model_detects_capability(model_id, expected):
    assert expected in classify_model(model_id)


def test_classify_model_embedding_is_not_chat():
    caps = classify_model("text-embedding-3-large")
    assert Capability.EMBEDDING in caps
    assert Capability.CHAT not in caps


def test_classify_model_unknown_keeps_chat_assumption():
    """无法识别的模型来自 OpenAI 兼容网关，按对话模型处理并标记 other。"""

    caps = classify_model("totally-unknown-model-xyz")
    assert Capability.CHAT in caps
    assert Capability.OTHER in caps


def test_classify_model_minilm_is_embedding():
    caps = classify_model("sentence-transformers/all-MiniLM-L6-v2")
    assert Capability.EMBEDDING in caps
    assert Capability.CHAT not in caps


@pytest.mark.parametrize(
    "model_id",
    [
        "e2e-image-gen",
        "image_gen_v2",
        "stabilityai/stable-diffusion-xl",
        "dall-e-3",
        "imagen-3.0-generate-001",
    ],
)
def test_classify_model_image_generation_variants(model_id):
    """图像生成模型的命名变体都应被识别，且不应被标记为对话模型。"""

    caps = classify_model(model_id)
    assert Capability.IMAGE in caps, f"{model_id} 未识别为图像生成"
    assert Capability.CHAT not in caps, f"{model_id} 不应被标记为对话模型"


@pytest.mark.parametrize(
    "model_id",
    [
        "deepseek-reasoner",
        "claude-3-5-sonnet-20241022",
        "qwen2.5-vl-72b-instruct",
        "codestral-latest",
        "e2e-vision-max",
        "e2e-reasoner-v2",
    ],
)
def test_classify_model_chat_capable_specialists(model_id):
    """推理 / 视觉 / 代码模型本身就是对话模型，必须同时带 chat 标签。

    否则用户在"对话"过滤器下会看不到这些模型。
    """

    caps = classify_model(model_id)
    assert Capability.CHAT in caps, f"{model_id} 缺少 chat 标签: {caps}"


def test_classify_model_audio_and_rerank_are_not_chat():
    for model_id in ("whisper-1", "bge-reranker-v2-m3"):
        caps = classify_model(model_id)
        assert Capability.CHAT not in caps, f"{model_id} 不应被标记为对话模型: {caps}"


def test_classify_model_caps_label_count():
    caps = classify_model("o3-vision-code-reasoning-embed")
    assert len(caps) <= 4


# --------------------------------------------------------------- 去重排序


def test_dedupe_models_removes_duplicates_and_sorts():
    models = [
        ModelInfo(id="b-model", capabilities=(Capability.CHAT,)),
        ModelInfo(id="a-model", capabilities=(Capability.CHAT,)),
        ModelInfo(id="b-model", capabilities=(Capability.EMBEDDING,)),
    ]
    deduped = dedupe_models(models)
    assert [item.id for item in deduped] == ["a-model", "b-model"]
    # 保留先出现的条目
    assert deduped[1].capabilities == (Capability.CHAT,)


def test_dedupe_models_ignores_blank_ids():
    assert dedupe_models([ModelInfo(id="  "), ModelInfo(id=" ok ")]) != []
    assert [item.id for item in dedupe_models([ModelInfo(id="  "), ModelInfo(id=" ok ")])] == ["ok"]
