import argparse
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from ambisql.core.schema_generator import SchemaGenerator


def build_parser():
    parser = argparse.ArgumentParser(
        description="Build a versioned schema artifact for AmbiSQL."
    )
    parser.add_argument(
        "--db-name",
        default="pgim_property_finance",
        help="Database name to build the artifact for.",
    )
    parser.add_argument(
        "--db-path",
        default=str((REPO_ROOT / "MINIDEV" / "dev_databases").resolve()),
        help="Root directory containing database folders.",
    )
    parser.add_argument(
        "--artifacts-root",
        default=str((REPO_ROOT / "data" / "schema_artifacts").resolve()),
        help="Root directory where schema artifacts are stored.",
    )
    parser.add_argument(
        "--version",
        default=None,
        help="Optional schema version. Defaults to a UTC timestamp version.",
    )
    parser.add_argument(
        "--activate",
        action="store_true",
        help="Promote the built artifact to ACTIVE_VERSION after creation.",
    )
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    result = SchemaGenerator.build_schema_artifact(
        db_name=args.db_name,
        db_path=args.db_path,
        version=args.version,
        artifacts_root=args.artifacts_root,
        activate=args.activate,
    )

    print("Schema artifact build complete")
    print(f"  db_name: {result['db_name']}")
    print(f"  schema_version: {result['schema_version']}")
    print(f"  bundle_path: {result['bundle_path']}")
    print(f"  table_count: {result['table_count']}")
    print(f"  activated: {result['activated']}")


if __name__ == "__main__":
    main()
