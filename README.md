# AmbiSQL: Interactive Ambiguity Detection and Resolution for Text-to-SQL

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)
[![Python 3.10](https://img.shields.io/badge/python-3.10-blue.svg)](https://www.python.org/downloads/release/python-390/)

## Introduction

AmbiSQL is an interactive Text-to-SQL system designed to reduce SQL errors caused by ambiguous natural-language questions.

Instead of sending a user question directly into a one-shot SQL prompt, AmbiSQL:

1. interprets the conversational turn
2. detects ambiguity using a taxonomy-driven workflow
3. asks clarification questions when needed
4. rewrites the user intent
5. generates SQL from the clarified request
6. executes SQL on a real database
7. produces a grounded answer with citations

The current codebase is built around:

- a FastAPI backend in `ambisql/server_fastapi.py`
- a React frontend in `frontend/`
- a versioned schema-artifact flow for production-style schema reuse

## Key Features

- Automatic ambiguity detection
- Interactive clarification questions
- Structured clarification memory
- SQL generation from clarified intent
- SQL execution against SQLite
- Grounded natural-language answers with citations
- Schema artifact build and startup preload
- Local structured debug logging for request tracing

## Repository Layout

Important directories and files:

- `ambisql/server_fastapi.py`
  Main FastAPI backend
- `ambisql/core/`
  Ambiguity resolution, schema loading, preference memory
- `ambisql/utils/`
  LLM calling, SQL generation helpers, logging, parsing, usage monitoring
- `frontend/`
  React UI
- `scripts/import_pgim_excel.py`
  Builds the local SQLite database and schema metadata from the Excel source
- `scripts/build_schema_artifact.py`
  Builds and optionally activates a versioned schema artifact
- `data/schema_artifacts/`
  Versioned schema bundles and `ACTIVE_VERSION`
- `logs/chatbot_debug/`
  Local structured logs
- `docs/technical_execution_flow.md`
  End-to-end architecture and runtime flow
- `docs/production_issues_register.md`
  Production gaps and recommended final-state solutions
- `docs/log_event_catalog.md`
  How to debug wrong clarification, wrong SQL, wrong grounded answers, and prompt oversizing

## Architecture Overview

### Offline build-time flow

1. Convert the source workbook into a SQLite database and metadata CSVs.
2. Build a versioned schema artifact from the database and metadata.
3. Promote the active schema version through `ACTIVE_VERSION`.

### Startup-time flow

1. The backend loads the active schema artifact at startup.
2. The active schema is kept in memory.
3. Normal requests reuse the loaded artifact instead of rebuilding schema.

### Runtime flow

1. The frontend calls `POST /api/sql/analyze`.
2. The backend interprets the user turn.
3. Ambiguity detection decides whether clarification is needed.
4. The frontend calls `POST /api/sql/resolve` with clarification answers.
5. The backend generates SQL, executes it, and produces a grounded answer.
6. Structured logs are written for the full workflow.

## Prerequisites

Install:

- Python 3.10+
- Node.js and npm

You also need:

- an OpenAI API key for `gpt-4o-mini`

## Environment Setup

Create a virtual environment and install Python dependencies:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Install frontend dependencies:

```powershell
cd frontend
npm install
cd ..
```

Create or update `.env` in the project root:

```env
OPENAI_API_KEY=your_openai_api_key_here
DEFAULT_DB_NAME=pgim_property_finance
PORT=8765
```

## Run from Scratch

### 1. Build the local SQLite database and metadata

If you want to regenerate the local development database from the Excel source:

```powershell
python scripts\import_pgim_excel.py
```

This creates:

- `MINIDEV/dev_databases/pgim_property_finance/pgim_property_finance.sqlite`
- `MINIDEV/dev_databases/pgim_property_finance/database_description/*.csv`

### 2. Build and activate the schema artifact

Build the schema artifact and promote it as active:

```powershell
python scripts\build_schema_artifact.py --db-name pgim_property_finance --activate
```

This creates:

- `data/schema_artifacts/pgim_property_finance/versions/<schema_version>/schema_bundle.json`
- `data/schema_artifacts/pgim_property_finance/ACTIVE_VERSION`

### 3. Start the backend

```powershell
python ambisql\server_fastapi.py
```

By default the backend runs on:

- `http://localhost:8765`

At startup, it:

1. reads `DEFAULT_DB_NAME`
2. loads the active schema artifact
3. preloads it into memory
4. fails startup if the active artifact is missing or invalid

Health endpoint:

- `GET http://localhost:8765/health`

### 4. Start the frontend

In a second terminal:

```powershell
cd frontend
npm run dev
```

The frontend talks to:

- `http://localhost:8765/api/sql`

## Development Workflow

Typical local workflow:

1. Update database source or metadata if needed
2. Rebuild the SQLite database if needed
3. Rebuild and activate the schema artifact
4. Start the backend
5. Start the frontend
6. Use the logs and docs to debug behavior

Typical commands:

```powershell
python scripts\import_pgim_excel.py
python scripts\build_schema_artifact.py --db-name pgim_property_finance --activate
python ambisql\server_fastapi.py
```

```powershell
cd frontend
npm run dev
```

## Logs and Debugging

The backend writes structured local logs automatically.

### Session logs

- `logs/chatbot_debug/sessions/<YYYY-MM-DD>/session_<timestamp>_<session_id>.jsonl`

### System logs

- `logs/chatbot_debug/system/server_fastapi.jsonl`

These logs include:

- `session_id`
- `request_id`
- schema version
- ambiguity results
- prompt metrics
- SQL generation events
- SQL execution preview
- grounded-answer events
- fallback behavior
- stage latencies
- token usage and estimated cost summaries

Use these docs when debugging:

- [Technical Execution Flow](docs/technical_execution_flow.md)
- [Production Issues Register](docs/production_issues_register.md)
- [Log Event Catalog](docs/log_event_catalog.md)

## Common Debug Scenarios

### Wrong clarification

Start with:

- `question_interpreted`
- `ambiguity_detection_parsed`
- `ambiguity_filter_applied`
- `clarification_question_generation_response`

### Wrong SQL

Start with:

- `clarification_memory_updated`
- `sql_generation_request`
- `sql_generation_response`
- `sql_execution_completed`

### Wrong grounded answer

Start with:

- `sql_execution_completed`
- `grounded_answer_generation_request`
- `grounded_answer_generation_response`
- `grounded_answer_fallback_used`

### Prompt oversizing

Start with:

- `ambiguity_detection_request`
- `sql_generation_request`
- `grounded_answer_generation_request`

and inspect:

- `prompt_metrics.total_characters`
- request summary latencies
- token usage

The detailed event catalog is documented in [docs/log_event_catalog.md](docs/log_event_catalog.md).

## Notes for New Developers

- The current runtime uses a schema artifact, not request-time schema generation.
- `SchemaGenerator` now acts as a schema bundle loader for runtime usage.
- The schema source of truth for requests is the active artifact under `data/schema_artifacts/`.
- Session state is still in memory only.
- The grounded-answer stage currently caps row context through `build_result_rows`.
- The current observability layer is strong for local debugging, but not yet a centralized enterprise monitoring stack.

## Recommended Reading Order

For onboarding, read in this order:

1. [README.md](README.md)
2. [docs/technical_execution_flow.md](docs/technical_execution_flow.md)
3. [docs/log_event_catalog.md](docs/log_event_catalog.md)
4. [docs/production_issues_register.md](docs/production_issues_register.md)

## License

This project is licensed under the [Apache License 2.0](LICENSE).
