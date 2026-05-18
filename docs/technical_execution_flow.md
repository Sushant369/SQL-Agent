# AmbiSQL Technical Execution Flow

This document explains the detailed execution flow and technical implementation of the current AmbiSQL backend, with the FastAPI backend in `ambisql/server_2.py` as the primary runtime reference.

The explanation is organized around three core stages:

1. Understanding user intent and asking clarification questions
2. Mapping business tables to clarified intent and generating SQL
3. Executing SQL and generating grounded answers with citations

---

## 1. System Overview

At runtime, the system is driven by two main API endpoints exposed by `ambisql/server_2.py`:

- `POST /api/sql/analyze`
- `POST /api/sql/resolve`

The high-level control flow is:

1. The user submits a question through the UI.
2. The backend decides whether the question is a new request or a follow-up to the previous turn.
3. The backend constructs a business-aware schema representation from the SQLite database plus curated metadata CSVs.
4. The ambiguity engine checks whether the question is underspecified.
5. If ambiguity exists, the backend returns targeted clarification questions.
6. Once the user clarifies the request, the backend generates SQL from the clarified intent and the grounded schema.
7. The SQL is executed on the SQLite database.
8. The result rows are summarized into a grounded natural-language answer.
9. The backend returns SQL, answer, query result preview, and citations for traceability.

This architecture is intentionally not a pure text-generation pipeline. It is a controlled workflow that combines:

- LLM-based semantic understanding
- business schema grounding
- interactive ambiguity resolution
- actual SQL execution on the database
- evidence-backed answer generation

---

## 2. Stage One: Understanding User Intent and Asking Clarification Questions

### 2.1 API entrypoint and session model

The process starts in `ambisql/server_2.py` inside `analyze_sql_query`.

The backend maintains in-memory conversation sessions using the `ChatSession` class. Each session stores:

- `session_id`
- `db_name`
- current interpreted `question`
- message history
- ambiguity workflow usage
- SQL generation usage

This session memory is important because the system supports conversational follow-ups instead of treating every user message as an isolated query.

### 2.2 Detecting whether the user asked a new question or a follow-up

Before ambiguity analysis, the backend runs `interpret_user_question` in `ambisql/server_2.py`.

Its purpose is to decide whether the current turn is:

- a new standalone question, or
- a follow-up modification on top of the previous question

This is implemented using:

- `FOLLOW_UP_INTERPRETATION_PROMPT` in `ambisql/server_2.py`
- `LLMCaller` in `ambisql/utils/llm_caller.py`
- recent chat history from `build_recent_history_text`

Technical behavior:

1. If the session has no previous active question, the turn is treated as `new_question`.
2. If the database changed between turns, the turn is also treated as `new_question`.
3. Otherwise, an LLM is prompted with:
   - previous active question
   - recent message history
   - new user message
4. The LLM returns strict JSON:
   - `mode`
   - `standalone_question`

This standalone rewrite is critical because downstream ambiguity detection and SQL generation work best on a fully explicit query rather than on elliptical follow-up fragments like:

- `only top 10`
- `what about above 90%`
- `exclude sold properties`

So the system first converts conversational follow-ups into a complete query before deeper analysis.

### 2.3 Building the business-aware schema representation

Once the user intent is normalized into a standalone question, the backend creates an `AmbiguityResolver` from `ambisql/core/ambiguity_resolver.py`.

Inside its constructor, it initializes:

- `SchemaGenerator`
- `PreferenceTree`
- `CQGenerator`
- `LLMCaller`

The most important grounding step here is `SchemaGenerator` in `ambisql/core/schema_generator.py`.

This module does not rely only on raw SQLite schema. It merges two sources:

1. physical schema from SQLite
2. semantic metadata from curated `database_description/*.csv` files

For each table:

1. It reads true column structure using `PRAGMA table_info(table)`.
2. It reads business metadata from the corresponding CSV.
3. It joins:
   - column name
   - primary key information
   - data type
   - column description
   - value description
4. It samples example values from the live database using:
   - `SELECT DISTINCT [column_name] FROM table LIMIT 3`

This produces:

- `formatted_full_schema`: a text schema prompt used for SQL generation
- `formatted_full_schema_json`: a structured dictionary used for ambiguity analysis and semantic grounding

This is a key design decision: the system is not interpreting questions against bare technical table names only. It is interpreting them against a semantically enriched business schema.

That business enrichment is how the model can associate natural language like:

- `physical occupancy percentage`
- `fund`
- `valuation`
- `property`

with the most relevant tables and columns, even if the wording does not exactly match the raw SQL field names.

### 2.4 Ambiguity detection logic

The core ambiguity engine is `AmbiguityResolver.check_ambiguity`.

It builds an LLM prompt from:

- the current question
- the schema JSON
- any existing clarification evidence
- taxonomy examples

using:

- `AmbiguityDetection_prompt`
- `AmbiguityDetection_examples`

from `ambisql/prompts/ambiguity_detection_prompt.py`.

The ambiguity taxonomy is intentionally fine-grained. It distinguishes:

- Database-sourced ambiguity
  - `AmbiSchema`
  - `AmbiValue`
  - `AmbiView`
- LLM-sourced ambiguity
  - `AmbiSource`
  - `AmbiContext`
  - `AmbiFallacy`
  - `AmbiRef`

This taxonomy matters because each ambiguity type requires different clarification logic.

Examples:

- `AmbiSchema`: Which table or column is intended?
- `AmbiValue`: Which stored value interpretation should be used?
- `AmbiView`: Which SQL operation is intended?
- `AmbiRef`: Which temporal or spatial interpretation is meant?

The prompt instructs the LLM to return strict JSON containing:

- `has_ambiguity`
- `question_set`

where each item in `question_set` includes:

- clarification question text
- level 1 ambiguity label
- level 2 ambiguity label
- structured description of plausible choices

### 2.5 Guardrails against unnecessary ambiguity questions

Ambiguity detection is LLM-based, but it is not left unfiltered. The backend applies deterministic post-processing to reduce false positives.

This happens in:

- `find_exact_unique_column_matches`
- `find_strong_natural_language_matches`
- `has_explicit_literal_condition`
- `filter_false_positive_ambiguities`

inside `ambisql/core/ambiguity_resolver.py`.

These routines provide several technical safeguards:

#### Exact unique schema grounding

If the user explicitly names a column and that column is unique in the schema, the system suppresses unnecessary `AmbiSchema` follow-ups.

#### Natural-language schema grounding

The method `find_strong_natural_language_matches` tokenizes:

- the user question
- column names
- column descriptions
- value descriptions

and scores lexical overlap.

It also boosts important domain signals such as:

- `occupancy`
- `physical`
- `percent`
- `property`

If one candidate column is clearly stronger than the others, the system treats the user phrase as already grounded.

This is how business semantics are used to avoid asking low-value questions when intent is already reasonably inferable from the schema metadata.

#### Explicit literal condition recognition

If the user provides a direct condition such as:

- `< 80`
- `= 'US'`
- `>= 0.09`

the system recognizes that the value intent may already be sufficiently explicit and can suppress false `AmbiValue` prompts.

### 2.6 Turning ambiguity items into user-friendly clarification questions

Once ambiguity is detected, the system does not show the raw technical ambiguity object directly to the user.

Instead it uses `CQGenerator` in `ambisql/core/cq_generator.py`.

This module:

1. takes each ambiguity item
2. reads its description
3. prompts the LLM to rewrite it into simpler, human-friendly multiple-choice options
4. validates the response as JSON
5. attaches the resulting `choices` array

This separation is important:

- ambiguity detection decides what is unclear
- clarification question generation decides how to ask the user about it

That makes the interaction both technically grounded and business-friendly.

### 2.7 Clarification memory and residual ambiguity resolution

When the user answers clarification questions, the backend processes them in `resolve_ambiguities` and passes them into `AmbiguityResolver.ambi_correction`.

Clarifications are stored in a structured evidence model called `PreferenceTree` in `ambisql/core/preference_index.py`.

The tree groups evidence by:

- level 1 ambiguity class
- level 2 ambiguity class

Each leaf stores question-answer pairs.

If a new answer overlaps semantically with an existing answer, `node_merge` uses an LLM to merge or replace the old evidence instead of appending redundant records.

This design is useful in multi-turn chats because it prevents evidence drift and allows later prompts to receive a clean summary of user decisions rather than an uncontrolled transcript.

The evidence tree is then traversed into a compact text representation using `PreferenceTree.traverse()`, which becomes part of the next ambiguity-detection or SQL-generation context.

This means the system does not merely remember past messages. It remembers past decisions in a structured intent model.

---

## 3. Stage Two: Mapping Business Tables to Clarified Intent and Generating SQL

### 3.1 Why the schema is business-grounded rather than only structural

The SQL generation stage depends heavily on the schema object produced earlier.

The most important design choice is that the model receives:

- physical schema structure
- business descriptions
- value descriptions
- sample values

instead of only raw table and column names.

This creates a semantic bridge between business language and SQL language.

For example, if a user asks for:

- `highest physical occupancy`
- `funds with net IRR above 9%`
- `property valuation`

the model can associate business terminology with:

- likely fact tables
- likely dimension tables
- likely metric fields
- likely join anchors

That is how the system restricts itself to asking relevant questions from business tables rather than asking abstract or ungrounded follow-ups.

### 3.2 Clarified intent package used for SQL generation

After ambiguity resolution completes, `AmbiguityResolver.format_response` returns:

- `is_clarified = True`
- refined `question`
- `evidence`

The `evidence` field is the structured preference trace from `PreferenceTree.traverse()`.

This evidence is important because it explicitly tells downstream generation:

- which column interpretation the user chose
- which filter interpretation was selected
- which temporal or business reference was intended
- which constraints were added later

So the SQL generator is not guessing from the original user utterance alone. It works from:

1. normalized question
2. accumulated clarification evidence
3. business-grounded schema

### 3.3 SQL generation implementation

SQL generation happens in `ambisql/utils/nl2sql_agent.py` through the `XiYanAgent` class.

The pipeline is:

1. Build prompt using `xiyan_template_en`
2. Inject:
   - `dialect`
   - clarified `question`
   - full business-grounded schema text
   - clarification `evidence`
3. Send prompt to `gpt-4o-mini`
4. Return generated SQL text

The key method is `XiYanAgent.generate_sql(question, evidence, schema)`.

This method is prompt-based, but it is constrained by strong grounding inputs:

- the clarified natural-language intent
- the full schema with business descriptions
- the explicit evidence trail from prior clarifications

This is the main semantic mapping mechanism from business language to SQL.

### 3.4 Why clarification reduces SQL error

Without clarification, one business phrase may correspond to multiple plausible SQL expressions.

Examples:

- multiple candidate metric columns
- multiple time interpretations
- multiple business definitions of `top`, `high`, or `active`
- multiple stored value representations

Clarification narrows the search space before SQL generation.

Technically, this reduces error in two ways:

1. It reduces prompt ambiguity before generation.
2. It injects explicit user-selected evidence back into the SQL generation prompt.

So instead of asking the LLM to infer both:

- what the user means
- how to translate that meaning into SQL

the pipeline decomposes the task:

- first resolve intent
- then translate resolved intent into SQL

That decomposition is the main reason the system is more reliable than a direct one-shot text-to-SQL call.

### 3.5 SQL normalization before execution

Generated SQL is normalized before execution inside `ambisql/server_2.py`.

Two helper functions are used:

- `normalize_sql_query`
- `add_semicolon_if_missing`

These ensure that:

- markdown code fences are stripped
- the final SQL ends with a semicolon

This is a small but practical hardening step that prevents execution failures caused by formatting artifacts from the model output.

---

## 4. Stage Three: Executing SQL and Generating the Final Response with Citations

### 4.1 SQL execution

Once the final SQL is generated, the backend executes it using `execute_query` in `ambisql/utils/db_utils.py`.

This function:

1. opens a SQLite connection using:
   - `path/db_name/db_name.sqlite`
2. executes the SQL query
3. if the statement is `SELECT` or `WITH`, fetches:
   - column names from `cursor.description`
   - rows from `cursor.fetchall()`
4. closes the connection
5. returns either:
   - raw rows, or
   - `{columns, rows}` when `include_columns=True`

In the FastAPI server, execution is done with `include_columns=True` so the backend can later build:

- grounded answers
- result previews
- citations
- query metadata

### 4.2 Grounded answer generation

The system does not directly show raw SQL output as the final answer. It converts the returned result set into a natural-language answer using `build_grounded_answer` in `ambisql/server_2.py`.

This method works as follows:

1. If zero rows are returned:
   - return a deterministic answer saying no matching rows were found
   - attach a `[query result]` citation
2. Otherwise:
   - build a structured preview of the first result rows via `build_result_preview`
   - prompt the LLM with:
     - original clarified question
     - executed SQL
     - row count
     - structured result preview
   - require strict JSON output with:
     - `answer`
     - `citations`

This is a grounded summarization step, not an open-ended answer generation step.

The prompt explicitly tells the model:

- use only the supplied SQL result
- do not guess
- include inline citation markers

That means the answer is based on returned database rows rather than on the model’s world knowledge.

### 4.3 Query metadata extraction for traceability

To improve traceability, the backend also extracts query metadata using `extract_query_metadata` in `ambisql/server_2.py`.

This routine scans the generated SQL and compares it against `formatted_full_schema_json` to infer:

- `tables_used`
- `columns_used`
- `row_count`

Important behavior:

- it only includes columns that appear to be referenced by the SQL
- if explicit columns cannot be detected reliably, it falls back to result columns

This metadata is then converted into a citation object by `build_query_metadata_citation`.

This allows the UI to explain not only what the answer is, but also:

- which business tables participated
- which columns were used
- how many rows were returned

### 4.4 Row-level citations

If grounded answer generation succeeds, the model returns citations such as:

- `[rows 1-3]`
- `[row 1]`

If grounded answer generation fails or returns malformed JSON, the backend falls back to deterministic row-level evidence using `build_result_citations`.

That fallback ensures the system still returns traceability information even when the LLM summarization step is imperfect.

### 4.5 Final response payload returned to the UI

When a query is fully resolved and executed, the backend returns a payload containing:

- `sql_statement_clarified`
- `grounded_answer`
- `citations`
- `query_metadata`
- `query_result`
- `monitoring`

This is what makes the final UI answer explainable.

The UI can show:

- the generated SQL
- the natural-language answer
- the tables used
- the columns used
- the number of returned rows
- query result preview
- token/cost monitoring

This combination allows the system to demonstrate both:

- functional correctness
- operational traceability

---

## 5. Why the Answer is More Accurate Than a Direct Chatbot Guess

The current implementation improves answer reliability because it does not let the model answer from natural language alone.

It introduces three strong grounding layers:

### Layer 1: Intent grounding

The system interprets follow-ups, detects ambiguity, and asks clarification questions before SQL generation.

### Layer 2: Schema grounding

The system maps user language to a business-enriched schema built from:

- actual SQLite structure
- curated business descriptions
- sample values

### Layer 3: Result grounding

The system executes the SQL on the real database and builds the final answer only from the returned rows.

That means the model is used in three controlled roles:

- ambiguity classifier
- clarification generator
- grounded result summarizer

It is not used as an unconstrained answer source.

---

## 6. Technical Strengths of the Current Design

### 6.1 Separation of responsibilities

The system decomposes the problem into modular stages:

- conversational interpretation
- ambiguity detection
- clarification question generation
- intent memory
- SQL generation
- SQL execution
- grounded answer generation

This makes the pipeline easier to debug and explain.

### 6.2 Business-semantic schema grounding

The use of `database_description/*.csv` plus live example values gives the model domain context it would not get from raw DDL alone.

### 6.3 Structured memory

The `PreferenceTree` stores resolved intent as reusable evidence rather than just as loose chat history.

### 6.4 Traceable final answer

Because the final answer is generated from executed rows and includes metadata citations, the UI can justify how the answer was produced.

---

## 7. Current Limitations

For completeness, the current implementation also has some practical limits:

### 7.1 In-memory sessions

Sessions are stored in memory only. Restarting the backend clears all history.

### 7.2 SQL metadata extraction is heuristic

`extract_query_metadata` uses SQL string matching against schema names. It works well for many queries but is not a full SQL parser.

### 7.3 Grounded answer still uses an LLM summarizer

The final answer is grounded in rows, but phrasing is still generated by an LLM. The raw result preview and citations remain the safety mechanism for verification.

### 7.4 Schema quality depends on metadata quality

Business grounding is only as strong as the `database_description` CSVs. Poor descriptions reduce semantic alignment quality.

---

## 8. Summary

The current AmbiSQL backend is not simply generating SQL from a prompt. It is performing a multi-stage grounded reasoning workflow:

1. Understand whether the user asked a new or follow-up question.
2. Build a business-aware schema representation from structural and semantic metadata.
3. Detect unresolved ambiguity using a taxonomy-driven LLM prompt.
4. Ask targeted clarification questions when intent is underspecified.
5. Store clarification decisions in a structured evidence tree.
6. Generate SQL from clarified intent plus schema plus evidence.
7. Execute the SQL against the actual database.
8. Generate a grounded natural-language answer from the returned rows.
9. Return citations and query metadata for traceability.

This design is what allows the system to be both interactive and explainable, and it is the core reason it is more trustworthy than a direct natural-language chatbot response.

---

## 9. Confidence Score Logic

The UI confidence score is implemented as a deterministic execution-confidence heuristic in `ambisql/server_2.py`. It is not a model probability and it is not a benchmark accuracy metric. Instead, it is a weighted score derived from concrete checkpoints in the AmbiSQL pipeline.

The purpose of this score is to communicate answer reliability to end users in a transparent and explainable way.

### 9.1 Why a heuristic score is used

At runtime, the system usually does not have ground-truth SQL or ground-truth answers for the user’s question. Because of that, the backend cannot honestly compute true accuracy on the fly.

What it can compute is how many reliability checkpoints were successfully passed, such as:

- whether the user intent was interpreted cleanly
- whether ambiguity was resolved
- whether SQL was generated
- whether SQL executed successfully
- whether the final answer was grounded in actual returned rows
- whether traceability metadata was extracted

This is why the system uses a weighted confidence heuristic instead of a probabilistic accuracy estimate.

### 9.2 Implementation location

The confidence score is produced by `build_confidence_report` in `ambisql/server_2.py`.

This function returns:

- `score_percentage`
- `label`
- `summary`
- `calculation_note`
- `factors`

Each factor contains:

- `name`
- `earned_points`
- `max_points`
- `detail`

The total maximum is 100 points, so the final confidence score is directly expressed as a percentage.

### 9.3 Confidence score formula

The current score is composed of six weighted factors:

1. `Conversation interpretation` out of 5
2. `Intent clarity` out of 25
3. `SQL generation` out of 20
4. `SQL execution` out of 25
5. `Result grounding` out of 15
6. `Traceability` out of 10

The full formula is:

```text
Confidence Score (%) =
Conversation interpretation
+ Intent clarity
+ SQL generation
+ SQL execution
+ Result grounding
+ Traceability
```

Because the weights sum to 100, the final numeric score is already a percentage.

### 9.4 Factor-by-factor technical logic

#### A. Conversation interpretation: 0 to 5 points

This measures whether the system successfully normalized the user turn into a standalone analytical question.

Logic:

- `5/5` if the question was classified as either `new_question` or `follow_up`
- `0/5` otherwise

This stage is implemented using:

- `interpret_user_question`
- `FOLLOW_UP_INTERPRETATION_PROMPT`
- session history from `build_recent_history_text`

#### B. Intent clarity: 10 to 25 points

This measures whether ambiguity was resolved before query generation.

Logic:

- `25/25` if the request is fully clarified
- `10/25` if clarification questions are still pending
- `18/25` if the system currently considers the question clear but SQL generation has not yet completed

This factor uses the ambiguity workflow output from:

- `AmbiguityResolver.check_ambiguity`
- `AmbiguityResolver.ambi_detection`
- `AmbiguityResolver.ambi_correction`

#### C. SQL generation: 0 to 20 points

This measures whether a concrete SQL statement was successfully generated.

Logic:

- `20/20` if SQL was produced
- `0/20` otherwise

This stage is implemented by:

- `XiYanAgent.generate_sql`

#### D. SQL execution: 0 to 25 points

This measures whether the generated SQL actually ran against the SQLite database.

Logic:

- `25/25` if execution succeeded
- `0/25` otherwise

This is implemented through:

- `execute_query` in `ambisql/utils/db_utils.py`

This is one of the most important reliability factors because it ensures the answer is based on executable database logic rather than on an unverified generated query.

#### E. Result grounding: 0 to 15 points

This measures whether the final answer was grounded in returned rows.

Logic:

- `15/15` if a grounded answer was produced from a non-empty result set
- `8/15` if the SQL executed successfully but returned zero rows and the answer reflects that empty result honestly
- `0/15` if no grounded answer exists

This stage is implemented by:

- `build_grounded_answer`
- `build_result_preview`

This factor explicitly rewards answer generation from real query results rather than from general model reasoning.

#### F. Traceability: 0 to 10 points

This measures whether the system can explain how the answer was produced.

Logic:

- `10/10` if query metadata includes both detected tables and detected columns
- `6/10` if only partial metadata is available
- `0/10` if no metadata or citations are available

This is implemented through:

- `extract_query_metadata`
- `build_query_metadata_citation`

This factor rewards transparency and auditability.

### 9.5 Confidence labels

The numeric score is converted into a qualitative label:

- `85-100`: High confidence
- `65-84`: Moderate confidence
- `45-64`: Provisional confidence
- `0-44`: Low confidence

This label is what the UI shows alongside the percentage for easier interpretation by non-technical users.

### 9.6 Example interpretation

If the system:

- understands the question correctly
- resolves all ambiguity
- generates SQL
- executes SQL successfully
- produces an answer from returned rows
- identifies the tables and columns used

then the score can reach `100%`.

If ambiguity is still unresolved and no SQL has been generated yet, the score remains low because the pipeline has not yet passed the key reliability checkpoints.

If SQL runs successfully but returns zero rows, the score can still remain moderately high because:

- execution succeeded
- the response is honest
- the answer is still grounded in the real database result

but it receives fewer points for result grounding.

### 9.7 UI interpretation

The confidence score shown in the UI should be explained as:

`This percentage reflects how many reliability checkpoints the system successfully completed, including ambiguity resolution, SQL generation, SQL execution, grounding in returned rows, and citation-based traceability.`

That framing is technically honest and also clear for demo audiences and clients.
