# Ambiguity detection & Question refinement prompt

AmbiguityDetection_prompt = """
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
- If the user explicitly mentions an exact column name that appears uniquely in the schema, do NOT raise AmbiSchema for that reference. You should treat it as already grounded.
- If the user explicitly writes a comparison using an exact column name and a literal value (for example `physical_occupancy_percent < 80`), do NOT raise AmbiValue for that condition.
- If a natural-language phrase clearly maps to one unique schema concept based on column names and descriptions, do NOT raise AmbiSchema just because the wording is not identical to the column name.
- If a natural-language metric is clearly grounded to one unique numeric field and the user provides an explicit threshold, comparison, or literal value, do NOT raise AmbiValue for that condition unless multiple stored interpretations are still genuinely plausible.
- If an exact unique column reference is enough to infer the necessary joins, do NOT ask which table to use merely because the final output may come from a related dimension table.
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
"""

AmbiguityDetection_examples = """
### Example 1:
User Question: "List all basketball players born before the end of 2018 NBA season who got the most points."
Response:
{{
  "has_ambiguity": true,
  "question_set": [
    {{
      "question": "Which column in the 'nba_basketball_player' database should be used to determine player who got the most points?",
      "level_1_label": "Database-sourced ambiguity",
      "level_2_label": "AmbiSchema",
      "description": {{
        "options": [
          "record_rank::yearRecored, representing the record the player ranked in one year.",
          "rank::matches, representing the rank of the player in a specific match.",
          "position::season, representing the record of a player in one season."
        ]
      }}
    }},
    {{
      "question": "Do you mean basketball players born before the start day, end day or year of the 2018 NBA season?",
      "level_1_label": "LLM-sourced ambiguity",
      "level_2_label": "AmbiRef",
      "description": {{
        "options": [
          "The start day of 2018 NBA season is 2017-10-17",
          "The end day of 2018 NBA season is 2018-06-08",
          "The end year of 2018 NBA season is 2018"
        ]
      }}
    }}
  ]
}}

### Example 2:
User Question: "Who are the top developers in the Silicon Valley area?"
Response:
{{
  "has_ambiguity": true,
  "question_set": [
    {{
      "question": "Which SQL operation should be used to determine the top developers in the Silicon Valley area?",
      "level_1_label": "Database-sourced ambiguity",
      "level_2_label": "AmbiView",
      "description": {{
        "options": [
          "The SQL operation could be a SUM of reputation points.",
          "The SQL operation could be a COUNT of completed projects.",
          "The SQL operation could be a RANK based on user ratings."
        ]
      }}
    }},
    {{
      "question": "Which spatial granularity should be used to determine the top developers in the Silicon Valley area?",
      "level_1_label": "LLM-sourced ambiguity",
      "level_2_label": "AmbiRef",
      "description": {{
        "options": [
          "The spatial granularity could be only Palo Alto and Mountain View.",
          "The spatial granularity could be the entire San Francisco Bay Area."
        ]
      }}
    }}
  ]
}}

### Example 3:
User Question: "List the most senior users who joined after the 1940 London Olympics."
Response:
{{
  "has_ambiguity": true,
  "question_set": [
    {{
      "question": "Which column should be used to determine the most senior users who joined after the London Olympics?",
      "level_1_label": "Database-sourced ambiguity",
      "level_2_label": "AmbiSchema",  
      "description": {{
        "options": [
          "age::User, representing the age of the user.",
          "account_created_at:: User, representing the account creation date of the user."
        ]
      }}
    }},
    {{  
      "question": "There is no 1940 London Olympics. Which year of the London Olympics should be used to determine the most senior users who joined after the London Olympics?",
      "level_1_label": "LLM-sourced ambiguity",
      "level_2_label": "AmbiFallacy",
      "description": {{
        "options": [
          "1908 London Olympics",
          "1948 London Olympics",
          "2012 London Olympics"
        ]
      }}
    }}
  ]
}}

### Example 4:
User Question: "Show me the total sales for Apple products yesterday."
Response:
{{
  "has_ambiguity": true,
  "question_set": [
    {{
      "question": "Which column should be used to determine the total sales for Apple products yesterday?",
      "level_1_label": "Database-sourced ambiguity",
      "level_2_label": "AmbiValue",    
      "description": {{
        "options": [
          "brand = 'Apple'",
          "brand LIKE '%Apple%'",
          "brand = 'iPhone'",
          "brand LIKE '%iPhone%'",
          "brand = 'MacBook'",
          "brand LIKE '%MacBook%'"
        ]
      }}
    }},
    {{
      "question": "Yesterday is a dynamic, time-sensitive term. The LLM lacks the current system date context to translate 'yesterday' into a specific YYYY-MM-DD string for the query.", 
      "level_1_label": "LLM-sourced ambiguity",
      "level_2_label": "AmbiContext",
      "description": {{
        "options": [
              "The date of yesterday is 2024-01-01."
              "The date of yesterday is 2024-01-02."
              "The date of yesterday is 2024-01-03."
        ]
      }}
    }}
  ]
}}

### Example 5:
User Question: "Calculate the average of the price for all records in the products table where the category_id is 5, and group the results by the supplier_name column."
Response: 
{{
  "has_ambiguity": false,
  "question_set": [
  ]
}}

### Example 6:
User Question: "Find all female engineers with a high salary."
Response:
{{
  "has_ambiguity": true,
  "question_set": [
    {{
      "question": "How should the system identify female engineers?",
      "level_1_label": "LLM-sourced ambiguity",
      "level_2_label": "AmbiSource",
      "description": {{
        "options": [
          "Query the gender column directly from the database (e.g., gender = 'Female' or gender = 'F').",
          "Use LLM semantic reasoning/inference on the first_name column to infer gender from names."
        ]
      }}
    }},
    {{
      "question": "Which SQL operation should be used to determine engineers with a high salary?",
      "level_1_label": "Database-sourced ambiguity",
      "level_2_label": "AmbiView",
      "description": {{
        "options": [
          "ORDER BY salary DESC LIMIT 10, selecting the top 10 engineers by salary.",
          "Filter where salary > (SELECT AVG(salary) FROM employees), selecting engineers with above-average salary.",
          "Filter where salary > percentile_cont(0.9) WITHIN GROUP (ORDER BY salary), selecting engineers in the top 10% salary range."
        ]
      }}
    }}
  ]
}}

### Example 7:
User Question: "List the history of the Bitcoin exchange rate in the Middle East."
Response:
{{
  "has_ambiguity": true,
  "question_set": [
    {{
      "question": "Which target currency and time interval should be used for the Bitcoin exchange rate history?",
      "level_1_label": "LLM-sourced ambiguity",
      "level_2_label": "AmbiContext",
      "description": {{
        "options": [
          "Bitcoin exchange rate against USD (United States Dollar) with daily intervals.",
          "Bitcoin exchange rate against SAR (Saudi Riyal) with monthly intervals.",
          "Bitcoin exchange rate against EGP (Egyptian Pound) with yearly intervals."
        ]
      }}
    }},
    {{
      "question": "Which spatial granularity should be used to define the Middle East region?",
      "level_1_label": "LLM-sourced ambiguity",
      "level_2_label": "AmbiRef",
      "description": {{
        "options": [
          "The Middle East region includes only core countries: Saudi Arabia, UAE, Qatar, Kuwait, Bahrain, and Oman.",
          "The Middle East region includes extended countries: Saudi Arabia, UAE, Qatar, Kuwait, Bahrain, Oman, Egypt, Jordan, Lebanon, and Syria.",
          "The Middle East region includes all possible countries: Saudi Arabia, UAE, Qatar, Kuwait, Bahrain, Oman, Egypt, Jordan, Lebanon, Syria, Turkey, Cyprus, and Iran."
        ]
      }}
    }}
  ]
}}

### Example 8:
User Question: "Return the user_id and email for all users where the registration_date is between '2023-01-01' and '2023-12-31' and the country_code is 'US'."
Response: 
{{
  "has_ambiguity": false,
  "question_set": [
  ]
}}
"""

QuestionRefine_prompt = '''
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
'''
