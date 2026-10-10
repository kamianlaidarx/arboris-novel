"""蓝图 schema 的容错回归测试。

真实故障：gemini 生成的蓝图里 10 个章节全都没有 title 字段，
而 ChapterOutline.title 是必填，于是 Pydantic 抛 ValidationError，
整次生成（耗时 43 秒）作废。

取舍：模型偶尔漏字段是常态，而一次蓝图生成要几十秒。
因为一个缺失的章节标题就丢掉整份蓝图不划算——界面能展示空标题，
用户可以手动补。所以 title/summary 改为带默认值。
"""
from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.schemas.novel import Blueprint, ChapterOutline


def test_chapter_outline_allows_missing_title():
    """复现线上失败的数据形状。"""
    outline = ChapterOutline(chapter_number=1, summary="主角醒来")
    assert outline.chapter_number == 1
    assert outline.title == ""
    assert outline.summary == "主角醒来"


def test_chapter_outline_allows_missing_summary():
    outline = ChapterOutline(chapter_number=2, title="开端")
    assert outline.title == "开端"
    assert outline.summary == ""


def test_blueprint_without_chapter_titles_constructs():
    """核心：漏 title 不应让整份蓝图构造失败。"""
    bp = Blueprint(
        title="断尘照骨录",
        chapter_outline=[
            {"chapter_number": 1, "summary": "主角醒来"},
            {"chapter_number": 2, "summary": "遭遇追兵"},
        ],
    )
    assert len(bp.chapter_outline) == 2
    assert all(c.title == "" for c in bp.chapter_outline)


def test_blueprint_keeps_titles_when_present():
    """有 title 时必须原样保留，不能被默认值覆盖。"""
    bp = Blueprint(
        title="X",
        chapter_outline=[{"chapter_number": 1, "title": "开端", "summary": "s"}],
    )
    assert bp.chapter_outline[0].title == "开端"


def test_blueprint_title_still_required():
    """顶层 title 仍必填：没有标题的蓝图基本不可用。"""
    with pytest.raises(Exception):
        Blueprint()


def test_blueprint_defaults_are_independent():
    """默认值不能用可变对象共享，否则实例之间会互相污染。"""
    a = Blueprint(title="A")
    b = Blueprint(title="B")
    a.chapter_outline.append(ChapterOutline(chapter_number=1))
    assert b.chapter_outline == [], "默认列表被共享了"
