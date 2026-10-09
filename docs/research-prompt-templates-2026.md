# High-Quality Prompt Templates for AI Novel / Short-Story Writing

**Research report — compiled 2026.** All prompt text below is quoted verbatim from public sources. Every entry is labelled with purpose, length, and construction notes, plus a critical assessment of whether it is well-founded or folklore.

> **A note on method.** Most "best AI novel prompts" content on the web is SEO filler that restates the same five clichés. The genuinely reusable material lives in three places: (1) **open-source agent-skill repositories**, which ship prompt files as versioned source code; (2) **academic NLP papers** (ACL/INLG), which publish their exact prompt templates in appendices; and (3) a small number of **vendor docs and craft blogs** that publish real text. Everything below comes from those. Where a source only *describes* a prompt without giving text, I say so rather than inventing it.

---

## Table of contents

1. [Chapter / scene prose generation](#1-chapter--scene-prose-generation)
2. [Outline / plot structure](#2-outline--plot-structure)
3. [Character consistency](#3-character-consistency)
4. [Continuity / revision](#4-continuity--revision)
5. [Anti-slop / style control](#5-anti-slop--style-control)
6. [Long-context strategies (chapter N of a novel)](#6-long-context-strategies-chapter-n-of-a-novel)
7. [System prompts from real writing tools](#7-system-prompts-from-real-writing-tools)
8. [What the best prompts have in common](#8-what-the-best-prompts-have-in-common)
9. [Well-founded vs. folklore](#9-well-founded-vs-folklore)
10. [Source index](#10-source-index)

---

## 1. Chapter / scene prose generation

### 1.1 Prose-writing guidelines block (Story Skills `chapter-writing`)

**Source:** <https://raw.githubusercontent.com/danjdewhurst/story-skills/main/skills/chapter-writing/references/writing-guidelines.md> (repo: <https://github.com/danjdewhurst/story-skills>)
**For:** the craft rulebook an agent loads before drafting a chapter. **Length:** ~350 words. **Notable:** it is the only prompt I found that handles POV discipline, dialogue-tag economy, pacing-by-sentence-length, and scene Goal/Conflict/Outcome in one compact block — and it explicitly warns "Avoid opening with weather or waking up (unless deliberately subverting the cliche)," which is the single most common AI chapter opening.

```markdown
# Writing Guidelines

Guidelines for writing chapter prose. Adapt to the story's genre, tone, and POV as defined in `story.md`.

## Show, Don't Tell

- Convey emotion through action, dialogue, and sensory detail rather than stating feelings
- BAD: "She was angry."
- GOOD: "Her fingers whitened around the hilt. She spoke through her teeth."

## POV Consistency

- **First person:** Everything filtered through narrator's voice, knowledge, and bias
- **Third-person limited:** Stay in one character's head per scene. Only describe what they perceive, think, and feel
- **Third-person omniscient:** Can reveal any character's thoughts, but maintain a consistent narrative voice

Do NOT shift POV mid-scene. If a POV shift is needed, use a scene break (marked with `---`).

## Dialogue

- Dialogue should reveal character, advance plot, or both
- Each character should have a distinct voice (reference their Voice & Speech Patterns)
- Use dialogue tags sparingly - in English, "said" is invisible and fancy tags distract. Other languages have their own neutral tags and dialogue punctuation (see `../../line-editing/references/language-conventions.md`)
- Break up long speeches with action beats
- Avoid exposition dumps disguised as conversation

## Pacing

- Short sentences and paragraphs = fast pace, tension, action
- Longer sentences and paragraphs = slower pace, reflection, atmosphere
- Vary sentence length for rhythm
- Scene length should match importance - don't over-write minor moments

## Scene Structure

Each scene should have:
- **Goal:** What the POV character wants in this scene
- **Conflict:** What opposes them
- **Outcome:** What happens (often a setback that drives the next scene)

Not every scene needs explosive conflict - quiet character moments matter too. But every scene should change something.

## Sensory Detail

Ground scenes in the physical world:
- Sight, sound, smell, touch, taste
- Choose 2-3 senses per scene, not all five
- Use details specific to the location (reference the location file)
- Sensory details should reflect the POV character's state of mind

## Chapter Openings

- Orient the reader quickly: who, where, when
- Hook with tension, mystery, or voice
- Avoid opening with weather or waking up (unless deliberately subverting the cliche)

## Chapter Endings

- End on a moment of change, revelation, or tension
- Cliffhangers work for action chapters
- Quiet resonance works for character chapters
- The last line should make the reader want to continue

## Continuity

Before writing, check:
- Previous chapter's ending (pick up threads, don't contradict)
- Character states (injuries, emotional state, knowledge)
- Timeline consistency (time of day, travel times, seasons)
- Plot arc progress (what beats need to land)
```

**Assessment:** Well-founded. "Choose 2-3 senses per scene, not all five" is a genuinely useful constraint that stops the AI signature of synaesthetic over-description. The Goal/Conflict/Outcome triad is Swain's scene model in miniature. **Weakness:** it is advice, not an instruction *format* — it tells the model what good prose is but does not force the output shape (see §1.3 for that).

---

### 1.2 Continuous chapter drafting with an explicit continuity contract (Storydex `续写当前章节`)

**Source:** <https://github.com/TensorHub-ORG/Storydex/blob/main/docs/prompts/剧情设计/02-续写当前章节.md>
**For:** generating the next stretch of an in-progress chapter with continuity preserved. **Length:** ~250 words (Chinese). **Notable:** point 4 is the single best one-line anti-hallucination rule I found — *"角色行为必须由其动机、已知信息和现场条件驱动；禁止无依据获得信息、能力或物品"* ("Character behaviour must be driven by their motivation, known information and on-scene conditions; it is forbidden to obtain information, abilities or items without basis"). Point 7 forces a plan + risk list before prose.

```prompt
请续写当前 Storydex 小说项目中的当前章节或当前剧情片段。

执行要求：
1. 先读取当前文件、同章前文、最近相关章节、角色档案、世界书、长期记忆、当前变量和有效预设。
2. 总结本次续写的起点状态、场景目标、参与角色、已知信息和不能违反的约束。
3. 延续当前叙述视角、时态、文风、称谓、对话习惯和节奏，不突然切换叙事规则。
4. 角色行为必须由其动机、已知信息和现场条件驱动；禁止无依据获得信息、能力或物品。
5. 优先推进[本次剧情目标]，同时自然处理[需要延续的伏笔或冲突，可留空]。
6. 本章篇幅以本轮 TurnContract 的策略为准；短 / 中 / 长档位仅在实验开关启用时生效。核心转折完成后自然收束，保留必要行动、心理、对话与因果过渡；不得为了篇幅填充、压缩、重复或截断场景。结尾保留有效推进或钩子，不强行总结。
7. 先给出 3-6 条续写计划和连续性风险；除非用户已明确要求直接写入，否则先输出正文草稿供确认。
```

**English rendering of the operative requirements:**

```
1. First read the current file, the earlier part of this chapter, relevant recent chapters,
   character profiles, the worldbook, long-term memory, current variables and active presets.
2. Summarise this continuation's starting state, scene goal, participating characters,
   known information, and the constraints that must not be violated.
3. Continue the current narrative POV, tense, style, forms of address, dialogue habits and
   pacing; do not suddenly switch narrative rules.
4. Character behaviour must be driven by their motivation, known information and on-scene
   conditions; it is forbidden to obtain information, abilities or items without basis.
5. Prioritise advancing [this continuation's plot goal], while naturally handling
   [foreshadowing or conflicts needing continuation — may be left blank].
6. Length follows this round's TurnContract policy... After the core turn completes, close
   naturally; keep necessary action, interiority, dialogue and causal transitions; do not
   pad, compress, repeat or truncate a scene for length. End with effective progress or a
   hook; do not force a summary.
7. First give 3-6 continuation plan points and continuity risks; unless the user has
   explicitly asked for a direct write, output the prose draft for confirmation first.
```

**Assessment:** Well-founded and unusually disciplined. Point 6 ("do not pad, compress, repeat or truncate a scene for length") targets a real failure mode: LLMs told "write 2000 words" will pad. Point 7's plan-before-prose is a cheap quality gate. **Caveat:** the `TurnContract` reference is Storydex-internal and won't transfer directly.

---

### 1.3 Beat-driven scene generation with specificity enforcement (Novelcrafter "Scene Beats")

**Source:** <https://www.novelcrafter.com/courses/ultimate-beginners-guide/improving-ai-output-for-scene-beats> (tool: <https://www.novelcrafter.com>)
**For:** a real commercial writing tool's documented approach to steering prose generation. **Length:** the *pattern* is short (user writes a beat); the tool injects Codex + prior prose around it. **Notable:** this is not a prompt text but a **prompt architecture**, and it is the most practically validated one in the industry.

The documented loop, quoted from the Novelcrafter lesson:

> "A scene beat is an instruction you write for the AI. It describes what should happen next in your story, and can cover a short moment in time, or an entire scene. It acts like a direction you might give to a co-writer."

Their worked example of a *good* beat (verbatim from the page):

```
Connor enters the shop and almost trips over Sparky, managing to grab him at the last minute. He remarks that Gwendolyn the baker has been experimenting with new recipes again, and Sparky's tail wags at the mention of food. They exchange a few lines of dialogue about the upcoming town festival, where Gwendolyn plans to debut her latest creation — a mysterious pastry that has everyone buzzing with curiosity.
```

And the stated rule for calibrating beat detail:

> "A guideline to follow is to give as much information as you would need to give a human writing partner to write the same prose. Be specific about what happens. A vague beat like 'Mia talks to someone' generates vague prose."

**Assessment:** Well-founded. The "write the beat as you would brief a human co-writer" heuristic is the most reliable single piece of practical advice in this whole report, and it correctly locates the quality lever in the *input*, not in elaborate system prompts. The author's own note — *"I rarely use the very first generation without edits. I usually put at least one or two into sections, using different AI models, and then edit it by hand to match my voice"* — is honest about the ceiling.

---

### 1.4 Verbatim academic chapter-generation prompts (LSG Challenge, INLG 2024)

**Source:** <https://aclanthology.org/2024.inlg-genchal.13.pdf> — *The LSG Challenge Workshop at INLG 2024: Prompting Techniques for Crafting Extended Narratives with LLMs*
**For:** the exact prompts a research workshop used to generate multi-chapter narrative. **Length:** each 60–120 words. **Notable:** published in full in the appendix, and shows the **start / continue / finish** trifurcation — the same prompt with a different closing instruction depending on position in the chapter. This is a clean, reusable pattern.

**Prompt 2 — summary heading (sets style/tone constraints before generation):**

```
You are a popular fanfiction creator tasked with writing a new chapter for a Harry Potter
fanfiction according to the summary below. Your text should be distinct yet cohesive,
maintaining the original tone and style of the Harry Potter series.

Instructions:
1. The text should be for secondary school students.
2. Always narrate in the third person.
3. Ensure that text is rich in detail and narrative depth.
4. Avoid including any text outside of the story (e.g., meta comments, thank you notes,
   or personal addresses).
5. Write the text with no additional comments.
6. Use only English letters and Arabic numerals.

Here is summary of whole text:
```

**Prompt 3 — start of the chapter:**

```
Start generating the chapter {chapter_n} based on what happened before.

here's what happened in the whole book so far: {book_summary}

here's what happened in the previous chapter so far: {previous_chapter}

Start writing the text with no additional comments.
The structure of the beggining is: Chapter {chapter_n}. Name of the chapter. Text of the chapter
```

**Prompt 4 — continue generating the chapter:**

```
Continue generating the chapter {chapter_n} based on what happened before.

here's what happened in the whole book so far: {book_summary}

here's what happened in the chapter so far: {full_chapter_context}

Start writing the text with no additional comments.
Do not write chapter and the name of the chapter. Just continue writing the story.
```

**Prompt 5 — finish generating the chapter:**

```
Finish generating the chapter {chapter_n} based on what happened before.

here's what happened in the whole book so far: {book_summary}

here's what happened in the chapter so far: {full_chapter_context}

Start writing the text with no additional comments.
Do not write chapter and the name of the chapter. Just finish writing the story.
```

**Assessment:** Mixed. The **start/continue/finish trifurcation is genuinely well-founded** — it solves the real problem that a long chapter cannot be produced in one call, and the "do not write the chapter heading" guard prevents the model restarting the chapter on every continuation. Instruction 4 ("Avoid including any text outside of the story") is a necessary anti-chatbot guard. **Weakness:** the style instruction is generic ("rich in detail and narrative depth") and produces generic prose; the Harry Potter framing does the heavy lifting via the model's prior. Studies of this workshop reported that most generated stories still had coherence problems — the prompts alone did not solve long-form structure.

---

## 2. Outline / plot structure

### 2.1 Chapter outline generator mapped to a real structure (AgentDock prompt library)

**Source:** <https://raw.githubusercontent.com/AgentDock/prompt-library/main/writing/creative/chapter-outline-generator.mdx>
**For:** turning a premise into a chapter-by-chapter outline on a named beat sheet. **Length:** ~250 words. **Notable:** three features almost no other outline prompt has — (a) an explicit **no-mashup rule**, (b) **proportional beat placement** enforced with a reason, (c) a **self-critique clause** asking the model to flag thin stretches and say *why* they are thin.

```text
I need a chapter-by-chapter outline for a book, mapped to a real story structure instead of a loose list of scenes.

My premise: [BOOK_PREMISE] (the story's premise, main character, and goal)

The structure I want to follow is [STRUCTURE:select:three-act structure,hero's journey,Save the Cat beat sheet,simple beginning-middle-end].

The genre is [GENRE:select:fantasy,romance,horror,mystery or thriller,science fiction,literary fiction,young adult].

I want [CHAPTER_COUNT:number:8-40] chapters total.

Build a chapter-by-chapter breakdown across [CHAPTER_COUNT] chapters using [STRUCTURE]. For each chapter, give a one-line summary of what happens and name the structural beat it serves, such as the inciting incident or the midpoint, matched to whichever structure I picked. Use the beats that belong to [STRUCTURE], not a mashup: Save the Cat has its own fifteen named beats, the hero's journey has its stages, and three-act structure has its turning points, so don't relabel one framework's beats with another's names.

Place the major beats where they belong proportionally. The midpoint should land near the actual middle chapter, not wherever it's convenient, and the darkest moment belongs in the final third, not chapter four. Fold [GENRE] expectations into the beats themselves: a mystery outline should show where clues and red herrings land, a romance should track the relationship's push and pull alongside the main plot.

Flag any stretch of the outline that feels thin or repetitive, and say why it's thin, whether the character has no goal in those chapters, no obstacle, or nothing changes between the start of the stretch and the end. That tells me what to fix before I start drafting instead of just where to worry.
```

**Assessment:** **Genuinely good** — the strongest outline prompt in this report. The no-mashup rule fixes the very common failure where a model writes "Save the Cat" beats using Hero's Journey names. The proportional-placement clause with a *reason* ("not wherever it's convenient") is far more effective than "follow three-act structure". The final paragraph is a diagnostic that names the three actual causes of a sagging middle (no goal / no obstacle / no change), which is craft knowledge, not prompt decoration. **Caveat:** the `[STRUCTURE:select:...]` syntax is AgentDock-specific Template syntax, not plain text — strip the `:select:` and the option list if reusing elsewhere.

---

### 2.2 Beat sheets for six structures (Story Skills `plot-structure`)

**Source:** <https://raw.githubusercontent.com/danjdewhurst/story-skills/main/skills/plot-structure/references/structure-models.md>
**For:** a ready reference of beat names an outline can be tagged with. **Length:** ~600 words. **Notable:** covers Save the Cat *with percentage positions*, which is what makes it usable for enforcing pacing.

```markdown
## Save the Cat (Snyder)

Popular in screenwriting, works well for tightly paced stories.

| Beat | Position | Description |
|------|----------|-------------|
| Opening Image | 1% | Visual/thematic snapshot of starting state |
| Theme Stated | 5% | Theme hinted at in dialogue |
| Set-Up | 1-10% | Establish world, characters, stakes |
| Catalyst | 10% | The event that changes everything |
| Debate | 10-20% | Protagonist wrestles with the call |
| Break into Two | 20% | Protagonist chooses to act |
| B Story | 22% | Secondary story begins (often love interest) |
| Fun and Games | 20-50% | The "promise of the premise" delivered |
| Midpoint | 50% | False victory or false defeat |
| Bad Guys Close In | 50-75% | Opposition intensifies |
| All Is Lost | 75% | Lowest point, whiff of death |
| Dark Night of the Soul | 75-80% | Protagonist processes the loss |
| Break into Three | 80% | Solution discovered, often from B story |
| Finale | 80-99% | Protagonist acts, defeats opposition |
| Final Image | 99% | Visual/thematic proof of change |
```

Also included, verbatim from the same file, are **Dan Harmon's Story Circle** (the eight steps, which the file notes "fits episodic and short-form stories well: each episode runs one full circle while the season traces a larger one"):

```markdown
## Dan Harmon's Story Circle

| Beat | Step | Description |
|------|------|-------------|
| You | 1 | Character in a zone of comfort |
| Need | 2 | But they want something |
| Go | 3 | They enter an unfamiliar situation |
| Search | 4 | They adapt to the new situation |
| Find | 5 | They get what they wanted |
| Take | 6 | They pay a heavy price for it |
| Return | 7 | They return to their familiar situation |
| Change | 8 | Having changed — the circle completes where it began, but the character is different |
```

The file also carries **Kishotenketsu** (Ki/Sho/Ten/Ketsu, with the note "No central conflict required"), **Fichtean Curve**, **Five-Act**, **Three-Act** and **Hero's Journey**, plus a "Choosing a Structure" mapping of genre → structure.

**Assessment:** Well-founded as *reference data*, and notably honest: it ends with "Structures are guides, not rules. Mix and adapt as the story demands." The most valuable structural insight in the file is the pairing of each structure with the kind of story it fits (Kishotenketsu → literary/slice-of-life; Fichtean → crisis-driven) rather than pretending one beat sheet suits everything. The **percentage positions on Save the Cat are the actually useful part** — they let you mechanically check "the Midpoint is at chapter 9 of 18."

---

### 2.3 The Snowflake Method as an executable agent chain (snowflake-novel-subagents)

**Source:** <https://github.com/hahagood/snowflake-novel-subagents> (MIT) — 15 Claude Code subagents implementing Randy Ingermanson's ten-step method.
**For:** premise → full outline → scene list → draft, as a pipeline. **Notable:** each step is a separate agent with its own context, and each defines an exact **sentence formula** plus a worked example. This is the most complete implementation of a named method I found.

The three-act architect agent (`three-act-architect.md`) states the five-sentence expansion formula verbatim:

```
## 五句话公式

### 句子1：背景与开场（第一幕前半）
格式：在[地点/时间/设定]，[主角]过着[什么样的生活]，直到[激励事件]。

### 句子2：第一幕转折与目标（第一幕后半）
格式：[主角]为了[目标]，必须[进入新世界/接受挑战]，但不知道[隐藏的真相]。

### 句子3：第二幕的冲突升级（第二幕前半+中点）
格式：过程中，[主角]发现[更大的阴谋/真相]，情况变得[更加复杂/危险]。

### 句子4：黑暗时刻与抉择（第二幕后半）
格式：当[一切似乎失败/最大危机]时，[主角]意识到[真正重要的是什么]，决定[做出艰难选择]。

### 句子5：高潮与结局（第三幕）
格式：最终，[主角]通过[行动/牺牲]，[解决冲突]，世界/主角因此[如何改变]。
```

Translation of the five sentence templates:

```
Sentence 1 (setup): In [place/time/setting], [protagonist] lives [what kind of life],
                    until [inciting incident].
Sentence 2 (act 1 turn): [Protagonist], in order to [goal], must [enter new world /
                    accept challenge], but does not know [hidden truth].
Sentence 3 (act 2 escalation): Along the way, [protagonist] discovers [greater
                    conspiracy / truth], and the situation becomes [more complex / dangerous].
Sentence 4 (dark night): When [everything seems lost / greatest crisis], [protagonist]
                    realises [what truly matters], and decides [to make a hard choice].
Sentence 5 (climax/resolution): Finally, [protagonist], through [action / sacrifice],
                    [resolves the conflict], and the world / protagonist is [changed how].
```

With a worked sci-fi example for sentence 1: *"2087年的数字永生时代，黑客林昭日复一日地清理垃圾数据，直到他发现一个已故老人的意识碎片在哀嚎求救。"* ("In the digital-immortality era of 2087, hacker Lin Zhao cleans junk data day after day — until he discovers that a dead old man's consciousness fragment is screaming for help.")

The agent also includes a "story spine" completeness check:

```
使用"故事脊椎"检查法：
- [ ] 主角是谁？（明确）
- [ ] 主角想要什么？（目标清晰）
- [ ] 阻碍是什么？（冲突强烈）
- [ ] 主角如何改变？（弧光明显）
- [ ] 结局如何？（冲击力强）
```

**Assessment:** Well-founded. The value is the **fill-in-the-blank sentence formulas**: they are specific enough to force causal structure ("必须…但不知道…" — *must… but does not know…*) while staying genre-agnostic. **Critique:** ten sequential agents is heavy ceremony for most projects; steps 1–4 alone capture most of the benefit. The method itself (Ingermanson's) is a respected craft technique, not hype — but note it is a *top-down design* method, not a beat sheet, and the repo is honest about that in the sibling reference (see §2.4).

---

### 2.4 The Snowflake Method as a design ladder (Story Skills `snowflake.md`)

**Source:** <https://raw.githubusercontent.com/danjdewhurst/story-skills/main/skills/plot-structure/references/snowflake.md>
**For:** the same method, described precisely and pragmatically, with explicit guidance on stopping partway. **Length:** long (a full reference). **Notable:** it states plainly that Snowflake *is not* a beat sheet and must be paired with one, and it defines the three-disaster rule.

Verbatim:

```markdown
## Step 1: One-Sentence Summary

The whole novel in one sentence of about fifteen words: who, what they want, what stands in
the way. No character names needed; a role and a situation carry it.

## Step 2: One-Paragraph Summary

Five sentences: the setup, the first disaster, the second disaster, the third disaster, and
the ending. Each disaster closes a phase and forces the protagonist into a harder course;
the ending resolves the third.
```

And the honest scoping note:

> "It is a design process, not a beat sheet: pair it with a structure from `references/structure-models.md` (three-act fits its three disasters) and use it when the user wants to plan the whole book before drafting."

**Assessment:** Well-founded, and the most intellectually honest treatment of Snowflake I found. The "three disasters at ~25% / ~50% / ~75%" mapping onto three-act beats is a concrete, checkable structural claim rather than vague encouragement.

---

## 3. Character consistency

### 3.1 Character creation that refuses to contradict canon (Storydex `创建新角色`)

**Source:** <https://github.com/TensorHub-ORG/Storydex/blob/main/docs/prompts/角色创作/01-创建新角色.md>
**For:** adding a character mid-project without breaking existing setup. **Length:** ~230 words. **Notable:** requirement 1 (scan for duplicates first), requirement 5 (three-way tagging of **confirmed fact / proposed setting / awaiting confirmation**), and requirement 6 (unknowns must be written as "unknown", not invented).

```prompt
请为当前 Storydex 小说项目创建一个新角色，并使用项目现有角色模板组织结果。

角色需求：
- 角色定位：[主角/配角/反派/导师/盟友/路人/自定义]
- 剧情功能：[希望角色承担的功能]
- 首次出现场景：[可留空]
- 其他约束：[性别、年龄、阵营、职业、气质等，可留空]

执行要求：
1. 先读取现有角色、世界书、大纲和相关正文，检查是否已有同功能或高度重复角色。
2. 角色必须与当前世界规则、时代、组织结构和力量体系兼容。
3. 建立清晰的外在目标、内在需求、核心恐惧、秘密、能力边界、说话方式和行为模式。
4. 至少设计 3 条与现有角色/势力/地点的关系钩子，并说明关系如何推动冲突或选择。
5. 区分"项目已确认事实""本次建议设定""仍待用户确认"；未知信息明确写"未知"。
6. 输出完整角色档案、首次出场建议、可持续发展的角色弧线，以及需要用户确认的问题。
7. 在用户确认前只输出草案；用户明确要求写入时，再保存到 `.storydex/characters/`，不得覆盖已有角色文件。
```

**English:**

```
Create a new character for the current Storydex novel project, organised using the
project's existing character template.

Character requirements:
- Role: [protagonist / supporting / antagonist / mentor / ally / extra / custom]
- Narrative function: [the function you want the character to carry]
- First appearance scene: [may be left blank]
- Other constraints: [gender, age, faction, occupation, temperament etc. — may be blank]

Execution requirements:
1. First read existing characters, the worldbook, the outline and relevant prose; check
   whether a character with the same function, or a highly duplicative one, already exists.
2. The character must be compatible with current world rules, era, organisational
   structure and power system.
3. Establish a clear external goal, internal need, core fear, secret, ability limits,
   manner of speech and behavioural pattern.
4. Design at least 3 relationship hooks to existing characters / factions / locations,
   and explain how each relationship drives conflict or choice.
5. Distinguish "project-confirmed fact" / "setting proposed this time" / "still awaiting
   user confirmation"; write "unknown" explicitly for unknown information.
6. Output the full character profile, a first-appearance suggestion, a sustainable
   character arc, and the questions needing user confirmation.
7. Before user confirmation, output only a draft; when the user explicitly asks to write,
   save to `.storydex/characters/`; do not overwrite existing character files.
```

**Assessment:** Well-founded and notably careful. Requirement 5 is the epistemically correct design: it stops the model laundering its own inventions into canon, which is *the* mechanism by which AI-written long fiction drifts. Requirement 4's demand for relationship *hooks with consequences* ("explain how the relationship drives conflict or choice") is craft knowledge — it prevents decorative character sheets.

---

### 3.2 Voice fingerprinting: `voice-words` / `voice-avoid` (Story Skills `voice-style`)

**Source:** <https://raw.githubusercontent.com/danjdewhurst/story-skills/main/skills/voice-style/SKILL.md>
**For:** making each character's dialogue measurably distinguishable. **Notable:** this is the most *mechanically enforceable* character-consistency design in the report — it moves "distinct voice" out of vibes and into two explicit word lists plus a script check.

Verbatim from the skill:

```markdown
4. Character Voices entries summarise each character file's Voice & Speech Patterns section
   in one line and link to it. Record words a speaker reaches for in the character file's
   `voice-words` list and words they would never say in `voice-avoid`, so `story voices` can
   check them. The character file is canon; if the two disagree, fix the style sheet, or ask
   the user before changing the character.
```

And the enforcement step:

```shell
story voices .
```

> "`story voices` fingerprints each character's attributed dialogue and warns about a `voice-avoid` word said, a `voice-words` entry never said, and two characters who may sound alike. A line counts only when the narration names its speaker by a speech verb, or names one character in the paragraph."

Plus the differentiation heuristic, verbatim:

> "When two voices blur, differentiate them on more than one axis (sentence length, contractions, vocabulary, what they ask about) and see `dialogue-subtext.md` in the `scene-craft` skill for the tag-swap test."

**Assessment:** Well-founded and genuinely novel. The **`voice-avoid` list is the key idea** — it is far easier to specify what a character would *never* say than to describe their voice abstractly, and it is directly checkable. The tool is honest about its limits: "Pronoun tags (`she said`) are never attributed, so in close third person the POV character is often under-counted." The "tag-swap test" (swap the dialogue tags between two characters; if you can't tell whose line is whose, the voices aren't differentiated) is a real editorial technique.

---

### 3.3 Character development builder (AgentDock)

**Source:** <https://raw.githubusercontent.com/AgentDock/prompt-library/main/writing/creative/character-development.mdx>
**For:** one-shot deep character generation. **Length:** ~150 words. **Notable:** it asks for "what they want versus what they actually need" — the standard craft distinction — and for "moments in a story where their true nature would be revealed."

```text
I need to develop a fully realized character for my story.

This character is [CHARACTER_ROLE:select:the protagonist or main character,a major supporting character,the antagonist or villain,a love interest,a mentor or guide figure,a sidekick or companion,a minor but memorable character].

Basic information I already have: [BASIC_INFO] (name, age, role in the story, any details you have decided on)

The genre and setting of my story: [GENRE_SETTING]

This character's main purpose in the story is [PURPOSE].

Themes I want this character to embody or explore: [THEMES?]

Develop this character with depth and complexity. Include their physical appearance with distinctive details, core personality traits with both strengths and flaws, their backstory and formative experiences, their deepest desires and greatest fears, their voice and how they speak, relationships and how they interact with others, their internal conflict and potential arc, secrets or contradictions that add complexity, and small habits or quirks that make them feel real. Show how their past shapes their present behavior. Identify what they want versus what they actually need. Suggest moments in a story where their true nature would be revealed.
```

**Assessment:** **Mediocre — mostly checklist, partly hype.** It is a competent character questionnaire, but the long run-on final paragraph ("...with depth and complexity. Include ... and small habits or quirks...") is exactly the kind of comma-spliced instruction list that produces the *padded* character sheets AI is notorious for. The one strong element is "what they want versus what they actually need". **Use §3.1 instead** for anything that has to survive contact with an existing manuscript.

---

## 4. Continuity / revision

### 4.1 The consistency checker agent (snowflake-novel-subagents)

**Source:** <https://raw.githubusercontent.com/hahagood/snowflake-novel-subagents/master/.claude/agents/consistency-checker.md>
**For:** auditing a manuscript for contradictions. **Length:** very long (several thousand words of checklists). **Notable:** it is organised by *dimension × failure mode × concrete example of the bug*, which is what makes it work — the model is shown what a contradiction looks like, not just told to find them.

```markdown
### 1. 人物一致性

#### 外貌一致性
检查点:
□ 眼睛颜色前后一致
□ 身高体重没有突变
□ 疤痕标记位置固定
□ 发型变化有合理说明
□ 年龄增长符合时间线

常见错误:
第1章:林昭左眼角有疤痕
第50章:他摸了摸右眼角的疤痕
→ 位置矛盾!
```

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

```markdown
#### 伏笔回收
检查点:
□ 所有伏笔都有呼应
□ 悬念有解答
□ 没有遗忘的线索
□ 契诃夫的枪都有开火

常见错误:
第5章:提到神秘U盘的重要性
全书结束:U盘再也没出现
→ 伏笔遗忘!
```

**English (the three excerpts):**

```
1. Character consistency — Appearance
Checklist: eye colour consistent; height/weight do not jump; scar location fixed; hair
changes explained; age progression matches the timeline.
Common error: Ch1 "a scar at the corner of Lin Zhao's left eye" → Ch50 "he touched the
scar at the corner of his right eye" → location contradiction!

Memory consistency
Checklist: characters remember what they should remember; do not know what they should
not know; recollections are internally consistent; amnesia/recovery has a plausible
mechanism.
Common error: Ch20 "Aria tells Lin Zhao the truth" → Ch35 "Lin Zhao is astonished to
discover the truth" → forgot known information!

Foreshadowing payoff
Checklist: every plant is echoed; every mystery is answered; no clues are forgotten; every
Chekhov's gun fires.
Common error: Ch5 "mentions the importance of a mysterious USB drive" → end of book "the
USB drive never appears again" → forgotten foreshadowing!
```

The other dimensions are **plot consistency** (causal logic, foreshadowing payoff, event ordering), **world consistency** (magic/tech rules, geography, social background), **timeline consistency** (date/weekday correspondence, age arithmetic, travel time), and **detail consistency** (name spelling, numbers, object tracking).

**Assessment:** Well-founded, and the **"常见错误" (common error) worked examples are the mechanism that makes it work** — abstract instructions like "check for contradictions" produce vague output, whereas showing the model a scar migrating from the left eye to the right eye produces targeted search. The "记忆一致性" (memory consistency) dimension is the single most valuable check for AI-written long fiction, because *a character knowing something they were never told* is the characteristic AI continuity failure.

---

### 4.2 Project-wide consistency audit (Storydex `项目一致性检查`)

**Source:** <https://github.com/TensorHub-ORG/Storydex/blob/main/docs/prompts/编辑审校/01-项目一致性检查.md>
**For:** a structured continuity audit with severity levels. **Length:** ~200 words. **Notable:** it explicitly forbids modifying files, requires evidence + file path per finding, and creates a "待核实" (to be verified) bucket so speculation is never recorded as an error.

```prompt
请对当前 Storydex 小说项目执行一次一致性检查，检查范围为[全项目/指定章节/当前文件]。

检查维度：
1. 时间线、日期、昼夜、旅行时间和事件先后。
2. 角色年龄、外貌、称谓、能力、伤势、物品、位置、关系和知识边界。
3. 世界规则、力量/技术成本、组织制度、地理距离和资源限制。
4. 伏笔的埋设、强化、回收和遗忘情况。
5. 正文、角色档案、世界书、WIKI、变量和大纲之间的冲突。

输出要求：
- 按"严重/警告/建议"分级列出问题。
- 每项包含文件路径、证据摘要、冲突说明、影响范围和修复建议。
- 无法确认的问题标为"待核实"，不要把推测当错误。
- 正文和用户确认内容优先于派生摘要；不要自动修改任何文件。
- 最后输出一份按修复优先级排序的行动清单。
```

**English:**

```
Run a consistency check on the current Storydex novel project. Scope: [whole project /
specified chapters / current file].

Check dimensions:
1. Timeline: dates, day/night, travel times, and event ordering.
2. Characters: age, appearance, forms of address, abilities, injuries, possessions,
   location, relationships, and knowledge boundaries.
3. World rules: power/tech costs, organisational systems, geographic distances,
   resource limits.
4. Foreshadowing: planting, reinforcement, payoff, and forgetting.
5. Conflicts between prose, character profiles, worldbook, wiki, variables and outline.

Output requirements:
- List issues graded as "serious / warning / suggestion".
- Each item includes file path, evidence summary, description of the conflict, scope of
  impact, and a repair suggestion.
- Mark unverifiable issues as "to be verified"; do not treat speculation as an error.
- Prose and user-confirmed content take precedence over derived summaries; do not
  automatically modify any files.
- Finally output an action list sorted by repair priority.

```

**Assessment:** Well-founded. Two details are genuinely valuable: **"正文和用户确认内容优先于派生摘要"** (prose and user-confirmed content outrank derived summaries) establishes a **precedence order for conflicting sources**, which is the actual hard problem in story-bible maintenance — and **"不要把推测当错误"** (don't treat speculation as an error) prevents the audit from generating false positives that waste the author's time. The severity triage plus "no auto-modify" makes it safe to run repeatedly.

---

### 4.3 Revision as a named, ordered pass ladder (Story Skills `revision-continuity`)

**Source:** <https://raw.githubusercontent.com/danjdewhurst/story-skills/main/skills/revision-continuity/SKILL.md>
**For:** structuring a whole-book revision so expensive structure changes happen before cheap line edits. **Notable:** the ordering rationale is stated explicitly, and it is correct craft reasoning.

Verbatim:

```markdown
Track a full revision as a ladder of named passes in `story.md`
`revision-passes`, so the work happens in order (big structural changes
before polishing sentences that may be cut) and survives between sessions:
```

The default ladder, verbatim:

```
structure, character, theme, continuity, pacing, line, copyedit, proof
```

With this per-pass check mapping:

| Pass | Checks | Checklists |
|------|--------|----------------|
| `structure` | `story timeline .`, `story pacing .`, `story diagram arcs` | Reverse outline, pacing waveform, removability audit |
| `character` | `story voices .`, `story knowledge <id> --at <chapter>`, `story diagram relationships` | Developmental revision (motivation, arcs) |
| `theme` | `story report .` | Theme audit |
| `continuity` | `story continuity .`, `story clues .`, `story links .` | Continuity audit, reveal economy, fact check |
| `pacing` | `story pacing .` | Pacing waveform |
| `line` | `story prose .`, `story voices .` | Line edit (the `line-editing` skill) |
| `copyedit` | `story prose .` + `style-sheet.md` | Copyedit (the `line-editing` skill) |
| `proof` | `story build --format print`, `story build --format html` | Proof (the `line-editing` skill) |

Two pass definitions worth quoting for their craft content:

> **Reverse outline** - what each chapter actually does, diffed against what the plot files say it should do
> **Removability audit (darling-killing)** - scenes whose removal would change nothing downstream

**Assessment:** Well-founded. The **ladder is the contribution** — most people (and most AI workflows) line-edit prose that then gets cut at the structural pass, wasting the work. "Reverse outline" (deriving what the manuscript *actually* does and diffing against the plan) and "removability audit" are both standard professional editorial techniques. Also strong: **"Cut, fold, or move only what they approve: a removability audit or a length pass proposes cuts, it does not make them."**

---

### 4.4 Constrained rewrite (Storydex `润色与改写`)

**Source:** <https://github.com/TensorHub-ORG/Storydex/blob/main/docs/prompts/编辑审校/02-润色与改写.md>
**For:** polishing prose without changing facts. **Length:** ~180 words. **Notable:** it names the rewrite *target* and *strength* as parameters and separates "rewritten version" from "notes on changes", and requires conflicts to be reported rather than silently fixed.

```prompt
请润色或改写当前选中文本；如果没有选中文本，则处理当前文件中用户指定的段落。

目标：[语言精炼/增强画面/加强情绪/改善对话/调整节奏/统一视角/自定义]
改写强度：[轻度/中度/重度]

要求：
1. 先读取前后文和相关角色资料，确认叙述视角、场景目标、角色声音和连续性。
2. 不改变关键事实、事件结果、角色动机、伏笔含义和世界规则，除非用户明确要求改剧情。
3. 删除重复解释、空泛形容和无功能动作，使用具体感官、动作与反应增强表达。
4. 对话必须符合角色身份、关系、知识边界和情绪状态。
5. 输出"改写版本"和"主要调整说明"；如果发现事实冲突，另列问题，不擅自修正。
6. 默认只输出候选文本，不直接覆盖原文；用户确认后再写入。
```

**English:**

```
Polish or rewrite the currently selected text; if nothing is selected, handle the
paragraph the user specifies in the current file.

Goal: [tighten language / strengthen imagery / strengthen emotion / improve dialogue /
adjust pacing / unify POV / custom]
Rewrite strength: [light / medium / heavy]

Requirements:
1. First read the surrounding text and relevant character material; confirm narrative POV,
   scene goal, character voice and continuity.
2. Do not change key facts, event outcomes, character motivation, the meaning of
   foreshadowing, or world rules, unless the user explicitly asks to change the plot.
3. Delete redundant explanation, vague description and functionless action; use concrete
   sensory detail, action and reaction to strengthen expression.
4. Dialogue must fit character identity, relationships, knowledge boundaries and
   emotional state.
5. Output the "rewritten version" and "summary of main adjustments"; if you find a factual
   conflict, list it separately — do not fix it on your own initiative.
6. By default output candidate text only; do not directly overwrite the original.
   Write only after user confirmation.
```

**Assessment:** Well-founded. Item 2's enumerated invariants (facts, outcomes, motivations, foreshadowing meaning, world rules) is a better "change only what you're told" contract than the vague "preserve the meaning". Item 5's "report conflicts, don't fix them" is important: an AI asked to polish will happily "correct" a deliberate unreliability or an intentional contradiction into bland consistency.

---

## 5. Anti-slop / style control

### 5.1 `better-writing` — the most rigorous anti-slop reference available

**Source:** <https://github.com/forjd/better-writing> — MIT, version 2.0.0. Files: `skills/better-writing/references/ai-writing-patterns.md`, `structures-and-phrases.md`, `genre-tells.md`, `preflight.md`.
**For:** detecting and removing AI prose tells. **Length:** very long (the patterns file alone is thousands of words). **Notable:** **it is the only anti-slop resource I found that cites corpus studies for its claims and grades its tells by confidence tier**, and it explicitly warns against over-application.

Its methodology statement is the most important paragraph in this entire report, verbatim:

```markdown
## How to use this catalogue

One feature is never a verdict. The reliable signal is a cluster of tells plus the absence of genre adaptation. AI prose stays at one pleasant altitude no matter the audience; human prose shifts register, takes sides, and varies its rhythm. Treat uniform tone across a whole piece as the most durable tell of all.

Work in this order:

1. Scan for near-conclusive artefacts. If one is present, the text is almost certainly machine-generated or pasted from a chatbot. See below.
2. Otherwise count clustered tells in context. A passage needs several, not one. Use the confidence tiers when reading the vocabulary list.
3. Apply genre exemptions. Passive voice in a methods section, bullet lists in release notes, hedging in legal text, and markdown in a README are correct, not tells. See Genre defaults in `voice-and-context.md` and the per-genre Exemptions in `genre-tells.md`.
4. Never trigger an edit on a single feature. Detector-evasion is not the goal; clarity and fit are.
```

Its confidence tiering, verbatim:

```markdown
- Tier 1: distinctive markers. Flag when two or more appear in the same passage.
- Tier 2: common but overused. Flag only at higher density, and never replace a word on sight.
- Tier 3: ordinary English whose elevated rate shows up only across a large corpus. A single instance is never a tell.
```

**The fiction-specific tell list — the most directly relevant section** (`genre-tells.md`, "Fiction and creative writing"), verbatim:

```markdown
## Fiction and creative writing

The vocabulary tells here are the strongest in any genre. A 2026 study measured phrases over-represented in LLM fiction against human baselines and found some at more than a thousand times the human rate:

- names: Elara, Elias, Kael, Lyra, Seraphina, Thorne
- verbs and adjectives: shimmered, flickered, unsettlingly, palpable, sends shivers down your spine
- body-metaphor emotion: "heart hammered against her ribs", "a tightening in the chest", "let out a breath she didn't know she was holding", "felt a profound sense of"
- scene furniture: "the air was thick with", "a testament to", "dust motes danced", "the weight of"

Structural tells from a corpus of about 61,600 stories:

- stating the theme: AI stories end with the moral 77% of the time, humans 52%
- emotion through the body instead of through events and their cost (81% vs 38%). Humans more often name the fact and the consequence: "two of the five resigned the same day"
- tidy single-track plots with clean resolution; human stories leave protagonists' choices morally ambiguous
- per-model habits: Claude runs flat event escalation, GPT over-uses dream sequences, Gemini defaults to external character description

Fix by cutting the over-represented phrase for the plain one, ending on the last event rather than its meaning, and letting a feeling show through what a character does or loses. Do not invent events or interiority the draft does not have; mark the gap for the writer.

Exemptions: a writer's deliberate voice, including ornate or mannered prose, is theirs to keep. Flag it, do not strip it.
```

**The fiction-relevant structure tells** (`structures-and-phrases.md`), verbatim:

```markdown
### Binary contrast

These patterns feel pre-baked:

- "Not because X. Because Y."
- "X is not the problem. Y is."
- "The answer is not X. It is Y."
- "It feels like X. It is actually Y."
- "Not just X, but Y."
- "Not only X but Y."
- "This is not about X, it is about Y."
- "This does not mean X. It means Y." The same contrast split across two sentences.
- A clipped negative tail after the claim: "Deploys run on every merge, no guessing."
- "X rather than Y" and "rather than X, Y" used as a reflex (common in Grok output).

Fix by stating the point directly. This is a Tier 1 structure when it repeats: see Negative parallelism in `ai-writing-patterns.md`. In text you write, budget one per piece, and use it only where the source or brief names the misconception it corrects.
```

```markdown
### Stating the moral

The paragraph ends by explaining what it meant, the section ends with its lesson, the story ends with its theme. A 2026 study of about 61,600 stories found AI-written ones stated the moral 77% of the time against 52% for humans, and the habit carries into non-fiction as a closing "which is why X matters".

Fix by ending on the last fact or event and trusting the reader.
```

```markdown
### Narrator from a distance

Avoid hovering above the scene:

- "People tend to"
- "Nobody designed this"
- "This happens because"
- "This is why"

Fix by putting the reader, actor, or specific situation in the sentence. Keep the distant narrator when it is a deliberate register in an essay or opinion piece.
```

```markdown
### Dramatic fragmentation

Watch for:

- "X. That's it."
- "X. And Y. And Z."
- "This unlocks something. [Single abstract word]."
- full stops between words for emphasis: "Every. Single. Day."
- one word in capitals for emphasis: "This is NOT optional."

Fix with complete sentences unless the fragment is clearly part of the writer's voice. Exempt speech and fiction where fragments are voice.
```

Also relevant, verbatim:

```markdown
### Repetitive paragraph endings

If every paragraph ends with a punchline, the rhythm becomes artificial.

Fix by varying paragraph length, ending on details, and letting some paragraphs land quietly. Two tests:

- Aphorism budget: at most one punchy one-liner closing a paragraph in the whole piece. Count them.
- Pull-quote test: if a sentence sounds like it was written to be quoted, rewrite it as a plain statement.
```

**Quantified claims it makes (with their stated evidentiary basis), verbatim:**

```markdown
### Rule of three

The prose keeps packing ideas into threes. LLM argumentative prose runs tricolons at close to twice the rate of expert human writers.
```

```markdown
### Nominalisation and noun density

AI prose buries actions inside abstract nouns... Corpus studies find nominalisations at roughly 1.5 to 2 times the human rate.
```

```markdown
### Superficial present-participle analysis

The text appends "-ing" phrases to simulate depth. This is one of the most durable structural tells, not a vocabulary quirk: corpus studies measure present-participial clauses in LLM prose at roughly two to five times the human rate.
```

```markdown
### Sentence length

2025-era instruction-tuned models write sentences 15 to 30% longer than human authors of comparable text... Neither is a single-sentence tell; the signal is a whole piece that sits at one length with no short sentence anywhere.
```

**Assessment:** **The best resource in this report.** It is well-founded precisely because it is *self-limiting*: it refuses to ban words on sight, defines confidence tiers, mandates genre exemptions, and explicitly separates its "keep" list (stance adverbs like "really", "just", "actually", "very", "probably", "perhaps", "I think") from its "cut" list — noting that "corpus work finds LLM prose has fewer of them than human prose, not more." That observation alone puts it far above the typical banned-word list.

The per-model fingerprinting (Claude → flat escalation; GPT → dream sequences; Gemini → external character description) is a useful, falsifiable claim, though it should be treated as reported folklore rather than established fact. One caveat: the file flags its own claim about negative parallelism as *"a diagnostic hypothesis reported second-hand, not a verified rate"* — that intellectual honesty is rare and is a reason to trust the rest.

---

### 5.2 `ai-avoidance` — a hard banned-word list with the em-dash rule

**Source:** <https://raw.githubusercontent.com/itechmeat/llm-code/f53cef9bbfba29e5638afabb4c61677ba7af27dd/skills/social-writer/references/ai-avoidance.md>
**For:** a blunt, mechanically applicable blocklist. **Length:** long. **Notable:** it is business/technical writing rather than fiction, but two elements transfer directly to prose: the **em-dash rule** and the **sentence-length variance demonstration**. It also cites a useful test.

The core diagnostic, verbatim:

```markdown
**The test:** If you can swap out the subject, names, and locations and the content remains equally valid, it's slop.
```

Banned verbs, verbatim:

```markdown
| Word          | Why Banned                   | Alternative     |
| ------------- | ---------------------------- | --------------- |
| delve         | ChatGPT's signature word     | explore, look at|
| embark        | "Beginning a journey" cliché | start, begin    |
| unleash       | Hyperbolic                   | release, enable |
| harness       | Tech buzzword                | use             |
| unlock        | "Unlock the secrets" pattern | enable, open    |
| navigate      | "Navigate the landscape"     | work with, handle|
| revolutionize | Hyperbolic                   | change          |
| foster        | Corporate-speak              | build, support  |
| elevate       | Vague improvement            | improve         |
| leverage      | Business jargon              | use             |
| underscore    | Overly formal                | highlight, show |
| showcase      | Exhibition language          | show, demo      |
| streamline    | Process cliché               | simplify        |
| spearhead     | Leadership cliché            | lead            |
| facilitate    | Academic                     | help, enable    |
| illuminate    | Academic                     | explain, clarify|
| bolster       | Academic                     | support         |
| refine        | Academic (sometimes OK)      | improve         |
```

Banned nouns and phrases, verbatim (abridged to the fiction-relevant rows):

```markdown
| Word         | Why Banned               | Alternative   |
| ------------ | ------------------------ | ------------- |
| tapestry     | "Rich tapestry" cliché   | (be specific) |
| realm        | Fantasy-speak in tech    | area, field   |
| landscape    | "Navigate the landscape" | field, space  |
| paradigm     | Academic buzzword        | model, pattern|
| synergy      | Corporate buzzword       | (cut it)      |
| beacon       | Guidance metaphor        | guide         |
| testament    | Evidence cliché          | proof, sign   |
| game-changer | Hyperbolic impact        | big change    |
| cornerstone  | Foundation cliché        | foundation    |
| catalyst     | Change metaphor          | trigger       |
| ecosystem    | Tech buzzword            | system        |
| deep dive    | Exploration cliché       | look, analysis|
```

The em-dash rule, verbatim:

```markdown
### Em-Dash (—): BANNED ENTIRELY

Em-dashes are **the** signature of AI writing. GPT-4 uses ~10x more em-dashes than GPT-3.5.

**Instead use:**

- Commas for mild pauses
- Parentheses for asides
- Periods for separate sentences
- Colons for explanations
- Semicolons for related clauses

**Before (AI):**

> The system processes requests in real-time—analyzing patterns, executing tools, and returning results—all within milliseconds.

**After (human):**

> The system processes requests in real-time. It analyzes patterns, executes tools, and returns results, all within milliseconds.
```

And the sentence-length demonstration, verbatim:

```markdown
### Uniform Sentence Length

**Problem:** AI generates sentences averaging 25-30 words with minimal variation.

**Fix:** Deliberately vary length. Some 5 words. Some 40.

**Before (AI):**

> The model processes input through multiple layers of transformation. Each layer applies attention mechanisms to understand context. The final layer produces output tokens sequentially.

All sentences ~10 words. Mechanical rhythm.

**After (human):**

> The model processes input through multiple layers. Each layer? Attention mechanisms that build context understanding. The final layer produces tokens one by one, which is why responses stream rather than appear all at once. Simple concept, but the implications are massive.

Sentence lengths: 7, 7, 19, 8 words. Natural rhythm.
```

**Assessment:** **Mixed, and worth flagging clearly.** The word tables are *broadly* well-founded as a heuristic — those words genuinely do spike in LLM output. But `better-writing` is right and this file is wrong on two counts:

1. **"Em-dash: BANNED ENTIRELY" is folklore.** Em-dash frequency is a real distributional difference, but the em-dash is a legitimate and heavily used mark in published literary fiction. Banning it outright produces stilted prose. `better-writing`'s version is the correct one: *"No em dashes or en dashes remain in strict de-AI rewrites... Exempt literary and editorial long-form where dashes are the writer's voice."*
2. **Reflexive word bans damage text.** "Being on a tell list is not a failure, and neither is a word you would not have chosen: 'delve' carries its sentence's meaning, so it is a word choice, not filler" (`better-writing`).

**Use this file for the em-dash *awareness* and the sentence-variance demonstration; do not paste its word list into a fiction system prompt as a hard ban.** Also note: it is business-writing tuned, and several entries ("leverage", "robust", "scalable") are legitimately correct in technical genres.

---

### 5.3 `Arcanea anti-trope` — a fiction-native banned lexicon

**Source:** <https://raw.githubusercontent.com/frankxai/arcanea/main/arcanea-skills-opensource/skills/arcanea/anti-trope/SKILL.md>
**For:** a fantasy-writing project's banned-word protocol. **Length:** ~600 words. **Notable:** it pairs every banned word with a *reason* and a replacement, and adds structural-trope rules (Chosen One, Ancient Evil Awakens, Magic Feather) and a naming protocol.

Verbatim, the banned lexicon table (abridged to representative rows):

```markdown
| The Forbidden Word | Why It's Banned | The Better Alternative |
|--------------------|-----------------|------------------------|
| **Delve** | Overused, implies generic depth without detail. | Investigate, excavate, study, pierce, analyze. |
| **Tapestry** | The ultimate AI cliché for complexity. | Network, system, architecture, collision, knot. |
| **Unleash** | Hyperbolic, comic-book power fantasy. | Release, unbind, trigger, deploy, open. |
| **Elevate** | Corporate marketing speak disguised as magic. | Raise, sharpen, refine, heighten, transcend. |
| **Unlock** | Gamified language. | Access, reveal, decrypt, open, solve. |
| **Symphony** | Unless actual music is playing, it's lazy. | Coordination, alignment, resonance, chorus. |
| **Nestled** | Every AI village is "nestled". | Hidden, perched, buried, anchored, set. |
| **Testament** | "A testament to..." is passive filler. | Proof, scar, monument, result, evidence. |
| **Realms** | (Context specific) Don't use for "areas". | Domains, zones, territories, disciplines. |
| **Nexus** | Generic sci-fi center. | Hub, core, convergence, heart, intersection. |
| **Whispers** | "Whispers of the past..." is a trope. | Echoes, records, dust, scars, remnants. |
```

The naming protocol, verbatim:

```markdown
### The "Star Wars" Rule
Names must not sound like random syllables (e.g., *Xyloph*, *Zorpt*). They must have etymological roots (Latin, Greek, Norse, Sanskrit) or clear phonetics.

**Bad:** *Kael'thas*, *Xylar*, *Morpheus* (Matrix stolen).
**Good:** *Lumina* (Light), *Nero* (Black/Water), *Vorun* (Vor/Truth).

### The "Noun-Verb" Rule
Avoid "The [Adjective] [Noun]" formula for everything.
**Bad:** *The Silent Watcher*, *The Dark Blade*, *The Eternal Flame*.
**Good:** *Azariel*, *The Hungry Void*, *Yggdrasil*.
```

The structural tropes section, verbatim:

```markdown
### The "Chosen One" Trap
Arcanea is about **collaboration**, not a single savior.
*   **Avoid:** "Only you can save the realm."
*   **Embrace:** "Only together can we sustain the Arc."

### The "Ancient Evil Awakens" Trap
*   **Avoid:** A generic dark lord waking up because "it is time."
*   **Embrace:** Systems decaying due to neglect (Entropy). The Dark Lord (Malachar) is a *result* of broken compassion, not just "evil".

### The "Magic Feather" Trap
*   **Avoid:** Artifacts that do everything for you.
*   **Embrace:** Tools that amplify *effort*. Magic requires cost (Energy Laws).
```

And its read-aloud test, verbatim:

```markdown
## 4. The "Human Check"
Before finalizing any text, read it aloud. If you sound like a movie trailer voiceover ("In a world where..."), delete it. If you sound like a marketing brochure ("Elevate your experience..."), delete it.

**The Goal:** Write like a historian of a world that actually exists.
```

**Assessment:** **Partly well-founded, partly project-specific.** The banned list is sensible and the "why it's banned" column is the right construction. The naming rules (avoid apostrophe-syllable fantasy names; avoid "The [Adjective] [Noun]") target real AI fantasy tells. The structural-trope section is genuinely good craft advice. **But:** the *Better Alternative* column is itself a trap — swapping "tapestry" for "network" is exactly the **synonym-cycle** failure `better-writing` warns about ("a synonym swap leaves the rhythm and shape that readers notice"). And the whole thing is authored for one specific fictional universe ("Arcanea", "the Arc", "Malachar"), so it transfers as *pattern* but not as *text*. **Verdict: steal the structure (banned word → why → replacement *principle*), not the word pairs.**

---

### 5.4 The Chinese "AI-flavor banned words and sentence patterns" table (oh-story-claudecode)

**Source:** <https://raw.githubusercontent.com/zenstory-ai/oh-story-claudecode/main/skills/story-short-write/references/banned-words.md> (MIT)
**For:** a web-fiction deslop pass. **Length:** ~1,200 words in tables. **Notable:** **the most granular banned-pattern taxonomy I found anywhere** — it grades each pattern by "toxicity" (★ to ★★★★★), gives an erroneous example, and prescribes the *fix*, not just the ban. It also splits tier-1 (replace on sight) from tier-2 (density control only) — a distinction most English-language lists miss entirely.

Verbatim, the highest-severity pattern table:

```markdown
| 毒级 | 句式 | 错误例 | 修法 |
|------|------|--------|------|
| ★★★★★ | "不是A，（而）是B" / "不是A，不是B，（而）是C"（"而"可省略，省掉也算命中）| "他不是冷漠，而是绝望" | 直接写 B 或用更自然的表达 |
| ★★★☆☆ | 跨段「不是A。/也不是B。/只是C。」 | 「不是嚎啕大哭。/也不是扯着嗓子喊不舍。/只是一个人走远了……」 | 语义复核；重复提纲或拖慢画面时压成 C，有辩解/悬念排除功能可保留 |
| ★★★★ | "，带着……" 万能状语 | "他笑了一下，带着一丝不易察觉的嘲讽" | 删掉状语留主句，或换具体动作 |
| ★★★★ | 无情绪声线："声音不大，却带着……" / "语气毫无波澜" / "平静无波" / "声音平直/平平/听不出情绪" | "她声音不大，却带着不容置疑的力量" | 直接写台词内容、声音特征或动作 |
| ★★★★ | "他/她知道……" | "他知道这一切都来不及了" | 用行为展示认知 |
| ★★★ | "仿佛/犹如/宛若……一般" | "仿佛能穿透一切一般" | 删掉或白描 |
| ★★★ | "眼中闪过一丝……" / "嘴角勾起一抹……" | "眼中闪过一丝悲伤" | 删掉；写他当场说的话或做出的决定 |
| ★★★ | "心中涌起一股……" / "心头一震" | "心中涌起一股暖流" | 写它改变了什么：选择、台词、物件或后果 |
| ★★★ | 抽象命运/开端收束："命运……棋局/獠牙" / "这一刻终于明白" / "反击才刚刚开始" | "命运终于露出獠牙；属于他的反击才刚刚开始" | 回到角色当下可见的文件、动作、对话或物理后果 |
| ★★ | 章末预告 "他不知道的是……" | "他不知道的是，更大的风暴即将来临" | 用具体钩子物件/事件收束，避免空泛预告 |
```

**Key English translations (the four most transferable patterns):**

```
★★★★★  "Not A, but B" / "Not A, not B, but C"
        e.g. "He wasn't cold — he was desperate."
        Fix: write B directly, or find a more natural expression.
        Note: this is flagged as the single most toxic pattern.

★★★★   ", with a ..." — the universal adverbial
        e.g. "He smiled, with a trace of barely-perceptible mockery."
        Fix: delete the adverbial, keep the main clause; or substitute a concrete action.

★★★★   Emotionless vocal timbre: "her voice wasn't loud, yet carried..." /
        "her tone was utterly flat" / "so calm it betrayed nothing"
        e.g. "Her voice wasn't loud, yet carried unquestionable authority."
        Fix: write the actual line, a vocal characteristic, or an action.

★★★    "In his/her eyes flashed a trace of ..." / "the corner of the mouth
        hooked into a ..."
        e.g. "A trace of sadness flashed in his eyes."
        Fix: delete it; write what they say right now or what decision they make.
```

The tier-1 vocabulary lists, verbatim:

```markdown
### 情态类
仿佛、犹如、宛若、如同、一丝、一抹、些许、几分、隐约、毫无征兆、几不可闻、微不可察

### 动作类
深吸一口气、不禁

### 表情类
眼中闪过、嘴角勾起、眉头微皱、眉眼低垂、瞳孔微缩、瞳孔收缩、瞳孔一缩、指节泛白、眼神锐利、目光锐利

### 心理类
心中一动、心头一震、心下了然、心中暗道、心底泛起、不由得、心中一凛

### 判断类
不容置疑、不容置喙、不易察觉、显而易见、毫无疑问、不可否认、前所未有

### 形容类
坚定、闪烁着光芒、狡黠、深邃、凛冽、冰冷

### 过渡类
不由自主、情不自禁、自然而然、话锋一转
```

```markdown
## 二级禁用词（高频出现时替换）

### 弱化副词（密度控制）
缓缓、微微、轻轻、淡淡（每千字合计 ≤3；这四个词同时计入 `cliche-density-tic` 的套词密度统计；孤立自然使用可保留，成串出现或每个动作都垫一个时才替换）
```

Translation of that last one — this is the most sophisticated rule in the file:

```
Tier-2 banned words (replace only when they occur at high frequency)

Weakening adverbs (density control):
  缓缓 (slowly), 微微 (slightly), 轻轻 (gently), 淡淡 (faintly)
  Combined limit: ≤3 per 1,000 characters. These four also count toward the
  cliche-density-tic statistic. An isolated natural use may be kept; replace only
  when they appear in strings, or when one is padded onto every single action.
```

Also notable, the punctuation rule, verbatim:

```markdown
**标点**：正文（含叙述和对话）禁用破折号 `——`/`—`、双连字符 `--` 和省略号停顿，改用句号、逗号、短句或动作断句；不设置对话破折号例外。
```

> Punctuation: in the body text (narration and dialogue alike) the dash `——`/`—`, the double hyphen `--`, and the ellipsis-as-pause are banned; use full stops, commas, short sentences, or action beats instead. No exception is made for dialogue dashes.

**Assessment:** **Outstanding — and the single best-designed anti-slop artifact I found.** Four things make it work:

1. **Severity grading with an enforcement rule** ("★★★★★ 命中一处就要改" — a ★★★★★ hit requires a fix on a single occurrence; lower tiers are density-based). This avoids the all-or-nothing problem of naive word bans.
2. **Two-tier structure**: tier 1 = words that essentially never occur in human web-fiction corpora, replace on sight; tier 2 = words humans do use, controlled by *density*. The file's own rationale is exactly right: *"只收真人语料里几乎不出现、AI 特有的词。真人高频使用的自然副词和虚词不进一级，走二级密度控制"* ("Tier 1 only takes words that essentially never appear in human corpora and are AI-specific. Natural adverbs and function words that humans use frequently do not enter tier 1; they go to tier-2 density control.")
3. **Every entry has a fix that is a craft move, not a synonym.** "Delete the adverbial, keep the main clause." "Write what they say right now or what decision they make." "Write what it changed: a choice, a line, an object, or a consequence." The "眼中闪过一丝悲伤" → *write what they say or decide instead* is a genuinely better instruction than any synonym substitution.
4. **It names the cross-paragraph pattern**, not just the phrase: the "不是A。/也不是B。/只是C。" negation-ladder spanning three paragraphs is a real AI cadence that word-level filters miss.

**Caveats:** Chinese-language web fiction (网文) has its own conventions, so the specific words do not transfer. The ★★★☆☆ entry is honestly marked as needing semantic review rather than automatic replacement — good discipline. The dash ban is stricter than I'd endorse for English literary fiction.

**Companion document** describing the 7-Gate deslop process (Gate A banned words, B sentence patterns, C emotional idling, D uniform rhythm, E flat dialogue voices, F ending-elevation, G explanatory omniscience) with deletion caps of 15%/25%/35% by severity: <https://github.com/zenstory-ai/oh-story-claudecode/blob/main/docs/how-to-remove-ai-flavor-from-web-fiction.md>

---

## 6. Long-context strategies (chapter N of a novel)

### 6.1 Rolling summary with a structured JSON contract

**Source:** <https://huggingface.co/spaces/build-small-hackathon/Omniscient-Novel-Reader/blob/main/novel_parser/pass1_characters.py>
**For:** processing a novel chapter-by-chapter under a token budget while accumulating state. **Length:** ~250 words. **Notable:** it demonstrates the **rolling-summary + accumulator** pattern with an explicit output schema, and it explicitly notes the token-budget purpose in its module docstring: *"A rolling summary of previous chapters (for token budget)."*

```python
_EXTRACTION_USER = """\
STORY SO FAR (summary of previous chapters):
{rolling_summary}

CHARACTERS FOUND SO FAR:
{characters_json}

CURRENT CHAPTER ({chapter_index}/{total_chapters}) — "{chapter_title}":
---
{chapter_text}
---

Tasks:
1. Extract ALL named characters appearing in this chapter (new or previously seen).
2. For new characters: provide name, aliases (other names/titles/nicknames used),\
 gender (male/female/unknown), age_range (child/teen/young/young_adult/adult/middle_aged/elderly/unknown),\
 role_hint (protagonist/deuteragonist/antagonist/major/minor), description.
3. For existing characters from the "CHARACTERS FOUND SO FAR" list: note any new aliases,\
 updated description, or role changes. Only include characters that have new information.
4. Write a 2-3 sentence summary of this chapter's key events.

Respond ONLY with valid JSON:
{{
  "new_characters": [
    {{"name": "...", "aliases": [...], "gender": "...", "age_range": "...",\
 "role_hint": "...", "description": "...", "first_seen_here": true}}
  ],
  "updated_characters": [...],
  "chapter_summary": "..."
}}
"""
```

The consolidation pass, verbatim:

```python
_CONSOLIDATION_USER = """\
Novel title: "{novel_title}"

All characters extracted (may contain duplicates or characters referred to by different names):
{all_characters_json}

Full chapter summaries:
{chapter_summaries}

Tasks:
1. Merge any duplicate characters (same person referred to by different names/titles/nicknames).
   Keep the most commonly used name as the primary name, others as aliases.
2. For each unique character, provide the final consolidated profile:
   name, aliases, gender, age_range, role (protagonist/deuteragonist/antagonist/major/minor).
   description (comprehensive summary across all chapters).
3. Determine the narrator type:
   - "character": if the novel is narrated in first person by a character in the story.\
 Provide that character's name.
   - "external": if the novel uses third-person or omniscient narration.
   Provide brief reasoning.

Respond ONLY with valid JSON:
{{
  "characters": [...],
  "narrator": {{
    "narrator_type": "character" or "external",
    "narrator_character_name": "..." or null,
    "reasoning": "..."
  }}
}}
"""
```

**Assessment:** Well-founded. It is the *reading* direction (novel → state), but it is directly invertible for *writing*: keep a rolling summary + a structured character/motivation accumulator, and inject both when drafting chapter N. **The critical design detail is task 3: "Only include characters that have new information."** Without that, the accumulator re-emits the whole cast every chapter and the context grows without bound — which defeats the entire purpose. The separate consolidation pass (merge aliases, dedupe) is also good practice, because rolling extraction reliably produces "Lord Ashford" and "Ashford" as two people.

**Limitation:** the summary is fixed at "2-3 sentences", which is lossy for a novel. For drafting, you want a *typed* summary (see §6.3).

---

### 6.2 What a chapter summary must preserve (Story Skills `chapter-writing` context packing)

**Source:** <https://raw.githubusercontent.com/danjdewhurst/story-skills/main/skills/chapter-writing/SKILL.md>, plus <https://github.com/danjdewhurst/story-skills/blob/main/docs/skills.md>
**For:** deciding what to inject when drafting chapter N. **Notable:** the most sophisticated context-selection design in this report — it distinguishes **character knowledge** from **reader knowledge** and enforces a *token budget* with explicit "left out" semantics.

The knowledge rule, verbatim:

> "A line marked `reader-knowledge` may be used in the prose. A line marked `character-knowledge` and `do not reveal` is known to the POV from a flashback the reader has not reached; write them as knowing it, and do not put the fact on the page. Everything else from a later chapter is left out."

The budget discipline, verbatim:

> "If it ends with 'Left out to fit the budget', do not open the files that list names, even though the line under it says to read them: they are whole files, and context filtered their items to the target. `continuity/state.md` holds knowledge learned later, character and location files hold later `progressions`, and promise and clue files hold their payoffs. Instead rerun with a larger `--budget`, or run with `--json` and use the `text` of each item in `sections` whose `included` is `false`, which is already filtered."

And what the packed context contains, verbatim:

> "It prints, within a token budget (`--budget`, default 6000), the chapter's outline and cast, the `story.md` essentials (including the book's language, writing mode, chapter numerals, and count unit) and `style-sheet.md` rules, the POV character's knowledge and state at that point, cards for the characters on the page and the chapter's locations (with their `progressions` applied at this chapter), open promises, clues, and questions, and summaries of the previous scenes."

**Assessment:** **Well-founded and the most important idea in this section.** The crucial insight is the **`do not reveal` marker combined with the "write them as knowing it, but do not put the fact on the page" instruction.** This solves the single hardest long-fiction problem: a POV character who learned something in a flashback the reader hasn't seen must *act* on that knowledge while the narration must not state it. Naive story-bible injection gets this wrong in both directions — either the character acts ignorant of what they know, or the text spoils the reveal.

The second key idea is the **budget with explicit omission reporting**. Rather than silently truncating (which makes the model hallucinate missing facts) or reading whole files (which blows the budget and dilutes attention), it reports what was left out so the caller can decide to raise the budget. The design principle: **"Do not open project files for background" during drafting** — the context pack is the interface, and circumventing it is what reintroduces inconsistency.

---

### 6.3 File-system-as-memory rather than context-as-memory (oh-story-claudecode)

**Source:** <https://github.com/zenstory-ai/oh-story-claudecode/blob/main/docs/ai-long-novel-character-consistency.md>
**For:** keeping a novel consistent over 100+ chapters. **Notable:** it correctly diagnoses *why* long AI novels drift, and its answer is architectural rather than prompt-level.

Its diagnosis, verbatim:

> "崩人设的直接原因几乎都是同一个：模型每次续写拿到的上下文，要么是"最近几章正文"（于是忘了第 3 章埋的伏笔），要么是"全书摘要"（于是把还没发生的计划当成已发生的事实）。上下文窗口再大，也小于一部 200 万字的书；而且越塞越多，模型对单条设定的注意力越低。"
>
> "所以问题不是"模型记不住"，而是"该给它看什么"。"

Translation:

> "The direct cause of character-collapse is almost always the same: the context the model gets for each continuation is either 'the last few chapters of prose' (so it forgets a setup planted in chapter 3), or 'a whole-book summary' (so it treats a not-yet-happened plan as an established fact). However large the context window, it is smaller than a two-million-character book; and the more you stuff in, the lower the model's attention to any single setting."
>
> "So the problem is not 'the model can't remember' but 'what should you show it'."

The three design rules, verbatim:

```markdown
1. **一个权威，其余派生。** `_tracking-state.json` 是唯一可写的真相；`上下文.md`、角色快照、`伏笔.md`、两条时间线都由它确定性生成。所有追踪写入走 `scripts/tracking_commit.py`，禁止手改派生文件，因此不会出现"两份状态各说各话"。
2. **作者真相和读者已知分开记。** `时间线/作者真相.md` 记故事里真正发生了什么，`时间线/读者已知.md` 记读者到当前章为止看到了什么。写第 40 章时，模型能看到"凶手是谁"属于作者真相，但"主角还不知道"，于是不会让角色提前开口。
3. **每章写入是有上限的增量。** `逐章记录/第NNN章.md` 目标 ≤1536 字节、硬上限 3072 字节，只记会影响后续连续性的变化。状态不会随章数线性膨胀，第 300 章的续写上下文和第 30 章差不多大。
```

Translation:

```
1. One authority, everything else derived. `_tracking-state.json` is the only
   writable truth; `上下文.md` [the context card], character snapshots, `伏笔.md`
   [foreshadowing], and the two timelines are all deterministically generated from
   it. All tracking writes go through `scripts/tracking_commit.py`; hand-editing
   derived files is forbidden, so you never get "two states each telling a
   different story".
2. Author-truth and reader-knowledge are recorded separately. `时间线/作者真相.md`
   records what actually happened in the story; `时间线/读者已知.md` records what the
   reader has seen up to the current chapter. When writing chapter 40, the model can
   see that "who the murderer is" belongs to author-truth, but that "the protagonist
   does not yet know" — so it will not let the character speak early.
3. Each chapter's write is a capped increment. `逐章记录/第NNN章.md` targets
   ≤1536 bytes, hard cap 3072 bytes, recording only changes that affect later
   continuity. State does not grow linearly with chapter count; the continuation
   context for chapter 300 is about the same size as for chapter 30.
```

And the single-chapter loop, verbatim:

```markdown
1. **写前必读，先读后写。** 读本章细纲、卷纲和当前追踪状态，写前记下本轮约束：本章字数范围、必须发生、禁止发生、时间锚点、停笔点、章尾新债。这些项目事实优先于任何写作技法参考。
2. **只加载必需信息。** 写这章需要出场的角色，读 `设定/角色/{名}.md`（稳定人设）和 `追踪/角色状态/{名}.md`（当前位置、目标、关系、已知信息、未了线索）。"徐棠有个哥哥"是设定；"徐棠不知道这封信是哥哥寄的"是状态。两者分开读，模型就不会把设定当成角色知道的事。
```

Translation:

```
1. Read before writing, always. Read this chapter's detailed outline, the volume
   outline and the current tracking state; before writing, note down this round's
   constraints: chapter word range, must-happen, must-not-happen, time anchor,
   stopping point, and new debts owed at the chapter end. These project facts take
   precedence over any craft reference.
2. Load only what is necessary. For characters appearing in this chapter, read
   `设定/角色/{name}.md` (stable characterisation) and `追踪/角色状态/{name}.md`
   (current location, goal, relationships, known information, open threads).
   "Xu Tang has an older brother" is *setting*; "Xu Tang does not know this letter
   was sent by her brother" is *state*. Reading them separately prevents the model
   from treating setting as something the character knows.
```

**Assessment:** **Well-founded, and the best architectural answer in this report.** Four ideas are load-bearing and all transfer to any stack:

1. **"One authority, everything else derived."** Prevents the classic failure where the outline, the tracker and the prose each hold a different version of the truth.
2. **Author-truth vs. reader-knowledge as two separate timelines.** This is the correct data model for dramatic irony and it is the thing naive "story bible" designs get wrong.
3. **Capped incremental writes.** A hard per-chapter byte budget means state is O(1) in chapter count rather than O(N) — this is what makes 300 chapters tractable.
4. **Setting vs. state as distinct files.** "Has a brother" (setting) vs. "doesn't know the letter is from him" (state). Clean and directly implementable.

The document is also **honest about its limits**: *"追踪文件减少的是"忘记"和"提前知道"这两类错误；它不能替作者决定剧情走向，也不保证零错误"* ("Tracking files reduce the two error classes of 'forgetting' and 'knowing too early'; they cannot decide the plot for the author, and do not guarantee zero errors"). The stated boundary — that structured tracking requires the author to actually write settings and detailed outlines, and that writing *pauses* rather than falling back to a default word count when the outline is missing — is a real design commitment, not a marketing claim.

**Related, from the same project** — an 7-level deslop taxonomy with deletion caps (15%/25%/35% by severity) and three protection rules: *"改最少"* (change the least — if one word will do, don't change a sentence), *"只改怎么说，不改说什么"* (change only *how* it's said, never *what* is said), and never delete a whole paragraph. Source: <https://github.com/zenstory-ai/oh-story-claudecode/blob/main/docs/how-to-remove-ai-flavor-from-web-fiction.md>. The explicit refusal to promise detector scores — *"去 AI 味治读感，不治检测器…不写'0% AI'，不注水、不故意错字、不打乱标点"* ("de-AI-ing treats reading feel, not detectors… it does not write '0% AI', does not pad, does not insert deliberate typos, does not scramble punctuation") — is a notable piece of integrity in a space full of detector-evasion snake oil.

---

## 7. System prompts from real writing tools

### 7.1 Novelcrafter — documented prompt architecture (commercial, closed source)

**Source:** <https://www.novelcrafter.com/courses/ultimate-beginners-guide/generating-prose-with-ai>, <https://www.novelcrafter.com/help/docs/prompt-presets/prompt-preset-uses>, <https://www.novelcrafter.com/help/faq/plan/where-do-i-put-my-scene-chapter-act-book-summary-what-about-my-beats>

Novelcrafter does not publish its system prompt, but it **does publicly document the architecture**, which is more useful than a leaked prompt:

- **Codex** — a structured story bible (characters, locations, items, lore) with automatic tracking and progressions. It is injected automatically into every generation.
- **Scene beats** — the per-generation instruction (§1.3).
- **Prompt presets** — user-swappable prompt templates, with a "Tweak and Generate" mode exposing every prompt input.
- **Sections** — accept a generation but keep it beside alternatives, so multiple models' outputs can be compared before editing.
- **Continue Writing vs. Scene Beat** — the documented distinction: *"A scene beat follows your specific instruction. The continue writing option prompts the AI to keep going based on your existing text."*

**Assessment:** The architecture is well-founded and the industry consensus: **the quality lever is structured context (Codex) + a specific instruction (beat), not a clever system prompt.** Note the design decision to expose prompt inputs rather than hide them — and the author's own workflow note about generating with multiple models and hand-editing, which is honest about where the human remains necessary.

### 7.2 Story Skills — 24 skills, published in full

**Source:** <https://github.com/danjdewhurst/story-skills> (MIT) — skill catalogue: <https://raw.githubusercontent.com/danjdewhurst/story-skills/main/docs/skills.md>

This is the most complete **open-source writing-tool system prompt set** I found. Every skill is a `SKILL.md` with YAML frontmatter whose `description` field doubles as a **routing trigger list** with an explicit **"NOT for"** clause pointing to the neighbouring skill. Verbatim examples:

```yaml
---
name: chapter-writing
description: This skill should be used when the user asks to "write a chapter", "next chapter", "chapter outline", "draft chapter", "continue the story", "write a scene", "outline a chapter", or wants to write prose for a story project. NOT for planning a scene's structure, subtext, or outcome (use scene-craft), drafting without an outline (use discovery-drafting), or revising existing chapters (use revision-continuity).
---
```

```yaml
---
name: voice-style
description: This skill should be used when the user asks to "create a style sheet", "style guide", "house style", "keep the voice consistent", "voice drift", "British or American spelling", "character voices", "lint the prose", "prose check", "filter words", "said-bookisms", "overused words", "repeated phrases", "similar character names", "voice fingerprints", or wants to record and enforce the voice and surface conventions of a story project. NOT for rewriting dialogue to make the voices distinct when everyone sounds the same (use line-editing), or a character's profile or arc (use character-management).
---
```

The documentation explains the design intent, verbatim:

> "Each trigger phrase belongs to one skill, and most descriptions end with a 'NOT for' line that points neighbouring requests elsewhere. That is why similar-sounding requests can land on different skills: 'premise' goes to premise-workshop but 'controlling idea' to theme-craft, 'pacing' and 'sagging middle' go to plot-structure but 'chapter hook' to scene-craft, 'voice fingerprints' goes to voice-style but 'everyone sounds the same' to line-editing..."

And the division of labour, verbatim:

> "- **Skills make the creative decisions**, and they ask you before inventing canon.
> - **The `story` CLI does the mechanical work**: validation, registry rebuilds, word counts, link and continuity checks.
> - **Story content is plain markdown.** Agents write chapters and entity files directly."

**Assessment:** Well-founded, and the **"NOT for" routing clause is the most transferable single technique in this section.** A model given overlapping skills will pick the wrong one; a mutual-exclusion clause per skill makes routing deterministic — and the repo enforces it with a test (`test/skill-conventions.test.js` checks no two skills claim the same trigger phrase). Also notable: the machine-readable `style-sheet.md` frontmatter with `dialect`, `preferred`/`avoid` spelling pairs, `watch-words`, `allow-words`, and `samples` (a folder of the *author's own approved* prose, used as the baseline instead of fixed limits). The `allow-words` mechanism — letting a book *whitelist* words a linter flags — is the correct answer to the false-positive problem that plagues every banned-word list.

### 7.3 Storydex — a browsable, user-facing prompt library shipped in the product

**Source:** <https://github.com/TensorHub-ORG/Storydex> — prompt files under `docs/prompts/`, documented at <https://github.com/TensorHub-ORG/Storydex/blob/main/docs/guide/07-指令仓库.md>

Storydex ships a "prompt repository" panel inside the app, reading markdown files with a defined convention. Verbatim from its README:

```markdown
## 文件约定

- 使用一级标题作为指令名称。
- 使用紧随标题的引用段落 `>` 作为简短说明。
- 按用途建立一级分类目录，例如"项目包装""角色创作""世界观""剧情设计""编辑审校"。
- 可复制执行的正文必须放在第一个 `prompt` 代码块中。
- 可替换参数使用方括号，例如 `[主题]`、`[目标字数]`；程序会自动识别并展示。
- 指令必须适用于任意 Storydex 小说项目，不得写入固定角色名、固定世界观或项目专属路径。
- 默认要求 Agent 先读取当前项目证据，不把推测写成既定事实，也不在未经授权时直接覆盖正文。
```

Translation:

```
File conventions:
- Use a level-1 heading as the instruction name.
- Use the blockquote paragraph `>` immediately after the heading as a short description.
- Create top-level category directories by purpose, e.g. "project packaging",
  "character creation", "worldbuilding", "plot design", "editorial review".
- The copyable, executable body must live in the first `prompt` code block.
- Replaceable parameters use square brackets, e.g. `[主题]` (theme), `[目标字数]`
  (target word count); the program detects and displays them automatically.
- An instruction must apply to any Storydex novel project; it must not hardcode
  character names, a fixed world, or project-specific paths.
- By default, require the agent to first read the current project's evidence, to not
  write speculation as established fact, and to not directly overwrite prose without
  authorisation.
```

The shipped categories and prompt files (verified in the repo), verbatim paths:

```
docs/prompts/项目包装/01-生成小说简介.md          (generate blurb)
docs/prompts/项目包装/02-生成封面AI绘图提示词.md
docs/prompts/项目包装/03-生成书名与宣传语.md
docs/prompts/角色创作/01-创建新角色.md            (create character)  ← §3.1
docs/prompts/角色创作/02-设计角色关系网.md        (relationship web)
docs/prompts/世界观/                              (worldbuilding)
docs/prompts/剧情设计/01-制定卷纲与章节大纲.md    (volume + chapter outline)
docs/prompts/剧情设计/02-续写当前章节.md          (continue chapter)  ← §1.2
docs/prompts/编辑审校/01-项目一致性检查.md        (consistency check) ← §4.2
docs/prompts/编辑审校/02-润色与改写.md            (polish/rewrite)    ← §4.4
```

**Assessment:** **Well-founded, and its two systemic rules are the most valuable part.** Rule 6 ("must apply to any project; no hardcoded names or paths") keeps the prompt library reusable across manuscripts. Rule 7 is a **global safety default applied to every prompt in the product**: read evidence first, never launder speculation into fact, never overwrite prose without authorisation. That is a better contract than any individual prompt in the library. **Caveat:** the prompt *bodies* are competent but conventional; the framework around them is what is worth copying.

### 7.4 Anthropic's "Storytelling Sidekick" (official vendor prompt library)

**Source:** <https://docs.claude.com/en/resources/prompt-library/storytelling-sidekick> (also at the `docs.anthropic.com` and `platform.claude.com` mirrors; locale variants exist at `/ko/`, `/pt/`, `/zh-CN/`)

**Status: I could not retrieve the verbatim prompt text.** The page is client-side rendered (Next.js), the `.md` variant returns HTML, and reader proxies were blocked. I am **not** going to reconstruct it from memory or from SEO sites that paraphrase it — that would violate the verbatim requirement.

What I can verify: the prompt exists in Anthropic's official prompt library under the title "Storytelling Sidekick" / "讲故事助手" / "Parceiro de narrativas", it is catalogued as a creative-writing use case, and it appears in the library index at <https://docs.claude.com/en/resources/prompt-library/library>. Anyone needing the exact text should open the page in a browser (it renders client-side) and copy from the "Prompt" panel.

**Assessment:** flagged as unverified. Do not cite a reconstructed version as verbatim.

### 7.5 Google Vertex AI prompt gallery — screenwriting sample

**Source:** <https://docs.cloud.google.com/vertex-ai/generative-ai/docs/prompt-gallery/samples/write_and_generate_screenwriting> (also a multimodal "write story from image" sample at `.../multimodal_write_story_from_image_67`)

**Status: could not retrieve verbatim text.** The docs site serves content through a JS app loader; the extracted HTML contains only bootstrap scaffolding. Same honesty note as §7.4 — I am not reconstructing it.

---

## 8. What the best prompts have in common

Across roughly two dozen genuinely reusable artifacts, the strong ones converge on a consistent structure. The weak ones (the large majority of what's published) consistently miss it.

**1. They specify *what not to do* more precisely than what to do.**
The best artifacts are prohibition-shaped: `better-writing`'s tell catalogues, oh-story's ★-graded banned patterns, Arcanea's forbidden lexicon. Generic positive instruction ("write vivid prose with rich sensory detail") is what *everyone* writes and it produces the average of all prose on the internet. **Negative specification is where the signal is** — but it must be paired with point 2.

**2. Every prohibition comes with a *craft move*, not a synonym.**
Weak list: "don't say 'a testament to'." Strong list: "delete the adverbial and keep the main clause"; "write what they say right now or what decision they make"; "write what it changed: a choice, a line, an object, or a consequence." The Chinese file's fix column is the model here — none of its fixes are word swaps, they are all "replace the abstraction with a visible consequence." `better-writing` states the same rule explicitly: *"When a sentence carries two or more tells, rebuild its structure instead of swapping the flagged word for a synonym. A synonym swap leaves the rhythm and shape that readers notice."*

**3. They distinguish *severity* or *tier*, and forbid acting on a single signal.**
`better-writing`: Tier 1/2/3, "never edit on a single feature of any tier." oh-story: ★ to ★★★★★, with "one ★★★★★ hit requires a fix" and density limits for everything else. This matters because a flat ban list produces over-correction and stilted prose; tiering produces proportional response. **This is the single biggest differentiator between professional and amateur anti-slop prompts.**

**4. They establish *precedence orders* for conflicting sources.**
Storydex: "prose and user-confirmed content take precedence over derived summaries." Story Skills: "These project facts take precedence over any craft reference." Without an explicit precedence rule, an agent will happily rewrite correct prose to match a stale outline.

**5. They separate *setting* from *state*, and *author-truth* from *reader-knowledge*.**
"Xu Tang has an older brother" is setting; "Xu Tang doesn't know the letter is from him" is state. "Who the murderer is" is author-truth; "the reader has seen the clue" is reader-knowledge. Naive story bibles collapse these and produce the two signature long-fiction bugs: characters acting on knowledge they never acquired, and narration spoiling reveals.

**6. They tag epistemic status on every fact.**
Storydex: "project-confirmed fact / setting proposed this time / awaiting user confirmation", with unknowns written as "unknown". Revision-continuity: problems graded critical/high/medium/low, unverifiable items marked "to be verified". **This prevents the model laundering its own inventions into canon** — the primary drift mechanism.

**7. They force a plan or an outline *before* prose.**
Story Skills `chapter-writing`: context → beat outline → *user approval* → prose. Storydex: "first give 3-6 continuation plan points and continuity risks." Novelcrafter: write the beat first. Every serious system inserts a checkpoint between deciding and writing, because prose is expensive to regenerate and a bad beat wastes a whole generation.

**8. They make output *shape* explicit.**
LSG's start/continue/finish trifurcation with "do not write the chapter heading." Rolling summarisation's JSON schema with `new_characters` vs `updated_characters`. Storydex's separation of "rewritten version" from "summary of main adjustments". Ambiguous output shape is a silent cost that shows up as parse failures and re-runs.

**9. They have a *scope boundary* and say what belongs to a neighbour.**
Story Skills' "NOT for ... (use X)" routing clauses; better-writing's genre exemptions ("passive voice in a methods section... is correct, not a tell"); Arcanea's "Context specific" flags. A rule applied outside its scope is a bug, not a feature.

**10. They are honest about limits, and refuse to promise detection scores.**
oh-story: "tracking files reduce 'forgetting' and 'knowing too early'; they cannot decide the plot for the author, and do not guarantee zero errors" and "we do not write '0% AI', we do not pad, insert deliberate typos, or scramble punctuation." `better-writing` flags one of its own claims as "a diagnostic hypothesis reported second-hand, not a verified rate." **Artifacts that admit what they cannot do are systematically more trustworthy than those that don't** — and this is a very cheap signal to screen sources by.

**Structure that consistently appears, in order:**

```
(1) ROLE + SCOPE          who the model is, and the one job it has
(2) EVIDENCE TO READ      which files/context, read-first, "do not open others"
(3) CONSTRAINTS TO HOLD   invariants: POV, tense, facts, world rules, knowledge boundary
(4) PROHIBITIONS          tiered tells/patterns, each with a craft-move fix
(5) TASK PARAMETERS       this unit's goal, POV, location, word budget, must/must-not happen
(6) PROCESS               plan → approval → draft → tracking write-back
(7) OUTPUT SHAPE          exact format, with anti-chatter guards
(8) EPISTEMIC TAGS        confirmed / proposed / unknown; severity levels
(9) SCOPE BOUNDARY        what to hand to a neighbouring skill
```

---

## 9. Well-founded vs. folklore

A candid scorecard. This section is the most useful part of the report for anyone deciding what to actually implement.

### Well-founded (adopt)

| Technique | Why it holds up |
|---|---|
| **Structured story bible injected per generation** | Universal across every serious tool (Novelcrafter Codex, Storydex, Story Skills). The context *is* the product. |
| **Setting vs. state as separate records** | Directly prevents "character acts on knowledge they don't have" — the #1 long-fiction bug. |
| **Author-truth vs. reader-knowledge timelines** | Correct data model for dramatic irony; needed for any reveal-driven plot. |
| **Rolling summary + structured accumulator** | Standard, and the "only include new information" clause is what keeps it O(1) in chapter count. |
| **Scene Goal / Conflict / Outcome** | Swain's model; 50+ years of craft consensus. |
| **Plan → approve → draft → write-back loop** | Cheap gate; every mature system has it. |
| **Chapter summary capped at a fixed size** | Bounded context per chapter; prevents quadratic growth. |
| **Reverse outline (manuscript vs. plan diff)** | Standard professional editorial technique. |
| **Removability audit ("would removing this change anything downstream?")** | Direct test for filler; unambiguous. |
| **Ordered revision ladder (structure → … → proof)** | Prevents polishing sentences that later get cut. |
| **`voice-avoid` lists (what a character would never say)** | Easier to specify and check than abstract "voice". |
| **Read-aloud check** | Real, and LLM prose genuinely fails it ("movie trailer voiceover"). |
| **Sentence-length variance** | Well-documented model behavior; the fix is mechanical and effective. |
| **Named-never-revealed knowledge marking** | Solves the flashback/secret-POV problem cleanly. |
| **Epistemic tagging of invented facts** | The direct antidote to canon drift. |
| **Density limits rather than absolute word bans** | The right way to control overused-but-legitimate words. |

### Well-founded but **easily over-applied** (adopt with restraint)

| Technique | The trap |
|---|---|
| **Banned-word lists** | Swap-the-synonym preserves the rhythm that actually reads as AI. `better-writing` is right: a lone "delve" in a voice-approved draft is a word choice, not a failure. Use `allow-words` whitelists. |
| **"Show, don't tell"** | Stated absolutely it produces the opposite failure: 600 words of eyebrow raises for one emotion. The better formulation (from the corpus data) is *name the fact and the consequence* — "two of the five resigned the same day." |
| **Em-dash bans** | A real distributional tell, but em-dashes are legitimate literary punctuation. Exempt literary long-form; treat as a dial, not a switch. |
| **"Avoid AI-sounding words" without a genre exemption** | "robust", "scalable", "leverage" are correct in technical writing. |
| **Scene/sequel and beat sheets** | Useful scaffolds that, applied rigidly, produce the "tidy single-track plot with clean resolution" the corpus study identifies as *itself* an AI tell. |

### Folklore or hype (be skeptical)

| Claim | Assessment |
|---|---|
| **"This prompt writes a full novel"** | No. Every system that actually works is multi-pass with human approval gates. Single-prompt novel generators produce drift by chapter 5. |
| **Detector evasion / "0% AI" guarantees** | Not achievable and not desirable. oh-story explicitly refuses it. "Humanisers" measurably degrade text — `better-writing` cites a benchmark of 19 such tools where *every one* degraded the original. |
| **Banning a word outright fixes AI feel** | The tell is *cluster density and uniform cadence*, not any one word. `better-writing`: "One feature is never a verdict." |
| **"Make it more literary / add sensory detail"** | This is how you get purple slop. Specificity beats decoration: "Miata" > "car"; a named consequence > an adjective. |
| **Model-specific magic words ("act as a bestselling author")** | The role framing does very little. What works is concrete constraints, real context injection, and negative specification. |
| **Longer system prompts are better** | Diminishing returns and dilution. `better-writing` is long because it is a *reference* loaded conditionally, not because length helps. Story Skills deliberately keeps `SKILL.md` short and pushes detail into `references/` loaded on demand: *"Reference files hold templates and craft guidance that the skill loads when it needs them, so the main instructions stay short."* |
| **Boilerplate "rich in detail and narrative depth" style instructions** | Generic. They specify nothing and produce the average. |
| **Character-sheet questionnaires with 15 bullet fields** | Reliably produce padded, generic output. §3.3 is the example. |
| **Per-model "fingerprints" (Claude does X, GPT does Y)** | Plausible and reported, but treat as folklore — the one source that offers them cites no primary study for the per-model claims. |
| **"Chain of thought improves creative writing"** | Unverified. What's verified is that **plan-then-draft** helps (it's a checkpoint, not a reasoning trick). |
| **Anything that promises consistency without structured state** | The oh-story diagnosis is correct: no context window is larger than a novel. Prompt-only consistency fails at scale; it needs files. |

---

## 10. Source index

**Primary open-source prompt repositories (all MIT or similarly permissive):**

| Repo | What it is | Best material |
|---|---|---|
| [forjd/better-writing](https://github.com/forjd/better-writing) | Anti-slop / anti-AI prose skill, corpus-grounded, v2.0.0 | `references/ai-writing-patterns.md`, `structures-and-phrases.md`, `genre-tells.md`, `preflight.md` — **[§5.1](#51-better-writing--the-most-rigorous-anti-slop-reference-available)** |
| [danjdewhurst/story-skills](https://github.com/danjdewhurst/story-skills) | 24 skills for end-to-end novel writing, with a `story` CLI | `chapter-writing`, `plot-structure/references/structure-models.md`, `voice-style`, `revision-continuity` — §§1.1, 2.2, 2.4, 3.2, 4.3, 6.2, 7.2 |
| [zenstory-ai/oh-story-claudecode](https://github.com/zenstory-ai/oh-story-claudecode) | Chinese web-fiction system; 13 skills, deslop gates, tracking architecture | `references/banned-words.md`, `docs/ai-long-novel-character-consistency.md`, `docs/how-to-remove-ai-flavor-from-web-fiction.md` — **[§5.4](#54-the-chinese-ai-flavor-banned-words-and-sentence-patterns-table-oh-story-claudecode)**, **[§6.3](#63-file-system-as-memory-rather-than-context-as-memory-oh-story-claudecode)** |
| [TensorHub-ORG/Storydex](https://github.com/TensorHub-ORG/Storydex) | Desktop novel tool shipping a browsable prompt library | `docs/prompts/**` — §§1.2, 3.1, 4.2, 4.4, 7.3 |
| [hahagood/snowflake-novel-subagents](https://github.com/hahagood/snowflake-novel-subagents) | 15 Claude Code subagents implementing the Snowflake Method | `three-act-architect.md`, `scene-planner.md`, `consistency-checker.md` — §§2.3, 4.1 |
| [frankxai/arcanea](https://github.com/frankxai/arcanea) | Fantasy project's anti-trope + naming protocol | `skills/arcanea/anti-trope/SKILL.md` — [§5.3](#53-arcanea-anti-trope--a-fiction-native-banned-lexicon) |
| [AgentDock/prompt-library](https://github.com/AgentDock/prompt-library) | General prompt library, `writing/creative/` | `chapter-outline-generator.mdx` (**best outline prompt in the report**), `character-development.mdx` — §§2.1, 3.3 |
| [pavelkudrna83/creative-writing-skill](https://github.com/pavelkudrna83/creative-writing-skill) | Craft-fundamentals skill from René Nekuda's course | `SKILL.md` — 12-lesson craft syllabus with an interactive workflow (good on clichés, detail specificity, hero/antagonist pairing, and consistency) |
| [lornshrimp/Lorn.NovelWriteSkills](https://github.com/lornshrimp/Lorn.NovelWriteSkills) | Large Chinese novel-workflow asset library | Style-Distillation and multi-platform adaptation pipeline design; chapter control cards; deslop skills |
| [itechmeat/llm-code](https://github.com/itechmeat/llm-code) | Agent skills, includes a social/technical writer | `skills/social-writer/references/ai-avoidance.md` — [§5.2](#52-ai-avoidance--a-hard-banned-word-list-with-the-em-dash-rule) |

**Academic (peer-reviewed, prompt templates in appendices):**

| Source | Content |
|---|---|
| [The LSG Challenge Workshop at INLG 2024](https://aclanthology.org/2024.inlg-genchal.13.pdf) | Start/continue/finish chapter prompts — [§1.4](#14-verbatim-academic-chapter-generation-prompts-lsg-challenge-inlg-2024) |
| [build-small-hackathon/Omniscient-Novel-Reader](https://huggingface.co/spaces/build-small-hackathon/Omniscient-Novel-Reader/blob/main/novel_parser/pass1_characters.py) | Rolling-summary + accumulator prompts with JSON schema — [§6.1](#61-rolling-summary-with-a-structured-json-contract) |
| [EACL 2026 Findings 94](https://aclanthology.org/2026.findings-eacl.94.pdf) | Long-story outline generation prompts (plot-point extraction) |
| [EMNLP 2024 main 456](https://aclanthology.org/2024.emnlp-main.456.pdf) | Sequential segment summarisation ("gradually update one comprehensive summary of the character") |
| [arXiv 2502.13028](https://arxiv.org/pdf/2502.13028) | Story-rule extraction prompts (author-written vs. average-author contrast) |

**Vendor documentation and craft references:**

| Source | Content |
|---|---|
| [Novelcrafter — Generating Prose with AI](https://www.novelcrafter.com/courses/ultimate-beginners-guide/generating-prose-with-ai) | Scene beats, Codex injection, Sections — [§1.3](#13-beat-driven-scene-generation-with-specificity-enforcement-novelcrafter-scene-beats) |
| [Novelcrafter — Improving AI Output for Scene Beats](https://www.novelcrafter.com/courses/ultimate-beginners-guide/improving-ai-output-for-scene-beats) | "Brief it like a human co-writer" calibration rule |
| [Novelcrafter — Prompt Presets](https://www.novelcrafter.com/help/docs/prompt-presets/prompt-preset-uses) | Swappable prompt templates, model-per-scene-type workflow |
| [Novelcrafter — Where do I put my scene/chapter/act/book summary?](https://www.novelcrafter.com/help/faq/plan/where-do-i-put-my-scene-chapter-act-book-summary-what-about-my-beats) | Context placement conventions |
| [Anthropic prompt library — Storytelling Sidekick](https://docs.claude.com/en/resources/prompt-library/storytelling-sidekick) | **Exists but not retrievable verbatim** (client-rendered) — see [§7.4](#74-anthropics-storytelling-sidekick-official-vendor-prompt-library) |
| [Google Vertex AI prompt gallery — screenwriting](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/prompt-gallery/samples/write_and_generate_screenwriting) | **Not retrievable verbatim** (JS-rendered) — see [§7.5](#75-google-vertex-ai-prompt-gallery--screenwriting-sample) |
| [Randy Ingermanson — Snowflake Method](https://www.advancedfictionwriting.com/articles/snowflake-method/) | The original method; the basis for §§2.3–2.4 |
| [Dan Harmon's Story Circle](https://www.notion.so/templates/dan-harmon-story-circle) | The eight-step circle, tabulated in §2.2 |

**Two reproduction caveats, stated plainly:**

1. **The Anthropic and Google prompts (§§7.4–7.5) are not quoted**, because their pages are client-rendered and I could not obtain the text. Reconstructed versions circulating on third-party sites were not used. Open the pages in a browser to copy the real text.
2. **Chinese-language sources (§§1.2, 3.1, 4.2, 4.4, 5.4, 6.3)** are quoted verbatim in the original, with English translations provided. Translations are mine and are marked as renderings, never as the source text. The §5.4 word lists in particular are for Chinese web fiction and do not transfer word-for-word.
