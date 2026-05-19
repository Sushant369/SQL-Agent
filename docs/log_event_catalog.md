# AmbiSQL Log Event Catalog

This document explains the local debug logs produced by AmbiSQL and shows which events to inspect first when debugging:

1. wrong clarification
2. wrong SQL
3. wrong grounded answer
4. prompt oversizing

The current logging implementation writes structured JSONL logs locally and is intended to support debugging, workflow tuning, and production hardening.

---

## 1. Log Locations

### Session logs

Each chat session gets its own log file:

- `logs/chatbot_debug/sessions/<YYYY-MM-DD>/session_<timestamp>_<session_id>.jsonl`

These files are the primary source for debugging user-specific chatbot behavior.

### System logs

Application startup and service-level events are written to:

- `logs/chatbot_debug/system/server_fastapi.jsonl`

Use this when checking startup schema preload or server-level failures.

---

## 2. Log Format

Each line is one JSON object.

Typical fields are:

- `timestamp_utc`
- `level`
- `channel`
- `session_id`
- `request_id`
- `component`
- `event`
- `payload`
- `error` for exception events

### Important identifiers

#### `session_id`

Groups all logs for the same chat session.

#### `request_id`

Groups all logs for one API request such as:

- one `/api/sql/analyze` call
- one `/api/sql/resolve` call

This is the fastest way to isolate one problematic request inside a longer session.

---

## 3. Main Components and Event Families

### Session lifecycle

Component:

- `session`

Important events:

- `session_created`
- `session_reused`

Use these to confirm whether a user request started a new session or reused an existing one.

### Startup

Component:

- `startup`

Important events:

- `schema_preload_started`
- `schema_preload_completed`
- `schema_preload_failed`

Use these to confirm the active schema version that was loaded into memory.

### Analyze API

Component:

- `analyze_api`

Important events:

- `analyze_request_received`
- `question_interpreted`
- `schema_loaded_for_analysis`
- `analyze_response_ready`
- `analyze_request_summary`
- `analyze_request_failed`

### Resolve API

Component:

- `resolve_api`

Important events:

- `resolve_request_received`
- `clarification_payload_prepared`
- `ambiguity_correction_parsed`
- `clarification_still_required`
- `sql_normalized`
- `final_answer_ready`
- `resolve_response_sent`
- `resolve_request_summary`
- `resolve_request_failed`

### Ambiguity workflow

Component:

- `ambiguity_workflow`

Important events:

- `resolver_initialized`
- `initial_ambiguity_result`
- `clarification_memory_updated`
- `ambiguity_detection_request`
- `ambiguity_detection_response`
- `ambiguity_detection_parsed`
- `ambiguity_filter_applied`
- `question_refined`
- `clarified_response_ready`

### SQL generation

Component:

- `sql_generation`

Important events:

- `sql_generation_request`
- `sql_generation_response`
- `sql_generation_failure`

### SQL execution

Component:

- `sql_execution`

Important events:

- `sql_execution_completed`

### Grounded answer

Component:

- `grounded_answer`

Important events:

- `grounded_answer_generation_request`
- `grounded_answer_generation_response`
- `grounded_answer_completed`
- `grounded_answer_empty_result`
- `grounded_answer_fallback_used`

### Conversation interpretation

Component:

- `conversation_interpretation`

Important events:

- `new_question_without_history`
- `new_question_due_to_database_change`
- `interpret_user_question_request`
- `interpret_user_question_response`
- `interpret_user_question_failure`

### Clarification question generation

Component:

- `ambiguity_workflow`

Operation-level events embedded through the LLM caller:

- `clarification_question_generation_request`
- `clarification_question_generation_response`
- `clarification_question_generation_failure`

### Preference merging

Component:

- `ambiguity_workflow`

Important operation-level events:

- `preference_node_merge_request`
- `preference_node_merge_response`
- `preference_node_merge_failure`

---

## 4. How to Debug Wrong Clarification

Wrong clarification usually means one of four things happened:

1. the question was misinterpreted as a follow-up
2. ambiguity detection identified the wrong ambiguity
3. false-positive filtering failed to suppress an unnecessary question
4. clarification question rewriting turned a valid ambiguity into a poor user-facing question

### Check these events first

1. `analyze_request_received`
   - confirms the raw input payload

2. `question_interpreted`
   - check:
     - `raw_question`
     - `interpreted_question`
     - `question_mode`

3. `schema_loaded_for_analysis`
   - confirm:
     - `schema_version`
     - table count

4. `ambiguity_detection_request`
   - inspect prompt size and the exact prompt context sent to the model

5. `ambiguity_detection_response`
   - inspect raw model output

6. `ambiguity_detection_parsed`
   - inspect parsed ambiguity objects

7. `ambiguity_filter_applied`
   - compare:
     - `original_question_count`
     - `filtered_question_count`
   - if a bad ambiguity survived filtering, this is often the key event

8. `clarification_question_generation_request`
   - inspect the ambiguity item that was turned into a question

9. `clarification_question_generation_response`
   - inspect the actual choices given to the user

### Common patterns

#### The question was not actually ambiguous

Look for:

- ambiguity item present in `ambiguity_detection_parsed`
- but it should have been removed in `ambiguity_filter_applied`

This usually means:

- schema grounding rules are too weak
- explicit literal detection is insufficient
- natural-language match scoring needs tuning

#### The ambiguity was correct but the displayed clarification was poor

Look for:

- correct ambiguity object in `ambiguity_detection_parsed`
- poor wording or options in `clarification_question_generation_response`

This usually means:

- clarification phrasing prompt needs improvement
- answer option ranking needs improvement

---

## 5. How to Debug Wrong SQL

Wrong SQL usually means:

1. wrong interpreted question
2. wrong clarification evidence
3. wrong schema grounding
4. SQL generation prompt failed despite correct inputs

### Check these events first

1. `question_interpreted`
   - verify the interpreted question is still the intended user request

2. `clarification_memory_updated`
   - inspect:
     - `qa_set`
     - `additional_info`
     - `evidence`

3. `clarified_response_ready`
   - verify the final clarified question and evidence going into SQL generation

4. `sql_generation_request`
   - inspect:
     - question
     - evidence
     - prompt metrics
     - full generated prompt messages

5. `sql_generation_response`
   - inspect:
     - generated SQL text
     - token usage

6. `sql_normalized`
   - verify the normalized SQL actually sent to execution

7. `sql_execution_completed`
   - check:
     - row count
     - result preview

### Common patterns

#### SQL references the wrong table or column

Usually inspect:

- `sql_generation_request`
- `clarification_memory_updated`
- `sql_generation_response`

Likely causes:

- ambiguity detector chose the wrong interpretation
- evidence was insufficient or misleading
- schema prompt is too broad and noisy

#### SQL is syntactically invalid

Check:

- `sql_generation_response`
- `sql_normalized`
- `resolve_request_failed`

Likely causes:

- prompt formatting issue
- model drift
- insufficient schema constraint

#### SQL executes but returns clearly wrong data

Check:

- `sql_execution_completed`
- compare rows with intended question and evidence

Likely causes:

- semantically wrong SQL
- missing filter
- wrong join path

---

## 6. How to Debug Wrong Grounded Answer

Wrong grounded answer usually means:

1. SQL was correct but answer summarization was poor
2. SQL result context sent to the answer model was incomplete
3. fallback logic was triggered

### Check these events first

1. `sql_execution_completed`
   - inspect:
     - returned columns
     - result preview
     - row count

2. `grounded_answer_generation_request`
   - inspect:
     - question
     - row count
     - columns
     - prompt metrics
     - actual result rows passed into the prompt

3. `grounded_answer_generation_response`
   - inspect the raw answer JSON returned by the model

4. `grounded_answer_completed`
   - inspect final answer and citations

5. `grounded_answer_fallback_used`
   - if present, the structured summarizer failed and fallback logic was used

### Common patterns

#### Answer contradicts the SQL result rows

Check:

- `sql_execution_completed`
- `grounded_answer_generation_request`
- `grounded_answer_generation_response`

Likely causes:

- model summarization hallucination
- prompt too large or noisy
- result rows truncated too aggressively for the use case

#### Answer is too shallow or partial

Check:

- whether only limited rows were sent into the answer prompt
- current helper behavior in `build_result_rows`

Likely cause:

- row capping is hiding important result context

#### Fallback answer was used

Check:

- `grounded_answer_fallback_used`
- exception payload
- raw SQL result rows

Likely causes:

- malformed JSON from the model
- empty answer field
- parsing issue

---

## 7. How to Debug Prompt Oversizing

Prompt oversizing usually shows up as:

- high latency
- high token usage
- degraded SQL or ambiguity quality
- unstable model behavior

### Check these events first

1. `ambiguity_detection_request`
2. `sql_generation_request`
3. `grounded_answer_generation_request`

For each of these, inspect `prompt_metrics`:

- `message_count`
- `total_characters`
- `max_message_characters`

### Supporting events

Also inspect:

- `analyze_request_summary`
- `resolve_request_summary`

Look at:

- stage latencies
- token usage
- estimated cost

### Practical interpretation

#### Large ambiguity prompt

Likely when:

- `ambiguity_detection_request.payload.prompt_metrics.total_characters` is high
- `ambiguity_detection` latency is high

Common cause:

- too much schema JSON
- too many prompt examples

#### Large SQL generation prompt

Likely when:

- `sql_generation_request.payload.prompt_metrics.total_characters` is high
- `sql_generation` latency is high

Common cause:

- full schema text is too large
- evidence is too verbose

#### Large grounded answer prompt

Likely when:

- `grounded_answer_generation_request.payload.prompt_metrics.total_characters` is high

Common cause:

- too many rows passed into the answer stage

### Recommended response

If prompt oversizing is suspected:

1. reduce schema payload
2. add query-time schema selection
3. summarize large row sets before answer generation
4. keep monitoring token usage and stage latency together

---

## 8. Summary Events

Two events are especially useful for high-level debugging:

### `analyze_request_summary`

Contains:

- `request_id`
- `endpoint`
- `session_id`
- `schema_version`
- `stage_latencies_ms`
- `usage`
- `estimated_cost_usd`
- ambiguity count
- question mode

### `resolve_request_summary`

Contains:

- `request_id`
- `endpoint`
- `session_id`
- `schema_version`
- `stage_latencies_ms`
- `usage`
- `estimated_cost_usd`
- row count
- SQL size
- grounded answer size
- clarification status

These summary events are the fastest way to compare good and bad runs.

---

## 9. Suggested Debugging Workflow

When a chatbot result looks wrong, use this order:

1. Find the session log file.
2. Find the relevant `request_id`.
3. Read the request summary event.
4. Decide whether the failure is:
   - clarification failure
   - SQL generation failure
   - execution/result mismatch
   - grounded answer failure
   - prompt size problem
5. Inspect the event family for that failure mode.

This makes debugging much faster than reading the whole session line by line.

---

## 10. What This Logging Still Does Not Replace

This event catalog supports strong local and single-service debugging, but it does not replace:

- centralized log aggregation
- dashboards
- alerting
- distributed tracing
- production metrics backend

Those are the next observability steps for enterprise-grade deployment.
