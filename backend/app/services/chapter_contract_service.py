# AIMETA P=章间契约服务_提取与校验|R=契约提取_规则扫描_约束渲染|NR=不含API路由|E=ChapterContractService|X=internal|A=服务类|D=sqlalchemy|S=db|RD=./README.ai
"""
章间交接契约的提取、校验与渲染。

三段职责
--------
1. ``extract_and_save`` —— 定稿时从章节正文提取结构化契约（一次 LLM 调用）。
2. ``check_transition`` —— **确定性**规则扫描，找出相邻章之间的明显矛盾（零 LLM 成本）。
3. ``render_contract``  —— 渲染成注入下一章的 P0 块。

为什么规则扫描重要
------------------
jarvis-write 的审计明确指出，只看「与契约/摘要是否矛盾」的健康检查有个天然盲区：

    「如果它【一贯地错】，就抓不出来。」
    （典型例子：理科生背政治、高考天数写错）

但反过来，相邻章之间的**瞬时状态矛盾**恰恰是规则能精确抓到的：
前一章 `doing="刚睡着"` 且 `time_jump_hint="none"`，下一章
`doing="醒着发呆"` —— 这是确定性矛盾，不需要也不应该花 LLM 去判断。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.chapter_contract import ChapterContract
from ..utils.json_utils import remove_think_tags, unwrap_markdown_json

logger = logging.getLogger(__name__)

#: 契约尾部原文截取长度（供语感，不宜过长）。
PROSE_TAIL_LIMIT = 800

EXTRACT_CONTRACT_PROMPT = """\
以下是小说第 {chapter_number} 章的完整正文：

{chapter_text}

请提取**本章结束那一刻**的状态快照，用于保证下一章自然承接。

要求：
- 只依据正文明写的内容，不要推测。
- `doing` 写角色在章末【正在做/刚做完】的动作，越具体越好。
- `time_jump_hint` 判断本章结尾更像哪种推进：none（同一场景连续）、
  next_morning（次日清晨）、days_later（数日后）、scene_change（换场景但时间连续）。
- `open_threads` 只列本章结尾留下的、尚未解释的悬念。
- 严格输出 JSON，不要任何解释文字，不要 markdown 代码围栏。

输出格式：
{{
  "in_story_time": "故事内时间，如「第3天 深夜」；无法判断则填空字符串",
  "location": "章末场景地点",
  "scene_continues": false,
  "time_jump_hint": "none",
  "characters": [
    {{
      "name": "角色名",
      "location": "该角色章末所在地",
      "physical": "身体状态，如「左臂刀伤未愈」；正常则填「正常」",
      "emotional": "情绪状态",
      "doing": "章末正在做的动作",
      "knows": ["本章末该角色已知道的关键信息"],
      "unresolved_intent": "该角色已决定但尚未执行的事"
    }}
  ],
  "open_threads": ["章末未解释的悬念"]
}}
"""


@dataclass
class TransitionViolation:
    """一条相邻章之间的确定性矛盾。"""

    kind: str            # time_regression | action_contradiction | location_teleport | ...
    severity: str        # blocker | warning | info
    message: str
    prev_chapter: int
    curr_chapter: int
    evidence: Dict[str, Any] = field(default_factory=dict)


@dataclass
class TransitionCheckResult:
    violations: List[TransitionViolation] = field(default_factory=list)

    @property
    def has_blocker(self) -> bool:
        return any(v.severity == "blocker" for v in self.violations)

    @property
    def is_clean(self) -> bool:
        return not self.violations


class ChapterContractService:
    """章间契约的读写与校验。"""

    def __init__(self, session: AsyncSession, llm_service: Any):
        self.session = session
        self.llm_service = llm_service

    # ------------------------------------------------------------ 读

    async def get_contract(
        self, project_id: str, chapter_number: int
    ) -> Optional[ChapterContract]:
        result = await self.session.execute(
            select(ChapterContract).where(
                ChapterContract.project_id == project_id,
                ChapterContract.chapter_number == chapter_number,
            )
        )
        return result.scalars().first()

    async def get_previous_contract(
        self, project_id: str, chapter_number: int
    ) -> Optional[ChapterContract]:
        """取严格早于 chapter_number 的最近一份契约。"""
        result = await self.session.execute(
            select(ChapterContract)
            .where(
                ChapterContract.project_id == project_id,
                ChapterContract.chapter_number < chapter_number,
            )
            .order_by(ChapterContract.chapter_number.desc())
            .limit(1)
        )
        return result.scalars().first()

    # ------------------------------------------------------------ 写

    async def extract_and_save(
        self,
        *,
        project_id: str,
        chapter_number: int,
        chapter_text: str,
        user_id: int,
    ) -> Optional[ChapterContract]:
        """从正文提取契约并落库。

        已有手工契约时不覆盖（人工编辑优先）。
        """
        existing = await self.get_contract(project_id, chapter_number)
        if existing is not None and existing.extracted_by == "manual":
            logger.info("第 %s 章契约是手工录入，跳过自动提取", chapter_number)
            return existing

        prompt = EXTRACT_CONTRACT_PROMPT.format(
            chapter_number=chapter_number,
            chapter_text=chapter_text,
        )
        try:
            response = await self.llm_service.generate(
                prompt=prompt, user_id=user_id, max_tokens=2000, temperature=0.2
            )
        except Exception as exc:
            logger.error("提取章间契约失败: chapter=%s error=%s", chapter_number, exc)
            return None

        payload = _parse_contract_payload(response)
        if payload is None:
            logger.warning("章间契约无法解析为 JSON，跳过: chapter=%s", chapter_number)
            return None

        contract = existing or ChapterContract(
            project_id=project_id, chapter_number=chapter_number
        )
        contract.in_story_time = (payload.get("in_story_time") or "")[:128] or None
        contract.location = (payload.get("location") or "")[:255] or None
        contract.scene_continues = bool(payload.get("scene_continues", False))
        contract.time_jump_hint = (payload.get("time_jump_hint") or "")[:64] or None
        contract.characters = payload.get("characters") or None
        contract.open_threads = payload.get("open_threads") or None
        contract.prose_tail = (chapter_text or "").strip()[-PROSE_TAIL_LIMIT:] or None
        contract.extracted_by = "llm"

        if existing is None:
            self.session.add(contract)
        await self.session.flush()
        return contract

    # ------------------------------------------------------ 规则扫描

    async def check_transition(
        self, project_id: str, prev_chapter: int, curr_chapter: int
    ) -> TransitionCheckResult:
        """对相邻两章做确定性一致性检查（零 LLM 成本）。

        只检查契约里**明写**的字段，不做语义推断——宁可漏报也不误报。
        """
        prev = await self.get_contract(project_id, prev_chapter)
        curr = await self.get_contract(project_id, curr_chapter)
        result = TransitionCheckResult()

        if prev is None or curr is None:
            return result

        prev_chars = _chars_by_name(prev.characters)
        curr_chars = _chars_by_name(curr.characters)

        # 1) 场景连续性矛盾：上一章刚睡着/刚昏迷，本章无时间跳跃却已醒着活动
        if not curr.scene_continues and _is_none_jump(curr.time_jump_hint):
            for name, pc in prev_chars.items():
                cc = curr_chars.get(name)
                if cc is None:
                    continue
                if _implies_unconscious(pc.get("doing")) and _implies_active(cc.get("doing")):
                    result.violations.append(
                        TransitionViolation(
                            kind="action_contradiction",
                            severity="blocker",
                            message=(
                                f"{name} 在第{prev_chapter}章末处于失去意识/睡眠状态，"
                                f"第{curr_chapter}章开头却已清醒活动，且未标注时间跳跃"
                            ),
                            prev_chapter=prev_chapter,
                            curr_chapter=curr_chapter,
                            evidence={"prev_doing": pc.get("doing"), "curr_doing": cc.get("doing")},
                        )
                    )

        # 2) 地点瞬移：同一角色换了地点，但既无时间跳跃也非场景连续
        if not curr.scene_continues and _is_none_jump(curr.time_jump_hint):
            for name, pc in prev_chars.items():
                cc = curr_chars.get(name)
                if cc is None:
                    continue
                ploc = _norm(pc.get("location"))
                cloc = _norm(cc.get("location"))
                if ploc and cloc and ploc != cloc:
                    result.violations.append(
                        TransitionViolation(
                            kind="location_teleport",
                            severity="warning",
                            message=(
                                f"{name} 从「{pc.get('location')}」直接出现在"
                                f"「{cc.get('location')}」，但未标注时间跳跃"
                            ),
                            prev_chapter=prev_chapter,
                            curr_chapter=curr_chapter,
                            evidence={"prev": pc.get("location"), "curr": cc.get("location")},
                        )
                    )

        # 3) 伤势倒退：上一章未愈，本章同一角色却无治疗描写地恢复
        for name, pc in prev_chars.items():
            cc = curr_chars.get(name)
            if cc is None:
                continue
            prev_phys = _norm(pc.get("physical"))
            curr_phys = _norm(cc.get("physical"))
            if not prev_phys or not curr_phys:
                continue
            injured_prev = prev_phys not in {"正常", "健康", ""}
            healthy_curr = curr_phys in {"正常", "健康"}
            if injured_prev and healthy_curr:
                result.violations.append(
                    TransitionViolation(
                        kind="injury_recovered_unexplained",
                        severity="warning",
                        message=(
                            f"{name} 第{prev_chapter}章末身体状态为「{pc.get('physical')}」，"
                            f"第{curr_chapter}章初已恢复；若正文未写明治疗过程则属矛盾"
                        ),
                        prev_chapter=prev_chapter,
                        curr_chapter=curr_chapter,
                        evidence={"prev": pc.get("physical"), "curr": cc.get("physical")},
                    )
                )

        # 4) 时间倒流：以解析得出的数字做粗判，解析不出就跳过
        prev_day = _extract_day(prev.in_story_time)
        curr_day = _extract_day(curr.in_story_time)
        if prev_day is not None and curr_day is not None and curr_day < prev_day:
            result.violations.append(
                TransitionViolation(
                    kind="time_regression",
                    severity="blocker",
                    message=(
                        f"故事时间倒流：第{prev_chapter}章末为「{prev.in_story_time}」，"
                        f"第{curr_chapter}章初为「{curr.in_story_time}」"
                    ),
                    prev_chapter=prev_chapter,
                    curr_chapter=curr_chapter,
                    evidence={"prev": prev.in_story_time, "curr": curr.in_story_time},
                )
            )

        return result

    # ------------------------------------------------------ 渲染

    async def render_contract(
        self, project_id: str, chapter_number: int
    ) -> Optional[str]:
        """把上一章契约渲染成注入下一章的 P0 块。"""
        prev = await self.get_previous_contract(project_id, chapter_number)
        if prev is None:
            return None
        return render_contract_block(prev)


def render_contract_block(contract: ChapterContract) -> str:
    """渲染上一章结束时的状态。"""
    lines: List[str] = [
        f"上一章（第{contract.chapter_number}章）结束时的状态——"
        "本章必须自然承接，不得与之矛盾："
    ]
    if contract.in_story_time:
        lines.append(f"  时间：{contract.in_story_time}")
    if contract.location:
        lines.append(f"  地点：{contract.location}")
    if contract.time_jump_hint and contract.time_jump_hint != "none":
        lines.append(f"  时间推进：{contract.time_jump_hint}")

    for char in contract.characters or []:
        if not isinstance(char, dict):
            continue
        name = char.get("name")
        if not name:
            continue
        bits = []
        if char.get("location"):
            bits.append(f"在{char['location']}")
        if char.get("doing"):
            bits.append(f"{char['doing']}")
        if char.get("physical") and char["physical"] not in ("正常", "健康"):
            bits.append(f"身体：{char['physical']}")
        if char.get("emotional"):
            bits.append(f"情绪：{char['emotional']}")
        lines.append(f"  {name}：" + "；".join(bits))
        if char.get("unresolved_intent"):
            lines.append(f"    尚未执行：{char['unresolved_intent']}")

    if contract.open_threads:
        threads = [str(t) for t in contract.open_threads if t]
        if threads:
            lines.append("  悬置未解：" + "；".join(threads))

    return "\n".join(lines)


# ---------------------------------------------------------------- 辅助

def _parse_contract_payload(text: Optional[str]) -> Optional[Dict[str, Any]]:
    """解析契约 JSON，容忍 markdown 围栏与思考标签。"""
    if not text or not text.strip():
        return None
    candidate = unwrap_markdown_json(remove_think_tags(text).strip())
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        data = json.loads(candidate[start : end + 1])
    except (json.JSONDecodeError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _chars_by_name(characters: Any) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    if not isinstance(characters, list):
        return out
    for item in characters:
        if isinstance(item, dict) and item.get("name"):
            out[str(item["name"])] = item
    return out


def _norm(value: Any) -> str:
    return str(value or "").strip()


def _is_none_jump(hint: Optional[str]) -> bool:
    """没有时间跳跃（或未标注）——此时场景必须严格承接。"""
    text = _norm(hint).lower()
    return text in ("", "none")


_SLEEP_MARKERS = ("睡着", "入睡", "昏迷", "昏过去", "失去意识", "沉睡", "睡了", "晕倒", "晕了")
_ACTIVE_MARKERS = ("醒", "睁开眼", "起身", "走动", "出发", "走向", "站在", "说", "喊", "战", "跑")


def _implies_unconscious(doing: Any) -> bool:
    text = _norm(doing)
    return any(m in text for m in _SLEEP_MARKERS)


def _implies_active(doing: Any) -> bool:
    text = _norm(doing)
    return any(m in text for m in _ACTIVE_MARKERS)


def _extract_day(text: Optional[str]) -> Optional[int]:
    """从「第3天 深夜」这类文本里抽出天数；抽不出返回 None。"""
    import re

    if not text:
        return None
    match = re.search(r"第\s*(\d+)\s*天", str(text))
    if match:
        return int(match.group(1))
    match = re.search(r"Day\s*(\d+)", str(text), re.IGNORECASE)
    if match:
        return int(match.group(1))
    return None
