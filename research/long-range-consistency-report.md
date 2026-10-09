# Long-Range Consistency in AI-Generated Long-Form Fiction: A State-of-the-Art Survey

**Scope:** techniques for maintaining consistency in LLM-generated novels of 100k–1M+ words.
**Compiled:** 2026. All URLs verified reachable during research.
**Evidence labels used throughout:** `[VALIDATED]` = peer-reviewed or shipped-and-audited implementation · `[PROMISING]` = plausible, some evidence, not yet independently replicated · `[HYPE]` = marketing or unsupported claim.

---

## 0. Executive summary — the consensus architecture

Across academic papers, open-source repos, and commercial tools, a single architecture has converged. It is **not** "use a bigger context window." It is:

> **Externalize narrative state into structured, chapter-indexed storage; retrieve a small, deterministic slice of it per generation; then run an explicit post-generation contradiction gate whose findings must cite source text.**

Every serious system found implements some subset of these five layers:

| Layer | What it is | Who does it |
|---|---|---|
| **1. Rolling summary** | Recursive compression of "what happened so far" | jarvis-write `chapter_summaries`, gpt-author, most tools |
| **2. Handoff contract / scene state** | Structured *transient* state at a chapter boundary (time, place, who is where, doing what, injuries) | jarvis-write design doc, MuMuAINovel |
| **3. Temporal fact store** | Atomic facts with `valid_from` / `valid_until` chapter intervals | FactTrack, jarvis-write `facts`, Graphiti (with caveats) |
| **4. Thread / promise ledger** | Foreshadowing with planted/reinforced/paid-off status and payoff windows | NovelClaw, Noveling, word-compiler IR, CFPG |
| **5. Contradiction gate** | LLM checker forced to emit evidence spans + severity, with a blocking/quarantine action | ConStory-Checker, ainovel-cli, jarvis-write |

The single strongest empirical result in the literature is a **negative** one: **LLM-as-judge cannot reliably detect unfaithfulness without retrieval of the original context, and even then auto-raters correlate poorly with humans** ([FABLES, COLM 2024](https://arxiv.org/abs/2404.01261)). This shapes every downstream design decision: *you cannot bolt a checker onto a system that didn't externalize state.*

---

## 1. Context management for long-form generation

### 1.1 The core constraint is real and measured, not hypothetical

`[VALIDATED]` **Chroma, "Context Rot" (July 2025)** — [https://www.trychroma.com/research/context-rot](https://www.trychroma.com/research/context-rot)

The most useful engineering measurement available. 18 models tested. Key findings:

- Performance degrades **non-uniformly** with input length even on trivially simple tasks — in the extreme case, replicating a repeated word list ("apple apple … **apples** … apple").
- **Lower needle–question semantic similarity → faster degradation.** This is the fiction-relevant case: "which character has been to Helsinki?" vs. the stored fact "Yuki lives next to the Kiasma museum" requires latent association, and degrades far faster than lexical matching.
- **A single distractor measurably degrades performance**, and the effect **amplifies with length**. Four distractors compound it.
- Surprising and important: **structurally coherent haystacks performed *worse* than shuffled ones** across all 18 models. Removing local logical flow *improved* retrieval.
- LongMemEval: focused prompts (~300 tokens) vastly outperform full prompts (~113k tokens) across every model family.

> **Implementable consequence:** the "just put the whole manuscript in a 1M context window" strategy is empirically refuted for anything requiring association rather than verbatim lookup. And the coherence finding cuts against the intuition that a well-written prior chapter is *good* context — it may actively mask the fact you need. **Prefer a short, non-narrative, structured fact block over a long, well-written prose excerpt** for state that must be honored exactly.

`[VALIDATED]` **FABLES (COLM 2024)** — [https://arxiv.org/abs/2404.01261](https://arxiv.org/abs/2404.01261)
Human evaluation of 3,158 claims across LLM summaries of 26 books. Findings directly relevant to novel generation:

- Most unfaithful claims relate to **events and character states**, and **require indirect reasoning over the narrative to invalidate**.
- **None of the tested LLM auto-raters correlated strongly with human annotations**, especially for detecting unfaithful claims.
- A systematic **over-emphasis on events occurring toward the end of the book** — direct evidence of recency bias in long-context processing.

> FABLES is the strongest caution against naive "LLM judge will catch it" designs. It is also why the good systems retrieve rather than judge from memory.

### 1.2 Approach comparison

**(a) Hierarchical summarization / outline-then-expand** — `[VALIDATED]`

`[VALIDATED]` **"Measuring Information Distortion in Hierarchical Ultra-long Novel Generation: The Optimal Expansion Ratio"** (Shen & Ying, Stevens Institute, 2025) — [https://ar5iv.labs.arxiv.org/html/2505.12572](https://ar5iv.labs.arxiv.org/html/2505.12572)

An information-theoretic treatment (rate–distortion framing) of exactly the 1M-word case. Concrete, quotable results:

- 40 ultra-long Chinese novels (≈1M words each, 4 genres), normalized into ~5,000-word chapters, **8 chapters sampled per novel**.
- **The central number: `R = α₁ × α₂ ≈ 0.01` is the optimal compression–expansion ratio** under their configuration. A 1M-word novel compressed to a 10,000-word outline and expanded back preserves semantics far better than compression to 1,000 words.
- **A two-stage hierarchy (K=2: global outline → section outline → manuscript) significantly reduces distortion vs. single-stage (K=1).** Concrete comparison at matched `R=0.01`:

| Method | Cosine | BERTScore F1 | Semantic sim. | Char. sim. | Style sim. |
|---|---|---|---|---|---|
| Direct compression (K=1) | 0.645 | 0.169 | 0.418 | 0.410 | 0.350 |
| LongWriter | 0.633 | 0.160 | 0.390 | 0.420 | 0.305 |
| **K2-* (two-stage)** | **0.677** | **0.199** | **0.613** | **0.566** | **0.611** |

- Two-stage nearly **doubles** character and style similarity vs. single-stage. **The hierarchy, not the model, is doing the work.**
- They also note GPT-4o and LongWriter collapse to ~0.39 semantic similarity at R=0.01, i.e. **outline-to-novel expansion at aggressive compression loses most of the story**.
- Both plain-text and structured-JSON outlines were tested as a controlled variable — worth noting they treated representation format as a first-class experimental factor.

> **Implementable:** budget your outline. If your manuscript is 1M words, a ~10k-word outline is the evidence-backed floor; a 1k-word outline is measurably lossy. Use two levels (global + per-section), not one. LongWriter's own claim that >100k-word generation "relies on an outline-to-novel workflow" is corroborated here, but this paper is the one that quantifies the ratio.

**(b) Retrieval-augmented generation — with *stateful* retrieval** `[VALIDATED]`

`[VALIDATED]` **ComoRAG: A Cognitive-Inspired Memory-Organized RAG for Stateful Long Narrative Reasoning** (AAAI 2026) — [https://arxiv.org/abs/2508.10419](https://arxiv.org/abs/2508.10419)

The most directly relevant RAG paper for fiction. Its diagnosis of standard RAG is the key insight:

> "traditional RAG methods could fall short due to their **stateless, single-step retrieval process**, which often overlooks the dynamic nature of capturing interconnected relations within long-range context."

ComoRAG's algorithm, concretely:

1. Encounter a **reasoning impasse** (a query that the current evidence can't answer).
2. Generate **probing queries** to open new exploratory paths.
3. Retrieve, then **integrate new evidence into a global memory pool**.
4. Iterate — the memory pool supports "the emergence of a coherent context for the query resolution."

Results: 4 long-context narrative benchmarks, 200K+ tokens, **up to 11% relative gain over the strongest baseline**, with the advantage concentrated on **queries requiring global context comprehension**. Code: [https://github.com/EternityJune25/ComoRAG](https://github.com/EternityJune25/ComoRAG)

> **Implementable:** this is one-step-retrieval-is-not-enough evidence. A continuity query like "is this scene consistent?" cannot be answered by embedding similarity to one chapter. You need a loop: retrieve → detect gap → generate a *new* query targeting the gap → retrieve again → accumulate. This is the algorithmic justification for a multi-round continuity checker rather than a single similarity lookup.

**(c) Rolling summaries + structured state, vector store removed** `[VALIDATED — shipped, self-audited]`

`[VALIDATED]` **jarvis-write (藏山)** — [https://ynnyh.github.io/jarvis-write/01-architecture](https://ynnyh.github.io/jarvis-write/01-architecture)

This project's architecture doc contains an unusually candid engineering note that is itself a finding:

> "向量库 / 分桶加权记忆已于 2026-07 移除（embedding 来源长期不可用、且长上下文已使其非必需）。长程一致性现由「时序故事圣经 + 滚动摘要」承担。"
>
> *"The vector store / bucketed weighted memory was removed in 2026-07 (embedding source was long-term unavailable, and long context made it non-essential). Long-range consistency is now carried by the temporal story bible + rolling summary."*

> **This is a real, reported rollback of RAG in favor of structured state.** It is one team's experience, not a controlled experiment, and should be weighed as such — but it is the kind of engineering report the question asks for, and it aligns with Chroma's finding that coherent prose in context actively hurts. The SQL-only design ("全部落在 SQL 里，不再有独立向量存储") is a legitimate architecture.

`[VALIDATED]` **Re³: Recursive Reprompting and Revision** (Yang, Tian, Peng, Klein — EMNLP 2022) — [https://arxiv.org/abs/2210.06774](https://arxiv.org/abs/2210.06774) · [HF page](https://huggingface.co/papers/2210.06774)

The canonical four-stage pipeline, and the ancestor of most later work:

- (a) LLM builds a **structured overarching plan**.
- (b) Generate passages by **repeatedly re-injecting contextual information from both the plan and the *current story state*** into the prompt. ("Recursive reprompting" = the state is recomputed each step, not accumulated raw.)
- (c) **Rerank** multiple continuations for *plot coherence* and *premise relevance*.
- (d) **Edit the best continuation for factual consistency** — an explicit consistency-repair step.

Measured results: **+14% absolute** on human judgments of coherent overarching plot, **+20% absolute** on premise relevance vs. same-base-model direct generation.

> **Implementable:** note (d) — editing the *best* candidate rather than rewriting the whole chapter. This is a token-cheap repair strategy and it recurs in later systems. Note also that "recursive reprompting" implies state is *regenerated* into the prompt each chunk, never accumulated.

**(d) Memory-architecture / multi-agent** `[PROMISING]`

`[PROMISING]` **DeepWriter: A Multi-Agent Collaboration Framework for Information-rich Ultra-long Book Writing** (AAAI-26) — [https://ojs.aaai.org/index.php/AAAI/article/view/40648](https://ojs.aaai.org/index.php/AAAI/article/view/40648)

Structured planning-then-generation; incrementally generates content "conditioned on retrieved knowledge and contextual signals." Claims **controllable generation exceeding 100,000 words**. Introduces `DeepWriter-Bench` (18 annotated bilingual books) and **BookScore**, a 100-point metric for "book maturity." Reports SOTA BookScore **80.92**.

`[PROMISING]` **Octopus: Entropy-Controlled Science Fiction Literature Generation with Persistent Memory-Context Binding** (AAAI-26) — [https://ojs.aaai.org/index.php/AAAI/article/view/41492](https://ojs.aaai.org/index.php/AAAI/article/view/41492) — persistent memory-context binding plus entropy control; the "entropy control" angle is interesting but details are thin in the abstract.

`[HYPE — be careful]` Multi-agent frameworks are the most heavily marketed and least rigorously evaluated category. DeepWriter's own benchmark is self-authored; BookScore is defined by the paper's authors. Treat BookScore 80.92 as an internal metric, not a comparable standard.

### 1.3 Where sources disagree

| Disagreement | Positions | Assessment |
|---|---|---|
| **RAG vs. structured state** | ComoRAG argues retrieval is *"pivotal in practice"* for 200K+ narratives. jarvis-write **removed** its vector store, keeping only SQL facts + rolling summary. | Not truly contradictory: ComoRAG retrieves over *narrative text for reasoning*; jarvis-write retrieves over *structured facts for hard constraints*. Both reject naive "top-k chunks of prose." The synthesis: **use SQL/graph retrieval for hard facts, and a stateful iterative retriever for reasoning tasks.** |
| **Is long context enough?** | Model vendors imply 1M windows solve this. Chroma and FABLES show degradation and recency bias even at 1M. Shen & Ying show 1M-token *input* is not the binding constraint — outline *detail density* is. | Vendor claims are `[HYPE]` for this use case. The evidence is one-sided against "context window solves consistency." |
| **Does coherent context help or hurt?** | Intuition (and every practitioner guide) says include prior prose for voice continuity. Chroma measured that **coherent haystacks perform worse**. | Genuinely unresolved and under-explored. Chroma themselves flag it as needing interpretability work. **Practical resolution: include prose for *voice*, structured facts for *truth* — keep them in separate context sections** (this is exactly what word-compiler's Ring 2/Ring 3 split does). |

---

## 2. Structured story state — concrete schemas

This is the area with the most implementable material and the best-documented schemas.

### 2.1 The temporal fact store — the heart of the design

`[VALIDATED]` **FactTrack: Time-Aware World State Tracking in Story Outlines** (NAACL 2025) — [https://aclanthology.org/2025.naacl-long.144/](https://aclanthology.org/2025.naacl-long.144/) · [HF](https://huggingface.co/papers/2407.16347)

**The single most important academic result for question 2.** FactTrack tracks **atomic facts with time-aware validity intervals**. The four-step pipeline per new event:

1. **Decompose the event into directional atomic facts.**
2. **Determine the validity interval** of each atomic fact using the world state.
3. **Detect contradictions** with existing facts in the world state.
4. **Add new facts and update existing atomic facts.**

Key claim: a `LLaMA2-7B-Chat` + FactTrack pipeline **substantially outperforms a LLaMA2-7B-Chat baseline and matches a GPT-4 baseline** on contradiction detection over structured story outlines; with GPT-4 as backbone, FactTrack **significantly outperforms the GPT-4 baseline**.

> **This is the strongest validation of the temporal-interval data model.** The structure does real work: a 7B model with the right data structure matches a raw frontier model. "Directional atomic facts" (subject→relation→object with a direction) matters — it enables contradiction detection as a structured comparison rather than free-text judgment.

**Schema (reconstructed from FactTrack's described semantics, and mirroring jarvis-write's shipped `facts` table):**

```jsonc
{
  "id": "fact_0187",
  "entity_id": "char_shenmo",
  "fact_type": "state",          // state | ability | possession | relationship | location
  "content": "left arm amputated",
  "valid_from": 5,               // chapter index where this became true
  "valid_until": 11,             // null = still true as of latest chapter
  "importance": "critical",      // critical | major | minor
  "source_chapter": 5,           // chapter whose text this was extracted from
  "direction": "character->state" // FactTrack's "directional" atomic fact
}
```

**The query that makes this work**, from jarvis-write's shipped design:

```sql
-- "What is true about Shen Mo in chapter N?"
SELECT * FROM facts
WHERE entity_id = 'char_shenmo'
  AND valid_from <= :N
  AND (valid_until IS NULL OR valid_until >= :N);
```

Their worked example: character A is injured in ch.5 → `fact(valid_from=5, valid_until=11)`; recovers in ch.12 → new `fact(valid_from=12, valid_until=null)`. **Querying chapter 8 returns "injured." Querying chapter 13 returns "recovered."** No contradiction is possible if generation honors the constraint block.

### 2.2 The chapter handoff contract — for *transient* state

`[PROMISING — well-specified design, not yet independently validated]` **jarvis-write chapter pipeline design (2026-08)** — [https://ynnyh.github.io/jarvis-write/08-章节生产流水线与前后审核体系设计](https://ynnyh.github.io/jarvis-write/08-%E7%AB%A0%E8%8A%82%E7%94%9F%E4%BA%A7%E6%B5%81%E6%B0%B4%E7%BA%BF%E4%B8%8E%E5%89%8D%E5%90%8E%E5%AE%A1%E6%A0%B8%E4%BD%93%E7%B3%BB%E8%AE%BE%E8%AE%A1)

The **best worked example of a failure mode being traced to a missing data structure.** Their diagnosis:

> Actual bug: *the previous chapter ended with the protagonist "falling asleep in the dark," and the next chapter opens with him "staring blankly into the dark."*
> Root cause: **"the immediate inter-chapter state (time, place, injuries, current action, who is present) was never structured and no gate was responsible for validating it."** The only mechanism was injecting the previous chapter's final 900 words and hoping the model inferred the state.

Their fix is a **`ChapterHandoffContract`**, extracted at low temperature after each chapter is finalized:

```json
{
  "chapter_no": 12,
  "in_story_time": "Day 3, late night",
  "location": "inside the ruined temple",
  "scene_continues": false,
  "characters": [
    {
      "name": "Shen Mo",
      "location": "inside the ruined temple",
      "physical": "left arm sword wound, unhealed",
      "emotional": "guarded, exhausted",
      "doing": "just fell asleep",
      "knows": ["the man in black is from Tingyu Tower"],
      "unresolved_intent": "set out for the ferry tomorrow"
    }
  ],
  "open_threads": ["footsteps outside the temple, unexplained"],
  "time_jump_hint": "next_morning"
}
```

**Two uses, both concrete:**

1. **Pre-generation injection** — chapter N's contract becomes a P0 context block for chapter N+1's draft prompt. Critically, they inject it **alongside** the raw prose tail: *"the prose supplies voice, the contract supplies facts"* (原文供语感，契约供事实). This directly resolves the Chroma coherence paradox from §1.3.
2. **Gate comparison** — after chapter N+1 produces its own contract, run **rule-based comparison first, LLM arbitration only for ambiguous cases**:
   - `doing="just fell asleep"` + `time_jump_hint="none"`, but next contract says `doing="awake, staring"` at late night → **contradiction**.
   - Previous `location="ruined temple"`, next `location="ferry"` with no time jump → **contradiction**.
   - `physical="left arm wound unhealed"`, and next chapter shows a sword fight with no treatment event → **contradiction**.
   - Anything the rules can't decide → one LLM call with both contracts + previous chapter's closing prose as input.

They also note the reason this is a *separate* structure from the fact store: **facts (`valid_from/valid_until` by chapter) only hold cross-chapter *persistent* facts; they do not record "where was he at the instant the chapter ended."**

Their research surveyed 7 GitHub projects; the three most useful citations:

- **ainovel-cli** ([github.com/voocel/ainovel-cli](https://github.com/voocel/ainovel-cli)) — Writer enforces a fixed tool order per chapter: `novel_context` → `read_chapter` (re-read prior text) → `plan_chapter` → `draft_chapter` → **`check_consistency` (mandatory, between draft and commit)** → `commit_chapter`. Maintains a **`state_changes.jsonl`** append-log of character state changes, with **character snapshots generated at arc boundaries**. Seven-dimension quality review where **every item must cite original text as evidence**. A `/diag` command checks for disappeared characters, timeline gaps, and stalled relationship data.
- **MuMuAINovel** ([github.com/xiamuceer-j/MuMuAINovel](https://github.com/xiamuceer-j/MuMuAINovel)) — **Handoff anchor**: when writing chapter N, inject the *complete* text of chapter N−1 at priority P0. Character cards carry "current state / psychology / situation" annotated with "changed in chapter N." A post-chapter `PlotAnalyzer` extracts hooks/foreshadowing/plot points/**character state changes (before → after)**/conflicts at low temperature and writes them back to the memory store. **Three-tier foreshadowing reminder: must resolve this chapter / overdue by N chapters / due within 3 chapters.**
- **novel-master** (Claude Skill, prompt-protocol only) — consistency reports use a fixed three-column format: **problem / evidence passage / suggested fix**, with **21 mandatory check items** including "time span and geographic distance are inconsistent" and "injury is inconsistent with physical capability."

### 2.3 The narrative IR — a per-scene extraction schema

`[VALIDATED — real implementation, Apache 2.0]` **word-compiler** (2389-research) — [github.com/2389-research/word-compiler](https://github.com/2389-research/word-compiler) · [Narrative IR doc](https://raw.githubusercontent.com/2389-research/word-compiler/refs/heads/main/docs/architecture/04-narrative-ir.md)

A context *compiler* for long-form fiction with a clean separation between what's extracted and what's injected. The extraction schema:

```typescript
interface NarrativeIR {
  sceneId: string;
  events: string[];                    // What happened (chronological)
  factsIntroduced: string[];           // New information entered the story
  factsRevealedToReader: string[];     // What the reader now knows
  factsWithheld: string[];             // What the reader doesn't know yet
  characterDeltas: CharacterDelta[];   // How characters changed
  unresolvedTensions: string[];        // Open questions / hooks
  setupsPlanted: string[];             // Setups for future payoff
  payoffsExecuted: string[];           // Payoffs of earlier setups
  verified: boolean;                   // Author confirmed accuracy
}

interface CharacterDelta {
  characterId: string;
  learned: string | null;
  suspicionGained: string | null;
  emotionalShift: string | null;
  relationshipChange: string | null;
}
```

Two design decisions worth stealing:

1. **The `verified` flag is a human gate.** IR is extracted with `verified: false`, shown in an "IR Inspector" UI, edited/confirmed by the author, then only `verified` IR is used in downstream context and cross-scene bridging. **This addresses the compounding-pollution problem** (below) directly.
2. **A 3-tier JSON parse fallback** for the extractor: direct `JSON.parse` → code-fence extraction → largest `{...}` regex. A small but real piece of production hardening that every extractor pipeline needs.

Their **three-ring context architecture** (from [02-context-compiler.md](https://raw.githubusercontent.com/2389-research/word-compiler/main/docs/architecture/02-context-compiler.md)):

- **Ring 1 (system):** voice, tone, kill list, global rules, POV.
- **Ring 2 (chapter):** chapter arc, **`READER_STATE_ENTRY`** (what the reader knows/suspects/is *wrong* about), **`ACTIVE_SETUPS`**, **`CHAR_STATE_{id}`** per character (cumulative from IR deltas), **`UNRESOLVED_TENSIONS`**.
- **Ring 3 (scene):** scene contract, voice fingerprints, **`CONTINUITY_BRIDGE`** (last chunk verbatim), **`CONTINUITY_BRIDGE_STATE`** (IR state bullets at scene entry, cross-scene only), anchor lines, `ANTI_ABLATION`.

**Budget algorithm** (`enforceBudget`): sum all section tokens; if over, remove **non-immune** sections in priority order — Ring 1 lowest priority first, then Ring 2, **Ring 3 compressed last** (most critical). Immune sections (`NEVER_WRITE` kill list, POV rules, per-character voice fingerprints, scene cast guardrail, anchor lines, micro-directives) are **never** removed, and there is an explicit lint check `IMMUNE_REMOVED` (severity: error) that fires if one ever is. **This is the most concrete token-budget policy found anywhere** and it's a genuinely good idea: *decide at schema-definition time which constraints are inviolable, then enforce that mechanically.*

`[PROMISING]` **Cognitae** — [github.com/cognitae-ai/Cognitae](https://github.com/cognitae-ai/Cognitae/blob/main/Cognitae_Techne/Elari_Story/009_Elari_Story_State_v2.yml) — a YAML story-state file with the same temporal-interval shape (facts bound to chapter ranges, reader-known vs character-known separation). Less documented than the others; treat as a reference data model, not a validated system.

### 2.4 Reader knowledge vs. character knowledge — the mystery-novel primitive

`[VALIDATED as a design pattern; appears independently in several systems]`

The **`knowledge_states`** table (jarvis-write, credited to KazKozDev):

| field | meaning |
|---|---|
| `fact_id` | which fact |
| `knower` | `"reader"` or a character `entity_id` |
| `known_from_chapter` | chapter from which they know it |
| `knower_state` | `known` / `suspected` / `blind` |

> Worked use: *the reader learns the truth in ch.3; character B doesn't learn it until ch.10.* Generation then enforces "this character must not speak about something they don't yet know."

word-compiler encodes the same idea as `factsRevealedToReader` / `factsWithheld` plus a `READER_STATE_ENTRY` section tracking **what the reader is *wrong* about** — a distinction most systems miss.

**Honest caveat:** jarvis-write's own audit notes **"`knowledge_states` is write-only — the generation prompt does not inject 'what this character doesn't yet know,' so knowledge isolation has no closed loop."** This is reported as an outstanding defect in their own system. **The data structure is validated as useful; the closed loop is not yet demonstrated by anyone found.**

### 2.5 The knowledge-graph approach and its measured failure

`[VALIDATED — with a strong negative result]`

`[VALIDATED]` **Synapse: "Your temporal knowledge graph is quietly deleting true facts"** (2026-07) — [docs/FINDING-silent-fact-loss.md](https://raw.githubusercontent.com/alexsh88/synapse/refs/heads/main/docs/FINDING-silent-fact-loss.md)

**The most important "evidence against" source in this report.** A production temporal knowledge graph (Graphiti/Zep over Neo4j, self-hosted, used across 11 projects). Findings:

- **70% of facts Graphiti automatically retired were still true** (28/40 hand-labelled, 95% CI [54.6%, 81.9%]).
- **The failure is silent**: no error, no warning, the write reports success, the fact simply stops appearing in search results.
- **Mechanism:** on every write, Graphiti searches for invalidation candidates with an **empty `SearchFilters()`** — so the candidate set is *every edge in the group*, ranked by hybrid semantic similarity, **with no requirement that a candidate share an entity with the new fact**. That set goes to one LLM call returning `contradicted_facts: list[int]` — **"a bare list of indices, no justification, no confidence"** — and `resolve_edge_contradictions` commits `invalid_at` on whatever comes back, gated only on temporal-overlap arithmetic.
- **Most common failure: a narrower new fact retiring a broader true one.** Example given: a statement about *one microservice's* storage choice retired a true statement about *the platform's* storage.
- **Second most common: pure restatement** — the same fact rephrased retires the original. Neither is a contradiction.
- **The attempted guard failed to help.** Measured against labels:

| rule | true facts silently lost | stale facts kept |
|---|---|---|
| unguarded (Graphiti as shipped) | **28** | 0 |
| structural test only | 13 | 5 |
| lexical test only | 0 | 11 |
| **guard (structural AND lexical)** | **0** | 11 |
| invalidation disabled entirely | 0 | 12 |

The author's conclusion: *"the guard is within one case in forty of simply disabling invalidation."* And: *"once ~three quarters of retirements are unjustifiable, no after-the-fact veto recovers a useful signal. The fix has to be upstream, in the candidate search, so the bad candidate never reaches the judge at all."*

Independent corroboration: a separate operator on a different backend and extraction model hand-audited 4 cases, found 3 wrong (75%) — matching the 70% on an independent corpus. An upstream structural-guard PR ([getzep/graphiti#1729](https://github.com/getzep/graphiti/pull/1729)) was **open and unreviewed** as of 2026-08.

Methodological notes the author explicitly flags (valuable in themselves):

- **Audit `expired_at` (transaction time), not `invalid_at` (valid time).** `invalid_at` is backdated, so joining on it pairs retirements with unrelated writes and makes analysis "roughly four times blinder."
- **Two LLM judges from different model families could not do this task** — Cohen's κ 0.393, and 0.348 *after* sharpening the rubric, upgrading the judge, and restricting to unambiguous cases. **Improving the instrument made agreement slightly worse.** The task "needs context that a pair of extracted sentences doesn't carry."

> **Implementable consequences — treat these as hard-won:**
> 1. **Never let an LLM auto-invalidate facts with an unbounded candidate set.** Restrict candidates structurally: same entity pair, or same subject + same relation name.
> 2. **Contradiction resolution must be *narrower-and-shared-entity* scoped**, or restatements and hyponym/hypernym pairs will silently destroy true facts.
> 3. **Silent data loss is the failure mode to hunt**, not crashes.
> 4. **If two of your measurements share a function, they are one measurement** — the author retracted a circular validation.
> 5. **Two independent LLM judges agreeing poorly is a signal the task lacks sufficient context, not that the rubric needs sharpening.**

This is a *temporal knowledge graph* — exactly the architecture question 3 asks about. Its measured failure rate on the invalidation step is the strongest caution available.

---

## 3. Contradiction detection

### 3.1 The best-specified pipeline: ConStory-Checker

`[VALIDATED]` **"Lost in Stories: Consistency Bugs in Long Story Generation by LLMs"** (Microsoft Beijing + SUTD, March 2026) — [arXiv:2603.05890](https://arxiv.org/abs/2603.05890) · [HTML](https://arxiv.org/html/2603.05890v1) · [project page](https://picrew.github.io/constory-bench.github.io/)

**The single most directly applicable paper for questions 3, 6, and 7.** It ships `ConStory-Bench` (2,000 prompts, four task types: generation / continuation / expansion / completion; targets 8,000–10,000 words) and `ConStory-Checker`.

**The error taxonomy — use this as your test suite** (5 categories, 19 subtypes):

| Category | Subtypes |
|---|---|
| **Timeline & Plot Logic** | Absolute Time Contradictions · Duration Contradictions · Simultaneity Contradictions · Causeless Effects · Causal Logic Violations · Abandoned Plot Elements |
| **Characterization** | Memory Contradictions · Knowledge Contradictions · Skill Fluctuations · Forgotten Abilities |
| **World-building & Setting** | Core Rules Violations · Social Norms Violations · Geographical Contradictions |
| **Factual & Detail Consistency** | Appearance Mismatches · Nomenclature Confusions · Quantitative Mismatches |
| **Narrative & Style** | Perspective Confusions · Tone Inconsistencies · Style Shifts |

Note that **"Abandoned Plot Elements" is a first-class error category**, as are **"Forgotten Abilities"** and **"Knowledge Contradictions"** — this taxonomy covers exactly the failure classes the other sources describe informally.

**The four-stage detection pipeline** (directly implementable):

1. **Category-Guided Extraction.** Scan the narrative with **category-specific prompts** across the five dimensions, extracting *contradiction-prone spans*. (Not "find all errors" — narrow, per-category extraction.)
2. **Contradiction Pairing.** Extracted spans are compared **pairwise** and classified `Consistent` / `Contradictory`. Rationale: *"this reduces false positives and isolates genuine inconsistencies."* Method follows CheckEval and ProxyQA.
3. **Evidence Chains.** For each contradiction, record **Reasoning** (why it is a contradiction), **Evidence** (quoted text *with positions*), and **Conclusion** (error type).
4. **JSON Reports.** Standardized JSON capturing quotations, positions, pairings, error categories, explanations — with **all judgments anchored to precise character-level offsets**.

Model used for checking: `o4-mini`. Appendices include a validation study of the checker itself and explicit category definitions.

**Metrics introduced:**

- **Consistency Error Density (CED)** = errors per 10,000 words. `CED_{m,i} = e_{m,i} / (w_{m,i}/10000)`. This **removes the length bias** that unfairly penalizes models generating longer outputs.
- **Group Relative Rank (GRR)** — within each prompt group, rank models by `Q_{m,i} = w_{m,i} / (1 + e_{m,i})`, then average ranks. This **controls for per-prompt difficulty**, since some prompts inherently elicit more errors across all models.

**Headline results table (CED, errors per 10K words; lower is better):**

| Model | CED (overall) | Char. | **Fact.** | Narr. | **Time.** | World | GRR | Avg words |
|---|---|---|---|---|---|---|---|---|
| GPT-5-Reasoning | **0.113** | 0.005 | 0.061 | 0.003 | 0.024 | 0.003 | 3.05 | 9050 |
| Gemini-2.5-Pro | 0.305 | 0.009 | 0.132 | 0.015 | 0.108 | 0.029 | 7.79 | 5584 |
| Claude-Sonnet-4.5 | 0.520 | 0.017 | 0.224 | 0.004 | 0.128 | 0.043 | 4.90 | 8929 |
| Grok-4 | 0.670 | 0.033 | 0.307 | 0.065 | 0.222 | 0.076 | 13.38 | 2765 |
| GPT-4o-1120 | 0.711 | 0.036 | 0.163 | 0.018 | 0.440 | 0.104 | 17.59 | 1241 |
| LongWriter-Zero (capability-enhanced) | 0.669 | | | | | | | |
| SuperWriter (agent-enhanced) | 0.674 | | | | | | | |

**Critical reading of these numbers:** even the best model produces ~0.11 consistency errors per 10,000 words. **At 1M words that is ~11 detected errors** — and the checker is a *detector*, so the true rate is higher. Also note **agent-enhanced and capability-enhanced systems landed at ~0.67, statistically indistinguishable from ordinary prompting at 0.71** — i.e., **elaborate multi-agent pipelines did not measurably improve consistency over a plain frontier model.**

> **Note the `Words` column interaction with CED.** Grok-4 writes 2,765 words and scores 0.670; Claude-Sonnet-4.5 writes 8,929 words and scores 0.520. Since CED normalizes by length, shorter outputs get small error counts divided by a small denominator — CED is not automatically kind to short outputs, but the interplay is worth being careful about when comparing systems with very different length distributions.

### 3.2 The five-layer defense model

`[PROMISING]` Synthesized by jarvis-write's research survey (7 GitHub projects + 4 papers), ordered by implementation cost — a good adoption roadmap:

1. **Handoff anchor pre-injection** — force-inject the previous chapter's ending state when writing a new chapter. *"Cheapest; doing this alone eliminates most contradictions."*
2. **End-of-chapter state write-back** — every commit produces a structured state update (character state before→after, time, place, thread changes), persisted as queryable data.
3. **State-aware context assembly** — inject "character current state (annotated with chapter of change) + single-chapter summary + history reverse-looked-up by state change."
4. **Post-generation hard gate** — an independent checker call; **reports must cite source text as evidence**; repairs go through *revise*, not full rewrite; **no passing without clearance**.
5. **Cross-chapter fallback review** — arc/volume-boundary review, offline diagnosis, whole-book wave revision.

### 3.3 Quarantine: the anti-pollution mechanism

`[PROMISING — strong design idea]`

jarvis-write's audit identified a subtle and severe failure mode:

> **"The contradiction text still gets extracted into the story bible by `extract_and_apply`, so the pollution is instead *fixed in place*."**

i.e. a buggy chapter's content becomes canon. Their fix is a three-tier gate action:

- **`blocker`** → automatic revise (reuse the existing revision loop, sharing a `review_max_revisions` cap); re-run the gate after. If blockers persist past the cap: **persist the chapter but mark `status = quarantined`** — do **not** run post-chapter extraction (so contradictions never enter the bible), do **not** update the rolling summary, and **pause the continuous-generation queue**.
- **`major`** → persist as `pending_review`; issues displayed; human decides.
- **`minor`** → persist as `pending_review`; informational only.

New tables: `chapter_states` (contract JSON + prose fingerprint + version snapshot) and `chapter_issues` (source ∈ {gate, preflight, diag, review}, severity, problem/evidence/suggestion, status ∈ {open, resolved, ignored}, **prose fingerprint** for dedup on rewrite).

**Two more genuinely good details:**

- **Pre-flight check** runs *before* drafting: validate the chapter blueprint against the previous chapter's contract. If the blueprint says "depart the ferry at dawn" but the prior contract is "late night, just fell asleep, no mention of dawn," warn before a word is generated. **Default warn-not-block** (deliberate time jumps are legitimate), configurable to pause on hard contradiction.
- **Post-hoc "rule scan"** as a complementary mechanism, with an explicit statement of why the gate alone is insufficient: *"the health check only finds *contradictions with the bible/contract/prior text* — **if it's wrong consistently, it won't be caught** (typical examples: a science student reciting politics, or the wrong number of days in the college entrance exam)."* Rule scan takes a user-authored `world_rules` "pinboard" (one rule per line) and either injects it preventively into blueprint/draft/finalize/revise, or runs a whole-book chapter-by-chapter scan emitting violations **with original-text evidence** into the per-chapter issue list. **This is the only mechanism found that catches globally-consistent-but-wrong errors.**

### 3.4 What doesn't work — and the evidence

`[VALIDATED negative result]` **FABLES** (above): **no LLM auto-rater correlated strongly with human annotations** on faithfulness; errors "generally require indirect reasoning over the narrative to invalidate."

`[VALIDATED negative result]` **Synapse/Graphiti** (§2.5): two different LLM judges from different model families reached only κ ≈ 0.35–0.39 agreement on whether a fact was contradicted, and **rubric sharpening made it worse**.

`[VALIDATED negative result]` **ConStory-Bench** (§3.1): agent-enhanced and capability-enhanced generation pipelines landed at **CED ≈ 0.67–0.67 vs. 0.71 for plain prompting** — no measurable consistency gain from architectural complexity.

> **Synthesis:** automatic contradiction detection is *possible* but **only when (a) candidates are structurally pre-scoped, and (b) the checker is given explicit original-text evidence to reason over.** Asking an LLM to judge consistency from memory or from a pair of extracted sentences does not work, and this has now been measured three independent ways.

---

## 4. Retrieval design for fiction specifically

### 4.1 Why fiction RAG ≠ QA RAG

The literature converges on these differences:

| QA RAG | Fiction RAG | Source |
|---|---|---|
| Single relevant passage suffices | Answers require **global context comprehension** across many passages | [ComoRAG](https://arxiv.org/abs/2508.10419) |
| Stateless single-step retrieval | Narrative reasoning is *"not a one-shot process but a dynamic, evolving interplay between new evidence acquisition and past knowledge consolidation"* | [ComoRAG](https://arxiv.org/abs/2508.10419) |
| Semantic similarity is the objective | **Recency matters**; facts have *validity intervals*, so the newest assertion is usually the true one | [FactTrack](https://aclanthology.org/2025.naacl-long.144/) |
| Query is given | **Query must be generated** — front-loading the whole book forces the model to do retrieval *and* reasoning in one call, which measurably hurts | [Chroma](https://www.trychroma.com/research/context-rot) |
| Chunks are interchangeable | **Plot threads and setups must be tracked as objects with state**, not retrieved as text | [CFPG](https://arxiv.org/abs/2601.07033), NovelClaw, Noveling |

### 4.2 Concrete strategies

**Strategy 1 — Generate the query; don't dump the corpus.** `[VALIDATED]`
Chroma's LongMemEval result is the cleanest evidence: focused prompts (~300 tokens, relevant parts only) vastly outperform full prompts (~113k tokens) containing the same information. Their framing is precise: *"adding irrelevant context adds the additional step of identifying what is relevant, forcing the model to perform two tasks simultaneously"* (retrieval + reasoning). **Retrieval should happen outside the model.**

**Strategy 2 — Iterative probing loops, not top-k.** `[VALIDATED]`
ComoRAG's algorithm (§1.2b). For a continuity check, the practical shape is:

```
memory_pool = []
query = derive_query(current_chapter_plan, character_names)
while not answerable(query, memory_pool) and rounds < MAX:
    evidence = retrieve(query)              # hybrid lexical + vector
    memory_pool += evidence
    query = generate_probing_query(gap(memory_pool))   # NEW query targeting the gap
answer = reason(query, memory_pool)
```

**Strategy 3 — Rule-based reverse lookup keyed on state change, not text similarity.** `[VALIDATED as shipped practice]`
ainovel-cli recommends related past chapters for re-reading along **four dimensions: foreshadowing / character appearance / state change / relationship** — *"once state is structured, writing time can retrieve 'the most recent character state.'"* `[PROMISING]` jarvis-write's P2 plan describes the same idea but **explicitly declined to implement it**, with an honest rationale worth quoting:

> **"Reverse-lookup injection: ❌ not doing it (bible hard constraints + contract + rolling summary already inject on three paths; rule-based retrieval would only bloat the prompt and add noise)."**

That is a rare and useful instance of a team deciding *against* adding retrieval after building the structured alternative.

**Strategy 4 — Hybrid lexical + vector, with recency as a hard filter.** `[PROMISING]`
The strongest signal here is indirect but consistent: **temporal databases implement recency as a `valid_from`/`valid_until` *filter*, not a similarity *boost*.** jarvis-write's shipped note is explicit: *"Retrieval systems by default query only the latest valid assertions unless a historical snapshot is explicitly requested."* This is architecturally cleaner than recency-weighted similarity, because it makes "what did I believe in chapter 8?" a first-class query.

**Strategy 5 — Structured fact retrieval beats chunk retrieval for hard constraints.** `[VALIDATED]`
jarvis-write's split: **hard facts go through the story bible (SQL, deterministic), soft context through rolling summary + recent chapter tails.** See §1.3 for the reconciliation with ComoRAG.

### 4.3 Where evidence is thin

- **No paper found directly compares recency-weighting schemes for fiction retrieval.** The claim "recency matters for fiction" is universally asserted and consistent with FABLES' measured end-of-book over-emphasis, but no ablation was located.
- **Hybrid lexical+vector for fiction specifically** is recommended by many engineering sources but was not found tested against pure-vector in a fiction setting. `[HYPE-adjacent]` — plausible, weakly evidenced.
- **Thread-aware retrieval** (retrieve *because a plot thread says you must*, not because of similarity) is implemented in NovelClaw and Noveling but **no evaluation was found for any of them.** `[PROMISING]`
- Chroma's surprising finding that **coherent haystacks retrieve worse** is explicitly flagged by the authors as lacking mechanistic explanation.

---

## 5. Foreshadowing / plot thread tracking

This is the area with the best-understood data model and the weakest evaluation.

### 5.1 The four-state ledger

`[VALIDATED as shipped]` **NovelClaw** — [github.com/iLearn-Lab/NovelClaw](https://github.com/iLearn-Lab/NovelClaw) (dynamic-memory-first collaborative framework; "Claw Banks" bucketed memory)

`[VALIDATED as shipped]` **jarvis-write** implements the same model, crediting **NovelClaw** for the four-state design and **KazKozDev** for the reveal-scheduling fields:

| field | type | meaning |
|---|---|---|
| `id` | PK | |
| `project_id` | FK | |
| `description` | text | the foreshadowing content |
| `chapter_planted` | int | chapter where it was planted |
| `expected_payoff_chapter` | int? | intended payoff chapter |
| **`earliest_payoff_chapter`** | int? | **cannot be paid off before this** (KazKozDev's `minimumChapter`) |
| **`status`** | enum | **`planted` / `reinforced` / `paid_off` / `abandoned`** |
| `payoff_chapter` | int? | actual payoff chapter |
| `reinforcement_chapters` | JSON | chapters where it was reinforced |
| `importance` | enum | `critical` / `major` / `minor` |
| **`required_hints`** | JSON | **prerequisite setups required before payoff** |
| `notes` | text | |

**The scheduling rule** (the actual algorithm):

```
if status in (planted, reinforced)
   and expected_payoff_chapter <= current_chapter + 2:
       add to "should pay off now" reminder list
       → inject into prompt: "The following foreshadowing should be resolved soon: …"
```

MuMuAINovel's version adds **three tiers**: must resolve this chapter / overdue by N chapters / due within 3 chapters.

> **Why `earliest_payoff_chapter` matters:** without it, a system that rewards paying off threads will resolve a mystery in ch.6 that was designed for ch.40. The interval `[earliest_payoff_chapter, expected_payoff_chapter]` is the payoff *window*. **`required_hints` is the underrated field** — it lets you express "you cannot reveal X until the reader has seen A and B," which is the actual constraint in mystery plotting.

### 5.2 The setup/payoff tracker as an extracted artifact

`[VALIDATED — shipped implementation]` **word-compiler** — [Narrative IR](https://raw.githubusercontent.com/2389-research/word-compiler/refs/heads/main/docs/architecture/04-narrative-ir.md) · [auditor](https://raw.githubusercontent.com/2389-research/word-compiler/main/docs/architecture/03-auditor-linter.md)

```typescript
setupsPlanted: string[];       // Setups for future payoff
payoffsExecuted: string[];     // Payoffs of earlier setups
```

The `src/auditor/setup-payoff.ts` module performs cross-scene analysis tracking setups planted in earlier scenes and whether they've been paid off, **reporting dangling setups (planted but never resolved)**. It operates on *verified* Narrative IR. The evaluation system includes a chapter-level deterministic check **`checkSetupPayoffClosure`** — "no dangling setups at manuscript completion" — which is a **hard pass/fail gate on the whole book**, not a warning.

Note the architectural choice: **threads are extracted from prose, not declared up front.** This is more robust than requiring the author to pre-register every setup, at the cost of extraction errors — which the `verified` human gate addresses.

### 5.3 The academic treatment: codifying the trigger mechanism

`[PROMISING — newest, least replicated]` **CFPG: Codified Foreshadowing-Payoff Text Generation** (Yun, Zhou, Hou, Peng, Shang — Jan 2026) — [arXiv:2601.07033](https://arxiv.org/abs/2601.07033) · [HF](https://huggingface.co/papers/2601.07033)

The most explicit statement of the problem:

> *"LLMs frequently fail to bridge these long-range narrative dependencies, often leaving **'Chekhov's guns' unfired even when the necessary context is present**. Existing evaluations largely overlook this structural failure, focusing on surface-level coherence rather than the logical fulfillment of narrative setups."*

**The key phrase is "even when the necessary context is present."** This is an argument that the problem is *not* purely context-window starvation — it is a missing representational structure. CFPG's approach:

- Reframes narrative quality through **payoff realization**.
- **Transforms narrative continuity into a set of executable causal predicates.**
- **Mines and encodes `Foreshadow → Trigger → Payoff` triples** from the **BookSum** corpus.
- The stated rationale: *"LLMs struggle to intuitively grasp the 'triggering mechanism' of a foreshadowed event."*

Result: CFPG **significantly outperforms standard prompting baselines in payoff accuracy and narrative alignment.**

> **Implementable — and this is the most actionable idea in the section.** A `ChekhovGun` record is not just `(description, planted, payoff)`. It is a **triple with an explicit trigger condition**:
>
> ```jsonc
> {
>   "id": "cg_0042",
>   "foreshadow": "the rusted iron key on the mantle",
>   "trigger":   "protagonist is locked in the cellar AND has searched the mantle",
>   "payoff":    "key opens the cellar door",
>   "planted_chapter": 3,
>   "earliest_payoff_chapter": 25,
>   "expected_payoff_chapter": 40,
>   "status": "planted",
>   "required_hints": ["cg_0011", "cg_0027"]
> }
> ```
>
> The **`trigger` predicate is what CFPG adds** over the four-state ledger, and it is what you evaluate against the chapter plan: *does this chapter's plan contain the trigger condition?* If yes, the gun is due. This converts "did I remember the thread?" from a memory problem into a **pattern match against the chapter outline** — a tractable, deterministic operation.

### 5.4 Failure modes this structure prevents

From Noveling's practitioner documentation ([Why Long-Form AI Fiction Breaks](https://noveling.dev/guide/en/blog/long-form-consistency-ai/)):

> *"Foreshadowing dies unresolved. A setup planted in chapter 8 is simply invisible to the AI by chapter 40. **It can't pay off what it can't see.**"*

And, importantly, their diagnosis of *why* the fix is a data-structure fix rather than a prompting fix:

> *"It's actually quite good when it has the relevant context. **The problem is purely mechanical: it doesn't know the promise was made.**"*

**Noveling's `Narrative Promise Tracking`** tracks each promise with **two signals**: `recency` (chapters since the promise was made) and `unresolved_lifespan` (how long it has stayed open without payoff). When *either* crosses a threshold, the promise is surfaced in the next generation as a **soft constraint** — explicitly not forced. They also maintain `Thread Coverage` ([docs](https://noveling.dev/guide/en/creative-tools/thread-coverage/)) so every story thread stays active.

> **Two tracking signals rather than one is a good idea:** a thread can be problematic because it was *just* introduced and is being dropped, or because it has been open *forever*. A single "chapters since payoff" counter conflates these.

### 5.5 A complementary mechanism: repeated-motif suppression

`[PROMISING — novel, shipping in jarvis-write]` — [data model doc §4.5](https://ynnyh.github.io/jarvis-write/02-data-model)

The inverse problem: not threads being *forgotten*, but imagery being *over-repeated*. Their `writing_motifs` table exists because *"n-gram dedup only catches literal repetition, not the reuse of the same beat with different wording."* Extraction distills each chapter's signature descriptive motifs into **short labels only — never original sentences**, on the explicit reasoning that **"putting the original sentence in the prompt causes it to be copied verbatim."** Aggregated across chapters by label; any motif recurring ≥2 times is injected into the next chapter's draft prompt as prohibited. Authors can also register a motif as a permanent "minefield," applying book-wide.

> **The "store labels, not sentences" rule is a genuinely non-obvious and important implementation detail.** Any system that stores representative prose for style continuity risks verbatim copying.

---

## 6. Known failure modes at scale

### 6.1 Academically measured

`[VALIDATED]` **ConStory-Bench** ([arXiv:2603.05890](https://arxiv.org/abs/2603.05890)) — five findings with direct engineering implications:

1. **Errors concentrate in Factual & Detail Consistency and Timeline & Plot Logic.** These two categories dominate. *"Entity tracking and temporal reasoning remain primary challenges."* — i.e., the problems a temporal fact store solves are the actual dominant problems.
2. **Errors cluster around the *middle* of narratives** — not the end. Extended positional analysis is in Appendix B.5.
3. **Errors occur in text segments with higher token-level entropy** — a *predictive signal*.
4. **Certain error types co-occur** systematically (Appendix B.4).
5. **Generation tasks have consistently higher CED than Continuation, Expansion, and Completion** across most models — *"open-ended creation without prior context poses the greatest consistency challenge."*

> **Implementable:** (2) and (3) mean you can **prioritize checking effort**. Mid-narrative, high-entropy segments are where errors live. This turns an O(whole book) checking problem into a targeted one. (5) means the *first* chapters written from scratch need the most checking.

`[VALIDATED]` **FABLES** ([arXiv:2404.01261](https://arxiv.org/abs/2404.01261)) — a **systematic over-emphasis on events occurring toward the end of the book**, plus the finding that unfaithful claims "generally require indirect reasoning over the narrative to invalidate."

### 6.2 Practitioner-reported

`[PROMISING — practitioner consensus, not controlled study]` **Noveling** ([long-form consistency](https://noveling.dev/guide/en/blog/long-form-consistency-ai/)) reports writers "hit the same wall **around chapter 30**" and enumerates **five named failure modes**:

| # | Failure mode | What goes wrong |
|---|---|---|
| 1 | **Unresolved narrative promises** | Foreshadowing and setups never pay off |
| 2 | **Fact drift** | "Her eyes were grey" in ch.3 → "his golden-eyed companion" in ch.67. Power scales become meaningless. A character who died offscreen is referenced as alive. Timeline math stops adding up. |
| 3 | **Rule erosion** | "The hero uses an ability that was established as impossible. The supposedly rigid hierarchy bends whenever convenient." |
| 4 | **Character drift** | "The quietest failure mode." Voice and decision patterns shift toward whatever's convenient for recent chapters. "By chapter 100, a character can feel like a different person than they were in the opening arc, and readers feel the discontinuity **even if they can't name it**." |
| 5 | **Thread abandonment** | "Unlike a human writer who might feel the absent thread nagging at them, **the AI has no such discomfort. If it's not in the current context, it doesn't exist.**" |

Their stated amplifier: *"AI accelerates this because it generates text much faster than a human writes. You can accumulate 150 chapters of drift in the time it would have taken you to write 20 chapters of drift manually. **Speed doesn't solve the problem. It compounds it.**"*

`[PROMISING]` **Phase-Fiction Workflow** ([methodology.md](https://raw.githubusercontent.com/nanzhipro/phase-fiction-skill/6ceef34f30ccaeac3b078b81ba32a5ef36709783/references/methodology.md)) — a detailed Chinese-language methodology for long AI-fiction projects. Names **five instability classes** that "stably appear" past 50k–several-hundred-thousand characters:

1. **Story promise drift** — the opening promises A; ten chapters later the novel is actually about B.
2. **Character core distortion** — desires, fears, wounds, speech patterns fail to hold across chapters.
3. **Tension collapse** — many chapters, but ever fewer scenes that actually drive choice, cost, and suspense.
4. **Setting and causal rupture** — foreshadowing, rules, relationship networks, and timelines contradict each other after compression or continuation.
5. **Revision-layer confusion** — structural, character, and language problems handled in the same pass, producing muddying.

Their central claim, which matches the empirical picture:

> **"Move the parts of the long novel task that need stability out of model memory and externalize them into creative contracts in the repository. The AI is not responsible for 'holding everything in memory by feel'; it is only responsible for completing the current creative contract within the current small window."**
>
> (把小说长任务里需要稳定性的部分，从模型记忆中剥离出来，外部化为仓库里的创作合同。)

Their **three invariants**: **I1** only one phase active at a time; **I2** the working window is always exactly three files (`common + phase + execution`); **I3** a stage counts as complete *only* when written to external state. And their revision ordering rule: **structural problems always precede prose polish** (结构问题永远先于文风抛光) — described as "the most common and most expensive ordering error in novel revision."

`[PROMISING]` **ai-novel-lab** (cited in jarvis-write's survey, [github.com/xindoo/ai-novel-lab](https://github.com/xindoo/ai-novel-lab)) — after a 40-chapter first draft, review found **5 major problem classes including timeline chaos, with coherence scoring only 73/100. After wave-based revision: 93/100.** Concrete evidence that **post-hoc batch revision is a necessary fallback**, not optional.

`[VALIDATED negative example]` **gpt-author** (~2.5k stars, cited in the same survey) — outline + chapter-by-chapter generation with **no state management whatsoever**. Described as the archetypal source of the "asleep then staring blankly" class of bug: *"proof that relying only on a front-loaded outline necessarily produces such contradictions."*

### 6.3 The arithmetic of the problem

Combining measured rates:

- ConStory-Bench best model: **~0.11 consistency errors per 10,000 words** (detected, by a checker whose own recall is <100%).
- At **1M words**: ≈ **11+ detected consistency errors**, likely more.
- At a more typical **100k-word novel**: ≈ 1–5 detected errors even with a frontier model.
- Independent practitioner data point: **73/100 coherence after 40 chapters** with no state management.

> The "over 100 chapters" threshold the question asks about is real, but the literature suggests the wall arrives earlier — Noveling reports ~chapter 30, ConStory-Bench shows mid-narrative clustering. **The failure is continuous, not a cliff.**

---

## 7. Evaluation

### 7.1 Benchmarks

| Benchmark | Source | What it measures | Notes |
|---|---|---|---|
| **ConStory-Bench** | [arXiv:2603.05890](https://arxiv.org/abs/2603.05890) | Narrative consistency; 2,000 prompts, 4 task types, 5 categories / 19 subtypes | **The most directly applicable.** Ships `ConStory-Checker`. Metrics: CED, GRR. |
| **FABLES** | [arXiv:2404.01261](https://arxiv.org/abs/2404.01261) | Faithfulness + content selection in book-length summarization | 3,158 human-annotated claims, 26 books. Human evaluation is the gold standard; shows LLM auto-raters fail. |
| **DeepWriter-Bench / BookScore** | [AAAI-26](https://ojs.aaai.org/index.php/AAAI/article/view/40648) | Book-scale coherence, richness, factual grounding | 18 annotated bilingual books. **Self-authored metric — not comparable to others.** |
| **LongMemEval** | [arXiv:2410.10813](https://arxiv.org/abs/2410.10813) (used in Chroma's study) | Long-term interactive memory; knowledge update, temporal reasoning, multi-session | Conversational, not narrative — but the **focused-vs-full-input methodology is directly transferable.** |
| **NoLiMa** | [arXiv:2502.05167](https://arxiv.org/abs/2502.05167) | Long-context beyond literal matching | Tests latent association — the fiction-relevant capability. |
| **AbsenceBench** | [arXiv:2506.11440](https://arxiv.org/abs/2506.11440) | Recognizing what's *missing* | Highly relevant: "which promised element is absent" is a fiction evaluation primitive. |

### 7.2 Metrics that correct for known biases

**CED (Consistency Error Density)** `[VALIDATED]` — errors per 10,000 words. Necessary because *"simply counting errors per story unfairly penalizes models that generate longer outputs — a 10K-word story would intuitively have more opportunities for errors than a 2K-word one."*

**GRR (Group Relative Rank)** `[VALIDATED]` — rank models within each prompt group by `Q = words / (1 + errors)`, then average ranks. Necessary because *"some prompts inherently elicit more errors across all models,"* so raw CED conflates model quality with prompt difficulty. **If you build an internal eval, adopt both.**

### 7.3 A shipping evaluation architecture

`[VALIDATED — running in CI]` **word-compiler** — [12-evaluation-system.md](https://raw.githubusercontent.com/2389-research/word-compiler/main/docs/architecture/12-evaluation-system.md)

A **three-layer hybrid** design, worth copying wholesale:

```
Driver (workflow)        Deterministic Checks       LLM Judge
┌─────────────┐          ┌────────────────────┐     ┌────────────────┐
│ Bible       │          │ Kill list          │     │ Voice          │
│ Scene Plans │─────────▶│ Budget compliance  │     │ Subtext        │
│ Chapter Arc │          │ Lint compliance    │     │ Tone whiplash  │
│ Config      │          │ Sentence dist.     │     │ Metaphor       │
│             │          │ Word count         │     │ Scene goal     │
│ GenerateFn()│          │ Structural bans    │     │ Continuity     │
└──────┬──────┘          │ IR completeness    │     └───────┬────────┘
       │                 │ Setup/payoff       │             │
       ▼                 └────────┬───────────┘             │
  DriverResult ──────────────────▶ EvalRunArtifact ◀────────┘
```

**11 deterministic checks** (9 per-scene + 2 chapter-level):

| Check | Validates |
|---|---|
| `checkKillListCompliance` | No Bible avoid-list violations |
| `checkBudgetCompliance` | Total tokens within available budget |
| `checkRing1Cap` | Ring 1 within hard cap |
| `checkLintCompliance` | No lint errors |
| `checkSentenceDistribution` | Variance ≥ 3.0 for 5+ sentences; within character voice range |
| `checkProhibitedLanguage` | No character-specific prohibited words |
| `checkStructuralBans` | No structural ban matches (regex or literal) |
| `checkWordCount` | Within plan estimate **±20%** |
| `checkDialoguePresence` | Informational |
| **`checkIRCompleteness`** | **All completed scenes have verified Narrative IRs** |
| **`checkSetupPayoffClosure`** | **No dangling setups at manuscript completion** |

**6 LLM judge dimensions with explicit pass thresholds:**

| Dimension | Scale | Pass | Evaluates |
|---|---|---|---|
| `voice_consistency` | 1–10 | ≥ 7 | Matches character voice fingerprint |
| `subtext_adherence` | 1–3 | ≥ 2 | Gap between surface dialogue and meaning |
| **`tone_whiplash`** | 1–10 | ≥ 7 | **Tonal continuity *across scene transitions*** |
| `metaphoric_register` | 1–3 | ≥ 2 | Approved domains only |
| `scene_goal` | 1–10 | ≥ 7 | Narrative goal achieved, beat lands |
| **`continuity`** | 1–10 | ≥ 7 | **Opening follows naturally from previous scene** |

> **The key design insight:** `tone_whiplash` and `continuity` **compare the end of scene N with the start of scene N+1** — they are *pairwise/cross-boundary* dimensions, not single-text quality scores. This is how you operationalize continuity as a measurable quantity. The judge returns structured JSON `{ reasoning, score, passed, violations }`.

**CI integration:** PRs run `pnpm test` + `pnpm eval:mock` (canned prose, no LLM cost); nightly runs 5 rollouts against a live model. Artifacts persisted as JSON. **`--rollouts=N` for N independent runs** is important — with a stochastic generator, single-run evaluation is noise.

`[PROMISING]` **ainovel-cli**: seven-dimension quality review where **each dimension must cite original text as evidence**; results route to either a rewrite queue or a polish queue. **The "must cite evidence" requirement is the recurring theme across every credible system** (ConStory-Checker evidence chains, novel-master's problem/evidence/fix format, ainovel-cli's seven dimensions, jarvis-write's gate).

### 7.4 The honest limits of evaluation

`[VALIDATED negative result]` **FABLES**: *"While LLM-based auto-raters have proven reliable for factuality and coherence in other settings, we implement several LLM raters of faithfulness and find that **none correlates strongly with human annotations**, especially with regard to detecting unfaithful claims."* Their conclusion: detecting unfaithful claims *"is an important future direction not only for summarization evaluation but also as a testbed for long-context understanding."*

`[VALIDATED negative result]` **Synapse**: two independent LLM judges reached κ ≈ 0.35–0.39 on contradiction judgment, and **rubric sharpening degraded agreement**.

`[VALIDATED — methodological]` **Synapse** again, on validating a guard: *"A guard you haven't measured against labels is decoration."* They measured their own guard three times; the **first measurement was circular** (two numbers "from the same function fed different identity keys — one heuristic agreeing with a relaxed copy of itself"), the second showed their newest addition changed nothing, the third showed an "obvious improvement" made it strictly worse. Retained lesson: ***"If your two measurements share a function, they are one measurement."***

> **Practical stance:** use ConStory-Checker-style pipelines as *triage* (find candidates), and treat **human adjudication as the ground truth**, with a labeled sample audit at regular intervals. Every serious source independently arrived at "the checker proposes, a human disposes."

---

## 8. Evidence-quality classification

### (a) Well-validated — real implementations and/or peer review

| Technique | Evidence |
|---|---|
| **Temporal fact store with `valid_from`/`valid_until`** | FactTrack (NAACL 2025): 7B model + structure matches GPT-4 baseline. Shipped in jarvis-write. |
| **Two-stage hierarchical outline (global + section)** | Shen & Ying 2025: near-doubles character/style similarity vs. single-stage at matched R. |
| **Outline compression ratio ≈ 0.01 for 1M-word targets** | Same paper, quantified across 40 novels, 4 genres. |
| **Long context degrades non-uniformly; distractors compound it** | Chroma, 18 models, controlled for input length only. |
| **LLM auto-raters fail at faithfulness** | FABLES (COLM 2024), 3,158 human-annotated claims. |
| **Iterative/stateful retrieval beats single-step RAG on long narrative** | ComoRAG (AAAI 2026), 4 benchmarks, up to 11% relative gain. |
| **Consistency error taxonomy (5 categories, 19 subtypes)** | ConStory-Bench (Microsoft, 2026). |
| **CED and GRR metrics** | ConStory-Bench; explicit bias-correction rationale. |
| **draft → rerank → edit-best-continuation** | Re³ (EMNLP 2022): +14% plot coherence, +20% premise relevance (human-judged). |
| **Four-state foreshadowing ledger** | NovelClaw, jarvis-write, MuMuAINovel (three independent implementations). |
| **Mandatory evidence-citation in consistency reports** | ConStory-Checker, ainovel-cli, novel-master, jarvis-write gate — universal across credible systems. |
| **Budget enforcement via immune/priority sections** | word-compiler, shipped with lint enforcement of immunity. |
| **Two-tier rubric: deterministic checks + LLM judge** | word-compiler, running in CI. |

### (b) Promising but unproven

| Technique | Status |
|---|---|
| **Chapter handoff contract** | Well-specified + solves a *documented real bug*, but no published evaluation of error reduction. |
| **CFPG's `Foreshadow → Trigger → Payoff` triples** | Newest paper (Jan 2026), self-reported gains, not yet independently replicated. The *idea* is excellent. |
| **Quarantine-on-blocker (don't extract contradictions to bible)** | Strong reasoning, addresses a real compounding-pollution bug, evaluation absent. |
| **Reader-knowledge vs. character-knowledge closed loop** | The table is shipped; jarvis-write's own audit says the *injection* side ("what this character doesn't know") is not implemented. |
| **Recency/lifespan dual-signal promise tracking** | Noveling ships it; no evaluation published. |
| **Multi-agent frameworks (DeepWriter, SuperWriter)** | ConStory-Bench measured them as **statistically indistinguishable from plain prompting** (CED 0.67 vs 0.71). |
| **Motif/repetition suppression by label** | Sound reasoning ("store labels, not sentences"), shipping, unevaluated. |
| **Rule scan for globally-consistent-but-wrong facts** | Only mechanism found that addresses this class; no evaluation. |
| **Story-bible versioning + cascade/staleness marking** | jarvis-write's `is_stale` + `outline_versions`; described as "a gap across the entire web" by its authors. Sensible, unevaluated. |
| **Entropy-based error prediction** | ConStory-Bench found correlation; using it to *prioritize* checking is an untested extrapolation. |

### (c) Hype — treat with skepticism

| Claim | Why |
|---|---|
| **"1M-token context window solves long-form consistency"** | Chroma (18 models) and FABLES both measure degradation + recency bias at long context. ConStory-Bench: GPT-5-Reasoning at 9,050 words still scores CED 0.113. |
| **"Our multi-agent system maintains consistency"** | ConStory-Bench measured agent-enhanced (SuperWriter, 0.674) ≈ capability-enhanced (LongWriter-Zero, 0.669) ≈ plain prompting (0.71). **No measured advantage.** |
| **Self-authored benchmarks and metrics** (BookScore 80.92) | Not comparable across systems; defined by the system's own authors. |
| **"Knowledge graph automatically resolves contradictions"** | Synapse measured **70% of auto-retired facts were still true**, silently. Two independent corpora agreed (70% / 75%). |
| **"Just prompt it better / give it a better system prompt"** | CFPG's central finding: LLMs leave Chekhov's guns unfired *"even when the necessary context is present."* This is a representation problem, not a prompt problem. |
| **Pure-vector RAG over chapter chunks** | No F1 evidence found; jarvis-write removed it; Chroma shows coherent prose in context actively harms retrieval. |

---

## 9. Where sources disagree, and where evidence is thin

**Direct disagreements:**

1. **RAG vs. structured state** — ComoRAG calls retrieval *"pivotal in practice"*; jarvis-write **removed** its vector store entirely. *Resolution:* they retrieve different things (narrative text for reasoning vs. facts for constraints). Both reject naive chunk retrieval.

2. **Does coherent context help?** — Every practitioner guide says include prior prose. Chroma measured that **coherent haystacks retrieve worse** across all 18 models. *Chroma explicitly flags this as unexplained.* Practical workaround in shipping systems: separate prose context (voice) from structured context (facts) into distinct prompt sections.

3. **How aggressive should summarization be?** — Shen & Ying find **R ≈ 0.01 optimal** and single-stage lossy. Yet ConStory-Bench found **Generation tasks (no prior context) have higher error density than Expansion tasks** — suggesting more prior context helps. These aren't strictly contradictory (outline detail vs. prior prose) but the tension is unresolved.

4. **Do agentic pipelines help?** — DeepWriter and SuperWriter claim SOTA via multi-agent collaboration; ConStory-Bench measured **no consistency advantage** for agent-enhanced over plain prompting. Different metrics (BookScore vs. CED), so not a clean contradiction — but the burden of proof is on the multi-agent claims.

**Thin evidence:**

- **No ablation of recency weighting for fiction retrieval** was located. Universally recommended, never tested.
- **No public evaluation of foreshadowing-tracking systems.** NovelClaw, Noveling, MuMuAINovel, and jarvis-write all ship one; none publishes error-reduction numbers. **This is the largest evidence gap in the whole area** — and it's the question the user cares most about.
- **No head-to-head of story-bible architectures.** Everyone has a schema; nobody has compared schemas.
- **Token cost of the full pipeline is unreported** by every source except jarvis-write, which notes ~2–3 extra LLM calls per chapter for contract extraction + gate + optional pre-flight, and argues the cost is low because these are small JSON outputs at low temperature.
- **Human evaluation at >100 chapters is entirely absent.** ConStory-Bench targets 8,000–10,000 words. FABLES covers book-length *summarization*, not generation. **Nobody has published a controlled study of whether these techniques work at 1M words.**
- **Shen & Ying's "optimal ratio" is a reconstruction experiment** — compress a human novel, expand it back, measure. That is a proxy for generation, not generation itself.

**One more methodological caution, generously supplied by the Synapse author:** *"One corpus, one operator, 40 labels. The labels are mine, and I wrote the rule they judge."* Every single-corpus practitioner finding in this report — including the good ones — carries that caveat.

---

## 10. Synthesized implementation blueprint

Ordered so each stage is independently useful, and matching the cost-ordering that both jarvis-write and ainovel-cli independently converged on.

**Stage 0 — Schema first, model second.**
Define `facts` (temporal), `entities`, `relationships`, `foreshadowings`, `knowledge_states`, `chapter_states` (handoff contract), `chapter_summaries` (rolling) *before* wiring anything. FactTrack's result — a 7B model with the right schema matching a GPT-4 baseline — is the argument that **the data structure carries more weight than the model**.

**Stage 1 — Handoff anchor + contract.** (Highest ROI per jarvis-write's cost ordering: *"cheapest; doing this alone eliminates most contradictions."*)
Inject chapter N−1's **full closing state** as a P0 block when writing chapter N. Extract a structured contract at low temperature after finalizing. Generate the contract *and* keep the prose tail: **contract for facts, prose for voice.**

**Stage 2 — Temporal fact store + write-back extractor.**
Every finalized chapter runs a structured extraction (forced JSON, low temperature, quality-tier model — *"extraction errors pollute the whole bible"*) producing: new/changed facts (setting `valid_until` on superseded ones), foreshadowing status changes, new entities. Inject `valid_from ≤ N ≤ valid_until` facts as **hard constraints**.
**Guard the invalidation step structurally.** Restrict contradiction candidates to the same entity pair or same subject+relation. Do not let an unbounded candidate set reach an LLM judge — Synapse measured that configuration at 70% silent true-fact loss.

**Stage 3 — Thread ledger with trigger predicates.**
Adopt the four states plus `earliest_payoff_chapter` and `required_hints`. Add CFPG's **`trigger` predicate**. Scheduling rule: `status ∈ {planted, reinforced} AND expected_payoff_chapter ≤ current + 2` → inject a soft reminder. Also surface on **recency OR lifespan** (Noveling's dual signal), not a single counter.

**Stage 4 — Post-generation gate with teeth, and quarantine.**
Four-stage checker: category-guided extraction → pairwise contradiction pairing → evidence chains (quote + character offsets) → JSON report with severity. Then:
- `blocker` → auto-revise (cap N), re-check; still failing → **persist as `quarantined`, skip extraction, skip summary update, pause the queue.**
- `major` → persist as `pending_review`.
- `minor` → informational.
Run **pre-flight** before drafting: blueprint vs. previous contract, warn-only by default.

**Stage 5 — Linting and budget.** Adopt word-compiler's immune/priority section model. Decide at schema time which constraints can never be dropped; enforce with a lint check that errors if one is.

**Stage 6 — Evaluation harness.** Deterministic checks (git-clean, word count ±20%, kill list, budget) + LLM judge dimensions with explicit thresholds, **including cross-boundary dimensions** (`continuity`, `tone_whiplash`) that compare chapter N−1's end to chapter N's start. Use **CED** and **GRR**. Run **N independent rollouts**. Audit a labeled sample against human judgment regularly.

**Stage 7 — Whole-book offline diagnostics, at arc boundaries.**
Timeline gaps (regression/jump detection in `in_story_time`), disappeared characters (no contract or prose appearance in N chapters), stalled threads, missing contracts. Plus a **rule scan** against a human-authored world-rules pinboard, since the gate by construction cannot catch errors that are internally consistent.

**Explicitly consider *not* building:** a vector store over chapter chunks. Two independent sources either removed one (jarvis-write) or measured that coherent prose context actively degrades retrieval (Chroma). If you do build retrieval, build **ComoRAG-style iterative probing over structured state**, not top-k similarity over prose.

---

## 11. Source index

**Papers**
1. [FactTrack: Time-Aware World State Tracking in Story Outlines — NAACL 2025](https://aclanthology.org/2025.naacl-long.144/) · [HF](https://huggingface.co/papers/2407.16347)
2. [Lost in Stories: Consistency Bugs in Long Story Generation by LLMs (ConStory-Bench/Checker) — arXiv:2603.05890](https://arxiv.org/abs/2603.05890) · [HTML](https://arxiv.org/html/2603.05890v1) · [project](https://picrew.github.io/constory-bench.github.io/)
3. [FABLES: Evaluating faithfulness and content selection in book-length summarization — COLM 2024](https://arxiv.org/abs/2404.01261)
4. [ComoRAG: Cognitive-Inspired Memory-Organized RAG for Stateful Long Narrative Reasoning — AAAI 2026](https://arxiv.org/abs/2508.10419) · [code](https://github.com/EternityJune25/ComoRAG)
5. [Measuring Information Distortion in Hierarchical Ultra-long Novel Generation: The Optimal Expansion Ratio](https://ar5iv.labs.arxiv.org/html/2505.12572)
6. [Codified Foreshadowing-Payoff Text Generation (CFPG) — arXiv:2601.07033](https://arxiv.org/abs/2601.07033) · [HF](https://huggingface.co/papers/2601.07033)
7. [Re³: Generating Longer Stories With Recursive Reprompting and Revision — EMNLP 2022](https://arxiv.org/abs/2210.06774) · [HF](https://huggingface.co/papers/2210.06774)
8. [DeepWriter: A Multi-Agent Collaboration Framework for Information-rich Ultra-long Book Writing — AAAI-26](https://ojs.aaai.org/index.php/AAAI/article/view/40648)
9. [Octopus: Entropy-Controlled Science Fiction Literature Generation with Persistent Memory-Context Binding — AAAI-26](https://ojs.aaai.org/index.php/AAAI/article/view/41492)

**Engineering reports**
10. [Chroma — Context Rot: How Increasing Input Tokens Impacts LLM Performance (2025)](https://www.trychroma.com/research/context-rot) · [code](https://github.com/chroma-core/context-rot)
11. [Synapse — Your temporal knowledge graph is quietly deleting true facts (2026)](https://raw.githubusercontent.com/alexsh88/synapse/refs/heads/main/docs/FINDING-silent-fact-loss.md)

**Open-source implementations**
12. [word-compiler (2389-research)](https://github.com/2389-research/word-compiler) — [Narrative IR](https://raw.githubusercontent.com/2389-research/word-compiler/refs/heads/main/docs/architecture/04-narrative-ir.md) · [Context Compiler](https://raw.githubusercontent.com/2389-research/word-compiler/main/docs/architecture/02-context-compiler.md) · [Auditor & Linter](https://raw.githubusercontent.com/2389-research/word-compiler/main/docs/architecture/03-auditor-linter.md) · [Evaluation System](https://raw.githubusercontent.com/2389-research/word-compiler/main/docs/architecture/12-evaluation-system.md)
13. [jarvis-write / 藏山](https://github.com/ynnyh/jarvis-write) — [Architecture](https://ynnyh.github.io/jarvis-write/01-architecture) · [Data Model](https://ynnyh.github.io/jarvis-write/02-data-model) · [Three Engines](https://ynnyh.github.io/jarvis-write/03-engines) · [Chapter Pipeline & Review Design](https://ynnyh.github.io/jarvis-write/08-%E7%AB%A0%E8%8A%82%E7%94%9F%E4%BA%A7%E6%B5%81%E6%B0%B4%E7%BA%BF%E4%B8%8E%E5%89%8D%E5%90%8E%E5%AE%A1%E6%A0%B8%E4%BD%93%E7%B3%BB%E8%AE%BE%E8%AE%A1)
14. [NovelClaw (iLearn-Lab)](https://github.com/iLearn-Lab/NovelClaw)
15. [ainovel-cli (voocel)](https://github.com/voocel/ainovel-cli)
16. [MuMuAINovel](https://github.com/xiamuceer-j/MuMuAINovel) · [novel-master](https://github.com/dashenbibi/novel-master) · [ai-novel-lab](https://github.com/xindoo/ai-novel-lab)
17. [graphify-novel — knowledge-graph AI writing assistant](https://github.com/Anshler/graphify-novel)
18. [Cognitae — story state YAML](https://github.com/cognitae-ai/Cognitae/blob/main/Cognitae_Techne/Elari_Story/009_Elari_Story_State_v2.yml)
19. [graphiti PR #1729 — structural guard on invalidation candidate selection (open, unreviewed)](https://github.com/getzep/graphiti/pull/1729)

**Practitioner methodology**
20. [Noveling — Why Long-Form AI Fiction Breaks](https://noveling.dev/guide/en/blog/long-form-consistency-ai/) · [Narrative Promise Tracking](https://noveling.dev/guide/en/ai/autopilot-consistency/) · [Keeping Characters Consistent Across 100+ Chapters](https://noveling.dev/guide/en/blog/character-consistency-long-form/) · [Thread Coverage](https://noveling.dev/guide/en/creative-tools/thread-coverage/)
21. [Phase-Fiction Workflow methodology](https://raw.githubusercontent.com/nanzhipro/phase-fiction-skill/6ceef34f30ccaeac3b078b81ba32a5ef36709783/references/methodology.md)
22. [SillyTavern World Info documentation (lorebook activation/recursion)](https://docs.sillytavern.app/usage/worldinfo/)

---

## 12. Bottom line

1. **The problem is representational, not contextual.** CFPG's finding that LLMs leave setups unpaid "even when the necessary context is present," combined with FactTrack's result that a 7B model with temporal intervals matches GPT-4 without them, and Chroma's finding that more coherent context makes retrieval *worse* — all three point the same direction. **Better schemas beat bigger windows.**

2. **Temporal validity intervals are the highest-value single data structure.** `valid_from` / `valid_until` on atomic facts converts "did the model remember?" into a deterministic SQL filter. This is the one technique with both peer-reviewed validation and multiple independent shipping implementations.

3. **Scope contradiction candidates structurally, or you will silently delete true facts.** The Synapse audit (70% of auto-retired facts still true; two independent corpora agreeing at 70%/75%) is the sharpest warning in this report, and the failure is silent.

4. **Cite evidence or don't bother.** Every credible consistency checker — ConStory-Checker, ainovel-cli, novel-master, jarvis-write's gate — forces the model to quote source text with positions. Systems that ask for a verdict without evidence produce judgments that don't agree with humans (FABLES: no auto-rater correlated strongly; Synapse: κ ≈ 0.35–0.39, and rubric sharpening made it worse).

5. **Track threads as scheduleable objects with trigger predicates**, not as text to retrieve. Four states + `earliest_payoff_chapter` + `required_hints` + CFPG's `trigger` turns "remember the Chekhov's gun" into a pattern match against the chapter plan.

6. **Don't let bad chapters become canon.** Quarantine is the mechanism: persist, skip extraction, skip summary update, pause the queue.

7. **The evidence is thinnest exactly where you need it most.** Nobody has published a controlled evaluation at 100+ chapters, and no foreshadowing-tracking system has public error-reduction numbers. Treat every practitioner claim in §5 and §6 — including the good ones — as informed intuition backed by real bugs, not measured outcomes.

8. **Agentic complexity is not the answer.** ConStory-Bench measured agent-enhanced and capability-enhanced systems at statistical parity with plain frontier-model prompting on consistency. The wins came from data structures and gates, not from more agents.
