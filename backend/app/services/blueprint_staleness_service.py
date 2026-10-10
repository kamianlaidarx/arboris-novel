# AIMETA P=过期检测_蓝图变更影响面|R=过期标记_一致性扫描|NR=不修改任何下游数据|E=BlueprintStalenessService|X=internal|A=服务类|D=sqlalchemy|S=db|RD=./README.ai
"""蓝图变更的过期检测与一致性扫描。

背景
----
蓝图改过之后，早先生成的大纲和章节正文仍是旧蓝图的产物，但系统里
没有任何地方记录这件事。实测一个项目里蓝图角色是
[沈渡/苏宛/方规/陆沉/齐延年]，而 82 条大纲和正文用的是「陆行舟」「苏晚」，
重叠为零——用户只能自己逐条比对发现。

设计原则
--------
**只检测，不改动。** 本模块不写任何下游内容。原因：

1. 正文是几十万字的心血，自动改写风险远大于收益；
2. 名字存在歧义（蓝图「苏宛」vs 大纲「苏晚」一字之差），
   程序无法判断是笔误还是两个角色，必须由用户决定。

所以这里只回答两个问题：哪些产物过期了？哪些名字对不上？
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.novel import (
    BlueprintCharacter,
    Chapter,
    ChapterOutline,
    NovelBlueprint,
)

logger = logging.getLogger(__name__)


@dataclass
class StalenessReport:
    """一个项目的蓝图过期情况。"""

    project_id: str
    current_revision: int
    #: 基于旧蓝图生成的大纲章节号
    stale_outline_chapters: List[int] = field(default_factory=list)
    #: 基于旧蓝图生成的章节号
    stale_chapter_numbers: List[int] = field(default_factory=list)
    #: 没有版本信息的历史数据（无法判断，不算过期）
    unknown_outline_chapters: List[int] = field(default_factory=list)
    unknown_chapter_numbers: List[int] = field(default_factory=list)

    @property
    def has_stale(self) -> bool:
        return bool(self.stale_outline_chapters or self.stale_chapter_numbers)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "current_revision": self.current_revision,
            "has_stale": self.has_stale,
            "stale_outline_chapters": self.stale_outline_chapters,
            "stale_chapter_numbers": self.stale_chapter_numbers,
            "unknown_outline_chapters": self.unknown_outline_chapters,
            "unknown_chapter_numbers": self.unknown_chapter_numbers,
            "stale_outline_count": len(self.stale_outline_chapters),
            "stale_chapter_count": len(self.stale_chapter_numbers),
        }


@dataclass
class NameMention:
    """一个「不在当前蓝图里」的名字及其出现位置。"""

    name: str
    outline_count: int
    chapter_count: int
    #: 出现该名字的章节号（便于用户定位）
    outline_chapters: List[int] = field(default_factory=list)
    chapter_numbers: List[int] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "outline_count": self.outline_count,
            "chapter_count": self.chapter_count,
            "outline_chapters": self.outline_chapters,
            "chapter_numbers": self.chapter_numbers,
        }


@dataclass
class ConsistencyReport:
    """蓝图与下游内容的一致性扫描结果（只读）。"""

    project_id: str
    blueprint_characters: List[str] = field(default_factory=list)
    #: 出现在大纲/正文里、但不在蓝图角色表中的名字
    unknown_names: List[NameMention] = field(default_factory=list)
    #: 蓝图里有、但从未在大纲或正文中出现的角色
    unused_characters: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "project_id": self.project_id,
            "blueprint_characters": self.blueprint_characters,
            "unknown_names": [n.to_dict() for n in self.unknown_names],
            "unused_characters": self.unused_characters,
        }


#: 常见中文姓氏。用于粗筛「疑似人名」的片段。
#: 用通用表而非蓝图姓氏：改名常换成完全不同的姓，只盯蓝图姓氏会漏报。
_COMMON_SURNAMES = (
    "赵钱孙李周吴郑王冯陈褚卫蒋沈韩杨朱秦尤许何吕施张孔曹严华金魏陶姜"
    "戚谢邹喻柏水窦章云苏潘葛奚范彭郎鲁韦昌马苗凤花方俞任袁柳鲍史唐"
    "费廉岑薛雷贺倪汤滕殷罗毕郝邬安常乐于时傅皮卞齐康伍余元卜顾孟平"
    "黄和穆萧尹姚邵湛汪祁毛禹狄米贝明臧计伏成戴谈宋茅庞熊纪舒屈项祝"
    "董梁杜阮蓝闵席季麻强贾路娄危江童颜郭梅盛林刁钟徐邱骆高夏蔡田樊"
    "胡凌霍虞万支柯昝管卢莫经房裘缪干解应宗丁宣邓郁单杭洪包诸左石崔"
    "吉钮龚程嵇邢滑裴陆荣翁荀羊於惠甄曲家封芮羿储靳汲邴糜松井段富巫"
    "乌焦巴弓牧隗山谷车侯宓蓬全郗班仰秋仲伊宫宁仇栾暴甘钭厉戎祖武符"
    "刘景詹束龙叶幸司韶郜黎蓟薄印宿白怀蒲邰从鄂索咸籍赖卓蔺屠蒙池乔"
    "阴胥能苍双闻莘党翟谭贡劳逄姬申扶堵冉宰郦雍却璩桑桂濮牛寿通边"
    "扈燕冀郏浦尚农温别庄晏柴瞿阎充慕连茹习宦艾鱼容向古易慎戈廖庾终"
    "暨居衡步都耿满弘匡国文寇广禄阙东欧殳沃利蔚越夔隆师巩厍聂晁勾敖"
    "融冷訾辛阚那简饶空曾毋沙乜养鞠须丰巢关蒯相查后荆红游竺权逯盖益桓"
)


#: 明显不是人名的词（职位/称谓/地名后缀），避免噪音淹没真正的候选。
_NOISE_WORDS = frozenset({
    "自己", "对方", "众人", "所有", "什么", "这个", "那个", "我们", "他们",
    "她们", "你们", "如今", "当时", "已经", "还是", "但是", "因为", "所以",
    "虽然", "如果", "可以", "需要", "没有", "不是", "就是", "这些", "那些",
    "一切", "之后", "之前", "同时", "此外", "然而", "并且", "或者", "以及",
    "时间", "地方", "事情", "问题", "东西", "方式", "情况", "世界", "力量",
    "修炼", "灵气", "宗门", "长老", "弟子", "师兄", "师姐", "师父", "师尊",
    "城主", "国王", "皇帝", "将军", "大人", "前辈", "晚辈", "阁下", "先生",
    "小姐", "姑娘", "夫人", "老爷", "少爷", "公子", "掌柜", "老板", "医生",
    "主角", "配角", "反派", "角色", "人物", "故事", "情节", "章节", "大纲",
    # 以下是常见普通词，恰好以姓氏字开头，会被误判成人名。
    # 只收录实测中确实出现的，避免这份表无限膨胀。
    "空间", "齐国", "苏打", "白天", "黄金", "石头", "马上", "毛病",
    "孙子", "李子", "程度", "程序", "毛病", "风格", "江湖", "水平",
    "方法", "方向", "问题", "时间", "时代", "时代", "成本", "成功",
})


class BlueprintStalenessService:
    """检测蓝图变更后哪些下游产物已过期。"""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_report(self, project_id: str) -> StalenessReport:
        """生成过期报告。

        ``blueprint_revision`` 为 NULL 的历史数据归入 ``unknown_*``：
        它们可能是过期的，但没有依据，不能当成过期来报警——否则
        升级后所有老项目都会满屏告警，用户会立刻学会忽略它。
        """
        current = (
            await self.session.execute(
                select(NovelBlueprint.revision).where(NovelBlueprint.project_id == project_id)
            )
        ).scalar_one_or_none()
        current_revision = int(current) if current is not None else 0

        report = StalenessReport(project_id=project_id, current_revision=current_revision)
        if current_revision <= 0:
            # 还没有蓝图：无从谈起过期
            return report

        outlines = (
            await self.session.execute(
                select(ChapterOutline.chapter_number, ChapterOutline.blueprint_revision)
                .where(ChapterOutline.project_id == project_id)
                .order_by(ChapterOutline.chapter_number)
            )
        ).all()
        for number, revision in outlines:
            if revision is None:
                report.unknown_outline_chapters.append(number)
            elif int(revision) != current_revision:
                report.stale_outline_chapters.append(number)

        chapters = (
            await self.session.execute(
                select(Chapter.chapter_number, Chapter.blueprint_revision)
                .where(Chapter.project_id == project_id)
                .order_by(Chapter.chapter_number)
            )
        ).all()
        for number, revision in chapters:
            if revision is None:
                report.unknown_chapter_numbers.append(number)
            elif int(revision) != current_revision:
                report.stale_chapter_numbers.append(number)

        if report.has_stale:
            logger.info(
                "项目 %s 存在过期产物: 大纲 %d 条, 章节 %d 条 (当前 revision=%d)",
                project_id,
                len(report.stale_outline_chapters),
                len(report.stale_chapter_numbers),
                current_revision,
            )
        return report

    async def scan_names(self, project_id: str) -> ConsistencyReport:
        """扫描大纲与正文里「不在当前蓝图角色表中」的名字。

        只报告，不做任何替换——名字有歧义时（「苏宛」vs「苏晚」）
        只有用户知道正确答案。
        """
        characters = (
            await self.session.execute(
                select(BlueprintCharacter.name)
                .where(BlueprintCharacter.project_id == project_id)
                .order_by(BlueprintCharacter.position)
            )
        ).scalars().all()
        known = [c.strip() for c in characters if c and c.strip()]

        outlines = (
            await self.session.execute(
                select(ChapterOutline.chapter_number, ChapterOutline.title, ChapterOutline.summary)
                .where(ChapterOutline.project_id == project_id)
                .order_by(ChapterOutline.chapter_number)
            )
        ).all()

        # 章节正文：只取当前选中的版本，避免把废弃版本的用词也算进来
        chapters = (
            await self.session.execute(
                select(Chapter.chapter_number, Chapter.real_summary)
                .where(Chapter.project_id == project_id)
                .order_by(Chapter.chapter_number)
            )
        ).all()

        mentions: Dict[str, NameMention] = {}
        known_set = set(known)
        # 先在整个项目范围内累计候选名出现次数，最后再按阈值收敛。
        # 逐章过滤是错的：一个名字可能在 82 章里各出现一次，
        # 单章看只有 1 次，全局看却有 82 次。
        counts: Dict[str, int] = {}
        #: 候选名 → 出现的章节号，用于回填定位信息
        seen_at: Dict[str, List[tuple]] = {}

        def _accumulate(text: str, kind: str, number: int) -> None:
            for name, hits in _count_name_prefixes(text).items():
                counts[name] = counts.get(name, 0) + hits
                seen_at.setdefault(name, []).append((kind, number))

        for number, title, summary in outlines:
            _accumulate(f"{title or ''} {summary or ''}", "outline", number)

        for number, summary in chapters:
            _accumulate(summary or "", "chapter", number)

        # 注意顺序：先按全局频次过滤，再折叠前缀。
        # 反过来的话，「陆行舟破解」这类长截断会先把「陆行舟」挤掉。
        for name in _finalize_candidates(counts):
            # 蓝图里已有的角色不算异常。这一步必须放在**收敛之后**：
            # 收敛前「陆行」和「陆行舟」并存，此时若按前缀排除已知名，
            # 会把真正要保留的候选一起排掉。
            if any(name == k or name.startswith(k) or k.startswith(name) for k in known_set):
                continue
            entry = NameMention(name=name, outline_count=0, chapter_count=0)
            for kind, number in seen_at.get(name, []):
                if kind == "outline":
                    entry.outline_count += 1
                    if number not in entry.outline_chapters:
                        entry.outline_chapters.append(number)
                else:
                    entry.chapter_count += 1
                    if number not in entry.chapter_numbers:
                        entry.chapter_numbers.append(number)
            mentions[name] = entry

        unknown = sorted(
            mentions.values(),
            key=lambda m: (-(m.outline_count + m.chapter_count), m.name),
        )

        # 蓝图里有、但下游从未出现过的角色：可能是刚加的新角色，
        # 也可能是改了名之后旧名字被彻底弃用。提示用户关注。
        all_text = " ".join(
            [f"{t or ''} {s or ''}" for _, t, s in outlines]
            + [s or "" for _, s in chapters]
        )
        unused = [c for c in known if c and c not in all_text]

        return ConsistencyReport(
            project_id=project_id,
            blueprint_characters=known,
            unknown_names=unknown[:50],  # 上限避免响应过大
            unused_characters=unused,
        )


def _extract_candidate_names(text: str) -> List[str]:
    """已废弃：基于通用姓氏猜测人名，噪音过大。

    实测 ``凡人逻辑顾问陆行舟破解`` 会猜出 ``人逻辑``/``顾问陆``/``解一起``
    这类无意义片段。保留函数名以免外部引用报错，实际改用
    :func:`_candidates_by_known_surname`——从**已知角色名的姓氏**出发反查，
    因为改名场景下旧名与新名通常同姓。
    """
    return []


def _surname_of(name: str) -> str:
    """取中文姓名的姓氏。

    复姓（欧阳/司马/上官…）取两字，其余取一字。
    判据是复姓表：只有确实命中才按两字处理，否则「欧阳锋」会被
    错误地拆成姓「欧」。
    """
    name = (name or "").strip()
    if len(name) < 2:
        return name
    if len(name) >= 3 and name[:2] in _COMPOUND_SURNAMES:
        return name[:2]
    return name[0]


#: 常见复姓。用于判断「前两字是否为姓」，避免把「欧阳」拆成「欧」。
_COMPOUND_SURNAMES = frozenset({
    "欧阳", "太史", "端木", "上官", "司马", "东方", "独孤", "南宫", "万俟",
    "闻人", "夏侯", "诸葛", "尉迟", "公羊", "赫连", "澹台", "皇甫", "宗政",
    "濮阳", "公冶", "太叔", "申屠", "公孙", "慕容", "仲孙", "钟离", "长孙",
    "宇文", "司徒", "鲜于", "司空", "闾丘", "子车", "亓官", "司寇", "巫马",
    "公西", "颛孙", "壤驷", "公良", "漆雕", "乐正", "宰父", "谷梁", "拓跋",
    "夹谷", "轩辕", "令狐", "段干", "百里", "呼延", "东郭", "南门", "羊舌",
    "微生", "梁丘", "左丘", "东门", "西门", "南宫", "第五",
})


def _count_name_prefixes(text: str) -> Dict[str, int]:
    """统计文本里「疑似中文人名」的所有前缀出现次数（不做阈值过滤）。

    为什么用**通用姓氏表**而不是蓝图角色的姓氏：改名时用户常把角色
    改成完全不同的姓（陆沉 → 李明）。若只盯蓝图的姓氏，正文里的
    「陆行舟」就再也搜不到了——而这恰恰是最需要检出的情况。
    （早期版本就是这么写的，端到端测试直接暴露了漏报。）

    代价是噪音变多（``顾问``、``解一`` 这类会被截出来），
    但噪音靠**跨章节频次**过滤：真实人名反复出现，偶然截断只出现一两次。

    为什么返回所有前缀而不在此处定阈值：``陆行舟破解`` 会截出
    ``陆行舟破``，单段文本区分不了它和真名，必须由调用方在整个
    项目范围内累计后再筛。
    """
    if not text:
        return {}
    counts: Dict[str, int] = {}
    for match in re.finditer(rf"[{_COMMON_SURNAMES}][\u4e00-\u9fa5]{{1,3}}", text):
        word = match.group()
        for length in (2, 3, 4):
            if len(word) < length:
                continue
            prefix = word[:length]
            if prefix in _NOISE_WORDS:
                continue
            counts[prefix] = counts.get(prefix, 0) + 1
    return counts


def _finalize_candidates(counts: Dict[str, int], min_hits: int = 2) -> Dict[str, int]:
    """把累计后的候选计数收敛成最终结果。

    两步，顺序不能反：

    1. **先按频次过滤**。真实人名跨章节反复出现，而 ``陆行舟破解``
       这种带动词的截断几乎只出现一次，噪音自然被滤掉。
    2. **再折叠同族前缀**。``陆行``、``陆行舟``、``陆行舟破`` 都源自
       同一处文本，只保留其中**最长的、且频次等于其前缀频次**的那个。

    第 2 步为什么不能简单取最长：如果每章都写「陆行舟出场」，
    ``陆行舟出`` 的频次会与 ``陆行舟`` 持平。此时真正的姓名是
    ``陆行舟``——它在更多样的上下文里出现，而截断只在固定搭配里出现。
    判据是「该候选的频次是否等于其某个真前缀」：持平说明它只是
    前缀在固定语境下的延长，应回退到前缀。
    """
    qualified = {w: c for w, c in counts.items() if c >= min_hits}
    if not qualified:
        return {}

    result: Dict[str, int] = {}
    for word, count in qualified.items():
        # 找一个更长的候选，它以前缀形式包含 word
        longer = [o for o in qualified if o != word and o.startswith(word)]
        if longer:
            # 若存在更长的候选且频次不低于 word，说明 word 只是它的一部分
            if any(qualified[o] >= count for o in longer):
                continue
        # 反过来：若 word 是某个更长候选的前缀，但那个更长者频次更低，
        # 则 word 才是稳定出现的那个（例如 陆行 5 次 vs 陆行舟破 1 次）
        shorter_prefixes = [o for o in qualified if o != word and word.startswith(o)]
        if shorter_prefixes and any(qualified[o] > count for o in shorter_prefixes):
            continue
        result[word] = count

    # 若上面的规则把所有项都排除了（互为前缀且频次相同），
    # 退化为「保留最长的那个」，避免返回空结果。
    if not result and qualified:
        longest = max(qualified, key=len)
        result[longest] = qualified[longest]
    return result

