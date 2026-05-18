---
name: ambisql
description: >
  Detects and resolves natural language query ambiguities before SQL generation,
  preventing incorrect SQL from unclear user intent. Applies AmbiSQL's 7-type
  taxonomy (AmbiSchema, AmbiValue, AmbiView, AmbiSource, AmbiContext, AmbiFallacy,
  AmbiRef) to classify ambiguous phrases, generates intuitive multi-choice
  clarification questions, and rewrites queries into precise, unambiguous form
  with evidence. Use this skill whenever a user asks a database question in
  natural language, requests Text-to-SQL or NL2SQL conversion, writes a query
  that could map to multiple SQL interpretations, mentions table or column names
  ambiguously, uses vague filters like "top", "best", "popular", "recent", or
  "latest", references dates imprecisely like "after the World Cup" or
  "yesterday", asks about data where the question seems underspecified, or
  discusses improving SQL query accuracy. Even if the user doesn't explicitly
  mention "ambiguity", activate for any natural language database query that
  could benefit from clarification before generating SQL. Also activate when
  users ask about the AmbiSQL system, its taxonomy, or how ambiguity detection
  works.
---

# AmbiSQL — Ambiguity Detection & Resolution for Text2SQL

## Why This Matters

A seemingly simple question like "show me the oldest users" can produce
entirely different SQL depending on whether "oldest" means highest `age`
or earliest `registration_date`. Without catching these ambiguities upfront,
the generated SQL silently returns wrong results — and the user may never
realize it. AmbiSQL prevents this by detecting ambiguities *before* SQL
generation, asking targeted clarification questions, and rewriting the
query into a precise form that downstream text2sql systems can handle
accurately.

## High-Level Flow

```
User's natural language question
      ↓
【Phase 1】Detect ambiguities (7-type taxonomy)
      ↓
  Has ambiguity?
  ├─ YES → 【Phase 2】Clarify via multi-choice questions (up to 3 rounds)
  └─ NO  → Skip to Phase 3
      ↓
【Phase 3】Rewrite question + collect evidence
      ↓
Precise question + evidence → downstream text2sql
```

## When to Skip

Not every query needs ambiguity detection. Skip this workflow when:
- The user provides a fully specified query with exact column names, table
  names, filter values, and date ranges (e.g., "Return user_id and email
  for all US users registered between 2023-01-01 and 2023-12-31")
- The user explicitly says "just generate the SQL" or "don't ask questions"
- The user is debugging or modifying an existing SQL query rather than
  composing from natural language

## Inputs

| Input | Required | Description |
|---|---|---|
| question | Yes | User's natural language question (from conversation context) |
| db_name | No | Database name — used to obtain schema for more precise detection |
| sql_dialect | No | SQL dialect, defaults to `SQLite` |

Extract these from the conversation context. When a database name is
available, obtain the schema for more accurate ambiguity detection:

```bash
python .claude/skills/ambisql/scripts/schema_dump.py <db_name>
```

If schema is unavailable, proceed without it — the taxonomy and question
analysis still work, just with less precision on schema-related ambiguities
(AmbiSchema, AmbiValue).

---

## Phase 1: Ambiguity Detection

**Goal:** Find every phrase in the user's question that could lead to
multiple valid SQL interpretations.

Analyze the question against the database schema (if available) using
the 7-type ambiguity taxonomy. The taxonomy is organized in two levels:

| Source | Type | What's ambiguous |
|---|---|---|
| Database | AmbiSchema | Multiple columns/tables could satisfy the condition |
| Database | AmbiValue | WHERE clause value mapping is unclear |
| Database | AmbiView | SQL operation (COUNT vs SUM vs RANK etc.) is unclear |
| LLM | AmbiSource | Unclear if data should come from DB or LLM reasoning |
| LLM | AmbiContext | LLM reasoning lacks temporal/monetary/unit context |
| LLM | AmbiFallacy | Question contains incorrect factual assumptions |
| LLM | AmbiRef | Temporal/spatial reference scope is unclear |

For full definitions, option generation rules, and worked examples, read
[taxonomy.md](taxonomy.md).

### How to Detect

Use the `AmbiguityDetection_prompt` template from [prompts.md](prompts.md)
with these inputs:
- `{question}` — the user's natural language question
- `{schema}` — database schema (or `None` if unavailable)
- `{evidence}` — accumulated clarification evidence from prior rounds
  (`None` for initial detection)
- `{examples}` — few-shot examples from [taxonomy.md](taxonomy.md)

**Decision point:** If the detection returns `has_ambiguity: false`, skip
directly to Phase 3 — the question is already precise enough for SQL
generation.

---

## Phase 2: Clarification (Multi-round Interaction)

**Goal:** Resolve each detected ambiguity by presenting user-friendly
multi-choice questions and collecting the user's actual intent.

This is the most user-facing phase. The quality of clarification questions
directly determines whether the final SQL matches the user's intent.
Present each ambiguity as a clear, non-technical multiple-choice question
that a domain expert (not necessarily a SQL expert) can answer confidently.

### Generating Choices

For each ambiguity in `question_set`, use the `CQ_Generation_prompt`
template from [prompts.md](prompts.md) to transform the technical options
into user-friendly choices.

**Two mandatory choices at the end of every list:**
- **"Abstain"** — lets the user signal this isn't actually ambiguous for
  their use case, preventing unnecessary clarification overhead.
- **"Others"** — lets the user provide free-text context that the
  predefined options don't cover. Ambiguity detection can't anticipate
  every valid interpretation.

### Presenting to the User

Present clarification questions naturally in the conversation. Group related
ambiguities together when they share context, but don't overwhelm the user
with too many questions at once.

**Example of natural presentation:**

> I noticed your question "show me the top developers in Silicon Valley"
> could be interpreted in a couple of ways. Let me ask two quick questions:
>
> **What does "top" mean here?**
> 1. Developers with the highest total reputation points
> 2. Developers who completed the most projects
> 3. Developers with the best user ratings
> 4. Abstain (this isn't ambiguous for my needs)
> 5. Others (please specify)
>
> **How broadly should "Silicon Valley" be defined?**
> 1. Just Palo Alto and Mountain View
> 2. The entire San Francisco Bay Area
> 3. Abstain
> 4. Others (please specify)

### After Collecting Answers

```
User answers collected
    ↓
Build evidence (QA pairs organized by ambiguity type)
    ↓
Has free-text input ("Others" selected)?
    ├─ YES → Refine question with QuestionRefine_prompt
    │        → Re-run Phase 1 (check for residual ambiguity)
    └─ NO  → Proceed to Phase 3
```

**Max clarification rounds: 3.** If ambiguities remain after 3 rounds,
proceed to Phase 3 with the best available interpretation and flag
`partial_clarification: true`. This prevents frustrating the user with
endless questions while still capturing meaningful intent.

---

## Phase 3: Question Rewrite & Output

**Goal:** Produce a precise, unambiguous question with evidence that
downstream SQL generation can use confidently.

Collect all clarification evidence (all Q&A pairs organized by ambiguity
type) and produce the final output:

```json
{
  "is_clarified": true,
  "original_question": "User's original question",
  "refined_question": "The precise, rewritten question",
  "evidence": "Collected clarification evidence",
  "db_name": "Database name",
  "sql_dialect": "SQLite"
}
```

If no ambiguity was detected, `refined_question` equals the original
question and `evidence` is empty.

---

## Evidence Management (PreferenceTree)

Clarification answers are organized hierarchically by ambiguity source
and type:

```
root
├── Database-sourced ambiguity
│   ├── AmbiSchema → [Q&A pairs]
│   ├── AmbiValue  → [Q&A pairs]
│   └── AmbiView   → [Q&A pairs]
└── LLM-sourced ambiguity
    ├── AmbiSource  → [Q&A pairs]
    ├── AmbiContext → [Q&A pairs]
    ├── AmbiFallacy → [Q&A pairs]
    └── AmbiRef     → [Q&A pairs]
```

When a new answer conflicts with an existing one (same question intent,
different answer), the new answer takes precedence via semantic merging
(see `NodeMerge_prompt` in [prompts.md](prompts.md)).

The tree produces a flat text representation of all evidence, used in
subsequent detection rounds and the final output.

---

## Usage Examples

**Example 1 — Multiple ambiguities detected and resolved:**

> User: "Show me the top developers in Silicon Valley"

Phase 1 detects two ambiguities:
- **AmbiView**: "top" could mean highest reputation, most projects, or
  best ratings — each produces a different SQL operation
- **AmbiRef**: "Silicon Valley" could mean just Palo Alto/Mountain View
  or the entire Bay Area

Phase 2 presents targeted multi-choice questions. User clarifies intent.

Phase 3 rewrites: "Show me the developers in the San Francisco Bay Area
with the highest total reputation points."

**Example 2 — No ambiguity (skip to output):**

> User: "Return user_id and email for all US users registered between
> 2023-01-01 and 2023-12-31"

Phase 1 finds no ambiguity — columns, filters, and dates are fully
specified. Question passes through unchanged.

**Example 3 — Factual error caught:**

> User: "List athletes from the 1940 London Olympics"

Phase 1 detects **AmbiFallacy** — no Olympics were held in 1940. Presents
correction options: 1908, 1948, or 2012 London Olympics.

---

## Error Handling

| Scenario | Behavior |
|---|---|
| Schema unavailable | Proceed without schema; rely on question analysis alone |
| Malformed JSON from LLM | Extract JSON from markdown blocks or surrounding text; retry if extraction fails |
| User selects "Abstain" for all | Treat question as unambiguous; skip to Phase 3 |
| User selects "Others" with free text | Incorporate via `QuestionRefine_prompt`; re-run Phase 1 |
| Max rounds (3) exceeded | Output current best question with `partial_clarification: true` |

---

## Additional Resources

- [taxonomy.md](taxonomy.md) — Full ambiguity taxonomy definitions + 8 few-shot examples
- [prompts.md](prompts.md) — Complete prompt templates with variable documentation
