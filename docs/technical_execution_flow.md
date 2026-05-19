# AmbiSQL Technical Execution Flow

This document explains the current AmbiSQL architecture and end-to-end runtime flow, using the FastAPI backend in `ambisql/server_fastapi.py` as the primary reference.

The current design has four major stages:

1. Offline database and schema-artifact preparation
2. Startup-time schema preload
3. Runtime ambiguity detection and clarification
4. SQL generation, execution, grounded answering, and traceability
5. Structured debug logging and observability

This document also includes a full "run from scratch" guide at the end.

---

## 1. System Overview

At runtime, the system is driven by two API endpoints exposed by `ambisql/server_fastapi.py`:

- `POST /api/sql/analyze`
- `POST /api/sql/resolve`

The high-level control flow is now:

1. The database and metadata are prepared offline.
2. A versioned schema artifact is built offline and promoted via `ACTIVE_VERSION`.
3. The backend starts and preloads the active schema artifact into memory.
4. The user submits a question through the UI.
5. The backend decides whether the question is a new request or a follow-up.
6. The ambiguity engine checks whether the question is underspecified.
7. If ambiguity exists, the backend returns targeted clarification questions.
8. Once the user clarifies the request, the backend generates SQL from the clarified intent and preloaded schema.
9. The SQL is executed on the SQLite database.
10. The result rows are summarized into a grounded natural-language answer.
11. The backend returns SQL, answer, citations, confidence, and query result preview.
12. Structured debug logs are written locally for startup, request tracing, model calls, SQL execution, and fallback behavior.

The important production-oriented change is that schema construction is no longer intended to happen on every user query. Instead, schema is packaged into a versioned artifact and loaded into memory at service startup.

The current backend also includes structured local observability so that each session and request can be traced across the ambiguity workflow, SQL generation, execution, and grounded-answer stages.

---

## 2. Offline Preparation Layer

### 2.1 Database creation from the source workbook

For the current local project setup, the starting data source is:

- `data/pgim_property_finance_dummy_data.xlsx`

The script:

- `scripts/import_pgim_excel.py`

parses the workbook and creates:

- a SQLite database at `MINIDEV/dev_databases/pgim_property_finance/pgim_property_finance.sqlite`
- schema description CSV files under `MINIDEV/dev_databases/pgim_property_finance/database_description/`

The script performs the following:

1. Reads workbook sheets from the Excel file.
2. Normalizes sheet names into SQLite table names.
3. Normalizes column names.
4. Infers SQL column types.
5. Creates SQLite tables.
6. Inserts workbook rows into SQLite.
7. Generates metadata CSV files with:
   - `original_column_name`
   - `column_description`
   - `value_description`

This gives AmbiSQL both:

- physical schema structure from SQLite
- semantic business metadata from CSV files

### 2.2 Offline schema artifact build

The current project now supports an offline schema packaging step via:

- `scripts/build_schema_artifact.py`

This script uses:

- `ambisql/core/schema_generator.py`

to read:

- the SQLite database
- the `database_description/*.csv` files

and construct a versioned schema bundle containing:

- `db_name`
- `schema_version`
- `built_at_utc`
- `formatted_full_schema`
- `formatted_full_schema_json`
- `table_count`
- `value_sample_limit`
- `source_metadata`

The artifact is written to:

- `data/schema_artifacts/<db_name>/versions/<schema_version>/schema_bundle.json`

Example:

- `data/schema_artifacts/pgim_property_finance/versions/v20260519T020431Z/schema_bundle.json`

### 2.3 Manual promotion through ACTIVE_VERSION

The active schema version is selected using:

- `data/schema_artifacts/<db_name>/ACTIVE_VERSION`

Example:

- `data/schema_artifacts/pgim_property_finance/ACTIVE_VERSION`

This file contains only the active version string, for example:

```text
v20260519T020431Z
```

This is the manual promotion mechanism.

That means the runtime does not guess which schema version to use. It loads the exact version explicitly designated as active.

---

## 3. Startup-Time Schema Preload

### 3.1 Why schema preload exists

The current architecture is designed so that schema generation is not part of normal user request latency.

Instead:

- schema is built offline
- a version is promoted manually
- the backend preloads the active schema into memory at startup

This is a more production-oriented design because it avoids:

- repeated SQLite introspection on every request
- repeated CSV parsing on every request
- repeated sample-value extraction on every request
- non-deterministic schema changes during user traffic

### 3.2 Startup preload flow

When `ambisql/server_fastapi.py` starts, the FastAPI startup hook:

- `preload_active_schema_bundle`

loads the active schema artifact into memory by calling:

- `SchemaGenerator.preload_active_schema(...)`

This does the following:

1. Reads `ACTIVE_VERSION`.
2. Locates the corresponding `schema_bundle.json`.
3. Validates the bundle structure.
4. Stores the loaded schema bundle in a class-level in-memory cache.

If preload fails, startup raises an error instead of serving traffic with a missing or invalid schema artifact.

### 3.3 Runtime schema loading behavior

At request time, `SchemaGenerator` no longer needs to rebuild schema from SQLite and CSV sources.

Instead:

1. `AmbiguityResolver` creates a `SchemaGenerator`.
2. `SchemaGenerator` loads the active schema bundle from the in-memory runtime cache.
3. It exposes:
   - `formatted_full_schema`
   - `formatted_full_schema_json`
   - `schema_version`

This preserves the old consumer interface while changing the source of truth from "live schema build" to "prebuilt schema artifact".

---

## 4. Runtime Observability and Debug Logging

### 4.1 Why structured logging was added

The system now writes structured local logs so that it is possible to understand:

- why a clarification was asked
- how the question was interpreted
- which schema version served the request
- which prompt produced bad SQL or bad summarization
- where latency accumulated
- whether fallback behavior was triggered

This is intended to support both debugging and production hardening.

### 4.2 Log storage model

The current logging layer writes local JSONL files.

Session logs are written to:

- `logs/chatbot_debug/sessions/<YYYY-MM-DD>/session_<timestamp>_<session_id>.jsonl`

System logs are written to:

- `logs/chatbot_debug/system/server_fastapi.jsonl`

Each session gets a dedicated file so one conversation can be inspected independently.

### 4.3 Request tracing model

The backend now assigns:

- `session_id` for the conversation
- `request_id` for each individual API request

This means one session may contain multiple request traces, such as:

- one `/api/sql/analyze`
- one or more `/api/sql/resolve`

Each log record now contains enough context to isolate:

- the session
- the request
- the component
- the event type

### 4.4 Main observability coverage

The current logging captures:

- startup schema preload success or failure
- raw analyze and resolve request payloads
- interpreted question and follow-up mode
- schema version used for the request
- ambiguity detection raw and filtered results
- clarification payloads and evidence updates
- SQL generation prompt and response
- SQL normalization
- SQL execution output preview
- grounded answer prompt and response
- fallback behavior
- request summaries with stage latencies and usage

### 4.5 Stage latency coverage

The current request summaries include per-stage latency tracking for:

- conversation interpretation
- resolver initialization
- ambiguity detection
- ambiguity correction
- SQL generation
- SQL execution
- grounded answer generation
- total request time

### 4.6 Prompt-size coverage

The current LLM call logs include prompt metrics such as:

- `message_count`
- `total_characters`
- `max_message_characters`

This makes it easier to debug prompt oversizing without manually counting prompt payloads.

### 4.7 Debugging guide

The detailed event catalog and debugging workflow are documented in:

- `docs/log_event_catalog.md`

That document explains which event families to inspect first for:

- wrong clarification
- wrong SQL
- wrong grounded answer
- prompt oversizing

---

## 5. Runtime Stage One: Understanding User Intent and Asking Clarification Questions

### 4.1 API entrypoint and session model

The runtime process starts in `ambisql/server_fastapi.py` inside:

- `analyze_sql_query`

The backend maintains in-memory conversation sessions using `ChatSession`.

Each session stores:

- `session_id`
- `db_name`
- current interpreted `question`
- message history
- ambiguity workflow usage
- SQL generation usage

This memory is used for conversational follow-ups.

### 4.2 Detecting whether the user asked a new question or a follow-up

Before ambiguity analysis, the backend runs:

- `interpret_user_question`

Its purpose is to determine whether the current user turn is:

- a new standalone question
- or a follow-up refinement of the prior question

This uses:

- `FOLLOW_UP_INTERPRETATION_PROMPT`
- `LLMCaller`
- recent history from `build_recent_history_text`

Technical behavior:

1. If there is no previous question, the turn is `new_question`.
2. If the selected database changes, the turn is `new_question`.
3. Otherwise, an LLM classifies the turn and may rewrite it into a standalone question.

This rewrite is important because downstream ambiguity detection and SQL generation work better on explicit questions than on short conversational fragments.

### 4.3 Constructing the ambiguity workflow context

Once the question is normalized, the backend creates:

- `AmbiguityResolver`

Inside its constructor, it initializes:

- `SchemaGenerator`
- `PreferenceTree`
- `CQGenerator`
- `LLMCaller`

At this point, `SchemaGenerator` does not rebuild live schema from the database. It loads the active prebuilt schema artifact and exposes the schema structures needed by the rest of the pipeline.

### 4.4 Ambiguity detection logic

The core ambiguity engine is:

- `AmbiguityResolver.check_ambiguity`

It builds an LLM prompt using:

- the current question
- the preloaded `formatted_full_schema_json`
- any existing clarification evidence
- ambiguity taxonomy examples

These prompts come from:

- `ambisql/prompts/ambiguity_detection_prompt.py`

The ambiguity taxonomy distinguishes:

- Database-sourced ambiguity
  - `AmbiSchema`
  - `AmbiValue`
  - `AmbiView`
- LLM-sourced ambiguity
  - `AmbiSource`
  - `AmbiContext`
  - `AmbiFallacy`
  - `AmbiRef`

The prompt instructs the LLM to return strict JSON with:

- `has_ambiguity`
- `question_set`

### 4.5 Guardrails against unnecessary ambiguity questions

Ambiguity detection is LLM-driven, but deterministic post-filters reduce false positives.

These include:

- `find_exact_unique_column_matches`
- `find_strong_natural_language_matches`
- `has_explicit_literal_condition`
- `filter_false_positive_ambiguities`

These routines help suppress unnecessary follow-ups when the user’s intent is already strongly grounded in the schema metadata.

### 4.6 Turning ambiguity items into user-friendly clarification questions

If ambiguity remains, AmbiSQL rewrites the technical ambiguity objects into user-facing multiple-choice questions using:

- `CQGenerator.generate_clarification_question`

This stage:

1. takes each ambiguity item
2. reads its description
3. prompts the LLM to simplify it
4. validates the JSON response
5. attaches a `choices` list

### 4.7 Clarification memory

When the user answers follow-up questions, their selections are stored in:

- `PreferenceTree`

This structure organizes clarification evidence by ambiguity class and merges semantically overlapping answers when necessary.

The evidence summary returned by:

- `PreferenceTree.traverse()`

is later injected into ambiguity redetection and SQL generation.

---

## 6. Runtime Stage Two: Mapping Business Tables to Clarified Intent and Generating SQL

### 5.1 Why the prebuilt schema still provides strong semantic grounding

Even though schema is now loaded from a versioned artifact instead of rebuilt live during requests, the contents of that artifact still carry the same business-rich grounding:

- physical SQLite schema
- column descriptions
- value descriptions
- sampled example values collected during artifact build

That means SQL generation remains grounded in business semantics rather than raw technical names only.

### 5.2 Clarified intent package used for SQL generation

After ambiguity resolution completes, `AmbiguityResolver.format_response` returns:

- `is_clarified = True`
- refined `question`
- `evidence`

This evidence explicitly records:

- selected interpretations
- chosen columns or filters
- added constraints
- follow-up clarifications

### 5.3 SQL generation implementation

SQL generation happens in:

- `ambisql/utils/nl2sql_agent.py`

through:

- `XiYanAgent.generate_sql(question, evidence, schema)`

The prompt includes:

- SQL dialect
- clarified question
- full business-grounded schema text
- clarification evidence

This produces the SQL statement used for execution.

### 5.4 SQL normalization before execution

Before execution, the backend normalizes model output using:

- `normalize_sql_query`
- `add_semicolon_if_missing`

This strips markdown fences and ensures the query ends with a semicolon.

---

## 7. Runtime Stage Three: Executing SQL and Generating the Final Response

### 6.1 SQL execution

The generated SQL is executed using:

- `execute_query` in `ambisql/utils/db_utils.py`

This opens:

- `path/db_name/db_name.sqlite`

and returns:

- column names
- result rows

### 6.2 Grounded answer generation

The final answer is generated using:

- `build_grounded_answer`

If zero rows are returned:

- the backend returns a deterministic no-results answer

Otherwise:

1. it packages result rows using `build_result_rows`
2. it sends the executed SQL, row count, and result rows into `GROUNDED_ANSWER_PROMPT`
3. it asks the LLM to return strict JSON with:
   - `answer`
   - `citations`

Important implementation detail:

- the current helper limits the result rows sent to the answer model to the first 20 rows
- the API response also limits the visible query preview to the first 20 rows

So the answer is grounded in SQL output, but in the current code path the grounded-answer prompt is still capped to a bounded row set for practicality.

### 6.3 Query metadata extraction

The backend extracts lightweight traceability metadata using:

- `extract_query_metadata`

This infers:

- `tables_used`
- `columns_used`
- `row_count`

and turns it into a citation via:

- `build_query_metadata_citation`

### 6.4 Fallback citations

If grounded-answer JSON parsing fails, the backend falls back to deterministic row citations using:

- `build_result_citations`

This ensures traceability is still returned even when summarization is imperfect.

### 6.5 Final response payload

When the query is fully resolved and executed, the backend returns:

- `sql_statement_clarified`
- `grounded_answer`
- `citations`
- `query_metadata`
- `query_result`
- `confidence`
- `monitoring`

The frontend can then display:

- the generated SQL
- the answer
- query result preview
- citations
- confidence score
- usage monitoring

---

## 8. Confidence Score Logic

The confidence score in the UI is implemented by:

- `build_confidence_report` in `ambisql/server_fastapi.py`

It is not a probability and not a benchmark metric. It is a deterministic heuristic based on pipeline checkpoints.

The current weighted factors are:

1. Conversation interpretation: 5
2. Intent clarity: 25
3. SQL generation: 20
4. SQL execution: 25
5. Result grounding: 15
6. Traceability: 10

The total is 100 points, so the score can be displayed directly as a percentage.

Current labels are:

- `85-100`: High confidence
- `65-84`: Moderate confidence
- `45-64`: Provisional confidence
- `0-44`: Low confidence

---

## 9. Why This Design Is More Reliable Than a Direct Chatbot Guess

The current implementation improves reliability through three controlled grounding layers:

### Layer 1: Intent grounding

The system interprets conversational follow-ups, detects ambiguity, and asks clarification questions.

### Layer 2: Schema grounding

The system uses a business-aware schema artifact built from:

- actual SQLite structure
- curated business descriptions
- sampled example values

### Layer 3: Result grounding

The system executes the SQL and generates the answer from the returned rows instead of answering directly from world knowledge.

This means the model is used in constrained roles:

- ambiguity classifier
- clarification question generator
- SQL generator
- grounded summarizer

not as an unconstrained answer engine.

---

## 10. Current Technical Strengths

### 10.1 Separation of build-time and run-time schema logic

Schema preparation is now split into:

- offline schema artifact build
- startup preload
- request-time reuse

This is a cleaner production-oriented pattern than rebuilding schema on every query.

### 10.2 Business-semantic schema grounding

The schema artifact preserves domain semantics through metadata CSVs and sample values.

### 10.3 Structured clarification memory

`PreferenceTree` stores reusable intent evidence rather than raw chat text only.

### 10.4 Traceable final answer

The final answer includes query metadata and citations grounded in the executed SQL result.

### 10.5 Structured debug observability

The backend now emits structured session logs, request summaries, prompt metrics, and fallback traces, which makes production debugging much more practical than console output alone.

---

## 11. Current Limitations

### 11.1 In-memory sessions

Conversation sessions are still stored only in process memory. Restarting the backend clears them.

### 11.2 Manual schema promotion

Schema artifact activation currently depends on a local `ACTIVE_VERSION` file and manual rebuild/promotion workflow.

### 11.3 SQL metadata extraction is heuristic

`extract_query_metadata` is based on SQL string matching, not a full SQL parser.

### 11.4 Grounded answer row cap

The current implementation limits the rows sent to the summarization prompt, which helps control prompt size but can underrepresent very large result sets.

### 11.5 Schema quality depends on metadata quality

The usefulness of the schema artifact still depends heavily on the quality of `database_description/*.csv`.

### 11.6 Local-file observability only

The current observability layer is local and file-based. It does not yet provide:

- centralized log aggregation
- dashboards
- alerting
- distributed tracing
- long-term operational metrics storage

---

## 12. End-to-End Runbook: Run the Project from Scratch

This section describes how to set up and run the full project locally from scratch.

### 12.1 Prerequisites

Install:

- Python 3.10+
- Node.js and npm

You also need an OpenAI API key because the backend uses `gpt-4o-mini`.

### 12.2 Create and activate a Python environment

From the project root:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 12.3 Configure environment variables

Create or update `.env` in the project root with at least:

```env
OPENAI_API_KEY=your_openai_api_key_here
DEFAULT_DB_NAME=pgim_property_finance
PORT=8765
```

### 12.4 Build the local SQLite database and metadata from the Excel file

If you want to rebuild the local database from the workbook, run:

```powershell
python scripts\import_pgim_excel.py
```

This creates:

- `MINIDEV/dev_databases/pgim_property_finance/pgim_property_finance.sqlite`
- `MINIDEV/dev_databases/pgim_property_finance/database_description/*.csv`

If these already exist and are valid, you can skip this step.

### 12.5 Build and activate the schema artifact

Run:

```powershell
python scripts\build_schema_artifact.py --db-name pgim_property_finance --activate
```

This creates:

- `data/schema_artifacts/pgim_property_finance/versions/<version>/schema_bundle.json`
- `data/schema_artifacts/pgim_property_finance/ACTIVE_VERSION`

This step is required whenever you want to promote a newly built schema bundle.

### 12.6 Start the backend

Run:

```powershell
python ambisql\server_fastapi.py
```

At startup, the backend will:

1. read `DEFAULT_DB_NAME`
2. load the active schema artifact for that DB
3. preload it into memory
4. fail startup if the active schema artifact is missing or invalid

By default the backend runs on:

- `http://localhost:8765`

You can confirm it is healthy with:

- `GET /health`

During runtime, the backend will also create local debug logs automatically under:

- `logs/chatbot_debug/`

### 12.7 Start the frontend

In a second terminal:

```powershell
cd frontend
npm install
npm run dev
```

The frontend talks to:

- `http://localhost:8765/api/sql`

The frontend default database selection is currently:

- `pgim_property_finance`

### 12.8 End-to-end runtime flow after startup

Once both frontend and backend are running:

1. Open the frontend in the browser.
2. Enter a natural-language business question.
3. The frontend calls `POST /api/sql/analyze`.
4. The backend:
   - interprets the turn
   - loads the preloaded schema from memory
   - runs ambiguity detection
5. If needed, the frontend renders clarification questions.
6. The frontend submits user clarifications to `POST /api/sql/resolve`.
7. The backend:
   - updates clarification memory
   - generates SQL
   - executes SQL
   - generates grounded answer and citations
8. The UI displays:
   - the answer
   - the SQL
   - query result preview
   - citations
   - confidence score
   - usage monitoring
9. The backend writes structured session and request logs for debugging and observability.

### 12.9 When schema changes

If the SQLite schema or metadata CSV files change:

1. rebuild the database and metadata if needed
2. build a new schema artifact
3. activate the new version
4. restart the backend

Typical commands:

```powershell
python scripts\import_pgim_excel.py
python scripts\build_schema_artifact.py --db-name pgim_property_finance --activate
python ambisql\server_fastapi.py
```

---

## 13. Summary

The current AmbiSQL backend is a multi-stage grounded reasoning workflow:

1. Prepare database and metadata offline.
2. Build a versioned schema artifact offline.
3. Promote one schema version through `ACTIVE_VERSION`.
4. Preload the active schema artifact into memory at startup.
5. Interpret whether the user turn is a new question or follow-up.
6. Detect unresolved ambiguity using taxonomy-guided prompting plus deterministic filters.
7. Ask targeted clarification questions when needed.
8. Store clarification decisions in structured evidence memory.
9. Generate SQL from clarified intent plus preloaded business schema plus evidence.
10. Execute the SQL on the SQLite database.
11. Generate a grounded answer from the SQL result rows.
12. Write structured logs for startup, requests, prompts, SQL execution, and fallback behavior.
13. Return answer, SQL, citations, confidence, and monitoring data.

This design is more production-worthy than request-time schema generation because schema preparation is now explicit, versioned, promotable, and reusable across all user queries.
