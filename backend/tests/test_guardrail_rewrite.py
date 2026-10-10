"""护栏自动修复的回归测试。

真实故障：生成的章节正文在版本表里变成了

    {"content": null, "parsed_json": null, "guardrail": {...}, "chapter_mission": {...}}

两个缺陷叠加导致：

1. ``_rewrite_with_guardrails`` 是**截断的函数**——只处理了「提示词未配置」
   分支，之后就结束，隐式返回 None。调用方不校验返回值，None 被当作正文
   一路传下去。
2. 兜底写法是 ``extracted_text or final_content``：正文取不到时，把整份
   **内部结构**当成了章节正文存进版本表。界面显示成一串 JSON，字数统计
   还把它算了进去，用户以为生成成功了。

护栏是「尽力修正」，绝不能因为修正失败而丢掉正文。
"""
from __future__ import annotations

import os
import sys
from typing import Any, Dict, Optional

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi import HTTPException

from app.api.routers.writer import _rewrite_with_guardrails


class FakePromptService:
    def __init__(self, prompt: Optional[str] = "修复提示词"):
        self._prompt = prompt

    async def get_prompt(self, name: str) -> Optional[str]:
        return self._prompt


class FakeLLM:
    def __init__(self, reply: Any = "修复后的正文", raises: Optional[Exception] = None):
        self._reply = reply
        self._raises = raises
        self.calls = 0
        self.last_input = ""

    async def get_llm_response(self, *, system_prompt: str, conversation_history, **kw):
        self.calls += 1
        self.last_input = conversation_history[0]["content"]
        if self._raises:
            raise self._raises
        return self._reply


ORIGINAL = "沈渡走进解剖室。" * 20  # 足够长，避免触发「过短」保护


# ==================================================== 正常路径

async def test_returns_rewritten_text():
    llm = FakeLLM("这是修复后的正文。" * 20)
    out = await _rewrite_with_guardrails(
        llm_service=llm,
        prompt_service=FakePromptService(),
        original_text=ORIGINAL,
        chapter_mission={"pov": "沈渡"},
        violations_text="- sudden_familiarity: 缺少介绍",
        user_id=1,
    )
    assert out is not None
    assert "修复后的正文" in out


async def test_prompt_contains_all_required_sections():
    """提示词模板要求 [原文] / [章节导演脚本] / [违规列表] 三段。"""
    llm = FakeLLM("修复" * 200)
    await _rewrite_with_guardrails(
        llm_service=llm,
        prompt_service=FakePromptService(),
        original_text=ORIGINAL,
        chapter_mission={"pov": "沈渡"},
        violations_text="违规说明",
        user_id=1,
    )
    assert "[原文]" in llm.last_input
    assert "[章节导演脚本]" in llm.last_input
    assert "[违规列表]" in llm.last_input
    assert "违规说明" in llm.last_input


async def test_handles_missing_mission():
    llm = FakeLLM("修复" * 200)
    out = await _rewrite_with_guardrails(
        llm_service=llm,
        prompt_service=FakePromptService(),
        original_text=ORIGINAL,
        chapter_mission=None,
        violations_text="v",
        user_id=1,
    )
    assert out is not None
    assert "（无）" in llm.last_input


# ==================================================== 失败路径必须返回 None

async def test_no_prompt_returns_original():
    """没配提示词时原样返回，不算失败。"""
    out = await _rewrite_with_guardrails(
        llm_service=FakeLLM(),
        prompt_service=FakePromptService(None),
        original_text=ORIGINAL,
        chapter_mission=None,
        violations_text="v",
        user_id=1,
    )
    assert out == ORIGINAL


async def test_llm_exception_returns_none():
    """修复调用失败 → None，由调用方保留原文。"""
    llm = FakeLLM(raises=RuntimeError("上游炸了"))
    out = await _rewrite_with_guardrails(
        llm_service=llm,
        prompt_service=FakePromptService(),
        original_text=ORIGINAL,
        chapter_mission=None,
        violations_text="v",
        user_id=1,
    )
    assert out is None


async def test_empty_reply_returns_none():
    llm = FakeLLM("   ")
    out = await _rewrite_with_guardrails(
        llm_service=llm,
        prompt_service=FakePromptService(),
        original_text=ORIGINAL,
        chapter_mission=None,
        violations_text="v",
        user_id=1,
    )
    assert out is None


async def test_none_reply_returns_none():
    """模型返回 None 时不能把它当正文。"""
    llm = FakeLLM(None)
    out = await _rewrite_with_guardrails(
        llm_service=llm,
        prompt_service=FakePromptService(),
        original_text=ORIGINAL,
        chapter_mission=None,
        violations_text="v",
        user_id=1,
    )
    assert out is None


async def test_too_short_reply_returns_none():
    """修复结果远短于原文时视为异常——直接采用会把正文截断，比不修更糟。"""
    llm = FakeLLM("好的，已修复。")
    out = await _rewrite_with_guardrails(
        llm_service=llm,
        prompt_service=FakePromptService(),
        original_text=ORIGINAL,
        chapter_mission=None,
        violations_text="v",
        user_id=1,
    )
    assert out is None


async def test_never_returns_none_implicitly_on_success_path():
    """回归：函数此前是截断的，配置了提示词时会隐式返回 None。

    这条测试直接盯住那个缺陷：只要提示词存在，就必须走完流程并给出
    明确结果（成功返回文本，失败返回 None），而不是无声地掉出函数体。
    """
    llm = FakeLLM("修复" * 300)
    out = await _rewrite_with_guardrails(
        llm_service=llm,
        prompt_service=FakePromptService("有提示词"),
        original_text=ORIGINAL,
        chapter_mission={},
        violations_text="v",
        user_id=1,
    )
    assert llm.calls == 1, "配置了提示词就必须真的调用模型"
    assert out is not None and out != ""
