#!/usr/bin/env python3
"""
Schema dump utility for AmbiSQL Skill.

Outputs formatted database schema text for injection into LLM prompts.
"""

import sys
import os
from typing import Optional

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../../../..")))

from ambisql.core.schema_generator import SchemaGenerator


DEFAULT_DB_PATH = os.environ.get("AMBISQL_DB_PATH", "MINIDEV/dev_databases")


def dump_schema(db_name: str, db_path: Optional[str] = None) -> str:
    path = db_path or DEFAULT_DB_PATH
    generator = SchemaGenerator(db_name=db_name, path=path, question="")
    return generator.formatted_full_schema


def main():
    if len(sys.argv) < 2:
        print("Schema not available", file=sys.stderr)
        sys.exit(1)

    db_name = sys.argv[1]
    db_path = sys.argv[2] if len(sys.argv) > 2 else None

    try:
        schema = dump_schema(db_name, db_path)
        print(schema)
    except Exception as e:
        print(f"Schema not available: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
