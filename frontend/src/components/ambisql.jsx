import React, { useEffect, useMemo, useRef, useState } from "react";
import "./ambisql.css";

const API_BASE = "http://localhost:8765/api/sql";

const createMessage = (role, content, tone = "default") => ({
  id: crypto.randomUUID(),
  role,
  content,
  tone,
});

const normalizeSQLForDisplay = (sql) => {
  if (!sql) return "";
  return sql
    .replace(/^```sql\s*/i, "")
    .replace(/^```\s*/i, "")
    .replace(/\s*```$/i, "")
    .trim();
};

const formatTokenCount = (value) => (value || 0).toLocaleString();

const formatCurrency = (value) => {
  const amount = Number(value || 0);
  if (amount === 0) return "$0.00";
  if (amount < 0.01) return `$${amount.toFixed(6)}`;
  return `$${amount.toFixed(4)}`;
};

const formatPercentage = (value) => {
  if (typeof value !== "number") return "--";
  return `${Math.round(value)}%`;
};

const formatCitationList = (citations) => {
  if (!citations || citations.length === 0) {
    return "";
  }

  return citations
    .map((citation) => {
      const metadataLines = [];

      if (citation.tables_used) {
        metadataLines.push(
          `Tables used: ${
            citation.tables_used.length > 0
              ? citation.tables_used.join(", ")
              : "None detected"
          }`
        );
      }

      if (citation.columns_used) {
        metadataLines.push(
          `Columns used: ${
            citation.columns_used.length > 0
              ? citation.columns_used.join(", ")
              : "None detected"
          }`
        );
      }

      if (typeof citation.row_count === "number") {
        metadataLines.push(`Rows returned: ${citation.row_count}`);
      }

      return [
        `${citation.marker}: ${citation.evidence}`,
        metadataLines.length > 0 ? metadataLines.join("\n") : "",
      ]
        .filter(Boolean)
        .join("\n");
    })
    .join("\n");
};

const DocsModal = ({ isOpen, onClose }) => {
  if (!isOpen) return null;

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-card" onClick={(event) => event.stopPropagation()}>
        <div className="modal-topline">
          <div>
            <p className="eyebrow">Ambiguity Taxonomy</p>
            <h2>How AmbiSQL decides when to ask follow-up questions</h2>
          </div>
          <button className="ghost-icon-btn" onClick={onClose} aria-label="Close">
            x
          </button>
        </div>

        <div className="modal-grid">
          <section className="modal-section">
            <h3>Database-sourced ambiguity</h3>
            <p>
              These are cases where the database itself allows multiple reasonable
              interpretations.
            </p>
            <div className="modal-chip-list">
              <div className="modal-chip">
                <strong>AmbiSchema</strong>
                <span>More than one table or column could satisfy the request.</span>
              </div>
              <div className="modal-chip">
                <strong>AmbiValue</strong>
                <span>A phrase may map to multiple stored values or filters.</span>
              </div>
              <div className="modal-chip">
                <strong>AmbiView</strong>
                <span>The intended SQL operation is underspecified.</span>
              </div>
            </div>
          </section>

          <section className="modal-section">
            <h3>LLM-sourced ambiguity</h3>
            <p>
              These are cases where reasoning, world knowledge, or missing context
              could change the query.
            </p>
            <div className="modal-chip-list">
              <div className="modal-chip">
                <strong>AmbiSource</strong>
                <span>It is unclear whether to retrieve or infer information.</span>
              </div>
              <div className="modal-chip">
                <strong>AmbiContext</strong>
                <span>Important temporal or factual context is missing.</span>
              </div>
              <div className="modal-chip">
                <strong>AmbiRef / AmbiFallacy</strong>
                <span>References are vague, conflicting, or factually inconsistent.</span>
              </div>
            </div>
          </section>
        </div>
      </div>
    </div>
  );
};

const MessageBubble = ({ message }) => (
  <div className={`message-row ${message.role}`}>
    <div className={`message-bubble ${message.role} ${message.tone}`}>
      {message.role === "user" ? <div className="message-role">You</div> : null}
      <div className="message-content">{message.content}</div>
    </div>
  </div>
);

const SQLAmbiguityResolver = () => {
  const [question, setQuestion] = useState("");
  const [dbDialect, setDbDialect] = useState("SQLite");
  const [dbUsed, setDBUsed] = useState("pgim_property_finance");
  const [messages, setMessages] = useState([
    createMessage(
      "assistant",
      "Ask a question in natural language and I will generate answer from the selected database."
    ),
  ]);
  const [ambiguities, setAmbiguities] = useState([]);
  const [clarificationList, setClarificationList] = useState([]);
  const [sessionId, setSessionId] = useState(null);
  const [additionalInfo, setAdditionalInfo] = useState("");
  const [showDocs, setShowDocs] = useState(false);
  const [isSQLReady, setIsSQLReady] = useState(false);
  const [clarifiedSQL, setClarifiedSQL] = useState("");
  const [groundedAnswer, setGroundedAnswer] = useState("");
  const [citations, setCitations] = useState([]);
  const [queryResult, setQueryResult] = useState(null);
  const [confidence, setConfidence] = useState(null);
  const [monitoring, setMonitoring] = useState(null);
  const [isDetectingAmbiguity, setIsDetectingAmbiguity] = useState(false);
  const [isTranslatingSQL, setIsTranslatingSQL] = useState(false);
  const [submittedClarifications, setSubmittedClarifications] = useState([]);
  const [submittedConstraints, setSubmittedConstraints] = useState([]);
  const [othersInputs, setOthersInputs] = useState({});
  const [lastQuestion, setLastQuestion] = useState("");
  const threadEndRef = useRef(null);

  useEffect(() => {
    threadEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, ambiguities, isDetectingAmbiguity, isTranslatingSQL]);

  useEffect(() => {
    if (ambiguities.length > 0) {
      setClarificationList((prev) =>
        ambiguities.map((item) => {
          const existing = prev.find(
            (prevItem) => prevItem.question === item.question
          );
          return (
            existing || {
              question: item.question,
              answer: "",
              level_1_label: item.level_1_label,
              level_2_label: item.level_2_label,
            }
          );
        })
      );
    }
  }, [ambiguities]);

  const canAskNewQuestion =
    !isDetectingAmbiguity && !isTranslatingSQL;

  const statusLabel = useMemo(() => {
    if (isDetectingAmbiguity) return "Analyzing question";
    if (isTranslatingSQL) return "Generating SQL";
    if (ambiguities.length > 0) return `${ambiguities.length} clarifications waiting`;
    if (isSQLReady) return "SQL ready";
    return "Ready";
  }, [ambiguities.length, isDetectingAmbiguity, isSQLReady, isTranslatingSQL]);

  const pushMessage = (message) => {
    setMessages((prev) => [...prev, message]);
  };

  const resetWorkspace = (nextQuestion = "") => {
    setQuestion(nextQuestion);
    setMessages([
      createMessage(
        "assistant",
        "Ask a question in natural language and I will generate answer from the selected database."
      ),
    ]);
    setAmbiguities([]);
    setClarificationList([]);
    setSessionId(null);
    setAdditionalInfo("");
    setIsSQLReady(false);
    setClarifiedSQL("");
    setGroundedAnswer("");
    setCitations([]);
    setQueryResult(null);
    setConfidence(null);
    setMonitoring(null);
    setIsDetectingAmbiguity(false);
    setIsTranslatingSQL(false);
    setSubmittedClarifications([]);
    setSubmittedConstraints([]);
    setOthersInputs({});
    setLastQuestion("");
  };

  const buildClarificationSummary = (clarifications, constraints) => {
    const lines = clarifications.map(
      (item) => `- ${item.question}\n  ${item.answer}`
    );

    if (constraints) {
      lines.push(`- Additional constraints\n  ${constraints}`);
    }

    return lines.join("\n\n");
  };

  const finalizeGeneration = async (
    activeSessionId,
    clarificationPayload,
    constraints,
    userSummary
  ) => {
    setIsTranslatingSQL(true);

    if (userSummary) {
      pushMessage(createMessage("user", userSummary));
    }

    try {
      const response = await fetch(`${API_BASE}/resolve`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          session_id: activeSessionId,
          clarificationList: clarificationPayload,
          additional_info: constraints,
        }),
      });

      if (!response.ok) {
        throw new Error(`Resolve request failed: ${response.statusText}`);
      }

      const data = await response.json();

      if (data.is_clarified === "True") {
        setIsSQLReady(true);
        setClarifiedSQL(data.sql_statement_clarified || "");
        setGroundedAnswer(data.grounded_answer || "");
        setCitations(data.citations || []);
        setQueryResult(data.query_result || null);
        setConfidence(data.confidence || null);
        setMonitoring(data.monitoring || null);
        setAmbiguities([]);
        setClarificationList([]);
        setAdditionalInfo("");
        setOthersInputs({});

        const citationText = formatCitationList(data.citations || []);
        pushMessage(
          createMessage(
            "assistant",
            [
              `Query:\n${data.sql_statement_clarified || "No SQL generated."}`,
              `Grounded Answer:\n${
                data.grounded_answer ||
                "The executed SQL query result was used to answer the question in natural language."
              }`,
              citationText ? `Citations:\n${citationText}` : "",
            ]
              .filter(Boolean)
              .join("\n\n")
          )
        );
      } else {
        const nextAmbiguities = data.ambiguities || [];
        setConfidence(data.confidence || null);
        setMonitoring(data.monitoring || null);
        setAmbiguities(nextAmbiguities);
        setClarificationList([]);
        setAdditionalInfo("");
        setOthersInputs({});

        pushMessage(
          createMessage(
            "assistant",
            `I still need ${nextAmbiguities.length} more clarification${
              nextAmbiguities.length === 1 ? "" : "s"
            } before the SQL is safe to generate.`
          )
        );
      }
    } catch (error) {
      pushMessage(
        createMessage(
          "assistant",
          `Something went wrong while resolving the question: ${error.message}`,
          "error"
        )
      );
    } finally {
      setIsTranslatingSQL(false);
    }
  };

  const analyzeQuestion = async (questionText, dialect, database) => {
    setIsDetectingAmbiguity(true);
    setAmbiguities([]);
    setClarificationList([]);
    setAdditionalInfo("");
    setSubmittedClarifications([]);
    setSubmittedConstraints([]);
    setOthersInputs({});
    setIsSQLReady(false);
    setClarifiedSQL("");
    setGroundedAnswer("");
    setCitations([]);
    setQueryResult(null);
    setConfidence(null);
    setMonitoring(null);
    pushMessage(createMessage("user", questionText));

    try {
      const response = await fetch(`${API_BASE}/analyze`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          question: questionText,
          dialect,
          db: database,
          session_id: sessionId,
        }),
      });

      if (!response.ok) {
        throw new Error(`Analyze request failed: ${response.statusText}`);
      }

      const data = await response.json();
      const activeSessionId = data.session_id;
      const nextAmbiguities = data.ambiguities || [];
      const interpretedQuestion = data.interpreted_question || questionText;
      const questionMode = data.question_mode || "new_question";
      setConfidence(data.confidence || null);
      setMonitoring(data.monitoring || null);
      setSessionId(activeSessionId);
      setLastQuestion(interpretedQuestion);
      setQuestion("");

      if (questionMode === "follow_up") {
        pushMessage(
          createMessage(
            "assistant",
            `I treated that as a follow-up and expanded it to: ${interpretedQuestion}`
          )
        );
      }

      if (nextAmbiguities.length > 0) {
        setAmbiguities(nextAmbiguities);
        pushMessage(
          createMessage(
            "assistant",
            `I found ${nextAmbiguities.length} ambiguity${
              nextAmbiguities.length === 1 ? "" : "ies"
            } in your question. Answer the follow-up questions below and I will turn the result into SQL.`
          )
        );
      } else {
        setIsDetectingAmbiguity(false);
        pushMessage(
          createMessage(
            "assistant",
            "Your question looks specific enough already, so I am generating SQL now."
          )
        );
        await finalizeGeneration(activeSessionId, [], "", "");
        return;
      }
    } catch (error) {
      pushMessage(
        createMessage(
          "assistant",
          `Something went wrong while analyzing the question: ${error.message}`,
          "error"
        )
      );
    } finally {
      setIsDetectingAmbiguity(false);
    }
  };

  const handleSubmit = async () => {
    const trimmedQuestion = question.trim();
    if (!trimmedQuestion || !canAskNewQuestion) {
      return;
    }
    await analyzeQuestion(trimmedQuestion, dbDialect, dbUsed);
  };

  const handleClarification = async () => {
    if (!sessionId) {
      pushMessage(
        createMessage(
          "assistant",
          "Start with a question first so I can create a session for the clarification flow.",
          "error"
        )
      );
      return;
    }

    const preparedClarificationList = clarificationList
      .filter((item) => item.answer && item.answer.trim())
      .map((item) => ({
        ...item,
        answer:
          item.answer === "Others" && othersInputs[item.question]
            ? othersInputs[item.question].trim()
            : item.answer,
      }))
      .filter((item) => item.answer);

    const constraints = additionalInfo.trim();

    if (preparedClarificationList.length === 0 && !constraints) {
      pushMessage(
        createMessage(
          "assistant",
          "Pick at least one clarification or add a constraint so I know how to refine the query.",
          "error"
        )
      );
      return;
    }

    const currentClarifications = preparedClarificationList.map((item) => ({
      question: item.question,
      answer: item.answer,
      level_1_label: item.level_1_label,
      level_2_label: item.level_2_label,
    }));

    setSubmittedClarifications((prev) => [...prev, ...currentClarifications]);
    if (constraints) {
      setSubmittedConstraints((prev) => [...prev, constraints]);
    }

    await finalizeGeneration(
      sessionId,
      preparedClarificationList,
      constraints,
      buildClarificationSummary(currentClarifications, constraints)
    );
  };

  return (
    <div className="workspace-shell">
      <DocsModal isOpen={showDocs} onClose={() => setShowDocs(false)} />

      <aside className="workspace-sidebar">
        <div className="sidebar-card">
          <div className="card-title-row">
            <h2>Workspace</h2>
            <span className="status-pill">{statusLabel}</span>
          </div>

          <label htmlFor="dialect-select">SQL dialect</label>
          <select
            id="dialect-select"
            value={dbDialect}
            onChange={(event) => setDbDialect(event.target.value)}
            disabled={!canAskNewQuestion}
          >
            <option value="SQLite">SQLite</option>
            <option value="MySQL">MySQL</option>
            <option value="PostgreSQL">PostgreSQL</option>
            <option value="SQL Server">SQL Server</option>
            <option value="Oracle">Oracle</option>
          </select>

          <label htmlFor="database-select">Database</label>
          <select
            id="database-select"
            value={dbUsed}
            onChange={(event) => setDBUsed(event.target.value)}
            disabled={!canAskNewQuestion}
          >
            <option value="pgim_property_finance">pgim_property_finance</option>
          </select>

          <div className="sidebar-actions">
              <button
              className="secondary-btn"
              onClick={() => resetWorkspace("")}
            >
              New chat
            </button>
            <button className="ghost-btn" onClick={() => setShowDocs(true)}>
              Taxonomy
            </button>
          </div>
        </div>

        <div className="sidebar-card confidence-card">
          <div className="card-title-row">
            <h2>Confidence score</h2>
            <span className="status-pill neutral-pill">
              {formatPercentage(confidence?.score_percentage)}
            </span>
          </div>

          <div className="confidence-score-ring">
            <strong>{formatPercentage(confidence?.score_percentage)}</strong>
            <span>{confidence?.label || "Waiting for evaluation"}</span>
          </div>

          <p className="confidence-copy">
            {confidence?.summary ||
              "The score will appear after the system evaluates intent clarity, execution success, and traceability."}
          </p>

          <p className="confidence-note">
            {confidence?.calculation_note ||
              "This is a pipeline-based heuristic, not a model probability."}
          </p>

          {confidence?.factors?.length ? (
            <div className="confidence-breakdown">
              {confidence.factors.map((factor) => (
                <div key={factor.name} className="confidence-factor">
                  <div className="confidence-factor-top">
                    <strong>{factor.name}</strong>
                    <span>
                      {factor.earned_points}/{factor.max_points}
                    </span>
                  </div>
                  <p>{factor.detail}</p>
                </div>
              ))}
            </div>
          ) : null}
        </div>
      </aside>

      <main className="workspace-main">
        <div className="workspace-grid">
          <section className="chat-panel">
            <div className="chat-thread">
              {messages.map((message) => (
                <MessageBubble key={message.id} message={message} />
              ))}

              {isDetectingAmbiguity && (
                <div className="message-row assistant">
                  <div className="message-bubble assistant status">
                    <div className="message-role">AmbiSQL</div>
                    <div className="message-content">Analyzing your question...</div>
                  </div>
                </div>
              )}

              {isTranslatingSQL && (
                <div className="message-row assistant">
                  <div className="message-bubble assistant status">
                    <div className="message-role">AmbiSQL</div>
                    <div className="message-content">
                      Generating SQL from the resolved intent...
                    </div>
                  </div>
                </div>
              )}

              {ambiguities.length > 0 && (
                <div className="clarification-panel">
                  <div className="clarification-header">
                    <div>
                      <p className="eyebrow">Follow-up questions</p>
                      <h3>Resolve the remaining ambiguity</h3>
                    </div>
                    <span className="clarification-count">
                      {ambiguities.length} pending
                    </span>
                  </div>

                  <div className="clarification-list">
                    {ambiguities.map((item, index) => (
                      <div key={item.question} className="clarification-card">
                        <div className="clarification-labels">
                          <span>{item.level_1_label}</span>
                          <span>{item.level_2_label}</span>
                        </div>
                        <p>{item.question}</p>
                        <select
                          value={clarificationList[index]?.answer || ""}
                          onChange={(event) => {
                            const updated = [...clarificationList];
                            updated[index] = {
                              ...(updated[index] || {}),
                              question: item.question,
                              level_1_label: item.level_1_label,
                              level_2_label: item.level_2_label,
                              answer: event.target.value,
                            };
                            setClarificationList(updated);
                          }}
                        >
                          <option value="" disabled>
                            Select an answer
                          </option>
                          {(item.choices || []).map((choice) => (
                            <option key={choice} value={choice}>
                              {choice}
                            </option>
                          ))}
                        </select>

                        {clarificationList[index]?.answer === "Others" && (
                          <textarea
                            className="inline-textarea"
                            value={othersInputs[item.question] || ""}
                            onChange={(event) =>
                              setOthersInputs((prev) => ({
                                ...prev,
                                [item.question]: event.target.value,
                              }))
                            }
                            placeholder="Add your own clarification"
                          />
                        )}
                      </div>
                    ))}
                  </div>

                  <div className="constraint-block">
                    <label htmlFor="constraints-input">Additional constraints</label>
                    <textarea
                      id="constraints-input"
                      className="inline-textarea"
                      value={additionalInfo}
                      onChange={(event) => setAdditionalInfo(event.target.value)}
                      placeholder="Example: Only include German drivers or limit this to the 2010 season."
                    />
                  </div>

                  <button className="primary-btn" onClick={handleClarification}>
                    Submit clarifications
                  </button>
                </div>
              )}

              <div ref={threadEndRef} />
            </div>

            <div className="composer-panel">
              <label htmlFor="question-input">Question</label>
              <textarea
                id="question-input"
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                disabled={!canAskNewQuestion}
                placeholder="Ask a new question or refine the last one..."
              />
              <div className="composer-footer">
                <p className="composer-hint">
                  {ambiguities.length > 0
                    ? "Answer the follow-up questions above, or send a brand-new question to change direction."
                    : "AmbiSQL will inspect ambiguity before producing SQL."}
                </p>
                <button
                  className="primary-btn"
                  onClick={handleSubmit}
                  disabled={!canAskNewQuestion || !question.trim()}
                >
                  Analyze question
                </button>
              </div>
            </div>
          </section>

          <aside className="result-panel">
            <div className="result-card usage-card">
              <div className="card-title-row">
                <h3>Usage monitoring</h3>
                <span className="muted-pill">
                  {monitoring?.session_total?.requests || 0} calls
                </span>
              </div>

              <div className="usage-summary">
                <div className="usage-total">
                  <span>Total tokens</span>
                  <strong>
                    {formatTokenCount(monitoring?.session_total?.total_tokens)}
                  </strong>
                </div>
                <div className="usage-total accent">
                  <span>Estimated cost</span>
                  <strong>
                    {formatCurrency(monitoring?.session_total?.estimated_cost_usd)}
                  </strong>
                </div>
              </div>

              <div className="usage-breakdown">
                {[
                  monitoring?.ambiguity_workflow,
                  monitoring?.sql_generation,
                ].map((item, index) => (
                  <div key={item?.label || index} className="usage-section">
                    <div className="usage-header">
                      <div>
                        <strong>{item?.label || "Not started"}</strong>
                        <span>{item?.pricing_model || "No model yet"}</span>
                      </div>
                      <span className="muted-pill">{item?.requests || 0} calls</span>
                    </div>
                    <div className="usage-grid">
                      <div className="usage-stat">
                        <span>Input</span>
                        <strong>{formatTokenCount(item?.input_tokens)}</strong>
                      </div>
                      <div className="usage-stat">
                        <span>Output</span>
                        <strong>{formatTokenCount(item?.output_tokens)}</strong>
                      </div>
                      <div className="usage-stat">
                        <span>Total</span>
                        <strong>{formatTokenCount(item?.total_tokens)}</strong>
                      </div>
                      <div className="usage-stat">
                        <span>Cost</span>
                        <strong>{formatCurrency(item?.estimated_cost_usd)}</strong>
                      </div>
                    </div>
                  </div>
                ))}
              </div>

              <p className="usage-note">
                Estimated using standard OpenAI API token pricing for the active models.
              </p>
            </div>

            <div className="result-card">
              <div className="card-title-row">
                <h3>Current query</h3>
                {lastQuestion ? <span className="muted-pill">Active</span> : null}
              </div>
              <p className="result-copy">
                {lastQuestion || "No question submitted yet."}
              </p>
            </div>

            <div className="result-card">
              <div className="card-title-row">
                <h3>Clarification memory</h3>
                <span className="muted-pill">{submittedClarifications.length}</span>
              </div>

              {submittedClarifications.length === 0 && submittedConstraints.length === 0 ? (
                <p className="empty-copy">
                  Clarifications and extra constraints will be collected here as the conversation progresses.
                </p>
              ) : (
                <div className="memory-stack">
                  {submittedClarifications.map((item, index) => (
                    <div key={`${item.question}-${index}`} className="memory-item">
                      <strong>{item.question}</strong>
                      <span>{item.answer}</span>
                    </div>
                  ))}

                  {submittedConstraints.map((constraint, index) => (
                    <div key={`${constraint}-${index}`} className="memory-item constraint">
                      <strong>Additional constraint</strong>
                      <span>{constraint}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>

            <div className="result-card sql-card">
              <div className="card-title-row">
                <h3>SQL output</h3>
                {isSQLReady ? <span className="muted-pill">Ready</span> : null}
              </div>

              <div className="sql-section">
                <label>Grounded answer</label>
                <div className="sql-box">
                  {groundedAnswer || "Waiting for query execution..."}
                </div>
              </div>

              <div className="sql-section">
                <label>Clarified SQL statement</label>
                <div className="sql-box accent">
                  {clarifiedSQL
                    ? normalizeSQLForDisplay(clarifiedSQL)
                    : "Waiting for SQL generation..."}
                </div>
              </div>

              <div className="sql-section">
                <label>Query result preview</label>
                <div className="sql-box">
                  {queryResult
                    ? JSON.stringify(queryResult, null, 2)
                    : "Waiting for query results..."}
                </div>
              </div>
            </div>
          </aside>
        </div>
      </main>
    </div>
  );
};

export default SQLAmbiguityResolver;
