import json
from ambisql.utils.llm_caller import LLMCaller
from ambisql.utils.parse import parse_json_response

SQL_DIFF_PROMPT = """
You are an expert SQL analyzer. Your task is to identify and describe all differences between two SQL queries.

## Task
Compare the two SQL queries below and identify ALL differences between them. Differences can include:
- Different table names or aliases
- Different column names
- Different JOIN conditions
- Different WHERE clauses or conditions
- Different values in conditions
- Different operators (e.g., = vs > vs <)
- Different aggregate functions
- Any other structural or semantic differences

## Input
**SQL Query 1 (Raw):**
{sql_raw}

**SQL Query 2 (Clarified):**
{sql_clarified}

## Output Format
You MUST respond with ONLY a valid JSON object without any additional text, explanations, or markdown formatting. The JSON must contain:
- "differences": A list of difference objects, where each object contains:
  - "type": The type of difference (e.g., "table", "column", "condition", "value", "join", "operator")
  - "location": Where the difference occurs (e.g., "WHERE clause", "JOIN condition", "SELECT clause")
  - "raw_value": The value/expression in SQL Query 1
  - "clarified_value": The value/expression in SQL Query 2
  - "description": A clear description of what changed and why it matters

Example output format:
{{
  "differences": [
    {{
      "type": "table",
      "location": "FROM clause",
      "raw_value": "results",
      "clarified_value": "driverstandings",
      "description": "Changed from 'results' table to 'driverstandings' table, affecting which data source is used"
    }},
    {{
      "type": "column",
      "location": "WHERE clause",
      "raw_value": "T1.rank = 2",
      "clarified_value": "T2.position = 2",
      "description": "Changed from 'rank' column to 'position' column, representing different ranking metrics"
    }},
    {{
      "type": "value",
      "location": "WHERE clause",
      "raw_value": "T2.dob > '1975-04-30'",
      "clarified_value": "T1.dob > '1973-03-29'",
      "description": "Changed date threshold from 1975-04-30 to 1973-03-29, representing different interpretations of 'end of Vietnam War'"
    }}
  ]
}}

Now analyze the two SQL queries and provide the differences:
"""

def detect_sql_differences(sql_raw: str, sql_clarified: str, model: str = "claude") -> dict:
    """
    Use LLM to detect and describe differences between two SQL queries.
    
    Args:
        sql_raw: The raw SQL query (without clarification)
        sql_clarified: The clarified SQL query (with clarification)
        model: The LLM model to use (default: "claude")
        
    Returns:
        A dictionary containing:
        - "differences": List of difference objects with type, location, raw_value, clarified_value, and description
    """
    try:
        llm_caller = LLMCaller(model)
        
        prompt = SQL_DIFF_PROMPT.format(
            sql_raw=sql_raw,
            sql_clarified=sql_clarified
        )
        
        query = [
            {"role": "system", "content": "You are an expert SQL analyzer specializing in identifying differences between SQL queries."},
            {"role": "user", "content": prompt},
        ]
        
        raw_response = llm_caller.call(query)
        parsed_response = parse_json_response(raw_response)
        
        # Ensure the response has the expected structure
        if not isinstance(parsed_response, dict) or "differences" not in parsed_response:
            return {"differences": []}
        
        return parsed_response
        
    except Exception as e:
        print(f"[SQL Diff Detection] Error: {e}")
        return {"differences": []}
