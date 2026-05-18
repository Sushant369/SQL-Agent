import csv
import re
import json

def format_message(qa_set, additional_info):
    message = {
        "qa_set": qa_set,
        "additional_info": additional_info
    }
    return json.dumps(message, ensure_ascii=False) 

def format_response(is_clarified, q_set):
    message = {
        "is_clarified": is_clarified,
        "question_set": q_set
    }
    return json.dumps(message, ensure_ascii=False) 

def parse_json_response(response):
    """
    parse json from LLM output
    """
    try:
        if "```json" in response:
            response = response.split("```json")[1].split("```")[0].strip()
        json_pattern = re.compile(r'{.*}', re.DOTALL)
        
        match = json_pattern.search(response)
        
        if match:
            json_str = match.group(0)

            json_str = (
                json_str.replace("True", "true")
                        .replace("False", "false")
                        .replace("None", "null")
            )

            return json.loads(json_str)
        else:
            raise ValueError("Can not retrieve JSON")
    except json.JSONDecodeError:
        print(response)
        raise ValueError("JSON Decoder failed.")
    except Exception as e:
        raise ValueError(f"Error: {e}")
    
def parse_schema_text(schema_text):
    tables = re.split(r'Table:\s*', schema_text)
    db_schema = []
    for t in tables:
        t = t.strip()
        if not t:
            continue
        lines = [l for l in t.split('\n') if l.strip()]
        if not lines:
            continue 
        table_name = lines[0].strip()
        columns = []
        for line in lines[1:]:
            line = line.strip()
            if line.startswith('-'):
                desc = line[1:].strip()
                if ':' in desc:
                    col_name, des = desc.split(':', 1)
                    columns.append({
                        "column_name": col_name.strip(),
                        "description": des.strip()
                    })
                continue

            try:
                row = next(csv.reader([line]))
            except Exception:
                row = []

            if row:
                col_name = row[0].strip() if len(row) > 0 else ""
                description = row[3].strip() if len(row) > 3 else ""
                if col_name:
                    columns.append({
                        "column_name": col_name,
                        "description": description
                    })
        if not columns:
            continue
        db_schema.append({"table": table_name, "columns": columns})
    return db_schema

def add_semicolon_if_missing(sql_query: str) -> str:
    if not isinstance(sql_query, str) or not sql_query.strip():
        return sql_query
    
    stripped_query = sql_query.rstrip()
    if not stripped_query.endswith(';'):
        return stripped_query + ';'
    return stripped_query


def normalize_sql_query(sql_query: str) -> str:
    if not isinstance(sql_query, str):
        return sql_query

    normalized = sql_query.strip()
    if normalized.startswith("```sql"):
        normalized = normalized[6:].strip()
    elif normalized.startswith("```"):
        normalized = normalized[3:].strip()

    if normalized.endswith("```"):
        normalized = normalized[:-3].strip()

    return normalized
