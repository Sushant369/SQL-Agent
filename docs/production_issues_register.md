# AmbiSQL Production Issues Register

This document tracks known production risks in the current AmbiSQL architecture and records the recommended production-grade solutions.

The goal is to maintain a practical engineering register for moving AmbiSQL from a working prototype into a final production-grade chatbot system suitable for enterprise clients.

This document is intentionally written from a senior solution architecture perspective:

- identify the issue clearly
- explain why it matters in production
- describe the recommended final-state design
- note the implementation direction for this codebase

---

## 1. Scope

This issues register focuses on the following areas:

- schema lifecycle and runtime reuse
- prompt size and schema narrowing
- ambiguity detection robustness
- clarification-question quality
- confidence score maturity
- session and state management
- runtime performance and cost
- observability and operational support
- testing and evaluation
- security and production controls

---

## 2. Current Architecture Snapshot

At a high level, the project currently does the following:

1. Creates a SQLite database and schema metadata from the local workbook.
2. Builds a versioned schema artifact.
3. Promotes one artifact through `ACTIVE_VERSION`.
4. Loads the active schema artifact into memory at backend startup.
5. Uses that schema for ambiguity detection and SQL generation.
6. Executes SQL and returns a grounded answer with citations.

This is already a stronger architecture than request-time schema generation, but it is still not the final production state in several important areas.

---

## 3. Issues and Production-Grade Solutions

## Issue 1: Full schema artifact is still injected into runtime prompts

### Current state

The full business-grounded schema is loaded into memory and passed into:

- ambiguity detection
- SQL generation

This keeps the implementation simple, but it means the runtime prompt payload can become very large.

### Why this is a production issue

Large prompt payloads increase:

- latency
- token cost
- model distraction
- risk of prompt truncation
- ambiguity misclassification
- SQL generation errors in large schemas

Even when the model context window can technically fit the prompt, oversized prompts usually reduce quality and increase cost.

### Production-grade solution

Keep the full schema artifact in memory as the system source of truth, but introduce a query-time schema selection layer.

The recommended design is:

1. Load the full schema artifact at startup.
2. Rank relevant tables and columns for each user question.
3. Build a reduced schema slice.
4. Send only the reduced slice to:
   - ambiguity detection
   - SQL generation

### Recommended implementation direction

Add a schema selector module that scores tables and columns using:

- question tokens
- column names
- column descriptions
- value descriptions
- optional business synonym dictionaries

Output:

- `filtered_schema_text`
- `filtered_schema_json`

The full schema artifact should remain available in memory, but the model should see only a relevant subset.

### Priority

Very high

---

## Issue 2: Ambiguity detection is still heavily prompt-driven

### Current state

Ambiguity detection uses a taxonomy-based LLM prompt with deterministic post-filters.

### Why this is a production issue

Prompt-driven ambiguity detection can:

- ask unnecessary follow-up questions
- miss genuine ambiguity
- become unstable as schema size grows
- drift with model updates

### Production-grade solution

Use a hybrid ambiguity engine:

- deterministic grounding and suppression logic first
- LLM ambiguity reasoning second
- rule-based and score-based post-processing last

The final design should classify ambiguity only after checking whether the user input is already sufficiently grounded.

### Recommended implementation direction

Introduce an ambiguity decision pipeline with:

1. explicit column grounding
2. literal value detection
3. business synonym resolution
4. candidate ranking
5. ambiguity severity scoring
6. final ask-or-suppress decision

### Priority

Very high

---

## Issue 3: Clarification questions may create user fatigue

### Current state

The system rewrites ambiguity findings into user-facing multiple-choice questions.

### Why this is a production issue

Even correct ambiguity detection can still create a poor experience if:

- too many questions are asked
- answer choices are noisy
- questions are too technical
- follow-up burden becomes higher than user value

### Production-grade solution

Split clarification logic into two decisions:

1. whether clarification is truly required
2. how to ask the question if it is required

Clarification should be used only when it materially changes the SQL semantics.

### Recommended implementation direction

Add:

- blocking vs non-blocking ambiguity classes
- option ranking
- deduplication of near-identical choices
- safe fallback options like:
  - `None of these`
  - `Use another interpretation`
  - `Add manual clarification`

Also support silent clarification when the grounding confidence is already high.

### Priority

High

---

## Issue 4: Grounded answer generation still has bounded row context

### Current state

The answer-generation stage currently caps the result rows it sends into the summarization prompt.

### Why this is a production issue

If the answer model sees only a bounded subset of rows, it may:

- underrepresent the total result set
- miss patterns in later rows
- produce summaries that sound complete but are only partially grounded

### Production-grade solution

The answering layer should adapt its summarization strategy based on result shape.

Recommended modes:

- single-row mode
- small-result full-row mode
- medium-result structured aggregate mode
- large-result summarized statistics mode

### Recommended implementation direction

For large result sets:

- summarize deterministic statistics first
- pass structured rollups instead of raw rows
- keep direct row citations for traceability

### Priority

High

---

## Issue 5: Confidence score is heuristic and not yet calibrated

### Current state

The confidence score is a deterministic weighted heuristic based on pipeline checkpoints.

### Why this is a production issue

If confidence is shown to business users, it can be misinterpreted as:

- probability of correctness
- benchmark accuracy
- model certainty

If it is not calibrated, high scores may still correspond to wrong answers.

### Production-grade solution

Keep the checkpoint-based logic, but calibrate it against evaluation data.

Confidence should ultimately reflect:

- intent clarity
- schema grounding quality
- SQL generation reliability
- execution success
- answer grounding completeness
- traceability quality

### Recommended implementation direction

Add:

- benchmark-based calibration
- explicit penalties for risky conditions
- better separation between execution confidence and semantic confidence

### Priority

High

---

## Issue 6: Runtime state is still held only in local process memory

### Current state

Chat sessions are currently stored in memory.

### Why this is a production issue

This does not survive:

- backend restarts
- multi-worker deployment
- multi-instance deployment
- autoscaling

It also makes support and debugging harder.

### Production-grade solution

Move session state to a durable external store.

Common production choices:

- Redis for fast session state
- SQL store for durable auditability
- hybrid cache + persistence model

### Recommended implementation direction

Abstract the session store behind an interface so the in-memory implementation can later be replaced without rewriting endpoint logic.

### Priority

High

---

## Issue 7: Schema artifact lifecycle still depends on manual local operations

### Current state

The project uses:

- local versioned schema bundles
- `ACTIVE_VERSION`

This is good for a prototype, but promotion is still a local filesystem workflow.

### Why this is a production issue

In real client environments, schema artifact promotion should be:

- controlled
- auditable
- repeatable
- consistent across instances

### Production-grade solution

Keep the artifact + active-version model, but eventually move to a more managed release process.

Final-state patterns could include:

- CI-generated schema artifacts
- approval before activation
- deployment-time promotion
- shared artifact storage across instances

### Recommended implementation direction

Short term:

- keep local artifact versioning
- add validation reports
- add a documented promotion procedure

Later:

- move artifact storage to shared infrastructure

### Priority

Medium to high

---

## Issue 8: Observability is still limited for production support

### Current state

The system now has a structured local observability layer, but it is still not the final enterprise-grade observability model.

Currently implemented:

- local JSONL session logs
- local system log for startup events
- `session_id` and `request_id`
- schema version logging
- ambiguity outcomes and clarification payload logging
- SQL generation request and response logging
- SQL execution result preview logging
- grounded-answer request, response, and fallback logging
- prompt-size metrics
- request summaries with:
  - stage latencies
  - token usage
  - estimated cost

This is a major improvement over simple console debugging, but it is still a local single-service observability implementation.

The event-level debugging guide is documented in:

- `docs/log_event_catalog.md`

### Why this is a production issue

Without strong observability, it becomes difficult to answer:

- why a clarification was asked
- why SQL was wrong
- which schema version served the request
- which prompts were large
- which latency stage dominated

### Production-grade solution

Add structured logging, monitoring, and request tracing.

### Recommended implementation direction

The current implementation now tracks:

- request id
- session id
- schema version
- ambiguity outcomes
- clarification count
- SQL generation latency
- execution latency
- grounded-answer latency
- total tokens
- estimated cost
- fallback usage

The remaining production-grade gaps are:

- centralized log aggregation
- dashboards and alerting
- searchable log indexing
- distributed tracing across services
- long-term metrics storage
- SLO-oriented monitoring

### Current status

Mitigated for local and single-service production debugging, but not fully resolved for enterprise-scale observability.

### Priority

High

---

## Issue 9: Testing coverage is not yet at production release standard

### Current state

The project does not yet operate with a full regression and evaluation harness for all critical behavior.

### Why this is a production issue

Without strong testing, changes to prompts, schema artifacts, or filtering logic can silently degrade:

- ambiguity precision
- SQL quality
- confidence scoring
- answer grounding

### Production-grade solution

Introduce a layered test strategy:

- unit tests
- integration tests
- golden-set regression tests
- adversarial tests
- load tests
- offline evaluation
- human review evaluation

### Recommended implementation direction

Build a labeled ambiguity benchmark set and use it as the foundation for:

- false-positive follow-up measurement
- ambiguity recall
- SQL correctness comparison
- confidence calibration

### Priority

Very high

---

## Issue 10: Security and execution controls are still lightweight

### Current state

The system executes generated SQL against the configured SQLite database.

### Why this is a production issue

Even if the database is read-mostly, production systems need stronger controls for:

- SQL safety
- allowed statement types
- query cost limits
- data exposure
- auditability

### Production-grade solution

Restrict the runtime to approved query patterns and enforce read-only access where possible.

### Recommended implementation direction

Add:

- read-only DB connection policy
- allowlist or parser checks for statement types
- execution timeout limits
- row count limits
- result size caps
- query logging for auditability

### Priority

High

---

## Issue 11: Evaluation of chatbot quality is not yet operationalized

### Current state

The system can be demonstrated, but production readiness requires a repeatable evaluation framework.

### Why this is a production issue

Without formal evaluation, it is impossible to make trustworthy claims about:

- ambiguity reduction
- SQL quality improvement
- user experience improvement
- confidence honesty

### Production-grade solution

Establish a formal evaluation framework with both offline and human review components.

### Recommended implementation direction

Track:

- ambiguity precision
- ambiguity recall
- false-positive clarification rate
- false-negative ambiguity miss rate
- SQL execution success
- SQL correctness
- grounded answer correctness
- clarification burden
- latency
- confidence calibration

### Priority

Very high

---

## 4. Recommended Final-State Target Architecture

The final production-grade architecture should look like this:

### Build-time

1. Build database metadata and schema sources.
2. Build a versioned schema artifact.
3. Validate the artifact.
4. Promote an approved active version.

### Startup-time

1. Backend loads the active schema artifact.
2. Artifact is stored in memory.
3. Service fails fast if the active artifact is invalid.

### Request-time

1. User question arrives.
2. Relevant schema slice is selected from the full in-memory artifact.
3. Ambiguity detection runs on the reduced schema slice.
4. Clarification is asked only when necessary.
5. SQL is generated using the reduced schema slice plus evidence.
6. SQL is executed in a controlled, read-only, bounded way.
7. Final answer is grounded in returned results with explicit traceability.

### Post-run and operations

1. Logs and metrics are recorded.
2. Evaluation data is collected.
3. New schema versions are promoted through a controlled release process.

---

## 5. Recommended Immediate Priorities

The next highest-value issues to address are:

1. Add query-time schema narrowing so full schema artifacts are not sent into prompts.
2. Strengthen ambiguity detection with a hybrid decision layer.
3. Improve clarification-question quality and reduce follow-up burden.
4. Add benchmark-based regression and evaluation.
5. Improve observability and confidence calibration.

---

## 6. How to Use This Document

This document should be treated as a living register.

Recommended workflow:

1. Add new issue entries as they are discovered.
2. Record the agreed production-grade target design.
3. Link implementation tasks or roadmap items to issue numbers.
4. Mark issues as:
   - open
   - in progress
   - mitigated
   - resolved

If desired later, this document can be converted into a more formal decision log or architecture review record.
