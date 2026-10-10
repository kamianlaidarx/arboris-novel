"""蓝图生成的可选用户输入（候选主角名 + 修改意见）。

背景：蓝图原本只依据概念对话历史生成，用户对角色命名没有任何直接
输入通道，只能靠多轮对话间接影响。实测模型每次取名都趋同
（同一套提示词下分布收敛到「姓+古风字」）。

这里验证「显式输入 → 提示词约束」这段拼装逻辑：
既要把要求表达清楚，也不能在用户没填时改变原有行为。
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.api.routers.novels import _build_blueprint_constraints
from app.schemas.novel import BlueprintGenerateRequest


# ==================================================== 不填时保持原样

def test_no_options_returns_empty():
    """没填任何内容时不能改动提示词——否则会影响既有生成质量。"""
    assert _build_blueprint_constraints(None) == ""
    assert _build_blueprint_constraints(BlueprintGenerateRequest()) == ""


def test_blank_values_return_empty():
    """只填空格/空字符串等同于没填。"""
    assert _build_blueprint_constraints(
        BlueprintGenerateRequest(protagonist_names=["", "   "], instructions="  ")
    ) == ""


# ==================================================== 候选主角名

def test_names_are_listed():
    block = _build_blueprint_constraints(
        BlueprintGenerateRequest(protagonist_names=["沈渡", "陆沉"])
    )
    assert "沈渡" in block and "陆沉" in block
    assert "必须从以下候选中选择" in block


def test_names_trimmed_and_empties_dropped():
    block = _build_blueprint_constraints(
        BlueprintGenerateRequest(protagonist_names=["  沈渡  ", "", "陆沉"])
    )
    assert "沈渡、陆沉" in block, "应去掉空白项并 trim"


def test_names_instruct_exact_use():
    """关键：要明确要求「原样使用」，否则模型会加姓氏或称号。"""
    block = _build_blueprint_constraints(
        BlueprintGenerateRequest(protagonist_names=["沈渡"])
    )
    assert "原样使用" in block
    assert "不得改写" in block


def test_names_allow_naming_other_characters():
    """只约束主角，配角仍可自行命名——否则模型可能不敢造名字。"""
    block = _build_blueprint_constraints(
        BlueprintGenerateRequest(protagonist_names=["沈渡"])
    )
    assert "其余角色" in block
    assert "自行命名" in block


# ==================================================== 修改意见

def test_instructions_included():
    block = _build_blueprint_constraints(
        BlueprintGenerateRequest(instructions="主角是女性，不要系统流")
    )
    assert "主角是女性，不要系统流" in block


def test_instructions_take_precedence_over_history():
    """必须声明优先级，否则模型会偏向对话历史里的旧说法。"""
    block = _build_blueprint_constraints(
        BlueprintGenerateRequest(instructions="主角是女性")
    )
    assert "优先级高于" in block or "以本节为准" in block


# ==================================================== 组合

def test_both_inputs_combined():
    block = _build_blueprint_constraints(
        BlueprintGenerateRequest(
            protagonist_names=["沈渡"],
            instructions="不要系统流",
        )
    )
    assert "沈渡" in block
    assert "不要系统流" in block


def test_block_is_appended_after_prompt():
    """约束块必须能安全地拼在提示词尾部（以分隔线开头）。"""
    block = _build_blueprint_constraints(
        BlueprintGenerateRequest(protagonist_names=["沈渡"])
    )
    assert block.startswith("\n"), "应以换行开头，避免和上文粘连"
    assert "---" in block


def test_names_not_mutated_by_builder():
    """拼装过程不应改动传入的列表。"""
    req = BlueprintGenerateRequest(protagonist_names=["沈渡", "陆沉"])
    _build_blueprint_constraints(req)
    assert req.protagonist_names == ["沈渡", "陆沉"]
