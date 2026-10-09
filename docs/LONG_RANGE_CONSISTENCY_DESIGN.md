# Arboris 长篇一致性架构方案

> 针对「字数大 → 上下文丢失 → 与前期章节对不上」这一核心问题。
> 基于对 Arboris 现有代码的逐行核查 + 22 个外部一手来源（论文 / 开源实现 / 工程笔记）。
> 配套研究材料：`research/long-range-consistency-report.md`（56 条引用）。

---

## 0. 结论先行

**问题不是「上下文窗口不够」，而是「叙事状态没有被结构化外置」。**

三条独立证据指向同一结论：

1. **CFPG (arXiv 2601.07033)** 发现 LLM 会「在必要上下文已经存在的情况下，仍然不让契诃夫之枪开火」。说明这是**表示问题**，不是窗口问题。
2. **FactTrack (NAACL 2025)** 用 7B 小模型 + 正确的时间区间数据结构，做到与裸 GPT-4 基线相当的矛盾检测水平。**数据结构的权重超过模型选择。**
3. **Chroma Context Rot (2025, 18 个模型)** 实测：上下文越长退化越不均匀；而且**结构连贯的 haystack 检索效果反而比打乱的更差**。把整本书塞进长窗口是被实证否定的做法。

### Arboris 的实际病根（已逐行核实）

系统里**已经存在正确的结构化数据模型，但生产路径完全绕开了它**：

| 系统 | 实现 | 存储 | 生产是否运行 |
|---|---|---|---|
| **结构化**：`MemoryLayerService.update_character_state()` | 完整正确 | `CharacterState` 的 `location`/`health_status`/`injuries`/`inventory` 等**独立列**，按 `character_name` + `chapter_number` 建快照 | ❌ **从不运行** |
| **自由文本**：`FinalizeService._update_character_state()` | 每章让 LLM 重写整棵文本树 | `character_id=0`、`character_name="__all__"`，全部塞进 `extra.raw_state_text` | ✅ **每章定稿都跑** |

关键代码（`backend/app/services/finalize_service.py:379-384`）：

```python
state = CharacterState(
    project_id=project_id,
    character_id=0,          # 通用记录
    character_name="__all__", # 所有角色挤在一行
    chapter_number=chapter_number,
    extra={"raw_state_text": state_text}   # 结构化列全部留空
)
```

而读取侧也在读文本（`knowledge_retrieval_service.py:613-617`）：

```python
CharacterState.character_name == "__all__"
...
return states.extra.get("raw_state_text")
```

**这一切换之所以没被发现的第二个原因**：前端从不发送 `preset`，后端默认为 `"basic"`，而 `basic` 分支里：

```python
if preset == "ultimate":
    config.enable_memory = True     # ← 结构化记忆只在这一支开启
```

即 `enable_memory=False`、`enable_foreshadowing=False`、`enable_consistency=False`。**三大一致性能力在生产默认全关。**

---

## 1. 现状盘点：一致性相关资产

好消息是**大部分零件都在**，缺的是接线和闭环：

| 资产 | 位置 | 状态 |
|---|---|---|
| `ProjectMemory.global_summary` | `models/project_memory.py:47` | ✅ 每章更新，但 2000 字上限，N 章内容反复压缩（300:1 有损） |
| `ProjectMemory.plot_arcs` | `models/project_memory.py:52` | ✅ 结构已定义（未回收钩子/主线矛盾/角色弧），但**无版本比较**，`version` 字段是装饰性的 |
| `CharacterState` 结构化列 | `models/memory_layer.py:34-70` | ✅ schema 完整，❌ 被 `__all__` blob 绕过 |
| `ChapterSnapshot` | `models/project_memory.py:70+` | ✅ 每章快照，但 `global_summary` 被 O(n) 重复存储 |
| `Foreshadowing` 四态模型 | `models/foreshadowing.py:35-57` | ✅ 已有 `planted/developing/revealed/abandoned` + `target_reveal_chapter` + `importance` + 伏笔链 |
| `ConsistencyService` | `services/consistency_service.py` | ✅ 有 check→auto_fix 闭环，❌ 默认关闭，且只喂 `global_summary` |
| `CharacterKnowledgeManager` | `services/character_knowledge_manager.py` | ⚠️ 设计精良（`is_known`/`acquired_chapter`/`acquisition_method`），但**纯内存、无持久化、仅被坏测试引用** |
| 定稿写回通道 | `FinalizeService` 5 个 `_update_*` | ✅ 通道畅通，但内容是自由文本 |

---

## 2. 目标架构

```
┌──────────────── 每章生成前（Pre-flight + 组装）─────────────────┐
│  1. 章间交接契约 (chapter_contract)  ← 上一章结构化的"瞬时状态"    │
│  2. 时序事实库 (facts)               ← valid_from/valid_until 过滤 │
│  3. 线程账本 (foreshadowing + trigger) ← 到期/超期提醒             │
│  4. 滚动摘要 (global_summary)        ← 语感与宏观走向              │
│  5. 上一章结尾原文                    ← 只供语感，不供事实          │
└──────────────────────────────────────────────────────────────┘
                              ↓ 生成
┌──────────────── 生成后（Gate，有牙齿）────────────────────────┐
│  规则扫描（确定性，0 成本）→ LLM 裁判（需引用原文证据）           │
│  blocker → 自动修订 N 次 → 仍不过 → quarantine（不进 canon）      │
└──────────────────────────────────────────────────────────────┘
                              ↓ 通过后才
┌──────────────── 写回（Extraction）────────────────────────────┐
│  结构化提取：新事实 / 事实失效 / 线程状态变更 / 实体新增           │
│  ⚠️ 只有通过的章节才更新状态；草稿永不进入 canon                  │
└──────────────────────────────────────────────────────────────┘
```

**核心纪律（两个独立来源一致强调）：草稿不更新 canon。**
- ConWriter: *"If no candidate passes verification within the retry budget, the scene is rejected and does not update the dynamic memory."*
- novel-studio-ai: *"Drafts do not update canon. Only accepted chapters write summaries, character states, graph triples, timeline events, and memory chunks."*

Arboris 违反此纪律的方式：定稿是 `asyncio.create_task` 的 fire-and-forget（`writer.py:329-346`），失败只写日志；`FinalizeService` 内部 `except Exception` 吞掉后 `commit()` 已经部分执行。

---

## 3. 数据模型设计

### 3.1 `narrative_facts` —— 时序事实库（最高价值）

来自 FactTrack 的「方向性原子事实 + 有效期区间」。

```sql
CREATE TABLE narrative_facts (
    id              BIGINT PRIMARY KEY AUTO_INCREMENT,
    project_id      CHAR(36) NOT NULL,
    entity_id       VARCHAR(128) NOT NULL,   -- 角色名/地点/派系
    entity_type     VARCHAR(32)  NOT NULL,   -- character|location|faction|item
    fact_type       VARCHAR(32)  NOT NULL,   -- state|ability|possession|relationship|location
    content         VARCHAR(512) NOT NULL,   -- "左臂截肢"
    valid_from      INT NOT NULL,            -- 生效章节
    valid_until     INT NULL,                -- NULL = 仍然有效
    importance      VARCHAR(16) NOT NULL DEFAULT 'major', -- critical|major|minor
    source_chapter  INT NOT NULL,
    extracted_by    VARCHAR(32) NOT NULL,    -- 'llm' | 'manual'
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_facts_query (project_id, entity_id, valid_from, valid_until),
    INDEX idx_facts_validity (project_id, valid_until)
);
```

**查询即约束**（这是整个方案的核心操作）：

```sql
SELECT * FROM narrative_facts
WHERE project_id = :pid
  AND entity_id IN (:involved_entities)
  AND valid_from <= :N
  AND (valid_until IS NULL OR valid_until >= :N);
```

工作示例：第 5 章受伤 → `valid_from=5, valid_until=11`；第 12 章痊愈 → 新事实 `valid_from=12, valid_until=NULL`。查第 8 章得「受伤」，查第 13 章得「已痊愈」。**只要生成时遵守约束块，矛盾在结构上不可能发生。**

### 3.2 ⚠️ 失效判定的安全红线

**必须结构化限定候选集。** Synapse 的生产事故审计（Graphiti/Zep + Neo4j，11 个项目）：

> **70% 被自动失效的事实仍然是真实的**（28/40 人工标注，95% CI [54.6%, 81.9%]），且**完全静默**——无报错、无告警、写入返回成功。
> 根因：失效候选搜索用了空的 `SearchFilters()`，候选集是**全图所有边**按语义相似度排序，不要求与新事实共享实体；然后交给**一次 LLM 调用返回裸索引列表**（无理由、无置信度）就提交。

| 规则 | 误删真事实 | 保留过期事实 |
|---|---|---|
| 无防护（Graphiti 原样） | **28** | 0 |
| 仅结构化测试 | 13 | 5 |
| 仅词法测试 | 0 | 11 |
| **结构化 AND 词法** | **0** | 11 |
| 完全禁用失效 | 0 | 12 |

**结论：** 失效判定只能限定在「**同一实体 + 同一 fact_type**」范围内，且必须要求新事实更**具体**（narrower）才允许把旧的置为失效。绝不把无界候选集交给 LLM 裁判。

**另外：默认「只增不改」。** 新事实一律追加、旧的 `valid_until` 保持不变，由人类在界面上确认后才真正失效。宁可保留过期事实（上表 11–12 列），也不要静默删真事实。

### 3.3 `chapter_contracts` —— 章间交接契约

解决「上一章结尾睡着了，下一章开头在发呆」这类**瞬时状态**问题。事实库记录跨章持久事实，但记不了"章节结束那一刻他在哪"。

```sql
CREATE TABLE chapter_contracts (
    id                BIGINT PRIMARY KEY AUTO_INCREMENT,
    project_id        CHAR(36) NOT NULL,
    chapter_number    INT NOT NULL,
    in_story_time     VARCHAR(128),      -- "第3天 深夜"
    location          VARCHAR(255),
    scene_continues   BOOLEAN DEFAULT FALSE,
    time_jump_hint    VARCHAR(64),       -- none|next_morning|days_later
    characters        JSON,   -- [{name,location,physical,emotional,doing,knows[],unresolved_intent}]
    open_threads      JSON,   -- 本章末未解释的悬念
    prose_tail        TEXT,   -- 结尾原文（供语感，非事实源）
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uq_contract (project_id, chapter_number)
);
```

**两个用途：**
1. **生成前注入**，与上一章结尾原文**并列**——「原文供语感，契约供事实」。这直接化解了 Chroma 的悖论（连贯散文反而干扰检索）：把**散文**和**结构化事实**拆到不同 prompt 区块。
2. **Gate 比对** —— 规则优先，LLM 只处理歧义：
   - `doing="刚睡着"` + `time_jump_hint="none"`，下一章 `doing="醒着发呆"` → 矛盾
   - 前一章 `location="破庙"`，下一章 `location="渡口"` 且无时间跳跃 → 矛盾
   - `physical="左臂刀伤未愈"`，下一章持剑激战且无治疗描写 → 矛盾

### 3.4 线程账本增强 —— 补 `trigger` 谓词

Arboris 的 `Foreshadowing` 已有四态 + `target_reveal_chapter`。**缺的是 CFPG 的触发谓词**：

```jsonc
{
  "id": "cg_0042",
  "foreshadow": "壁炉上生锈的铁钥匙",          // content
  "trigger":   "主角被困地窖 AND 已搜索过壁炉台", // ← 新增：可匹配的谓词
  "payoff":    "钥匙打开地窖门",
  "planted_chapter": 3,
  "earliest_payoff_chapter": 25,   // ← 新增：不能早于
  "expected_payoff_chapter": 40,   // 已有 target_reveal_chapter
  "status": "planted",
  "required_hints": ["cg_0011", "cg_0027"]  // ← 新增：前置铺垫
}
```

**为什么 `trigger` 关键**：它把「我有没有记得这把枪」从**记忆问题**变成**对着章节大纲做模式匹配**——一个确定性、可测试的操作。

**为什么 `earliest_payoff_chapter` 关键**：没有它，一个被激励"尽快回收伏笔"的系统会在第 6 章解掉第 40 章的谜。有效窗口是 `[earliest, expected]`。

**调度规则**：
```
if status in (planted, reinforced)
   and expected_payoff_chapter <= current_chapter + 2:
      注入软提醒："以下伏笔即将到期：…"
```
Noveling 的双信号值得抄：`recency`（刚埋下就被弃）与 `unresolved_lifespan`（开了太久）**分别**触发——单个"距回收章数"计数器会把这两种情况混为一谈。

### 3.5 读者知识 vs 角色知识

`knowledge_states` 表：`fact_id`、`knower`（`"reader"` 或角色名）、`known_from_chapter`、`knower_state ∈ known|suspected|blind`。

用途：读者第 3 章知道真相，角色 B 第 10 章才知道 → 生成时强制「此角色不得谈论他尚不知道的事」。

> **诚实标注**：jarvis-write 自己的审计承认这张表是 **write-only**——生成 prompt 并未注入「此角色还不知道什么」，知识隔离没有闭环。**数据结构有价值，闭环无人验证。** Arboris 实现时应把它作为二期目标，不要指望一期见效。

---

## 4. 生成流程改造

### 4.1 上下文预算（按优先级，而非按拼接顺序）

word-compiler 的「免疫/优先级」模型是找到的最具体方案：**在 schema 定义期就决定哪些约束不可丢弃，然后用 lint 机械强制**（`IMMUNE_REMOVED` 检查，severity=error）。

建议 Arboris 分三轮：

| 轮次 | 内容 | 可否裁剪 |
|---|---|---|
| **P0 不可裁** | 当前章节目标、POV 规则、禁止角色、**在期事实约束块**、章间契约 | ❌ 永不裁剪，超限则报错 |
| P1 | 到期伏笔提醒、角色结构化状态 | 超限时压缩为摘要 |
| P2 | RAG 检索片段、最近章节摘要、global_summary | 超限时按段数裁剪 |

**关键约束**：需要被**精确遵守**的状态（事实、契约、POV）必须是**短小的非叙事结构化块**，不能是长篇散文。Chroma 的实测结论支持这一点。

### 4.2 单章 LLM 调用序列（含成本）

```
1. Pre-flight（可选，warn-only）   蓝图 vs 上一章契约      ~1 call
2. 章导演脚本（已有）                                      ~1 call
3. 正文生成 × version_count（已有）                        2 calls
4. Gate：规则扫描（0 call）→ LLM 裁判（需引用原文）           ~1 call
5. 若不通过 → 定向修订（≤N 次）                            ~1-3 calls
6. 写回提取：新事实/失效/线程变更/契约                       ~1 call
```
相比现状（~4-6 calls/章）增加约 **2-3 次小输出调用**。jarvis-write 认为成本可接受（都是低温小 JSON 输出）。**这个成本必须实测，不要照抄。**

### 4.3 Gate 的四阶段检测（ConStory-Checker 方案）

1. **分类引导提取** —— 用**分类专用** prompt 扫描，提取「易矛盾片段」而非"找出所有错误"
2. **成对比较** —— 片段两两比对，判定 `Consistent`/`Contradictory`（降低假阳性）
3. **证据链** —— 每条矛盾必须给出：**理由** + **原文引用（含字符位置）** + **结论（错误类型）**
4. **JSON 报告** —— 所有引用锚定到字符级偏移

**「必须引用证据」是所有可信系统的共同要求**：ainovel-cli 的七维评审每一项都要引用原文；MuMuAINovel 的固定三列报告是「问题/证据段落/修改建议」。

**为什么证据是硬要求**：FABLES (COLM 2024, 3,158 条人工标注) 发现**没有任何 LLM 自动评分器与人类标注强相关**；Synapse 用两个不同模型家族的裁判，Cohen's κ 仅 **0.393**，而且**把评分细则写得更严谨之后一致性反而下降到 0.348**。

### 4.4 Quarantine —— 防止污染扩散

**最容易被忽略但极重要**：不通过的章节若照常写回，bug 就变成 canon。jarvis-write 审计发现：*"矛盾文本仍被 `extract_and_apply` 提取进 story bible，等于把污染原地固化。"*

三级处置：
- **blocker** → 自动修订（复用修订循环，有次数上限）→ 重新过 Gate；超限则**落库为 `quarantined`**，且：**不跑提取、不更新滚动摘要、暂停连续生成队列**
- **major** → 落库 `pending_review`，人类裁决
- **minor** → 落库 `pending_review`，仅作信息

---

## 5. 检索设计

### 5.1 明确建议：不要为章节正文建向量库

两个独立来源反对：
- **Chroma**：18 个模型实测，**结构连贯的 haystack 检索效果比打乱的更差**（作者明确标为未解释）
- **jarvis-write 公开回滚**：*"向量库/分桶加权记忆已于 2026-07 移除（embedding 来源长期不可用、且长上下文已使其非必需）。长程一致性现由「时序故事圣经 + 滚动摘要」承担。全部存在 SQL 里，无独立向量库。"*

**Arboris 的具体情况更糟**：现有向量检索是**暴力全表扫描**（`vector_store_service.py:172-178` 在 `vector_distance_cosine` 缺失时回退到 Python 逐条算余弦，而该函数是 libsql 专有 → **本地部署下这个回退就是默认路径**），而且存在**两套 chunk ID 方案写同一张表**导致重复索引。在这个基础上投入是浪费。

### 5.2 如果确实要检索：用迭代式而非 top-k

ComoRAG (AAAI 2026) 的诊断直指要害：*"传统 RAG 的**无状态、单步检索**过程，往往忽略了长程上下文中相互关联关系的动态性。"*

```
memory_pool = []
query = 从当前章计划 + 角色名派生查询
while not answerable(query, memory_pool) and rounds < MAX:
    memory_pool += retrieve(query)                    # 混合词法+向量
    query = generate_probing_query(gap(memory_pool))  # 针对缺口生成新查询
answer = reason(query, memory_pool)
```
200K+ token 上相对最强基线 **最高 11% 相对提升**，优势集中在**需要全局理解**的查询上。

**但注意**：jarvis-write 在已有时序圣经+契约+滚动摘要三条注入通道后，**明确拒绝**再加规则检索——*"规则检索只会让 prompt 膨胀、增加噪声。"* 这是罕见的"反检索"论证，值得认真对待。

---

## 6. 评估体系（否则无法知道是否变好）

### 6.1 指标

- **CED**（Consistency Error Density）= `错误数 / (字数/10000)`。*"简单按故事计错误数会不公平地惩罚生成更长输出的模型。"*
- **GRR**（Group Relative Rank）—— 同 prompt 组内排名取平均。*"某些 prompt 天然会引发更多错误"*，原始 CED 会混淆模型质量与 prompt 难度。

**必须两个都用**，因为单个指标会系统性误导。

### 6.2 跨边界维度（把"连续性"变成可测量）

word-compiler 的 LLM 裁判里有两个**成对/跨边界**维度，而非单文本质量分：

| 维度 | 量程 | 通过线 | 评估对象 |
|---|---|---|---|
| `continuity` | 1–10 | ≥7 | **第 N+1 章开头是否自然承接第 N 章结尾** |
| `tone_whiplash` | 1–10 | ≥7 | **跨场景转换的语气连续性** |

**这是把"连续性"操作化为可测量量的方法。** 其余维度（`voice_consistency`、`subtext_adherence`、`scene_goal`）都是单文本评分，价值不同。

### 6.3 用 ConStory-Bench 的 5 类 19 子类做测试清单

| 类别 | 子类 |
|---|---|
| 时间线与情节逻辑 | 绝对时间矛盾、时长矛盾、同时性矛盾、无因之果、因果违规、**被遗弃的情节点** |
| 角色一致性 | 记忆矛盾、知识矛盾、能力波动、**遗忘已有能力** |
| 世界观设定 | 核心规则违反、社会规范违反、地理矛盾 |
| 事实与细节 | 外貌不符、命名混淆、数量不符 |
| 叙事与风格 | 视角混乱、语气不一致、风格漂移 |

注意「被遗弃的情节点」和「遗忘已有能力」是一等类别。

### 6.4 已知的位置规律（可用于定向检查）

- 错误**集中在叙事中段**，不是结尾（ConStory-Bench 扩展位置分析）
- 错误**出现在 token 级熵更高的文本段**（可作预测信号）
- **Generation 类任务的 CED 持续高于 Continuation/Expansion/Completion** —— *"没有前文的开放式创作一致性挑战最大"*

→ 可把 O(全书) 的检查降为**定向检查**：中段 + 高熵段 + 从零生成的章节优先。

### 6.5 实操提醒

- `--rollouts=N`：随机生成器下单次评估是噪声
- CI 分层：PR 跑确定性检查 + mock 裁判（0 成本）；夜间跑 5 次真模型
- **人工裁决是 ground truth**，间隔性做标注样本审计

> **必须内化的警告**："一个你没用标注验证过的防线，只是装饰。"（Synapse 作者，在发现自己的第一次验证是循环论证、第二次显示新增项毫无作用、第三次显示"明显改进"反而严格变差之后）

---

## 7. 分阶段落地路线

按「修复成本 ÷ 收益」排序。**一至三期改动都很小且可独立验证。**

### 一期：止血（约 1–2 天，无新表）

1. **把 `FinalizeService` 切到结构化写回** —— 调用已存在但闲置的 `MemoryLayerService.update_character_state()`，写入 `CharacterState` 的真实列，而非 `__all__` blob。**这是全方案最高性价比的一步**：schema 已存在、服务已实现，只需要改调用点和读取点。
2. **统一读取侧** —— `knowledge_retrieval_service.py:613` 与 `consistency_service.py:383` 改为读结构化列。
3. **`basic` preset 打开 `enable_foreshadowing` 与 `enable_consistency`** —— 现在生产默认全关。
4. **去掉 fire-and-forget** —— 定稿失败必须可见（至少状态置为 `finalize_failed`，前端可见）。
5. **修 SQLite PRAGMA**（WAL / busy_timeout / foreign_keys）—— 3 行，同时解决孤儿行与锁冲突。

**验证方式**：跑 3 章，直接查 `character_states` 表，确认每角色每章一行且 `location`/`health_status` 有值。

### 二期：时序事实库（约 3–5 天）

6. 建 `narrative_facts` 表 + 查询函数
7. 定稿提取：新事实、事实失效（**严格限定同实体 + 同 fact_type + 更具体**）
8. 生成前注入「在期事实约束块」到 P0 区
9. **默认只增不改**，失效需人工确认

**验证方式**：构造「第 5 章受伤 → 第 8 章问询 → 第 12 章痊愈 → 第 13 章问询」，检查约束块内容随章节正确切换。

### 三期：章间契约 + 线程 trigger（约 3–5 天）

10. `chapter_contracts` 表 + 提取 + 注入
11. Gate 规则层（确定性，0 LLM 成本）
12. `Foreshadowing` 加 `trigger` / `earliest_payoff_chapter` / `required_hints`
13. 到期提醒接入生成流程
14. Quarantine 机制

### 四期：Gate 与评估（约 1 周）

15. ConStory-Checker 四阶段 Gate（需引用原文证据）
16. 定向修订循环（≤N 次）
17. CED/GRR 评估脚本 + 跨边界 LLM 裁判
18. 弧段边界离线诊断（时间线断层、消失角色、停滞线程、缺失契约）
19. 人工 `world_rules` 看板 + 全书规则扫描

---

## 8. 诚实的边界

**证据最薄弱的地方恰好是最需要的地方：**

1. **没有任何人在 100+ 章规模上做过受控评估。** ConStory-Bench 目标是 8,000–10,000 词；FABLES 是书长**摘要**而非生成。所有"写到后面会崩"的说法都来自实践者经验，不是测量结果。
2. **没有公开评估过任何伏笔追踪系统。** NovelClaw、Noveling、MuMuAINovel、jarvis-write 都上线了，都没发布错误率下降数据。**这是整个领域最大的证据缺口，也正是你最关心的部分。**
3. **Agent 化没有买到一致性。** ConStory-Bench 实测：agent-enhanced (0.674) ≈ capability-enhanced (0.669) ≈ 裸 prompt (0.71)，统计上无差异。**收益来自数据结构和门禁，不是更多 agent。** 这对 Arboris 是个警告——不要再去建第四套写作流程。
4. **即使最强模型也不完美**：GPT-5-Reasoning 的 CED 是 0.113，即 1M 词约 11+ 个被检出错误（真实率更高）。
5. **实际崩溃点比想象的早**：Noveling 报告作者在**约第 30 章**撞墙；ConStory-Bench 显示错误集中在中段。**这是连续退化，不是悬崖。**

**因此建议**：把上述方案当作"减少退化速率"的手段，而不是"消除矛盾"的保证。同时**必须**保留人类审阅环节——所有严肃来源都独立收敛到"检查器提出候选，人类做裁决"。

---

## 9. 明确不推荐做的事

| 不推荐 | 理由 |
|---|---|
| 把整本书塞进长上下文窗口 | Chroma 18 模型实测退化；CFPG 证明上下文存在也不够 |
| 为章节正文建/保留向量库 | 两个独立来源反对；Arboris 现有实现还是暴力全表扫描 + 重复索引 bug |
| 让 LLM 无界地自动失效事实 | Synapse 实测 **70% 误删真事实且静默** |
| 再建一套写作流程 | 已有三套（`writer.py` 内联 / `PipelineOrchestrator` / `UltimateWritingFlow`，最后一个从未被 import）；ConStory-Bench 证明 agent 化无一致性收益 |
| 无证据要求的一致性判定 | FABLES：无自动评分器与人类强相关；Synapse：κ≈0.35–0.39，细化细则后更差 |
| 依赖 LLM 重写整棵状态树 | 这正是当前 `raw_state_text` 的做法——有损、不可查、每次重写都可能丢事实 |

---

## 附录 A：写作 Prompt 改进建议

### A.0 先给结论：Arboris 的 prompt 底子比多数开源项目好

逐份读过 `backend/prompts/` 全部 21 个模板后，客观评价：**这套 prompt 不是短板**。`writing_v2.md` 已经包含：

- 严格有限视角 + 明确禁止「与此同时」「殊不知」等全知旁白
- 角色登场协议（rumor→trace→meet→name_reveal 四阶段认知过程）
- 禁止「AI 总结味」结尾（"他知道，挑战才刚刚开始"）
- Show-don't-tell 且带正反例
- `chapter_plan.md` 的 `pace_budget`（限制每章新事实/新角色/大爽点数量）与 `entrance_protocol`

这几项在公开可查的开源写作系统里属于上游水平。**下面只补真正的缺口。**

### A.1 反 AI 腔：把「感觉」换成「可统计的黑名单」

Arboris 现在的写法是「禁止 AI 套话：显而易见、综上所述、值得注意的是、总之、然而、不仅如此」——方向对，但覆盖面窄，且**没有区分严重程度**。

`NousResearch/autonovel` 的 [ANTI-SLOP.md](https://github.com/NousResearch/autonovel/blob/master/ANTI-SLOP.md) 是找到的**唯一有统计依据**的版本（依据 [slop-forensics](https://github.com/sam-paech/slop-forensics) 与 [EQ-Bench Slop Score](https://eqbench.com/slop-score.html)，后者把 slop 词频按 **60% 权重**计入综合指标）。

**它最重要的贡献是把禁用词分三档，而不是一律禁止**：

| 档位 | 处理方式 | 例词 |
|---|---|---|
| **Tier 1 见即杀** | 几乎不出现在人类口语写作中，出现就重写整句 | delve / utilize / leverage / facilitate / tapestry / testament to / myriad / plethora |
| **Tier 2 聚集才可疑** | 单独用没问题，一段里出现三个就重写 | robust / comprehensive / seamless / pivotal / intricate / profound / resonate / underscore |
| **Tier 3 零信息填充语** | 一律删 | "值得注意的是…" / "综上所述…" / "众所周知…" / "在当今快速发展的世界中…" |

**中文创作需要自己的 Tier 表**（直接照搬英文表无意义）。建议 Arboris 用同样的三档结构，基于自己的稿子统计产出中文版。候选（按同类逻辑）：

- **Tier 1（见即杀）**：「不禁」「不由自主地」「嘴角勾起一抹弧度」「眼中闪过一丝」「空气仿佛凝固」「时间仿佛静止」「心中五味杂陈」
- **Tier 2（聚集可疑）**：「深邃」「璀璨」「磅礴」「缱绻」「氤氲」「绝美」「震撼」
- **Tier 3（零信息）**：「总的来说」「不得不说」「值得一提的是」「与此同时」（后者已在 `writing_v2` 中被禁，但未列入统一黑名单）

### A.2 结构层面的 slop（比词更难抓，但更致命）

ANTI-SLOP 指出词汇只是表层，**骨架**才是破绽。四条与小说直接相关：

1. **主题句机器**：每段都是「主题句→展开→例子→收尾」，节奏完全一致。人类写作是**参差的**——有的段落只有一个句子。
2. **对称成瘾**：三优点三缺点、五步法、等长小节。*"Real writing is lumpy."*
3. **「不是 X，而是 Y」对举**：原文称其为 *"the single most overused rhetorical pattern in LLM output"*，在多个模型的 top trigram 列表中出现。中文对应的是「不是……而是……」「与其说……不如说……」。**这条应直接进 `writing_v2.md` 的硬约束。**
4. **破折号过载**：有论文支撑（[arXiv 2509.19163](https://arxiv.org/html/2509.19163v1)）。中文对应的是「——」的堆叠。

### A.3 可量化的检测信号（可用于自动 lint，而非只靠模型自觉）

| 信号 | 含义 | 可用于 |
|---|---|---|
| **低困惑度** | 文本过于可预测（阈值 <50 可疑） | 整章质检 |
| **低 burstiness** | 句长方差小；人类长短交错 | 计算句长变异系数，低于阈值告警 |
| **熵过于均匀** | 信息密度恒定，无疏密变化 | 分段落统计 |
| **trigram 过度代表** | 三词短语出现频率远超人类文本 | 检测 A.2 的对举句式 |

**这是 `ConsistencyService` / 编辑器评审可以直接加的确定性检查项——零 LLM 成本。**

### A.4 摘要 Prompt：最大的结构性缺口

`extraction.md` 要求「**严格控制在 500 字以内**」，`finalize_service.py` 的全局摘要要求「**2000 字以内**」。

对照 NstAgent（[arXiv 2609.35759](https://arxiv.org/abs/2609.35759)，10K→100K 词实测一致性不退化）的叙事状态三要素：

```
characters  |  past_events  |  future_requirements
```

**Arboris 的摘要只覆盖前两项。** `extraction.md` 第 28 行虽提到「悬念与伏笔」，但它是**自由文本**，无法按实体查询、无法表达有效期、无法参与「到期提醒」计算。

**建议**：把 `extraction.md` 的输出从纯 Markdown 改为**混合结构**——保留现有的 4 段叙事摘要（供语感与宏观走向），**追加一个强制 JSON 块**（供结构化写回）：

```jsonc
{
  "facts_changed": [
    {"entity": "沈墨", "fact_type": "state", "content": "左臂刀伤未愈",
     "valid_from": 5, "supersedes": null},
    {"entity": "沈墨", "fact_type": "location", "content": "破庙",
     "valid_from": 5, "supersedes": "客栈"}
  ],
  "threads": [
    {"id": "cg_0042", "action": "planted", "trigger": "主角被困地窖 AND 已搜索壁炉台"},
    {"id": "cg_0011", "action": "reinforced"}
  ],
  "contract": {
    "in_story_time": "第3天 深夜",
    "characters": [{"name": "沈墨", "location": "破庙", "doing": "刚睡着",
                    "physical": "左臂刀伤未愈", "unresolved_intent": "明早去渡口"}],
    "open_threads": ["庙外脚步声，未解释"]
  }
}
```

**关键要求（来自 ConWriter）**：`trigger` 必须写成**可在章节大纲上做模式匹配的谓词**，而不是描述性文字。这把「有没有记得这把枪」从记忆问题变成确定性匹配。

**同时必须要求：提取失败的章节不得写回。** ConWriter 明确：*"If no candidate passes verification within the retry budget, the scene is rejected and does not update the dynamic memory."*

### A.5 章节摘要的「未来要求」字段

新增一节，专门记录**本章向后文提出的义务**：

```markdown
### 5. 未兑现承诺（供后续章节检索）
- 对读者承诺：本章埋下的、必须在后续兑现的悬念（含预计回收章节）
- 对角色承诺：某角色说要做但尚未做的事
- 世界规则约束：本章新确立的规则，后续不得违反
```

这与伏笔账本的 `required_hints` 配合，能显著降低「伏笔断线」。

### A.6 参考：本次搜集到的高质量 prompt 资源

| 资源 | 内容 | 链接 |
|---|---|---|
| **autonovel ANTI-SLOP.md** | 三档禁用词表 + 结构 slop + 量化检测信号，有统计依据 | [GitHub](https://github.com/NousResearch/autonovel/blob/master/ANTI-SLOP.md) |
| **light-novel（小说执行规划）** | 中文长篇系统：L0–L3 分层知识库、双层真理仲裁、反 AI 腔黑名单、体检协议 | [GitHub](https://github.com/HUANLLK/light-novel) |
| **humanize-writing-skill** | AI 模式词典（英文） | [GitHub](https://github.com/lguz/humanize-writing-skill/blob/main/skills/humanize-writing/references/ai-patterns-dictionary.md) |
| **novel-studio-ai** | Story Bible / Style Bible / 图事实 / 连续性检查的完整工作流；**「草稿不更新 canon」原则** | [GitHub](https://github.com/YfengJ/novel-studio-ai) |
| **Novel-OS** | 五 agent + **确定性连续性引擎**（本地零成本，先于 LLM 裁判运行）+ `[STATE_UPDATE]` 输出契约 | [GitHub](https://github.com/mrigankad/Novel-OS) |
| **ralph-storywriter** | 单文件长文写作 prompt | [GitHub](https://github.com/heaversm/ralph-storywriter/blob/main/prompt.md) |
| **ConWriter** | 状态转移算子 `(Pre, Post, Forbid)` + 逐句定向修复，EMNLP 2026 Findings | [arXiv](https://arxiv.org/abs/2608.05169) |
| **NstAgent** | 10K→100K 词一致性不退化，含 `future_requirements` | [arXiv](https://arxiv.org/abs/2609.35759) |

---

## 附录 B：Prompt 研究补充（第二轮，含对附录 A 的修正）

> 完整报告：`docs/research-prompt-templates-2026.md`（113KB，含逐条 verbatim prompt）

### B.1 ⚠️ 对附录 A 的两处修正

附录 A 中两条建议被后续证据推翻，**以本节为准**：

| 附录 A 的说法 | 修正 | 依据 |
|---|---|---|
| 「破折号过载应列入硬约束」 | **破折号禁令对文学创作属于民间传说（folklore）**。它确实是一个真实的分布信号，但作为绝对规则是错的。 | 专项研究指出该信号在文学体裁中被误用 |
| 「Show, don't tell」绝对化 | **绝对化的 show-don't-tell 会产生相反的失败**。语料数据显示：AI 故事用**身体反应**替代事件与其代价的频率是人类的 **81% vs 38%**。更好的表述是**「陈述事实 + 说明后果」**。 | 61,600 篇故事语料研究 |

第二条尤其重要，因为它意味着 Arboris 现有 `writing_v2.md` 里这条：

```
## 7. Show, Don't Tell
- 禁止「他很愤怒」「她很害怕」「场面很壮观」。
```

**方向对但过度绝对**。语料证据显示，人类作者更常写「事实 + 后果」（*"two of the five resigned the same day"*），而不是把情绪全部翻译成身体反应。建议改为：

```
## 7. 情绪呈现
- 禁止抽象情绪词（「他很愤怒」）。
- 优先：事实 + 后果。例：❌他感到压力很大 → ✅那天有五个人辞职，其中两个当天就走了。
- 身体反应可用，但**不要每章都用同一套**（心跳/呼吸/手心出汗）。
  语料实测：AI 过度依赖身体反应（81%）远超人类（38%）。
```

### B.2 中文禁用句式分级表（直接可用，优于附录 A 的 A.1）

附录 A 建议「用三档结构统计自己的中文表」。第二轮找到了**已经做好且质量更高**的中文版——来自 `oh-story-claudecode`，是本轮全部来源里**最细粒度的禁用句式分类**，且**每条给出修法而非只给禁令**：

| 毒级 | 句式 | 错误例 | 修法 |
|---|---|---|---|
| ★★★★★ | 「不是A，（而）是B」（"而"可省略） | 「他不是冷漠，而是绝望」 | 直接写 B |
| ★★★★ | 「，带着……」万能状语 | 「他笑了一下，带着一丝不易察觉的嘲讽」 | 删状语留主句，或换具体动作 |
| ★★★★ | 无情绪声线：「声音不大，却带着……」 | 「她声音不大，却带着不容置疑的力量」 | 直接写台词内容或声音特征 |
| ★★★★ | 「他/她知道……」 | 「他知道这一切都来不及了」 | 用行为展示认知 |
| ★★★ | 「仿佛/犹如/宛若……一般」 | 「仿佛能穿透一切一般」 | 删掉或白描 |
| ★★★ | 「眼中闪过一丝……」/「嘴角勾起一抹……」 | 「眼中闪过一丝悲伤」 | 删掉；写他当场说的话或决定 |
| ★★★ | 「心中涌起一股……」/「心头一震」 | 「心中涌起一股暖流」 | 写它改变了什么：选择、台词、物件、后果 |
| ★★★ | 抽象命运收束：「命运……獠牙」/「反击才刚刚开始」 | 「属于他的反击才刚刚开始」 | 回到当下可见的动作、对话或物理后果 |
| ★★ | 章末预告「他不知道的是……」 | 「他不知道的是，更大的风暴即将来临」 | 用具体钩子物件/事件收束 |
| ★★ | 跨段「不是A。/也不是B。/只是C。」 | — | 语义复核；无功能则压成 C |

**密度控制（非绝对禁止）**：缓缓、微微、轻轻、淡淡 —— **每千字合计 ≤3**；成串出现或每个动作都垫一个时才替换。

**执行规则**：★★★★★ 命中**一处就要改**；其余按密度阈值。

> **这是专业与业余反 slop prompt 的最大分水岭**：扁平禁用表会导致过度修正、文风僵硬；分级产生**成比例的响应**。

### B.3 反 slop 元规则（防止误伤，务必一并采纳）

来自 `better-writing` 的方法论章节——**没有这段，禁用表会破坏正常写作**：

```markdown
## 如何使用本目录

单个特征永远不构成判决。可靠信号是【成簇出现】+【缺乏体裁适配】。
AI 文本无论什么受众都停在同一档"宜人高度"；人类文本会切换语域、
表明立场、变化节奏。【全篇语气均匀】是最持久的破绽。

按此顺序工作：
1. 扫描"近乎决定性的伪迹"。若存在，几乎可确定是机器生成或从聊天机器人粘贴。
2. 否则结合上下文统计成簇的 tell。一段需要【数个】，不是一个。参考置信度分级。
3. 应用体裁豁免。方法学章节的被动语态、发布说明的列表、法律文本的模糊措辞
   都是正确的，不是 tell。
4. 永远不要因单一特征触发修改。目标不是逃避检测器，而是清晰与贴合。
```

**四条可直接落地到 Arboris**：
1. 单特征不判罚 —— 避免误伤正常中文
2. 需要成簇 —— 与 B.2 的密度阈值一致
3. 体裁豁免 —— 说明文/设定章节不受小说规则约束
4. 不为规避检测器而改 —— 目标是质量

### B.4 一致性检查 prompt：优先级顺序 + 禁止把推测当错误

来自 Storydex 的审校 prompt，有两条 Arboris 完全没有的机制：

```
输出要求：
- 按"严重/警告/建议"分级列出问题。
- 每项包含文件路径、证据摘要、冲突说明、影响范围和修复建议。
- 无法确认的问题标为"待核实"，【不要把推测当错误】。
- 【正文和用户确认内容优先于派生摘要】；不要自动修改任何文件。
- 最后输出一份按修复优先级排序的行动清单。
```

**「正文优先于派生摘要」是硬性优先级声明**——没有它，agent 会为了迁就过期的摘要而改写正确的正文。这正好对应 Arboris 的 `global_summary` 反复 LLM 重写带来的漂移风险。

### B.5 角色记忆一致性检查（长篇第一号 bug）

来自 `snowflake-novel-subagents` 的一致性检查 agent。**它的价值在于用了具体反例**：

```markdown
#### 记忆一致性
检查点:
□ 角色记得应该记得的事
□ 不知道应该不知道的事
□ 回忆内容前后统一
□ 失忆/恢复有合理设定

常见错误:
第20章:艾莉亚告诉林昭真相
第35章:林昭惊讶地发现真相
→ 忘记了已知信息!
```

**建议**：把这段直接加入 `consistency_service` 的检查维度，并且**用具体反例而非抽象描述**——这是该 prompt 有效的真正原因。

### B.6 续写 prompt 的反幻觉契约（本轮找到的最佳单条规则）

来自 Storydex 续写 prompt 的第 4 条：

> **角色行为必须由其动机、已知信息和现场条件驱动；禁止无依据获得信息、能力或物品。**

这一条同时覆盖了三类高频崩坏：知识越界、能力跳跃、物品凭空出现。建议**原样加入 `writing_v2.md` 的硬约束区**。

同 prompt 另外两条也值得抄：
- 「不得为了篇幅填充、压缩、重复或截断场景」
- 「先给出 3–6 条续写计划和连续性风险，再输出正文」（计划→确认→动笔）

### B.7 滚动摘要的 O(1) 累加器技巧

来自 Omniscient-Novel-Reader 的角色提取 prompt。**关键在第 3 条**：

```
3. 对于"迄今发现角色"列表中的已有角色：记录任何新别名、更新的描述或角色变化。
   【只包含有新信息的角色。】
```

**没有这句，累加器每章都会重吐全部角色表**，token 成本 O(n²)。Arboris 的 `_collect_history_context` 目前正是无上限累加全部章节摘要，属于同类问题。

### B.8 章节续写的三段式拆分（对超长章节有用）

LSG Challenge (INLG 2024) 的方案：把章节生成拆成 start / continue / finish 三次调用，每次带 `book_summary` + `full_chapter_context`。适合 Arboris 输出长度被截断的场景（当前 `finish_reason=="length"` 直接抛 500，见 LLM 层审计）。

### B.9 未能获取的来源（诚实标注）

| 来源 | 状态 |
|---|---|
| Anthropic "Storytelling Sidekick" | 页面客户端渲染，`.md` 变体返回 HTML；**未重建、未使用第三方转述** |
| Google Vertex AI prompt gallery（编剧） | JS 渲染，仅取到骨架 |
| DeepWiki CyberNovelist-AI 摘要页 | HTTP 429 |
| Novelcrafter 系统提示词 | **未公开**——仅公开架构（Codex / scene beats / prompt presets / Sections） |

> 注意：`AgentDock` 的 `[STRUCTURE:select:...]` 是模板语法，不是纯文本，复用前需剥离。
