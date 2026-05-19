import os
import sys
import uuid
import json
import re
import warnings
import traceback
import pandas as pd
from pathlib import Path
from datetime import datetime
from time import perf_counter
from typing import Any, Dict, List, Optional

import uvicorn
from dotenv import load_dotenv
from fastapi import Body, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

# warnings.simplefilter(action='ignore', category=pd.errors.SettingWithCopyWarning)

CURR_DIR = Path(__file__).resolve().parent
PARENT_DIR = CURR_DIR.parent
sys.path.insert(0, str(PARENT_DIR))

from ambisql.core.ambiguity_resolver import AmbiguityResolver
from ambisql.core.schema_generator import SchemaGenerator
from ambisql.utils.parse import (
    format_message,
    parse_schema_text,
    add_semicolon_if_missing,
    parse_json_response,
    normalize_sql_query,
)
from ambisql.utils.nl2sql_agent import XiYanAgent
from ambisql.utils.llm_caller import LLMCaller
from ambisql.utils.debug_logger import (
    create_session_debug_logger,
    create_system_debug_logger,
)
from ambisql.utils.db_utils import execute_query
from ambisql.utils.usage_monitor import empty_usage_report, combine_usage_reports

load_dotenv()

db_path = str((CURR_DIR / "../MINIDEV/dev_databases").resolve())
DEFAULT_PORT = int(os.environ.get("PORT", 8765))
DEFAULT_DB_NAME = os.environ.get("DEFAULT_DB_NAME", "pgim_property_finance")
SCHEMA_ARTIFACTS_DIR = str(
    (CURR_DIR.parent / "data" / "schema_artifacts").resolve()
)
SYSTEM_LOGGER = create_system_debug_logger("server_fastapi")

app = FastAPI(title="AmbiSQL API", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

sessions: Dict[str, "ChatSession"] = {}


@app.on_event("startup")
async def preload_active_schema_bundle():
    print(
        f"[Startup] Preloading active schema artifact for database: {DEFAULT_DB_NAME}"
    )
    SYSTEM_LOGGER.log_event(
        component="startup",
        event="schema_preload_started",
        payload={
            "db_name": DEFAULT_DB_NAME,
            "schema_artifacts_dir": SCHEMA_ARTIFACTS_DIR,
        },
    )
    try:
        schema_info = SchemaGenerator.preload_active_schema(
            db_name=DEFAULT_DB_NAME,
            artifacts_root=SCHEMA_ARTIFACTS_DIR,
        )
        print(
            "[Startup] Active schema loaded: "
            f"version={schema_info['schema_version']} "
            f"tables={schema_info['table_count']}"
        )
        SYSTEM_LOGGER.log_event(
            component="startup",
            event="schema_preload_completed",
            payload=schema_info,
        )
    except Exception as exc:
        print("[Startup] Failed to preload active schema artifact")
        SYSTEM_LOGGER.log_exception(
            component="startup",
            event="schema_preload_failed",
            exception=exc,
            payload={
                "db_name": DEFAULT_DB_NAME,
                "schema_artifacts_dir": SCHEMA_ARTIFACTS_DIR,
            },
        )
        raise RuntimeError(
            f"Unable to preload active schema artifact for {DEFAULT_DB_NAME}: {exc}"
        ) from exc


FOLLOW_UP_INTERPRETATION_PROMPT = """
You are helping a text-to-SQL chat assistant decide whether a new user turn is:
1. a new standalone database question, or
2. a follow-up to the last active database question.

Return ONLY valid JSON:
{{
  "mode": "new_question" | "follow_up",
  "standalone_question": "string"
}}

Rules:
- Use "follow_up" when the new message depends on the prior question, result intent, or prior constraints.
- Use "follow_up" for messages like: "only in Newark", "what about above 90%", "now show top 10", "exclude sold properties", "also include property name".
- Use "new_question" when the user is clearly starting a different request that does not depend on the previous one.
- For "follow_up", rewrite the message into a single standalone question that preserves the previous intent and applies the new modification.
- For "new_question", the standalone_question should just be the user's new question, cleaned up if needed.

Previous active question:
{previous_question}

Recent conversation:
{recent_history}

New user message:
{new_message}
"""


GROUNDED_ANSWER_PROMPT = """
You are answering a database question using only the executed SQL result.

Return ONLY valid JSON:
{{
  "answer": "string",
  "citations": [
    {{
      "marker": "[rows 1-3]",
      "evidence": "Short explanation of what those rows show"
    }}
  ]
}}

Rules:
- Use only the supplied SQL result. Do not guess or add outside knowledge.
- Use the full SQL result rows provided below as the source of truth for the answer.
- Keep the answer concise and directly answer the user's question.
- Include inline citation markers in the answer, such as [rows 1-3] or [rows 1, 4].
- If the result is empty, clearly say that no matching rows were returned and cite [query result].
- Citations must match the provided row numbers.

User question:
{question}

Executed SQL:
{sql_query}

Result row count:
{row_count}

Full SQL result rows:
{result_rows}
"""


def build_session_monitoring(session):
    ambiguity_usage = getattr(
        session, "ambiguity_usage", empty_usage_report("Ambiguity workflow")
    )
    sql_generation_usage = getattr(
        session, "sql_generation_usage", empty_usage_report("SQL generation")
    )

    return {
        "ambiguity_workflow": ambiguity_usage,
        "sql_generation": sql_generation_usage,
        "session_total": combine_usage_reports(
            [ambiguity_usage, sql_generation_usage],
            label="Session total",
        ),
    }


def build_confidence_report(
    question_mode="new_question",
    ambiguities_pending=0,
    is_clarified=False,
    sql_generated=False,
    execution_success=False,
    row_count=None,
    query_metadata=None,
    grounded_answer_generated=False,
):
    factors = []

    interpretation_points = 5 if question_mode in {"new_question", "follow_up"} else 0
    factors.append(
        {
            "name": "Conversation interpretation",
            "earned_points": interpretation_points,
            "max_points": 5,
            "detail": "The system normalized the user turn into a standalone analytical question.",
        }
    )

    if ambiguities_pending > 0:
        intent_points = 10
        intent_detail = (
            f"{ambiguities_pending} clarification question(s) are still pending, "
            "so intent is only partially resolved."
        )
    elif is_clarified:
        intent_points = 25
        intent_detail = "Ambiguity resolution completed and the intent is fully clarified."
    else:
        intent_points = 18
        intent_detail = "The question appears clear so far, but SQL generation has not completed yet."
    factors.append(
        {
            "name": "Intent clarity",
            "earned_points": intent_points,
            "max_points": 25,
            "detail": intent_detail,
        }
    )

    sql_points = 20 if sql_generated else 0
    factors.append(
        {
            "name": "SQL generation",
            "earned_points": sql_points,
            "max_points": 20,
            "detail": (
                "A concrete SQL statement was generated from the clarified business intent."
                if sql_generated
                else "SQL has not been generated yet."
            ),
        }
    )

    execution_points = 25 if execution_success else 0
    factors.append(
        {
            "name": "SQL execution",
            "earned_points": execution_points,
            "max_points": 25,
            "detail": (
                "The generated SQL executed successfully on the SQLite database."
                if execution_success
                else "The SQL has not been executed yet."
            ),
        }
    )

    if grounded_answer_generated and row_count is not None:
        grounding_points = 15 if row_count > 0 else 8
        grounding_detail = (
            f"The grounded answer was generated from {row_count} returned row(s)."
            if row_count > 0
            else "The answer is grounded in a successful empty result set."
        )
    else:
        grounding_points = 0
        grounding_detail = "No grounded answer has been produced yet."
    factors.append(
        {
            "name": "Result grounding",
            "earned_points": grounding_points,
            "max_points": 15,
            "detail": grounding_detail,
        }
    )

    tables_used = (query_metadata or {}).get("tables_used", [])
    columns_used = (query_metadata or {}).get("columns_used", [])
    if query_metadata and tables_used and columns_used:
        traceability_points = 10
        traceability_detail = (
            f"Traceability is available through {len(tables_used)} table(s), "
            f"{len(columns_used)} column(s), and explicit citations."
        )
    elif query_metadata and (tables_used or columns_used):
        traceability_points = 6
        traceability_detail = (
            "Partial query metadata was extracted, but traceability is not complete."
        )
    else:
        traceability_points = 0
        traceability_detail = "No query metadata or citations are available yet."
    factors.append(
        {
            "name": "Traceability",
            "earned_points": traceability_points,
            "max_points": 10,
            "detail": traceability_detail,
        }
    )

    score_percentage = sum(item["earned_points"] for item in factors)
    if score_percentage >= 85:
        label = "High confidence"
    elif score_percentage >= 65:
        label = "Moderate confidence"
    elif score_percentage >= 45:
        label = "Provisional confidence"
    else:
        label = "Low confidence"

    return {
        "score_percentage": score_percentage,
        "label": label,
        "summary": (
            "This score is a weighted execution-confidence heuristic based on "
            "intent clarity, SQL generation, SQL execution, result grounding, and traceability."
        ),
        "calculation_note": (
            "It is not a model probability. It is a deterministic percentage "
            "computed from pipeline checkpoints whose maximum total is 100."
        ),
        "factors": factors,
    }


def build_result_rows(columns, rows, max_rows=20): #currently we only return top 20 rows to avoid overwhelming the LLM, but this can be adjusted as needed
    result_rows = []
    # for index, row in enumerate(rows, start=1):
    for index, row in enumerate(rows[:max_rows], start=1):
        result_rows.append(
            {
                "row_number": index,
                "values": {
                    column: row[position]
                    for position, column in enumerate(columns)
                },
            }
        )
    return result_rows


def build_result_citations(columns, rows, max_rows=20):
    citations = []
    for index, row in enumerate(rows[:max_rows], start=1):
        values = ", ".join(
            f"{column}={row[position]!r}"
            for position, column in enumerate(columns)
        )
        citations.append(
            {
                "marker": f"[row {index}]",
                "evidence": values,
            }
        )
    return citations


def extract_query_metadata(sql_query, schema_json, result_columns, row_count):
    lower_sql = (sql_query or "").lower()
    tables_used = []
    columns_used = set()

    for table_name, column_map in (schema_json or {}).items():
        table_pattern = rf"(?<!\w){re.escape(table_name.lower())}(?!\w)"
        if re.search(table_pattern, lower_sql):
            tables_used.append(table_name)

        for column_name in column_map.keys():
            column_pattern = rf"(?<!\w){re.escape(column_name.lower())}(?!\w)"
            qualified_pattern = (
                rf"(?<!\w){re.escape(table_name.lower())}\s*\.\s*"
                rf"{re.escape(column_name.lower())}(?!\w)"
            )
            if re.search(column_pattern, lower_sql) or re.search(
                qualified_pattern, lower_sql
            ):
                columns_used.add(column_name)

    if not columns_used and result_columns:
        columns_used.update(result_columns)

    return {
        "tables_used": sorted(set(tables_used)),
        "columns_used": sorted(columns_used),
        "row_count": row_count,
    }


def build_query_metadata_citation(query_metadata):
    tables_text = ", ".join(query_metadata["tables_used"]) or "None detected"
    columns_text = ", ".join(query_metadata["columns_used"]) or "None detected"
    return {
        "marker": "[query metadata]",
        "evidence": (
            f"Tables used: {tables_text}; "
            f"Columns used: {columns_text}; "
            f"Rows returned: {query_metadata['row_count']}"
        ),
        "tables_used": query_metadata["tables_used"],
        "columns_used": query_metadata["columns_used"],
        "row_count": query_metadata["row_count"],
    }


def build_grounded_answer(
    question,
    sql_query,
    columns,
    rows,
    model="gpt4o-mini",
    debug_logger=None,
):
    if not rows:
        if debug_logger:
            debug_logger.log_event(
                component="grounded_answer",
                event="grounded_answer_empty_result",
                payload={
                    "question": question,
                    "sql_query": sql_query,
                    "row_count": 0,
                },
            )
        return {
            "answer": "No matching rows were returned by the executed query. [query result]",
            "citations": [
                {
                    "marker": "[query result]",
                    "evidence": "The executed query returned 0 rows.",
                }
            ],
            "usage_report": empty_usage_report("SQL generation"),
        }

    llm_caller = LLMCaller(
        model,
        debug_logger=debug_logger,
        component="grounded_answer",
    )
    result_rows = json.dumps(
        build_result_rows(columns, rows),
        ensure_ascii=False,
        indent=2,
        default=str,
    )
    prompt = GROUNDED_ANSWER_PROMPT.format(
        question=question,
        sql_query=sql_query,
        row_count=len(rows),
        result_rows=result_rows,
    )
    query = [
        {
            "role": "system",
            "content": "You answer strictly from SQL query results. Return only JSON.",
        },
        {"role": "user", "content": prompt},
    ]

    try:
        response = llm_caller.call(
            query,
            operation="grounded_answer_generation",
            metadata={
                "question": question,
                "row_count": len(rows),
                "columns": columns,
            },
        )
        parsed = parse_json_response(response)
        answer = parsed.get("answer", "").strip()
        citations = parsed.get("citations", [])
        if not answer:
            raise ValueError("Grounded answer is empty.")
        if debug_logger:
            debug_logger.log_event(
                component="grounded_answer",
                event="grounded_answer_completed",
                payload={
                    "answer": answer,
                    "citations": citations,
                },
            )
        return {
            "answer": answer,
            "citations": citations,
            "usage_report": llm_caller.get_usage_report("SQL generation"),
        }
    except Exception as exc:
        first_row = rows[0]
        row_summary = ", ".join(
            f"{column}={first_row[position]!r}"
            for position, column in enumerate(columns)
        )
        fallback_answer = (
            f"The query returned {len(rows)} row(s). "
            f"The first row is {row_summary}. [row 1]"
        )
        if debug_logger:
            debug_logger.log_exception(
                component="grounded_answer",
                event="grounded_answer_fallback_used",
                exception=exc,
                payload={
                    "fallback_answer": fallback_answer,
                    "row_count": len(rows),
                },
            )
        return {
            "answer": fallback_answer,
            "citations": build_result_citations(columns, rows),
            "usage_report": llm_caller.get_usage_report("SQL generation"),
        }


def build_recent_history_text(session, limit=6):
    history = session.get_history()[-limit:]
    if not history:
        return "No prior conversation."
    return "\n".join(
        f"{item['role']}: {item['content']}"
        for item in history
    )


def interpret_user_question(current_session, new_question, model, db_name, debug_logger=None):
    previous_question = (current_session.question or "").strip()
    if not previous_question:
        if debug_logger:
            debug_logger.log_event(
                component="conversation_interpretation",
                event="new_question_without_history",
                payload={
                    "new_question": new_question.strip(),
                    "db_name": db_name,
                },
            )
        return {
            "mode": "new_question",
            "standalone_question": new_question.strip(),
            "usage_report": empty_usage_report("Conversation interpretation"),
        }

    if current_session.db_name and current_session.db_name != db_name:
        if debug_logger:
            debug_logger.log_event(
                component="conversation_interpretation",
                event="new_question_due_to_database_change",
                payload={
                    "previous_db_name": current_session.db_name,
                    "new_db_name": db_name,
                    "new_question": new_question.strip(),
                },
            )
        return {
            "mode": "new_question",
            "standalone_question": new_question.strip(),
            "usage_report": empty_usage_report("Conversation interpretation"),
        }

    llm_caller = LLMCaller(
        model,
        debug_logger=debug_logger,
        component="conversation_interpretation",
    )
    prompt = FOLLOW_UP_INTERPRETATION_PROMPT.format(
        previous_question=previous_question,
        recent_history=build_recent_history_text(current_session),
        new_message=new_question.strip(),
    )
    query = [
        {
            "role": "system",
            "content": "You classify follow-up questions for a text-to-SQL assistant. Return only JSON.",
        },
        {"role": "user", "content": prompt},
    ]

    try:
        response = llm_caller.call(
            query,
            operation="interpret_user_question",
            metadata={
                "previous_question": previous_question,
                "db_name": db_name,
            },
        )
        parsed = parse_json_response(response)
        mode = parsed.get("mode", "new_question")
        standalone_question = (
            parsed.get("standalone_question", "").strip() or new_question.strip()
        )
        if mode not in {"new_question", "follow_up"}:
            mode = "new_question"
        return {
            "mode": mode,
            "standalone_question": standalone_question,
            "usage_report": llm_caller.get_usage_report("Conversation interpretation"),
        }
    except Exception:
        return {
            "mode": "new_question",
            "standalone_question": new_question.strip(),
            "usage_report": llm_caller.get_usage_report("Conversation interpretation"),
        }


class ChatSession:
    def __init__(self, session_id):
        self.session_id = session_id
        self.db_name = None
        self.question = None
        self.created_at = datetime.now().isoformat()
        self.last_accessed = datetime.now().isoformat()
        self.messages = []
        self.ambiguity_resolver_instance = None
        self.text2sql_agent = None
        self.ambiguity_usage = empty_usage_report("Ambiguity workflow")
        self.sql_generation_usage = empty_usage_report("SQL generation")
        self.question_mode = "new_question"
        self.debug_logger = create_session_debug_logger(session_id)
        self.debug_logger.log_event(
            component="session",
            event="session_created",
            payload={
                "session_id": session_id,
                "created_at": self.created_at,
            },
        )

    def add_message(self, role, content):
        timestamp = datetime.now().isoformat()
        message = {
            "id": str(uuid.uuid4()),
            "role": role,
            "content": content,
            "timestamp": timestamp,
        }
        self.messages.append(message)
        self.last_accessed = timestamp
        return message

    def get_history(self):
        return self.messages

    def clear(self):
        self.messages = []
        self.last_accessed = datetime.now().isoformat()

    def to_dict(self):
        return {
            "session_id": self.session_id,
            "created_at": self.created_at,
            "last_accessed": self.last_accessed,
            "message_count": len(self.messages),
        }


def get_or_create_session(client_session_id: Optional[str]):
    if client_session_id and client_session_id in sessions:
        session_id = client_session_id
        current_session = sessions[session_id]
        current_session.last_accessed = datetime.now().isoformat()
        print(f"  Using existing session: {session_id}")
        current_session.debug_logger.log_event(
            component="session",
            event="session_reused",
            payload={
                "session_id": session_id,
                "last_accessed": current_session.last_accessed,
            },
        )
        return session_id, current_session

    session_id = str(uuid.uuid4())
    current_session = ChatSession(session_id)
    sessions[session_id] = current_session
    print(f"  Created new session: {session_id}")
    return session_id, current_session


@app.get("/health")
async def health_check():
    active_schema = SchemaGenerator.get_runtime_cache_metadata(
        artifacts_root=SCHEMA_ARTIFACTS_DIR
    )
    return {
        "status": "ok",
        "active_schema": active_schema,
    }


def build_request_id(prefix):
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


def elapsed_ms(start_time):
    return round((perf_counter() - start_time) * 1000, 3)


def safe_char_len(value):
    if value is None:
        return 0
    return len(str(value))


def build_request_observability_summary(
    request_id,
    endpoint,
    session,
    stage_latencies_ms,
    extra=None,
):
    monitoring = build_session_monitoring(session)
    summary = {
        "request_id": request_id,
        "endpoint": endpoint,
        "session_id": session.session_id,
        "schema_version": (
            SchemaGenerator.get_runtime_cache_metadata(
                artifacts_root=SCHEMA_ARTIFACTS_DIR
            )[0]["schema_version"]
            if SchemaGenerator.get_runtime_cache_metadata(
                artifacts_root=SCHEMA_ARTIFACTS_DIR
            )
            else None
        ),
        "stage_latencies_ms": stage_latencies_ms,
        "usage": monitoring,
    }
    if extra:
        summary.update(extra)
    return summary


@app.post("/api/sql/analyze")
async def analyze_sql_query(payload: Dict[str, Any] = Body(...)):
    try:
        print("\n[SQL Query Analysis] Processing request...")
        request_start = perf_counter()
        stage_latencies_ms = {}
        request_id = build_request_id("analyze")

        client_session_id = payload.get("session_id")
        session_id, current_session = get_or_create_session(client_session_id)
        current_session.debug_logger.set_request_id(request_id)
        current_session.debug_logger.log_event(
            component="analyze_api",
            event="analyze_request_received",
            payload={
                "request_id": request_id,
                "payload": payload,
            },
        )

        raw_question = payload.get("question", "")
        dialect = payload.get("dialect", "SQLite")
        db_name = payload.get("db", "") or DEFAULT_DB_NAME
        model = "gpt4o-mini"

        interpretation_start = perf_counter()
        interpretation = interpret_user_question(
            current_session=current_session,
            new_question=raw_question,
            model=model,
            db_name=db_name,
            debug_logger=current_session.debug_logger,
        )
        stage_latencies_ms["conversation_interpretation"] = elapsed_ms(interpretation_start)
        question = interpretation["standalone_question"]
        question_mode = interpretation["mode"]
        current_session.db_name = db_name
        current_session.question = question
        current_session.question_mode = question_mode
        current_session.add_message("user", raw_question)

        print(f"  Raw question: {raw_question}")
        print(f"  Interpreted question: {question}")
        print(f"  Question mode: {question_mode}")
        print(f"  Database: {db_name} | Dialect: {dialect} | Model: {model}")
        current_session.debug_logger.log_event(
            component="analyze_api",
            event="question_interpreted",
            payload={
                "request_id": request_id,
                "raw_question": raw_question,
                "interpreted_question": question,
                "question_mode": question_mode,
                "db_name": db_name,
                "dialect": dialect,
                "model": model,
                "raw_question_characters": safe_char_len(raw_question),
                "interpreted_question_characters": safe_char_len(question),
            },
        )

        resolver_start = perf_counter()
        qr_instance = AmbiguityResolver(
            db_name,
            db_path,
            question,
            model,
            debug_logger=current_session.debug_logger,
        )
        stage_latencies_ms["resolver_initialization"] = elapsed_ms(resolver_start)
        print("  Created Ambiguity Resolver instance")
        current_session.question_rewriter_instance = qr_instance

        schema_text = qr_instance.schema_generator.formatted_full_schema
        parsed_schema = parse_schema_text(schema_text)
        print(f"  Schema parsed: {len(parsed_schema)} tables")
        current_session.debug_logger.log_event(
            component="analyze_api",
            event="schema_loaded_for_analysis",
            payload={
                "request_id": request_id,
                "schema_version": getattr(qr_instance.schema_generator, "schema_version", None),
                "table_count": len(parsed_schema),
            },
        )

        print("  Starting ambiguity detection...")
        ambiguity_detection_start = perf_counter()
        response_json = qr_instance.ambi_detection()
        stage_latencies_ms["ambiguity_detection"] = elapsed_ms(ambiguity_detection_start)
        response = json.loads(response_json)
        print(f"  Detection result: {response}")
        question_set = response.get("question_set") or []
        print(f"  Identified {len(question_set)} ambiguity question(s)")
        current_session.debug_logger.log_event(
            component="analyze_api",
            event="analyze_response_ready",
            payload={
                "request_id": request_id,
                "ambiguity_count": len(question_set),
                "ambiguities": question_set,
            },
        )

        current_session.ambiguity_usage = combine_usage_reports(
            [
                interpretation["usage_report"],
                qr_instance.llm_caller.get_usage_report(label="Ambiguity workflow"),
            ],
            label="Ambiguity workflow",
        )
        current_session.sql_generation_usage = empty_usage_report("SQL generation")

        if question_set:
            current_session.add_message(
                "assistant",
                f"I found {len(question_set)} clarification question(s) before generating SQL.",
            )
        else:
            current_session.add_message(
                "assistant",
                "Your question is specific enough. I can move directly toward SQL generation.",
            )

        stage_latencies_ms["total_request"] = elapsed_ms(request_start)
        response_payload = {
            "request_id": request_id,
            "session_id": session_id,
            "suggested_schema": parsed_schema,
            "analysis": "Schema analysis completed",
            "dialect_info": dialect,
            "ambiguities": question_set,
            "question_mode": question_mode,
            "interpreted_question": question,
            "confidence": build_confidence_report(
                question_mode=question_mode,
                ambiguities_pending=len(question_set),
                is_clarified=len(question_set) == 0,
                sql_generated=False,
                execution_success=False,
                row_count=None,
                query_metadata=None,
                grounded_answer_generated=False,
            ),
            "monitoring": build_session_monitoring(current_session),
        }
        current_session.debug_logger.log_event(
            component="analyze_api",
            event="analyze_request_summary",
            payload=build_request_observability_summary(
                request_id=request_id,
                endpoint="/api/sql/analyze",
                session=current_session,
                stage_latencies_ms=stage_latencies_ms,
                extra={
                    "ambiguity_count": len(question_set),
                    "question_mode": question_mode,
                    "estimated_cost_usd": build_session_monitoring(current_session)[
                        "session_total"
                    ]["estimated_cost_usd"],
                    "schema_version": getattr(
                        qr_instance.schema_generator,
                        "schema_version",
                        None,
                    ),
                },
            ),
        )
        current_session.debug_logger.clear_request_id()
        return response_payload

    except Exception as e:
        print("\n[Error] Exception occurred during SQL query analysis")
        print(f"  Error message: {str(e)}")
        if "current_session" in locals() and current_session is not None:
            current_session.debug_logger.log_exception(
                component="analyze_api",
                event="analyze_request_failed",
                exception=e,
                payload={
                    "request_id": locals().get("request_id"),
                    "payload": payload,
                    "stage_latencies_ms": locals().get("stage_latencies_ms"),
                },
            )
            current_session.debug_logger.clear_request_id()
        else:
            SYSTEM_LOGGER.log_exception(
                component="analyze_api",
                event="analyze_request_failed_without_session",
                exception=e,
                payload={
                    "request_id": locals().get("request_id"),
                    "payload": payload,
                    "stage_latencies_ms": locals().get("stage_latencies_ms"),
                },
            )
        raise HTTPException(
            status_code=500,
            detail={
                "error": str(e),
                "message": "Error processing schema analysis",
            },
        ) from e


@app.post("/api/sql/resolve")
async def resolve_ambiguities(payload: Dict[str, Any] = Body(...)):
    print("\n[Ambiguity Resolution] Starting ambiguity resolution request processing")

    try:
        request_start = perf_counter()
        stage_latencies_ms = {}
        request_id = build_request_id("resolve")
        print(
            f"  [Request Data] Received JSON data: "
            f"{json.dumps(payload, indent=2, ensure_ascii=False)}"
        )

        session_id = payload.get("session_id")
        print(f"  [Session Management] Session ID: {session_id}")

        if not session_id:
            print("  [Session Management] No session_id provided, returning 400 error")
            raise HTTPException(status_code=400, detail={"error": "session_id is required"})

        current_session = sessions.get(session_id)
        print(f"  [Session Management] Current session object: {current_session}")
        if not current_session:
            print("  [Session Management] Session not found or expired, returning 404 error")
            raise HTTPException(
                status_code=404,
                detail={"error": "Session not found or expired"},
            )
        current_session.debug_logger.set_request_id(request_id)
        current_session.debug_logger.log_event(
            component="resolve_api",
            event="resolve_request_received",
            payload={
                "request_id": request_id,
                "payload": payload,
            },
        )

        qr_instance = current_session.question_rewriter_instance
        print(f"  [Ambiguity Resolver] QuestionRewriter instance from session: {qr_instance}")
        if not qr_instance:
            print("  [Ambiguity Resolver] QuestionRewriter instance not found in session, returning 400 error")
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "QuestionRewriter instance not found in session. Please call /analyze first."
                },
            )

        clarification_list = payload.get("clarificationList", [])
        print(
            f"  [Clarification Information] Clarification list contains "
            f"{len(clarification_list)} items: {clarification_list}"
        )

        qa_set: List[Dict[str, Any]] = []
        for item in clarification_list:
            ans = item.get("answer", "")
            qa_set.append(
                {
                    "level_1_label": item.get("level_1_label", None),
                    "level_2_label": item.get("level_2_label", None),
                    "question": item.get("question", None),
                    "answer": ans,
                }
            )
        print(f"  [Clarification Information] Prepared QA set: {qa_set}")

        additional_info = payload.get("additional_info", "")
        print(f"  [Additional Information] Additional info: {additional_info}")

        formatted_message = format_message(qa_set, additional_info)
        print(f"  [Message Formatting] Formatted message: {formatted_message}")
        if qa_set or additional_info.strip():
            current_session.add_message("user", formatted_message)
        current_session.debug_logger.log_event(
            component="resolve_api",
            event="clarification_payload_prepared",
            payload={
                "request_id": request_id,
                "qa_set": qa_set,
                "additional_info": additional_info,
                "formatted_message": formatted_message,
                "formatted_message_characters": safe_char_len(formatted_message),
            },
        )

        print("  [Ambiguity Correction] Calling qr_instance.ambi_correction for clarification processing...")
        ambiguity_correction_start = perf_counter()
        response_json = qr_instance.ambi_correction(message=formatted_message)
        stage_latencies_ms["ambiguity_correction"] = elapsed_ms(ambiguity_correction_start)
        print(f"  [Ambiguity Correction] ambi_correction returned: {response_json}")

        parsed_response = json.loads(response_json)
        print(
            f"  [Response Parsing] Parsed response: "
            f"{json.dumps(parsed_response, indent=2, ensure_ascii=False)}"
        )
        current_session.debug_logger.log_event(
            component="resolve_api",
            event="ambiguity_correction_parsed",
            payload={
                "request_id": request_id,
                "parsed_response": parsed_response,
            },
        )
        current_session.ambiguity_usage = qr_instance.llm_caller.get_usage_report(
            label="Ambiguity workflow"
        )

        if "has_ambiguity" in parsed_response or parsed_response["is_clarified"] is False:
            print("  [Result] Ambiguities still exist, returning ambiguity question set")
            response_data = {
                "request_id": request_id,
                "is_clarified": "False",
                "session_id": session_id,
                "ambiguities": parsed_response["question_set"],
            }
            current_session.add_message(
                "assistant",
                f"I still need {len(parsed_response['question_set'] or [])} clarification question(s).",
            )
            current_session.debug_logger.log_event(
                component="resolve_api",
                event="clarification_still_required",
                payload={
                    "request_id": request_id,
                    "ambiguity_count": len(parsed_response["question_set"] or []),
                    "ambiguities": parsed_response["question_set"],
                },
            )
        else:
            print("  [Result] Ambiguities clarified, starting SQL query generation")

            sql_agent = XiYanAgent(debug_logger=current_session.debug_logger)
            sql_generation_start = perf_counter()
            sql_clarified = sql_agent.generate_sql(
                parsed_response["question"],
                parsed_response["evidence"],
                qr_instance.schema_generator.formatted_full_schema,
            )
            stage_latencies_ms["sql_generation"] = elapsed_ms(sql_generation_start)
            sql_clarified = add_semicolon_if_missing(normalize_sql_query(sql_clarified))
            print(f"  [SQL Generation] Clarified SQL statement: {sql_clarified}")
            current_session.debug_logger.log_event(
                component="resolve_api",
                event="sql_normalized",
                payload={
                    "request_id": request_id,
                    "sql_statement": sql_clarified,
                    "sql_characters": safe_char_len(sql_clarified),
                },
            )

            sql_execution_start = perf_counter()
            query_execution = execute_query(
                db_path,
                current_session.db_name,
                sql_clarified,
                include_columns=True,
            )
            stage_latencies_ms["sql_execution"] = elapsed_ms(sql_execution_start)
            print(f"  [SQL Execution] Returned {len(query_execution['rows'])} row(s)")
            current_session.debug_logger.log_event(
                component="sql_execution",
                event="sql_execution_completed",
                payload={
                    "request_id": request_id,
                    "db_name": current_session.db_name,
                    "row_count": len(query_execution["rows"]),
                    "columns": query_execution["columns"],
                    "result_preview": build_result_rows(
                        query_execution["columns"],
                        query_execution["rows"],
                    ),
                },
            )

            grounded_answer_start = perf_counter()
            grounded_answer = build_grounded_answer(
                parsed_response["question"],
                sql_clarified,
                query_execution["columns"],
                query_execution["rows"],
                model="gpt4o-mini",
                debug_logger=current_session.debug_logger,
            )
            stage_latencies_ms["grounded_answer_generation"] = elapsed_ms(
                grounded_answer_start
            )
            query_metadata = extract_query_metadata(
                sql_clarified,
                qr_instance.schema_generator.formatted_full_schema_json,
                query_execution["columns"],
                len(query_execution["rows"]),
            )
            response_citations = [
                build_query_metadata_citation(query_metadata),
                *grounded_answer["citations"],
            ]
            current_session.sql_generation_usage = combine_usage_reports(
                [
                    sql_agent.get_usage_report(label="SQL generation"),
                    grounded_answer["usage_report"],
                ],
                label="SQL generation",
            )

            response_data = {
                "request_id": request_id,
                "session_id": session_id,
                "is_clarified": "True",
                "sql_statement_clarified": sql_clarified,
                "grounded_answer": grounded_answer["answer"],
                "citations": response_citations,
                "query_metadata": query_metadata,
                "query_result": {
                    "columns": query_execution["columns"],
                    "rows": query_execution["rows"][:20],
                    "row_count": len(query_execution["rows"]),
                },
            }
            current_session.add_message("assistant", grounded_answer["answer"])
            current_session.debug_logger.log_event(
                component="resolve_api",
                event="final_answer_ready",
                payload={
                    "request_id": request_id,
                    "sql_statement": sql_clarified,
                    "grounded_answer": grounded_answer["answer"],
                    "query_metadata": query_metadata,
                    "row_count": response_data["query_result"]["row_count"],
                },
            )

        if response_data["is_clarified"] == "False":
            response_data["confidence"] = build_confidence_report(
                question_mode=current_session.question_mode,
                ambiguities_pending=len(response_data.get("ambiguities") or []),
                is_clarified=False,
                sql_generated=False,
                execution_success=False,
                row_count=None,
                query_metadata=None,
                grounded_answer_generated=False,
            )
        else:
            response_data["confidence"] = build_confidence_report(
                question_mode=current_session.question_mode,
                ambiguities_pending=0,
                is_clarified=True,
                sql_generated=True,
                execution_success=True,
                row_count=response_data["query_result"]["row_count"],
                query_metadata=response_data["query_metadata"],
                grounded_answer_generated=bool(response_data.get("grounded_answer")),
            )

        response_data["monitoring"] = build_session_monitoring(current_session)
        stage_latencies_ms["total_request"] = elapsed_ms(request_start)
        current_session.debug_logger.log_event(
            component="resolve_api",
            event="resolve_response_sent",
            payload={
                "request_id": request_id,
                "is_clarified": response_data["is_clarified"],
                "confidence": response_data["confidence"],
            },
        )
        current_session.debug_logger.log_event(
            component="resolve_api",
            event="resolve_request_summary",
            payload=build_request_observability_summary(
                request_id=request_id,
                endpoint="/api/sql/resolve",
                session=current_session,
                stage_latencies_ms=stage_latencies_ms,
                extra={
                    "is_clarified": response_data["is_clarified"],
                    "ambiguity_count": len(response_data.get("ambiguities") or []),
                    "row_count": (
                        response_data.get("query_result", {}).get("row_count")
                        if response_data["is_clarified"] == "True"
                        else None
                    ),
                    "sql_characters": safe_char_len(
                        response_data.get("sql_statement_clarified")
                    ),
                    "grounded_answer_characters": safe_char_len(
                        response_data.get("grounded_answer")
                    ),
                    "estimated_cost_usd": response_data["monitoring"]["session_total"][
                        "estimated_cost_usd"
                    ],
                },
            ),
        )
        current_session.debug_logger.clear_request_id()

        print("  [Result] Processing completed, returning response data")
        return response_data

    except HTTPException:
        if "current_session" in locals() and current_session is not None:
            current_session.debug_logger.clear_request_id()
        raise
    except Exception as e:
        print("\n[Error] Exception occurred during ambiguity resolution")
        print(f"  Error message: {str(e)}")
        traceback.print_exc()
        if "current_session" in locals() and current_session is not None:
            current_session.debug_logger.log_exception(
                component="resolve_api",
                event="resolve_request_failed",
                exception=e,
                payload={
                    "request_id": locals().get("request_id"),
                    "payload": payload,
                    "stage_latencies_ms": locals().get("stage_latencies_ms"),
                },
            )
            current_session.debug_logger.clear_request_id()
        else:
            SYSTEM_LOGGER.log_exception(
                component="resolve_api",
                event="resolve_request_failed_without_session",
                exception=e,
                payload={
                    "request_id": locals().get("request_id"),
                    "payload": payload,
                    "stage_latencies_ms": locals().get("stage_latencies_ms"),
                },
            )
        raise HTTPException(
            status_code=500,
            detail={
                "error": str(e),
                "message": "Error processing ambiguity resolution",
            },
        ) from e


if __name__ == "__main__":
    print("\n[Server Startup] Starting FastAPI application server")
    print(f"  Listening address: 0.0.0.0:{DEFAULT_PORT}")
    print("  Reload mode: True")
    print()
    uvicorn.run(
        "ambisql.server_fastapi:app",
        host="0.0.0.0",
        port=DEFAULT_PORT,
        reload=True,
    )
