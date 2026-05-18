# AmbiSQL Production Hardening Roadmap

This document outlines a structured task plan for evolving AmbiSQL into a more robust production chatbot for enterprise or business databases.

The primary focus areas are:

1. Improving ambiguity detection
2. Improving clarification-question quality
3. Reducing false-positive follow-up questions
4. Performance tuning and optimization
5. More robust confidence scoring and edge-case handling
6. Full regression testing and broader validation
7. Systematic evaluation of chatbot quality

The roadmap is written against the current architecture centered on:

- [ambisql/server_2.py](../ambisql/server_2.py)
- [ambisql/core/ambiguity_resolver.py](../ambisql/core/ambiguity_resolver.py)
- [ambisql/core/cq_generator.py](../ambisql/core/cq_generator.py)
- [ambisql/core/preference_index.py](../ambisql/core/preference_index.py)
- [ambisql/core/schema_generator.py](../ambisql/core/schema_generator.py)
- [ambisql/utils/nl2sql_agent.py](../ambisql/utils/nl2sql_agent.py)

## 1. Objective

The goal is not only to make the chatbot generate SQL more accurately, but also to make it behave more reliably in production settings where:

- schemas are larger and less curated
- business language is inconsistent
- ambiguity is common but user patience is limited
- latency matters
- false clarifications create friction
- confidence must be defensible
- regressions must be caught automatically

The highest priority is to make the ambiguity detector and clarification workflow substantially more precise, so the system asks follow-up questions only when they are genuinely necessary.

## 2. Guiding Principles

- Prefer hybrid reasoning over pure prompt-based behavior.
- Ask fewer but better clarification questions.
- Avoid interrupting the user when the system already has strong grounding.
- Make uncertainty explicit when the system cannot safely infer intent.
- Build evaluation and observability before large behavior changes.
- Treat production robustness as a combination of accuracy, latency, traceability, and failure handling.

## 3. Phase 0: Baseline, Instrumentation, and Production Readiness

Before changing the ambiguity workflow, establish a baseline and create visibility into current behavior.

### Tasks

1. Define the production target.
   - Document the production database size, number of tables, number of columns, refresh frequency, and expected query workload.
   - Define latency targets such as median and p95 response times.
   - Define acceptable failure rates for ambiguity detection, SQL generation, and execution.

2. Build a representative benchmark set.
   - Collect 200-500 representative business questions.
   - Label each question as clear or ambiguous.
   - For ambiguous questions, annotate ambiguity type and expected clarification behavior.
   - Store expected SQL and expected answer where possible.

3. Add observability to the current pipeline.
   - Log raw question, interpreted question, question mode, ambiguity output, clarification questions shown, user selections, SQL execution status, confidence score, and latency per stage.
   - Track user corrections and follow-up retries as signals of failure.

4. Create a manual review workflow.
   - Save failure cases for inspection.
   - Separate false positives, false negatives, low-quality clarifications, SQL errors, and answer-grounding failures.

### Roadblocks

- Production data access may be restricted by privacy and compliance requirements.
- Real user questions may contain organization-specific jargon not present in schema metadata.
- Existing schema descriptions may be incomplete or inconsistent, which will weaken downstream ambiguity resolution.

## 4. Phase 1: Ambiguity Detector Hardening

This is the most important phase for improving the product experience.

### Current Risk

The current ambiguity detector in `AmbiguityResolver.check_ambiguity()` is strong conceptually, but it still depends heavily on LLM judgment. In large production schemas, this can lead to over-triggering clarification questions.

### Goals

- Reduce false-positive ambiguity detection
- Preserve or improve true ambiguity recall
- Improve grounding before asking follow-up questions
- Make ambiguity decisions more explainable

### Tasks

1. Introduce a hybrid ambiguity detector.
   - Keep the LLM taxonomy-based detector.
   - Add deterministic pre-checks and post-filters before surfacing follow-up questions.
   - Use hard rules to suppress low-value follow-ups when intent is already explicit.

2. Add ambiguity scoring instead of a binary decision.
   - Assign a score to each ambiguity candidate based on:
     - ambiguity severity
     - business impact
     - confidence in schema grounding
     - likelihood of SQL divergence across interpretations
   - Only ask clarifications above a configurable threshold.

3. Strengthen schema grounding.
   - Expand exact column-name matching.
   - Add synonym dictionaries for business terms and domain aliases.
   - Score candidates using column names, descriptions, value descriptions, and sample values.
   - Add tie-breaking logic when one candidate is clearly dominant.

4. Expand false-positive suppression logic.
   - Suppress follow-ups when the user already specifies:
     - a literal value or threshold
     - a unique metric
     - a unique business entity
     - an unambiguous date range
     - an obvious aggregation target
   - Suppress schema-level follow-ups when there is only one strong grounded interpretation.

5. Add production-oriented ambiguity categories.
   - Business metric definition ambiguity
   - Time-window ambiguity
   - Entity alias ambiguity
   - Geographic roll-up ambiguity
   - Join-path ambiguity
   - Comparative intent ambiguity

6. Add an internal rationale trace.
   - Store why a follow-up was asked or suppressed.
   - Make it possible to inspect which rule, score, or grounding signal drove the decision.

### Roadblocks

- Large schemas increase the number of plausible candidates and can sharply increase false positives.
- Curated metadata may not exist for all production tables.
- Synonym dictionaries require domain expertise and ongoing maintenance.
- LLM classification drift can cause behavior changes over time unless benchmarked regularly.

## 5. Phase 2: Clarification Question Quality and User Interaction

Once ambiguity is detected correctly, the next challenge is to ask questions that are useful, minimal, and easy to answer.

### Goals

- Ask only necessary questions
- Make questions easier to understand
- Reduce user fatigue
- Improve answer quality from the clarification step

### Tasks

1. Separate decision logic from wording logic.
   - First decide whether clarification is needed.
   - Then generate the best wording and answer choices.

2. Improve question phrasing.
   - Use business-friendly language instead of schema-heavy phrasing.
   - Keep each question focused on a single decision.
   - Avoid combining multiple unresolved issues in one prompt.

3. Improve answer choice generation.
   - Rank answer options by relevance.
   - Limit the number of options shown.
   - Remove duplicates and near-duplicates.
   - Add safe escape options such as:
     - `None of these`
     - `Use a different interpretation`
     - `I want to specify this manually`

4. Support clarification memory safely.
   - Reuse prior accepted interpretations when the same phrase appears again in the same session.
   - Re-ask only when context changes materially.
   - Prevent stale preferences from leaking across unrelated follow-up questions.

5. Add silent clarification behavior.
   - When the system has high grounding confidence, resolve internally and continue without interrupting the user.
   - Surface the assumption in the trace or UI rather than requiring a blocking question.

6. Distinguish blocking vs non-blocking ambiguity.
   - Blocking ambiguity changes SQL semantics materially and must be resolved.
   - Non-blocking ambiguity can be resolved silently or deferred.

### Roadblocks

- Even accurate clarifications can frustrate users if they are too frequent.
- Too many answer options reduce decision quality.
- Poor wording can make users select incorrect answers, which then harms SQL quality downstream.

## 6. Phase 3: Performance Tuning and Optimization

Production robustness also requires predictable latency and efficient use of model calls.

### Goals

- Lower end-to-end latency
- Reduce token usage and cost
- Maintain quality under larger schemas and more sessions

### Tasks

1. Reduce schema payload size.
   - Precompute table summaries and column summaries.
   - Retrieve only the relevant schema slice for each question.
   - Avoid sending the full production schema for every LLM call.

2. Add caching.
   - Cache parsed schema metadata.
   - Cache candidate grounding results.
   - Cache repeated prompt components.
   - Cache safe repeated ambiguity outcomes for duplicate questions.

3. Optimize model allocation.
   - Use smaller or faster models for low-risk classification and reranking tasks.
   - Reserve larger models for harder reasoning tasks only.

4. Parallelize independent work.
   - Candidate grounding, schema retrieval, and some validations can run in parallel.
   - Reduce serial waiting where pipeline steps do not depend on each other.

5. Add latency budgets and fallbacks.
   - Define target latency for:
     - follow-up interpretation
     - ambiguity detection
     - clarification generation
     - SQL generation
     - answer grounding
   - Add graceful fallback behavior when a stage exceeds its time budget.

6. Optimize database execution support.
   - Add query guards for unexpectedly broad SQL.
   - Consider result limits and preview limits for large result sets.
   - Add production-safe timeout handling for slow queries.

### Roadblocks

- Full-schema prompts will not scale to large production databases.
- LLM latency variance can dominate response time even when local code is fast.
- Aggressive caching can create stale or misleading behavior if schema metadata changes.

## 7. Phase 4: Confidence Score Redesign and Edge-Case Handling

The current confidence score is a useful heuristic, but production use requires deeper logic and better calibration.

### Goals

- Make the confidence score more faithful to actual reliability
- Penalize risky behavior more accurately
- Handle edge cases explicitly and safely

### Tasks

1. Redesign confidence as a multi-part score.
   - Separate:
     - intent confidence
     - schema-grounding confidence
     - ambiguity-resolution confidence
     - SQL-generation confidence
     - execution confidence
     - answer-grounding confidence
     - traceability confidence

2. Calibrate the score using benchmark data.
   - Compare score bands against actual correctness.
   - Tune weights using real failure patterns, not only intuition.

3. Penalize risky cases explicitly.
   - Multiple near-tied schema candidates
   - SQL generated from unresolved assumptions
   - Broad joins without clear filters
   - Empty results in cases where ambiguity may still be unresolved
   - Fallback JSON parsing or fallback answer generation

4. Improve edge-case handling.
   - Contradictory user clarifications
   - Follow-up questions that switch domain or database
   - Ambiguous temporal phrases such as `recent`, `current`, or `latest`
   - Unsupported business requests
   - Non-SELECT requests if those are disallowed in production
   - Empty schema descriptions or missing metadata

5. Add safe failure behavior.
   - Prefer admitting uncertainty over presenting low-confidence SQL as authoritative.
   - Provide structured fallback responses when grounding is weak.

### Roadblocks

- Confidence can look precise even when it is not calibrated.
- Some failure signals are indirect and must be inferred from user behavior or offline labels.
- Edge cases tend to grow quickly once real users start exploring the system.

## 8. Phase 5: Regression Testing and Full Test Strategy

Production hardening requires a broad automated test strategy that goes well beyond happy-path checks.

### Goals

- Prevent regressions in ambiguity logic
- Catch behavior drift early
- Validate robustness across normal and adversarial input

### Test Layers

1. Unit tests
   - `interpret_user_question()`
   - schema grounding helpers
   - false-positive suppression logic
   - clarification memory behavior
   - confidence score calculations
   - SQL normalization and parsing helpers

2. Integration tests
   - Full `/api/sql/analyze` flow
   - Full `/api/sql/resolve` flow
   - Mocked LLM responses for deterministic verification

3. Golden-set regression tests
   - Fixed set of representative business questions
   - Expected ambiguity outcome
   - Expected clarification count
   - Expected SQL or SQL pattern
   - Expected grounded answer behavior

4. Adversarial tests
   - Typos
   - synonyms
   - overloaded business terms
   - vague dates
   - contradictory filters
   - misleading follow-up questions
   - duplicated concepts across tables

5. Load and performance tests
   - concurrent sessions
   - large schema workloads
   - model latency spikes
   - cache hit and miss patterns

6. End-to-end user-journey tests
   - new question
   - follow-up refinement
   - multi-step clarification
   - zero-result response
   - failure recovery after a parsing or SQL error

7. Human review tests
   - Expert review of clarification usefulness
   - Expert review of false positives
   - Expert review of confidence label honesty

### Roadblocks

- Many of the current behaviors are nondeterministic because they depend on live LLM calls.
- Real robustness requires labeled data and mockable model layers.
- Large-schema and production-like load tests may need infrastructure not present in local development.

## 9. Phase 6: Evaluation Framework for the Chatbot

Evaluation should be treated as a first-class deliverable, not as a final afterthought.

### Goals

- Quantify whether the chatbot is actually getting better
- Measure the cost of clarifications as well as their value
- Tie confidence to observed correctness

### Core Evaluation Metrics

1. Ambiguity detection precision
   - Of the questions flagged as ambiguous, how many truly needed clarification?

2. Ambiguity detection recall
   - Of the truly ambiguous questions, how many were caught?

3. False-positive clarification rate
   - How often does the system ask an unnecessary follow-up question?

4. False-negative ambiguity miss rate
   - How often does the system fail to ask when clarification was required?

5. Clarification usefulness rate
   - How often does the clarification meaningfully improve the SQL?

6. Average clarification burden
   - Average number of follow-up questions per user request

7. SQL execution success rate
   - Percentage of generated SQL that executes successfully

8. SQL correctness rate
   - Percentage of SQL outputs judged semantically correct

9. Grounded answer correctness
   - Percentage of final answers supported by the result rows

10. End-to-end task success
   - Whether the user got the correct answer with acceptable friction

11. Latency and cost metrics
   - median latency
   - p95 latency
   - token usage
   - estimated cost per request

12. Confidence calibration
   - Whether higher confidence scores actually correspond to higher correctness

### Evaluation Modes

1. Offline evaluation
   - Run benchmark datasets through the system.
   - Compare old and new versions of the ambiguity workflow.

2. Human evaluation
   - Ask reviewers to judge:
     - whether clarification was necessary
     - whether wording was understandable
     - whether final SQL matched intent
     - whether confidence presentation was honest

3. Online evaluation
   - Track live product signals such as:
     - abandonment during clarifications
     - repeated re-asks
     - user restarts
     - retries after answer dissatisfaction
     - rate of manual reformulation

### Roadblocks

- SQL correctness is expensive to label well.
- User satisfaction signals can be noisy.
- Offline benchmark performance may not fully predict production behavior.

## 10. Suggested Delivery Order

The recommended implementation order is:

1. Baseline dataset, instrumentation, and observability
2. Hybrid ambiguity detector and false-positive suppression improvements
3. Clarification-question quality improvements
4. Schema retrieval optimization and performance work
5. Confidence score redesign and edge-case handling
6. Full regression suite
7. Offline and human evaluation
8. Production-like pilot rollout

## 11. Suggested Deliverables by Workstream

### Ambiguity and Clarification

- Hybrid ambiguity scoring module
- Expanded false-positive suppression rules
- Domain synonym library
- Improved clarification question templates
- Option-ranking logic for answer choices

### Performance

- Schema retrieval and prompt-size optimization
- Cache layer for schema and grounding artifacts
- Latency instrumentation and dashboards
- Query timeout and result-size protections

### Confidence and Safety

- Confidence score redesign
- Calibration report
- Edge-case policy document
- Safe fallback response logic

### Testing and Evaluation

- Benchmark dataset
- Regression test suite
- Adversarial test set
- Performance test suite
- Evaluation report comparing versions

## 12. Definition of Done

The production-hardening effort can be considered successful when:

- false-positive clarification rate is materially reduced
- ambiguity recall does not regress significantly
- clarification questions are shorter, clearer, and fewer
- SQL execution success improves or remains stable under larger schemas
- latency and token usage meet agreed targets
- confidence scores are better aligned with actual correctness
- edge-case handling is explicit and safe
- regression and evaluation suites run before release

## 13. Immediate Next Steps

The best next implementation steps are:

1. Build the benchmark set for ambiguity and false-positive follow-up questions.
2. Instrument the current pipeline to capture ambiguity decisions and user clarification outcomes.
3. Refactor ambiguity detection into a hybrid decision layer with scoring and suppression rules.
4. Add regression tests around the current false-positive cases before changing the logic.

These four steps will create the foundation needed to improve production robustness without losing visibility into what changed.
