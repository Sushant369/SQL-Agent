CQ_Generation_prompt = """
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
"""

CQ_Template_prompt = """
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
"""