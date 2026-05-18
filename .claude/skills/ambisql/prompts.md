# AmbiSQL Prompt Templates

This document contains the prompt templates used by the AmbiSQL Skill. Each
template includes its variable definitions and expected output format.

## Table of Contents

1. [AmbiguityDetection_prompt](#1-ambiguitydetection_prompt) — Phase 1: detect ambiguities in user questions
2. [CQ_Generation_prompt](#2-cq_generation_prompt) — Phase 2: generate user-friendly multi-choice options
3. [CQ_Template_prompt](#cq_template_prompt-9-templates) — 9 formatting templates for clarification choices
4. [QuestionRefine_prompt](#3-questionrefine_prompt) — Phase 2: merge free-text input into the question
5. [NodeMerge_prompt](#4-nodemerge_prompt-supporting) — Supporting: merge conflicting evidence in PreferenceTree

---

## 1. AmbiguityDetection_prompt

**Purpose:** Analyze user questions against database schema to detect
ambiguities that could lead to incorrect SQL.

**System prompt:**
```
You are a helpful assistant to find out inherent ambiguity in a natural language statement. Return only the result with no explanation.
```

**Variables:**

| Variable | Source | Description |
|---|---|---|
| `{question}` | Conversation context | The user's natural language question |
| `{schema}` | Schema dump script or `SchemaGenerator` | Formatted database schema (JSON or text) |
| `{evidence}` | `PreferenceTree.traverse()` output; `None` for initial detection | Previously collected clarification evidence |
| `{examples}` | Few-shot examples from [taxonomy.md](taxonomy.md) | 8 examples for ambiguity detection |

**Template:**

```
## Task
Given a user question, database schema, and optional evidence, identify ambiguities in the user question and generate clarification questions to resolve them.
Contents in the evidence are user provided clarifications to resolve previous detected ambiguities.
Note that the user question might use both data inside the database and external parametrized knowledge from the Large Language Model (LLM).


## Ambiguity Definition & Taxonomy:
A user question is identifies as ambiguous when there is more than one reasonable interpretation due to unclear, incomplete, or conflicting information.
The ambiguity in a user question are defined as two different levels.
- level_1 ambiguity type are defined from two different dimensions, database and LLM repectively:
    - "Database-sourced ambiguity": Ambiguity that leads to incorrect or incomplete data retrieval directly from the database, due to unclear or underspecified aspects of the user query with respect to the database schema or content.
    - "LLM-sourced ambiguity": Ambiguity that results in the misuse of LLM external knowledge, causing difficulties in correctly retrieving or applying information beyond the database.
- level_2 ambiguity type are defined under each level_1 ambiguity type as follows:
    - Database-sourced ambiguity:
      - "AmbiSchema": The question lacks sufficient context to determine which table or specific column to use for operations(e.g., filtering, grouping, ranking, joining, aggregation, etc.), resulting in multiple plausible interpretations.
        - (e.g., "the oldest user" could refer to 'age' column or 'registration_date' column, representing different aspects of user's age or registration date).
      - "AmbiValue": The question refers to a value that does not correctly correspond to the actual values stored in the database, making it unclear how to formulate the WHERE clause condition and potentially causing relevant results to be omitted or producing inaccurate results.
        - (e.g., querying posts mentioning the "R programming language", the WHERE clause might be "posts.Body LIKE '%R%'", or "posts.Body = 'programming language'", etc)
        - (e.g., querying for users living in "New York City", the WHERE clause might be "users.City = 'New York City'", or "users.City = 'NYC'", etc)
        - (e.g., querying for posts about coronavirus, the WHERE clause might be "posts.Body LIKE '%COVID-19%'", or "posts.Body = 'coronavirus'", etc)
      - "AmbiView": Key terms clarifying the intended operation are absent, leading to ambiguity about the desired SQL operation 
        - (e.g., query as 'Top 5 popular tags's star', which can list each tag's star or the amount of stars).
    - LLM-sourced ambiguity:
      - "AmbiSource": The question fails to specify whether the required information should be retrieved from the database or inferred through LLM reasoning(LLM's external knowledge).
        - (e.g., querying for "female employees," whether to query 'gender' column or use semantic analysis on 'name' column).
      - "AmbiContext": The question lacks adequate information to guide LLM reasoning effectively.
        - (e.g., requesting dynamic or time-sensitive external information like "current exchange rate" without specifying the target currencies or date).
      - "AmbiFallacy": Knowledge assumptions embedded within the question contradicts real-world facts or database contents 
        - (e.g., querying entities or participants in events that never occurred, like 2001 Olympic Games).
      - "AmbiRef": Spatial or temporal constraints are underspecified, resulting in multiple possible interpretations at different granularities 
        - (e.g., querying for records "after the 2018 World Cup" could mean immediately after the final match or after the entire tournament year).
        - (e.g., querying for records in the 'Middle East Region' might cause missing countries in the list for "Middle East" due to vague or imprecise geographic constraints from different sources).
      
## Instructions
1. Analyze user question, database schema and evidence(if provided) to identify all possible ambiguous phrases in the user question.
2. For each unresolved ambiguity: **(1)** Assign exactly one level-1 and one level-2 label. **(2)** Write a multi-choice question for user to further clarify their intent.
3. For each multi-choice question: provide several possible options for users to choose from, add a description for each option, and add an explanation for the whole question through thinking. Formulate options and corresponding description based on the ambiguity type detected as follows:
  i. For "AmbiSchema", list all plausible columns with the format of 'table_name::column_name', with relevant descriptive schema info retrieved from the input database schema.
  ii. For "AmbiValue", list most likely 2-3 possible interpretations of WHERE clause, with concise explanation for each interpretation.
  iii. For "AmbiView", list most likely 2-3 possible interpretations of SQL operations, with concise explanation for each interpretation.
  iv. For "AmbiSource", list 2 options representing data retrieval from database or LLM's external knowledge repectively, with concise explanation for each interpretation.
  v. For "AmbiContext", list most likely 2-3 possible values, ranges or constraints with concise explanation for each interpretation.
  vi. For "AmbiFallacy", list most likely 2-3 best-guessing interpretations of the 'fallacy' info considering it as a typo.
  vii. For "AmbiRef", list most likey 2-3 interpretations according to the reference part in the original user query.
**Important Note**: 
- All possible options should be in complete with concise description for user to select(Do not use such as or etc to omit some necessary options).
- Not each input question is ambiguous. If all ambiguities are resolved or the original user input is unambiguous, return an empty question_set. (e.g., If only one column in the database is plausible, it should not be an unclear schema reference)
- If the user's response in evidence to a specific ambiguity is 'Abstain', it means the identified ambiguity is not an actual ambiguity, and you can skip this ambiguity and not identify it again.


## Output Format Requirements:
You **MUST** output a strict JSON string as follows:
{{
  "has_ambiguity": true | false,
  "question_set": [
    {{
      "question": "string",
      "level_1_label": "Database-sourced ambiguity | LLM-sourced ambiguity",
      "level_2_label": "string",
      "description": "string - detailed description of all possible choices"
    }},
    ...
  ]
}}

---
## Example:
{examples}
---
**Input:**
Question: {question}
Schema: {schema}
Evidence: {evidence}
--
The ambiguity detection result is:
```

---

## 2. CQ_Generation_prompt

**Purpose:** Transform technical ambiguity options into clear, user-friendly
multiple-choice questions that non-technical users can answer confidently.

**System prompt:**
```
You are an expert that excels at simplifying complex technical information into clear, user-friendly, multiple-choice options.
```

**Variables:**

| Variable | Source | Description |
|---|---|---|
| `{question}` | `question_set[i].question` from Phase 1 output | The clarification question for a specific ambiguity |
| `{description}` | `question_set[i].description` from Phase 1 output | Context and potential options for the clarification |
| `{templates}` | `CQ_Template_prompt` (9 templates, see below) | Example templates for option formatting |

**Template:**

```
## Task
Your task is to analyze a clarification question and its accompanying description, and then generate a list of choices for the clarification question. 
Each choice should be a self-contained, natural language sentence that is easy for a non-technical user to understand and select.

## Instructions:
- Make sure all choices follow similar formats (e.g, choice + a concise and clear explanation/evidence for the choice) 
- If there are columns to be chosen, list each column choice as "column_name::table_name, column_description" in a descriptive sentence.
- Choose the most appropriate question template to formulate choices based on the given templates.
- You MUST always add two compulsory choices: "Abstain" and "Others" into the choice list.

## Input
- **Question**: The clarification question that needs to be answered.
- **Description**: The context, explanations or data evidences containing the potential choices for the clarification question. This can be a simple string or a structured JSON object.

## Output format
You MUST respond with ONLY a single, valid JSON string without any additional text, explanations, or markdown formatting. The string must contain a single key, "choices", which is a list of strings as follows:
{{
  "choices": [
    "choice1",
    "choice2",
    "choice3",
    ...,
    "Abstain",
    "Others"
  ]
}}
---
**Templates:** 
{templates}
---
**Input:**
Input question: {question}
Input description: {description}
---
The choices are:
```

### CQ_Template_prompt (9 templates)

These templates cover all 7 ambiguity types and show how to format choices
for each. The `{templates}` variable in `CQ_Generation_prompt` should be
filled with the full content below.

| Template # | Ambiguity Type | Example Question |
|---|---|---|
| 1 | AmbiSchema | "Which column should be used to determine player who got the most points?" |
| 2 | AmbiValue | "Which column should be used to determine total sales for Apple products?" |
| 3 | AmbiView | "Which SQL operation for engineers with a high salary?" |
| 4 | AmbiSource | "How should the system identify female engineers?" |
| 5 | AmbiContext | "Which target currency and time interval for Bitcoin exchange rate?" |
| 6 | AmbiFallacy | "There is no 1940 London Olympics. Which year?" |
| 7 | AmbiRef (temporal) | "Born before start day, end day or year of 2018 NBA season?" |
| 8 | AmbiRef (spatial) | "Which spatial granularity for the Middle East region?" |
| 9 | AmbiView | "Which SQL operation for top developers?" |

**Full template content:**

```
### Template 1:
Input question: "Which column in the 'nba_basketball_player' database should be used to determine player who got the most points?"
Input description:
{{
  "options": [
    "record_rank::yearRecored, representing the record the player ranked in one year.",
    "rank::matches, representing the rank of the player in a specific match.",
    "position::season, representing the record of a player in one season."
  ]
}}
Output: 
{{
  "choices": [
    "Use record_rank column from yearRecored table, representing the record the player ranked in one year.",
    "Use rank column from matches table, representing the rank of the player in a specific match.",
    "Use position column from season table, representing the record of a player in one season.",
    "Abstain",
    "Others"
  ]
}}

### Template 2:
Input question: "Which column should be used to determine the total sales for Apple products yesterday?"
Input description:
{{
  "options": [
    "brand = 'Apple'",
    "brand LIKE '%Apple%'",
    "brand = 'iPhone'",
    "brand LIKE '%iPhone%'",
    "brand = 'MacBook'",
    "brand LIKE '%MacBook%'"
  ]
}}
Output: 
{{
  "choices": [
    "Filter products where brand equals 'Apple' (exact match).",
    "Filter products where brand contains 'Apple' (partial match).",
    "Filter products where brand equals 'iPhone' (exact match).",
    "Filter products where brand contains 'iPhone' (partial match).",
    "Filter products where brand equals 'MacBook' (exact match).",
    "Filter products where brand contains 'MacBook' (partial match).",
    "Abstain",
    "Others"
  ]
}}

### Template 3:
Input question: "Which SQL operation should be used to determine engineers with a high salary?"
Input description:
{{
  "options": [
    "ORDER BY salary DESC LIMIT 10, selecting the top 10 engineers by salary.",
    "Filter where salary > (SELECT AVG(salary) FROM employees), selecting engineers with above-average salary.",
    "Filter where salary > percentile_cont(0.9) WITHIN GROUP (ORDER BY salary), selecting engineers in the top 10% salary range."
  ]
}}
Output: 
{{
  "choices": [
    "Select the top 10 engineers by salary (ORDER BY salary DESC LIMIT 10).",
    "Select engineers with above-average salary (salary greater than the average salary of all employees).",
    "Select engineers in the top 10% salary range (salary greater than the 90th percentile).",
    "Abstain",
    "Others"
  ]
}}

### Template 4:
Input question: "How should the system identify female engineers?"
Input description:
{{
  "options": [
    "Query the gender column directly from the database (e.g., gender = 'Female' or gender = 'F').",
    "Use LLM semantic reasoning/inference on the first_name column to infer gender from names."
  ]
}}
Output: 
{{
  "choices": [
    "Query the gender column directly from the database (e.g., gender = 'Female' or gender = 'F').",
    "Use LLM semantic reasoning/inference on the first_name column to infer gender from names.",
    "Abstain",
    "Others"
  ]
}}

### Template 5:
Input question: "Which target currency and time interval should be used for the Bitcoin exchange rate history?"
Input description:
{{
  "options": [
    "Bitcoin exchange rate against USD (United States Dollar) with daily intervals.",
    "Bitcoin exchange rate against SAR (Saudi Riyal) with monthly intervals.",
    "Bitcoin exchange rate against EGP (Egyptian Pound) with yearly intervals."
  ]
}}
Output: 
{{
  "choices": [
    "Bitcoin exchange rate against USD (United States Dollar) with daily intervals.",
    "Bitcoin exchange rate against SAR (Saudi Riyal) with monthly intervals.",
    "Bitcoin exchange rate against EGP (Egyptian Pound) with yearly intervals.",
    "Abstain",
    "Others"
  ]
}}

### Template 6:
Input question: "There is no 1940 London Olympics. Which year of the London Olympics should be used to determine the most senior users who joined after the London Olympics?"
Input description:
{{
  "options": [
    "1908 London Olympics",
    "1948 London Olympics",
    "2012 London Olympics"
  ]
}}
Output: 
{{
  "choices": [
    "1908 London Olympics",
    "1948 London Olympics",
    "2012 London Olympics",
    "Abstain",
    "Others"
  ]
}}

### Template 7:
Input question: "Do you mean basketball players born before the start day, end day or year of the 2018 NBA season?"
Input description:
{{
  "options": [
    "The start day of 2018 NBA season is 2017-10-17",
    "The end day of 2018 NBA season is 2018-06-08",
    "The end year of 2018 NBA season is 2018"
  ]
}}
Output: 
{{
  "choices": [
    "The start day of 2018 NBA season (2017-10-17).",
    "The end day of 2018 NBA season (2018-06-08).",
    "The end year of 2018 NBA season (2018).",
    "Abstain",
    "Others"
  ]
}}

### Template 8:
Input question: "Which spatial granularity should be used to define the Middle East region?"
Input description:
{{
  "options": [
    "The Middle East region includes only core countries: Saudi Arabia, UAE, Qatar, Kuwait, Bahrain, and Oman.",
    "The Middle East region includes extended countries: Saudi Arabia, UAE, Qatar, Kuwait, Bahrain, Oman, Egypt, Jordan, Lebanon, and Syria.",
    "The Middle East region includes all possible countries: Saudi Arabia, UAE, Qatar, Kuwait, Bahrain, Oman, Egypt, Jordan, Lebanon, Syria, Turkey, Cyprus, and Iran."
  ]
}}
Output: 
{{
  "choices": [
    "The Middle East region includes only core countries: Saudi Arabia, UAE, Qatar, Kuwait, Bahrain, and Oman.",
    "The Middle East region includes extended countries: Saudi Arabia, UAE, Qatar, Kuwait, Bahrain, Oman, Egypt, Jordan, Lebanon, and Syria.",
    "The Middle East region includes all possible countries: Saudi Arabia, UAE, Qatar, Kuwait, Bahrain, Oman, Egypt, Jordan, Lebanon, Syria, Turkey, Cyprus, and Iran.",
    "Abstain",
    "Others"
  ]
}}

### Template 9:
Input question: "Which SQL operation should be used to determine the top developers in the Silicon Valley area?"
Input description:
{{
  "options": [
    "The SQL operation could be a SUM of reputation points.",
    "The SQL operation could be a COUNT of completed projects.",
    "The SQL operation could be a RANK based on user ratings."
  ]
}}
Output: 
{{
  "choices": [
    "Use SUM of reputation points to determine top developers.",
    "Use COUNT of completed projects to determine top developers.",
    "Use RANK based on user ratings to determine top developers.",
    "Abstain",
    "Others"
  ]
}}
```

---

## 3. QuestionRefine_prompt

**Purpose:** When a user selects "Others" and provides free-text input,
merge that additional information into the current question to create a
more complete, refined question for re-analysis.

**System prompt:**
```
You are an expert specializing in query refinement. Your purpose is to merge and consolidate user questions with new information. Respond ONLY with the refined question. Do not add any explanation, formatting, or extra text.
```

**Variables:**

| Variable | Source | Description |
|---|---|---|
| `{question}` | Current question (original or previously refined) | The question to be refined |
| `{additional_info}` | User-provided free-text input from Phase 2 | Additional context or clarification from the user |

**Template:**

```
## Task
To combine an `original_question` with `additional_information` into a single, coherent, and complete new question that is logically sound and easy to understand.

## Core Principles
1.  **Absolute Preservation**: You MUST preserve ALL constraints, details, and intents from the `original_question`. Nothing from the original should be omitted or altered unless it is directly and explicitly contradicted by the `additional_information`.
2.  **Full Integration**: You MUST seamlessly integrate ALL new requirements and constraints from the `additional_information` into the new question.
3.  **Conflict Resolution**: If a piece of `additional_information` directly conflicts with a part of the `original_question`, the `additional_information` takes precedence and should be used to update or replace the conflicting part. This is the **only** scenario where original information may be modified.
4.  **Natural Language**: The final output must be a single, natural-sounding question, not a list of criteria.

## Examples
Original question: List all novels published after 2000 that won a Booker Prize.
Additional information: Only include novels published after 2010 that were also adapted into movies and written by female authors.
Rewritten question: List all novels published after 2010 that won a Booker Prize, were adapted into movies, and were written by female authors.

Original question: Which Asian countries have a GDP per capita above $30,000 and a population under 10 million?
Additional information: Exclude countries that are island nations and with a population more than 10 million.
Rewritten question: Which Asian countries that are not island nations have a GDP per capita above $30,000 and a population more than 10 million?

Original question: Provide the list of Olympic gold medalists in swimming events for the last three Summer Olympics, including their ages at the time of winning.
Additional information: I am only interested in male athletes from North America, and only in individual events.
Rewritten question: Provide the list of male North American Olympic gold medalists in individual swimming events for the last three Summer Olympics, including their ages at the time of winning.

## Response Format
- Return **only** the text of the rewritten question.
- Do not include any preamble, labels (like "Rewritten question:"), or explanations.

---
**Input:**
Original question: {question}
Additional information: {additional_info}

The rewritten question is:
```

---

## 4. NodeMerge_prompt (Supporting)

**Purpose:** Used internally by the PreferenceTree to merge new QA pairs
into existing evidence. When a user provides a new answer that conflicts
with a previous one for the same ambiguity, this prompt handles the
semantic merging — the newer answer takes precedence.

**Variables:**

| Variable | Source | Description |
|---|---|---|
| `{old_list}` | Existing `qa_list` in a leaf node | JSON array of existing question-answer pairs |
| `{new_pair}` | New QA pair to merge | JSON object with `question` and `answer` fields |

**Template:**

```
## Task
Merge a new question-answer pair into an existing list of question-answer pairs.

## Input
- old_list: an existing list of objects, each with a `question` and `answer` field.
- new_pair: an object with a `question` and `answer` field.

## Merge Instructions
1. Compare the `question` field of `new_pair` with each item in `old_list`. If any question in `old_list` has the same or highly similar meaning as `new_pair` (e.g., the same intent, but possibly different wording), consider it a conflict.
2. If there is a conflict, remove the conflicting item from `old_list` and replace it with `new_pair`.
3. If there is no conflict, append `new_pair` at the end of `old_list`.
4. Ensure the output list contains no duplicate questions (by meaning).
5. Return ONLY the merged list as a valid JSON array, with each item in the format: {{"question": "...", "answer": "..."}}
6. Do NOT return any explanation, comments, or text outside the JSON array.

## Now process the given input:

old_list:
{old_list}

new_pair:
{new_pair}

Merged Output:
```
