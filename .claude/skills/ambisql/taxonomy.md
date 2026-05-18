# AmbiSQL Ambiguity Taxonomy

This document defines the 7-type ambiguity taxonomy used by AmbiSQL and
provides 8 few-shot examples for ambiguity detection.

## Table of Contents

- [AmbiSQL Ambiguity Taxonomy](#ambisql-ambiguity-taxonomy)
  - [Table of Contents](#table-of-contents)
  - [Level 1: Database-sourced Ambiguity](#level-1-database-sourced-ambiguity)
    - [AmbiSchema](#ambischema)
    - [AmbiValue](#ambivalue)
    - [AmbiView](#ambiview)
  - [Level 2: LLM-sourced Ambiguity](#level-2-llm-sourced-ambiguity)
    - [AmbiSource](#ambisource)
    - [AmbiContext](#ambicontext)
    - [AmbiFallacy](#ambifallacy)
    - [AmbiRef](#ambiref)
  - [Quick Reference Table](#quick-reference-table)
  - [Few-shot Examples](#few-shot-examples)
    - [Example 1: AmbiSchema + AmbiRef](#example-1-ambischema--ambiref)
    - [Example 2: AmbiView + AmbiRef](#example-2-ambiview--ambiref)
    - [Example 3: AmbiSchema + AmbiFallacy](#example-3-ambischema--ambifallacy)
    - [Example 4: AmbiValue + AmbiContext](#example-4-ambivalue--ambicontext)
    - [Example 5: No Ambiguity (Explicit Query)](#example-5-no-ambiguity-explicit-query)
    - [Example 6: AmbiSource + AmbiView](#example-6-ambisource--ambiview)
    - [Example 7: AmbiContext + AmbiRef](#example-7-ambicontext--ambiref)
    - [Example 8: No Ambiguity (Fully Specified Query)](#example-8-no-ambiguity-fully-specified-query)

---

## Level 1: Database-sourced Ambiguity

Ambiguity that leads to incorrect or incomplete data retrieval directly from the database, due to unclear or underspecified aspects of the user query with respect to the database schema or content.

### AmbiSchema

**Definition:** The question lacks sufficient context to determine which table or specific column to use for operations (e.g., filtering, grouping, ranking, joining, aggregation, etc.), resulting in multiple plausible interpretations.

**Example trigger:** "the oldest user" could refer to `age` column or `registration_date` column.

**Option generation rule:** List all plausible columns with the format `table_name::column_name`, with relevant descriptive schema info retrieved from the input database schema.

### AmbiValue

**Definition:** The question refers to a value that does not correctly correspond to the actual values stored in the database, making it unclear how to formulate the WHERE clause condition and potentially causing relevant results to be omitted or producing inaccurate results.

**Example triggers:**
- Querying posts mentioning "R programming language" → `posts.Body LIKE '%R%'` vs `posts.Body = 'programming language'`
- Querying for users in "New York City" → `users.City = 'New York City'` vs `users.City = 'NYC'`
- Querying for posts about coronavirus → `posts.Body LIKE '%COVID-19%'` vs `posts.Body = 'coronavirus'`

**Option generation rule:** List 2–3 most likely WHERE clause interpretations, with concise explanation for each.

### AmbiView

**Definition:** Key terms clarifying the intended operation are absent, leading to ambiguity about the desired SQL operation.

**Example trigger:** "Top 5 popular tags's star" could mean listing each tag's star count or summing total stars.

**Option generation rule:** List 2–3 possible SQL operations (COUNT / SUM / RANK / ORDER BY, etc.) with concise explanation.

---

## Level 2: LLM-sourced Ambiguity

Ambiguity that results in the misuse of LLM external knowledge, causing difficulties in correctly retrieving or applying information beyond the database.

### AmbiSource

**Definition:** The question fails to specify whether the required information should be retrieved from the database or inferred through LLM reasoning (LLM's external knowledge).

**Example trigger:** "female employees" → query `gender` column or use semantic analysis on `name` column?

**Option generation rule:** Fixed two options — DB query vs LLM inference, with concise explanation for each.

### AmbiContext

**Definition:** The question lacks adequate information to guide LLM reasoning effectively.

**Example trigger:** "current exchange rate" without specifying target currencies or date.

**Option generation rule:** List 2–3 possible values, ranges, or constraints with concise explanation.

### AmbiFallacy

**Definition:** Knowledge assumptions embedded within the question contradict real-world facts or database contents.

**Example trigger:** "2001 Olympic Games" — no Olympics were held in 2001; likely a typo for 2000 or 2004.

**Option generation rule:** List 2–3 best-guessing "typo correction" interpretations.

### AmbiRef

**Definition:** Spatial or temporal constraints are underspecified, resulting in multiple possible interpretations at different granularities.

**Example triggers:**
- "after the 2018 World Cup" could mean immediately after the final match or after the entire tournament year.
- "Middle East Region" might cause missing countries due to vague geographic constraints from different sources.

**Option generation rule:** List 2–3 interpretations according to the reference part in the original user query.

---

## Quick Reference Table

| Level 1 | Level 2 | Trigger Scenario | Option Generation |
|---|---|---|---|
| Database-sourced | **AmbiSchema** | Multiple columns/tables could satisfy the condition | List all plausible `table::column` with descriptions |
| Database-sourced | **AmbiValue** | WHERE condition value is unclear | List 2–3 WHERE clause interpretations |
| Database-sourced | **AmbiView** | SQL operation type is unclear (COUNT vs SUM vs RANK) | List 2–3 SQL operations |
| LLM-sourced | **AmbiSource** | Data from DB query or LLM reasoning? | Fixed: DB query vs LLM inference |
| LLM-sourced | **AmbiContext** | LLM reasoning lacks temporal/monetary/unit context | List 2–3 specific values/ranges |
| LLM-sourced | **AmbiFallacy** | Question contains incorrect factual assumptions | List 2–3 "typo correction" guesses |
| LLM-sourced | **AmbiRef** | Temporal/spatial reference scope is unclear | List 2–3 granularity options |

---

## Few-shot Examples

### Example 1: AmbiSchema + AmbiRef

**User Question:** "List all basketball players born before the end of 2018 NBA season who got the most points."

**Response:**
```json
{
  "has_ambiguity": true,
  "question_set": [
    {
      "question": "Which column in the 'nba_basketball_player' database should be used to determine player who got the most points?",
      "level_1_label": "Database-sourced ambiguity",
      "level_2_label": "AmbiSchema",
      "description": {
        "options": [
          "record_rank::yearRecored, representing the record the player ranked in one year.",
          "rank::matches, representing the rank of the player in a specific match.",
          "position::season, representing the record of a player in one season."
        ]
      }
    },
    {
      "question": "Do you mean basketball players born before the start day, end day or year of the 2018 NBA season?",
      "level_1_label": "LLM-sourced ambiguity",
      "level_2_label": "AmbiRef",
      "description": {
        "options": [
          "The start day of 2018 NBA season is 2017-10-17",
          "The end day of 2018 NBA season is 2018-06-08",
          "The end year of 2018 NBA season is 2018"
        ]
      }
    }
  ]
}
```

### Example 2: AmbiView + AmbiRef

**User Question:** "Who are the top developers in the Silicon Valley area?"

**Response:**
```json
{
  "has_ambiguity": true,
  "question_set": [
    {
      "question": "Which SQL operation should be used to determine the top developers in the Silicon Valley area?",
      "level_1_label": "Database-sourced ambiguity",
      "level_2_label": "AmbiView",
      "description": {
        "options": [
          "The SQL operation could be a SUM of reputation points.",
          "The SQL operation could be a COUNT of completed projects.",
          "The SQL operation could be a RANK based on user ratings."
        ]
      }
    },
    {
      "question": "Which spatial granularity should be used to determine the top developers in the Silicon Valley area?",
      "level_1_label": "LLM-sourced ambiguity",
      "level_2_label": "AmbiRef",
      "description": {
        "options": [
          "The spatial granularity could be only Palo Alto and Mountain View.",
          "The spatial granularity could be the entire San Francisco Bay Area."
        ]
      }
    }
  ]
}
```

### Example 3: AmbiSchema + AmbiFallacy

**User Question:** "List the most senior users who joined after the 1940 London Olympics."

**Response:**
```json
{
  "has_ambiguity": true,
  "question_set": [
    {
      "question": "Which column should be used to determine the most senior users who joined after the London Olympics?",
      "level_1_label": "Database-sourced ambiguity",
      "level_2_label": "AmbiSchema",
      "description": {
        "options": [
          "age::User, representing the age of the user.",
          "account_created_at::User, representing the account creation date of the user."
        ]
      }
    },
    {
      "question": "There is no 1940 London Olympics. Which year of the London Olympics should be used to determine the most senior users who joined after the London Olympics?",
      "level_1_label": "LLM-sourced ambiguity",
      "level_2_label": "AmbiFallacy",
      "description": {
        "options": [
          "1908 London Olympics",
          "1948 London Olympics",
          "2012 London Olympics"
        ]
      }
    }
  ]
}
```

### Example 4: AmbiValue + AmbiContext

**User Question:** "Show me the total sales for Apple products yesterday."

**Response:**
```json
{
  "has_ambiguity": true,
  "question_set": [
    {
      "question": "Which column should be used to determine the total sales for Apple products yesterday?",
      "level_1_label": "Database-sourced ambiguity",
      "level_2_label": "AmbiValue",
      "description": {
        "options": [
          "brand = 'Apple'",
          "brand LIKE '%Apple%'",
          "brand = 'iPhone'",
          "brand LIKE '%iPhone%'",
          "brand = 'MacBook'",
          "brand LIKE '%MacBook%'"
        ]
      }
    },
    {
      "question": "Yesterday is a dynamic, time-sensitive term. The LLM lacks the current system date context to translate 'yesterday' into a specific YYYY-MM-DD string for the query.",
      "level_1_label": "LLM-sourced ambiguity",
      "level_2_label": "AmbiContext",
      "description": {
        "options": [
          "The date of yesterday is 2024-01-01.",
          "The date of yesterday is 2024-01-02.",
          "The date of yesterday is 2024-01-03."
        ]
      }
    }
  ]
}
```

### Example 5: No Ambiguity (Explicit Query)

**User Question:** "Calculate the average of the price for all records in the products table where the category_id is 5, and group the results by the supplier_name column."

**Response:**
```json
{
  "has_ambiguity": false,
  "question_set": []
}
```

### Example 6: AmbiSource + AmbiView

**User Question:** "Find all female engineers with a high salary."

**Response:**
```json
{
  "has_ambiguity": true,
  "question_set": [
    {
      "question": "How should the system identify female engineers?",
      "level_1_label": "LLM-sourced ambiguity",
      "level_2_label": "AmbiSource",
      "description": {
        "options": [
          "Query the gender column directly from the database (e.g., gender = 'Female' or gender = 'F').",
          "Use LLM semantic reasoning/inference on the first_name column to infer gender from names."
        ]
      }
    },
    {
      "question": "Which SQL operation should be used to determine engineers with a high salary?",
      "level_1_label": "Database-sourced ambiguity",
      "level_2_label": "AmbiView",
      "description": {
        "options": [
          "ORDER BY salary DESC LIMIT 10, selecting the top 10 engineers by salary.",
          "Filter where salary > (SELECT AVG(salary) FROM employees), selecting engineers with above-average salary.",
          "Filter where salary > percentile_cont(0.9) WITHIN GROUP (ORDER BY salary), selecting engineers in the top 10% salary range."
        ]
      }
    }
  ]
}
```

### Example 7: AmbiContext + AmbiRef

**User Question:** "List the history of the Bitcoin exchange rate in the Middle East."

**Response:**
```json
{
  "has_ambiguity": true,
  "question_set": [
    {
      "question": "Which target currency and time interval should be used for the Bitcoin exchange rate history?",
      "level_1_label": "LLM-sourced ambiguity",
      "level_2_label": "AmbiContext",
      "description": {
        "options": [
          "Bitcoin exchange rate against USD (United States Dollar) with daily intervals.",
          "Bitcoin exchange rate against SAR (Saudi Riyal) with monthly intervals.",
          "Bitcoin exchange rate against EGP (Egyptian Pound) with yearly intervals."
        ]
      }
    },
    {
      "question": "Which spatial granularity should be used to define the Middle East region?",
      "level_1_label": "LLM-sourced ambiguity",
      "level_2_label": "AmbiRef",
      "description": {
        "options": [
          "The Middle East region includes only core countries: Saudi Arabia, UAE, Qatar, Kuwait, Bahrain, and Oman.",
          "The Middle East region includes extended countries: Saudi Arabia, UAE, Qatar, Kuwait, Bahrain, Oman, Egypt, Jordan, Lebanon, and Syria.",
          "The Middle East region includes all possible countries: Saudi Arabia, UAE, Qatar, Kuwait, Bahrain, Oman, Egypt, Jordan, Lebanon, Syria, Turkey, Cyprus, and Iran."
        ]
      }
    }
  ]
}
```

### Example 8: No Ambiguity (Fully Specified Query)

**User Question:** "Return the user_id and email for all users where the registration_date is between '2023-01-01' and '2023-12-31' and the country_code is 'US'."

**Response:**
```json
{
  "has_ambiguity": false,
  "question_set": []
}
```
