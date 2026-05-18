import os
import sys
import uuid
import json
import re
import warnings
import pandas as pd
from pathlib import Path
from datetime import datetime
from dotenv import load_dotenv
from flask_cors import CORS
from flask import Flask, request, jsonify

# warnings.simplefilter(action='ignore', category=pd.errors.SettingWithCopyWarning)

CURR_DIR = Path(__file__).resolve().parent
PARENT_DIR = CURR_DIR.parent
sys.path.insert(0, str(PARENT_DIR))

from ambisql.core.ambiguity_resolver import AmbiguityResolver
from ambisql.utils.parse import (
    format_message,
    parse_schema_text,
    add_semicolon_if_missing,
    parse_json_response,
    normalize_sql_query,
)
from ambisql.utils.nl2sql_agent import XiYanAgent
from ambisql.utils.llm_caller import LLMCaller
from ambisql.utils.db_utils import execute_query
from ambisql.utils.usage_monitor import empty_usage_report, combine_usage_reports

# Database path configuration
db_path = str((CURR_DIR / "../MINIDEV/dev_databases").resolve())

# Flask application instance
app = Flask(__name__)

# Configure CORS to allow cross-origin requests
CORS(app, resources={r"/api/*": {"origins": "*"}}, supports_credentials=True)

# Default port number, can be configured via PORT environment variable
DEFAULT_PORT = int(os.environ.get("PORT", 8765))

# Load environment variables
load_dotenv()

# In-memory session data storage, key is session_id, value is ChatSession object
sessions = {}


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

Result preview:
{result_preview}
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


def build_result_preview(columns, rows, max_rows=20):
    preview_rows = []
    for index, row in enumerate(rows[:max_rows], start=1):
        preview_rows.append(
            {
                "row_number": index,
                "values": {
                    column: row[position]
                    for position, column in enumerate(columns)
                },
            }
        )
    return preview_rows


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


def build_grounded_answer(question, sql_query, columns, rows, model="gpt4o-mini"):
    if not rows:
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

    llm_caller = LLMCaller(model)
    result_preview = json.dumps(
        build_result_preview(columns, rows),
        ensure_ascii=False,
        indent=2,
        default=str,
    )
    prompt = GROUNDED_ANSWER_PROMPT.format(
        question=question,
        sql_query=sql_query,
        row_count=len(rows),
        result_preview=result_preview,
    )
    query = [
        {
            "role": "system",
            "content": "You answer strictly from SQL query results. Return only JSON.",
        },
        {"role": "user", "content": prompt},
    ]

    try:
        response = llm_caller.call(query)
        parsed = parse_json_response(response)
        answer = parsed.get("answer", "").strip()
        citations = parsed.get("citations", [])
        if not answer:
            raise ValueError("Grounded answer is empty.")
        return {
            "answer": answer,
            "citations": citations,
            "usage_report": llm_caller.get_usage_report("SQL generation"),
        }
    except Exception:
        first_row = rows[0]
        row_summary = ", ".join(
            f"{column}={first_row[position]!r}"
            for position, column in enumerate(columns)
        )
        fallback_answer = (
            f"The query returned {len(rows)} row(s). "
            f"The first row is {row_summary}. [row 1]"
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


def interpret_user_question(current_session, new_question, model, db_name):
    previous_question = (current_session.question or "").strip()
    if not previous_question:
        return {
            "mode": "new_question",
            "standalone_question": new_question.strip(),
            "usage_report": empty_usage_report("Conversation interpretation"),
        }

    if current_session.db_name and current_session.db_name != db_name:
        return {
            "mode": "new_question",
            "standalone_question": new_question.strip(),
            "usage_report": empty_usage_report("Conversation interpretation"),
        }

    llm_caller = LLMCaller(model)
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
        response = llm_caller.call(query)
        parsed = parse_json_response(response)
        mode = parsed.get("mode", "new_question")
        standalone_question = parsed.get("standalone_question", "").strip() or new_question.strip()
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
    """
    Chat session class for managing user session state and message history
    
    Attributes:
        session_id: Unique session identifier
        db_name: Database name
        question: User question
        created_at: Session creation time
        last_accessed: Last access time
        messages: Message history list
        ambiguity_resolver_instance: Ambiguity resolver instance for ambiguity detection and correction
        text2sql_agent: Text-to-SQL agent instance for generating SQL queries, default XiYan-SQL
    """
    def __init__(self, session_id):
        """
        Initialize chat session
        
        Args:
            session_id: Unique session identifier
        """
        self.session_id = session_id
        self.db_name = None
        self.question = None
        self.created_at = datetime.now().isoformat()
        self.last_accessed = datetime.now().isoformat()
        self.messages = []
        self.ambiguity_resolver_instance = None  # AmbiguityResolver Instance, used for ambiguity detection and correction
        self.text2sql_agent = None  # Text2SQL Agent Instance, used for generating SQL queries
        self.ambiguity_usage = empty_usage_report("Ambiguity workflow")
        self.sql_generation_usage = empty_usage_report("SQL generation")

    def add_message(self, role, content):
        """
        Add message to session history
        
        Args:
            role: Message role (e.g., 'user', 'assistant')
            content: Message content
            
        Returns:
            Added message dictionary object
        """
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
        """
        Get session history message list
        
        Returns:
            Message history list
        """
        return self.messages

    def clear(self):
        """
        Clear session history messages
        """
        self.messages = []
        self.last_accessed = datetime.now().isoformat()

    def to_dict(self):
        """
        Convert session object to dictionary format
        
        Returns:
            Dictionary containing session information
        """
        return {
            "session_id": self.session_id,
            "created_at": self.created_at,
            "last_accessed": self.last_accessed,
            "message_count": len(self.messages),
        }


# Ambiguity Identification
@app.route("/api/sql/analyze", methods=["POST"])
def analyze_sql_query():
    """
    API endpoint for analyzing SQL queries to identify ambiguities
    
    Receives POST request containing:
        - session_id: Client session ID (optional)
        - question: User question
        - dialect: SQL dialect (default: SQLite)
        - db: Database name
        
    Returns:
        - session_id: Session ID
        - suggested_schema: Parsed database schema
        - analysis: Analysis result description
        - dialect_info: SQL dialect information
        - ambiguities: Set of identified ambiguity questions
    """
    try:
        print("\n[SQL Query Analysis] Processing request...")
        
        data = request.json
        client_session_id = data.get("session_id") 

        session_id = None
        current_session = None

        if client_session_id and client_session_id in sessions:
            session_id = client_session_id
            current_session = sessions[session_id]
            current_session.last_accessed = datetime.now().isoformat() 
            print(f"  Using existing session: {session_id}")
        else:
            session_id = str(uuid.uuid4())
            current_session = ChatSession(session_id)
            sessions[session_id] = current_session
            print(f"  Created new session: {session_id}")

        raw_question = data.get("question", "")
        dialect = data.get("dialect", "SQLite")
        db_name = data.get("db", "")
        model = "gpt4o-mini"

        interpretation = interpret_user_question(
            current_session=current_session,
            new_question=raw_question,
            model=model,
            db_name=db_name,
        )
        question = interpretation["standalone_question"]
        question_mode = interpretation["mode"]
        current_session.db_name = db_name
        current_session.question = question
        current_session.add_message("user", raw_question)
        
        print(f"  Raw question: {raw_question}")
        print(f"  Interpreted question: {question}")
        print(f"  Question mode: {question_mode}")
        print(f"  Database: {db_name} | Dialect: {dialect} | Model: {model}")

        # Get or create session
        if session_id not in sessions:
            sessions[session_id] = ChatSession(session_id)
        current_session = sessions[session_id]
        
        # Create Ambiguity Resolver instance and store it to session
        qr_instance = AmbiguityResolver(db_name, db_path, question, model)
        print(f"  Created Ambiguity Resolver instance")
        current_session.question_rewriter_instance = qr_instance

        # parse schema
        schema_text = qr_instance.schema_generator.formatted_full_schema
        parsed_schema = parse_schema_text(schema_text)
        print(f"  Schema parsed: {len(parsed_schema)} tables")

        print("  Starting ambiguity detection...")
        response_json = qr_instance.ambi_detection()
        response = json.loads(response_json)
        print(f"  Detection result: {response}")
        question_set = response.get("question_set") or []
        print(f"  Identified {len(question_set)} ambiguity question(s)")

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

        response_data = {
            "session_id": session_id,
            "suggested_schema": parsed_schema,
            "analysis": "Schema analysis completed",
            "dialect_info": dialect,
            "ambiguities": question_set,
            "question_mode": question_mode,
            "interpreted_question": question,
            "monitoring": build_session_monitoring(current_session),
        }
        return jsonify(response_data), 200

    except Exception as e:
        print("\n[Error] Exception occurred during SQL query analysis")
        print(f"  Error message: {str(e)}")
        return (
            jsonify({"error": str(e), "message": "Error processing schema analysis"}),
            500,
        )

@app.route("/api/sql/resolve", methods=["POST"])
def resolve_ambiguities():
    """
    API endpoint for resolving ambiguities, processing user-provided clarification information and generating SQL queries
    
    Receives POST request containing:
        - session_id: Session ID (required)
        - clarificationList: List of clarification question-answer pairs
        - additional_info: Additional information
        
    Returns:
        If ambiguities still exist:
            - is_clarified: "False"
            - session_id: Session ID
            - ambiguities: Remaining ambiguity question set
        If clarified:
            - is_clarified: "True"
            - session_id: Session ID
            - sql_statement_clarified: Clarified SQL statement
    """
    print("\n[Ambiguity Resolution] Starting ambiguity resolution request processing")
    
    try:
        # session management
        data = request.json
        print(f"  [Request Data] Received JSON data: {json.dumps(data, indent=2, ensure_ascii=False)}")
        
        session_id = data.get('session_id')
        print(f"  [Session Management] Session ID: {session_id}") 

        if not session_id:
            print("  [Session Management] No session_id provided, returning 400 error")
            return jsonify({"error": "session_id is required"}), 400

        current_session = sessions.get(session_id)
        print(f"  [Session Management] Current session object: {current_session}") 
        if not current_session:
            print("  [Session Management] Session not found or expired, returning 404 error")
            return jsonify({"error": "Session not found or expired"}), 404

        # residual ambiguity identification and question rewrite
        qr_instance = current_session.question_rewriter_instance
        print(f"  [Ambiguity Resolver] QuestionRewriter instance from session: {qr_instance}") 
        if not qr_instance:
            print("  [Ambiguity Resolver] QuestionRewriter instance not found in session, returning 400 error")
            return jsonify({"error": "QuestionRewriter instance not found in session. Please call /analyze first."}), 400

        clarification_list = data.get('clarificationList', [])
        print(f"  [Clarification Information] Clarification list contains {len(clarification_list)} items: {clarification_list}") 
        
        qa_set = []
        for idx, item in enumerate(clarification_list, 1):
            q_data = item.get('question', {})
            ans = item.get('answer', '')
            qa_set.append({
                "level_1_label": item.get('level_1_label', None),
                "level_2_label": item.get('level_2_label', None),
                "question": item.get('question', None),
                "answer": ans
            })
        print(f"  [Clarification Information] Prepared QA set: {qa_set}") 
            
        additional_info = data.get('additional_info', '')
        print(f"  [Additional Information] Additional info: {additional_info}")

        formatted_message = format_message(qa_set, additional_info)
        print(f"  [Message Formatting] Formatted message: {formatted_message}")
        if qa_set or additional_info.strip():
            current_session.add_message(
                "user",
                formatted_message,
            )

        print("  [Ambiguity Correction] Calling qr_instance.ambi_correction for clarification processing...")
        response_json = qr_instance.ambi_correction(message = formatted_message)
        print(f"  [Ambiguity Correction] ambi_correction returned: {response_json}")
         
        parsed_response = json.loads(response_json) 
        print(f"  [Response Parsing] Parsed response: {json.dumps(parsed_response, indent=2, ensure_ascii=False)}") 
        current_session.ambiguity_usage = qr_instance.llm_caller.get_usage_report(
            label="Ambiguity workflow"
        )
        
        response_data = None
        
        if "has_ambiguity" in parsed_response or parsed_response['is_clarified'] == False:
            print("  [Result] Ambiguities still exist, returning ambiguity question set")
            response_data = {
                "is_clarified": "False",
                "session_id": session_id,
                "ambiguities": parsed_response['question_set'],
            }
            current_session.add_message(
                "assistant",
                f"I still need {len(parsed_response['question_set'] or [])} clarification question(s).",
            )
        else:
            print("  [Result] Ambiguities clarified, starting SQL query generation")
            
            sql_agent = XiYanAgent()
            sql_clarified = sql_agent.generate_sql(
                parsed_response['question'],
                parsed_response['evidence'],
                qr_instance.schema_generator.formatted_full_schema
            )
            sql_clarified = add_semicolon_if_missing(normalize_sql_query(sql_clarified))
            print(f"  [SQL Generation] Clarified SQL statement: {sql_clarified}")
            query_execution = execute_query(
                db_path,
                current_session.db_name,
                sql_clarified,
                include_columns=True,
            )
            print(f"  [SQL Execution] Returned {len(query_execution['rows'])} row(s)")

            grounded_answer = build_grounded_answer(
                parsed_response['question'],
                sql_clarified,
                query_execution["columns"],
                query_execution["rows"],
                model="gpt4o-mini",
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
            current_session.add_message(
                "assistant",
                grounded_answer["answer"],
            )

        response_data["monitoring"] = build_session_monitoring(current_session)
        
        print("  [Result] Processing completed, returning response data")
        return jsonify(response_data), 200 
    
    except Exception as e:
        print("\n[Error] Exception occurred during ambiguity resolution")
        print(f"  Error message: {str(e)}")
        import traceback
        traceback.print_exc() # print complete traceback
        return jsonify({
            "error": str(e),
            "message": "Error processing ambiguity resolution"
        }), 500


if __name__ == "__main__":
    """
    Main program entry point, starts Flask application server
    
    Server configuration:
        - host: 0.0.0.0 (listen on all network interfaces)
        - port: DEFAULT_PORT (default 8765, can be configured via PORT environment variable)
        - debug: True (enable debug mode)
    """
    print("\n[Server Startup] Starting Flask application server")
    print(f"  Listening address: 0.0.0.0:{DEFAULT_PORT}")
    print(f"  Debug mode: True")
    print()
    app.run(host="0.0.0.0", port=DEFAULT_PORT, debug=True)
