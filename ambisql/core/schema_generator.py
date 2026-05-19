import json
import sqlite3
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock

import pandas as pd


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ARTIFACTS_ROOT = REPO_ROOT / "data" / "schema_artifacts"


class SchemaGenerator:
    VALUE_SAMPLE_LIMIT = 3
    _loaded_schema_cache = {}
    _cache_lock = Lock()

    def __init__(self, db_name, path, question, schema_bundle=None, artifacts_root=None):
        self.db_name = db_name
        self.path = path
        self.question = question
        self.artifacts_root = Path(artifacts_root or DEFAULT_ARTIFACTS_ROOT)

        bundle = schema_bundle or self.load_active_schema(
            db_name=db_name,
            artifacts_root=self.artifacts_root,
        )
        self.formatted_full_schema = bundle["formatted_full_schema"]
        self.formatted_full_schema_json = deepcopy(
            bundle["formatted_full_schema_json"]
        )
        self.schema_version = bundle["schema_version"]
        self.bundle_metadata = bundle

    @classmethod
    def load_active_schema(cls, db_name, artifacts_root=None, force_reload=False):
        artifacts_root = Path(artifacts_root or DEFAULT_ARTIFACTS_ROOT)
        cache_key = (str(artifacts_root.resolve()), db_name)

        if not force_reload:
            with cls._cache_lock:
                cached_bundle = cls._loaded_schema_cache.get(cache_key)
                if cached_bundle is not None:
                    return cached_bundle

        active_version = cls.get_active_version(db_name, artifacts_root=artifacts_root)
        bundle_path = cls.get_bundle_path(
            db_name,
            active_version,
            artifacts_root=artifacts_root,
        )
        if not bundle_path.exists():
            raise FileNotFoundError(
                f"Active schema bundle not found for database '{db_name}': {bundle_path}"
            )

        with open(bundle_path, "r", encoding="utf-8") as bundle_file:
            bundle = json.load(bundle_file)

        cls._validate_bundle(bundle, db_name=db_name, bundle_path=bundle_path)

        with cls._cache_lock:
            cls._loaded_schema_cache[cache_key] = bundle

        return bundle

    @classmethod
    def preload_active_schema(cls, db_name, artifacts_root=None):
        bundle = cls.load_active_schema(
            db_name=db_name,
            artifacts_root=artifacts_root,
            force_reload=True,
        )
        return {
            "db_name": db_name,
            "schema_version": bundle["schema_version"],
            "table_count": bundle.get("table_count"),
            "built_at_utc": bundle.get("built_at_utc"),
        }

    @classmethod
    def build_schema_artifact(
        cls,
        db_name,
        db_path,
        version=None,
        artifacts_root=None,
        activate=False,
    ):
        artifacts_root = Path(artifacts_root or DEFAULT_ARTIFACTS_ROOT)
        version = version or cls.generate_schema_version()
        formatted_full_schema, formatted_full_schema_json, source_metadata = (
            cls._build_schema_from_source(db_name, db_path)
        )

        bundle = {
            "db_name": db_name,
            "schema_version": version,
            "built_at_utc": datetime.now(timezone.utc).isoformat(),
            "formatted_full_schema": formatted_full_schema,
            "formatted_full_schema_json": formatted_full_schema_json,
            "table_count": len(formatted_full_schema_json),
            "value_sample_limit": cls.VALUE_SAMPLE_LIMIT,
            "source_metadata": source_metadata,
        }

        bundle_path = cls.get_bundle_path(
            db_name=db_name,
            version=version,
            artifacts_root=artifacts_root,
        )
        bundle_path.parent.mkdir(parents=True, exist_ok=True)
        with open(bundle_path, "w", encoding="utf-8") as bundle_file:
            json.dump(bundle, bundle_file, ensure_ascii=False, indent=2, default=str)

        if activate:
            cls.set_active_version(
                db_name=db_name,
                version=version,
                artifacts_root=artifacts_root,
            )

        return {
            "db_name": db_name,
            "schema_version": version,
            "bundle_path": str(bundle_path),
            "table_count": len(formatted_full_schema_json),
            "activated": activate,
        }

    @classmethod
    def set_active_version(cls, db_name, version, artifacts_root=None):
        artifacts_root = Path(artifacts_root or DEFAULT_ARTIFACTS_ROOT)
        bundle_path = cls.get_bundle_path(
            db_name=db_name,
            version=version,
            artifacts_root=artifacts_root,
        )
        if not bundle_path.exists():
            raise FileNotFoundError(
                f"Cannot activate missing schema version '{version}' for '{db_name}'."
            )

        active_version_path = cls.get_active_version_path(
            db_name=db_name,
            artifacts_root=artifacts_root,
        )
        active_version_path.parent.mkdir(parents=True, exist_ok=True)
        with open(active_version_path, "w", encoding="utf-8") as active_file:
            active_file.write(version.strip())

        cls.clear_loaded_schema_cache(db_name=db_name, artifacts_root=artifacts_root)

    @classmethod
    def get_active_version(cls, db_name, artifacts_root=None):
        active_version_path = cls.get_active_version_path(
            db_name=db_name,
            artifacts_root=artifacts_root,
        )
        if not active_version_path.exists():
            raise FileNotFoundError(
                f"ACTIVE_VERSION not found for database '{db_name}': {active_version_path}"
            )

        version = active_version_path.read_text(encoding="utf-8").strip()
        if not version:
            raise ValueError(
                f"ACTIVE_VERSION is empty for database '{db_name}': {active_version_path}"
            )
        return version

    @classmethod
    def list_available_versions(cls, db_name, artifacts_root=None):
        artifacts_root = Path(artifacts_root or DEFAULT_ARTIFACTS_ROOT)
        versions_dir = artifacts_root / db_name / "versions"
        if not versions_dir.exists():
            return []
        return sorted(
            version_dir.name
            for version_dir in versions_dir.iterdir()
            if version_dir.is_dir()
        )

    @classmethod
    def clear_loaded_schema_cache(cls, db_name=None, artifacts_root=None):
        artifacts_root = Path(artifacts_root or DEFAULT_ARTIFACTS_ROOT)
        with cls._cache_lock:
            if db_name is None:
                cls._loaded_schema_cache.clear()
                return

            cache_key = (str(artifacts_root.resolve()), db_name)
            cls._loaded_schema_cache.pop(cache_key, None)

    @classmethod
    def get_runtime_cache_metadata(cls, artifacts_root=None):
        artifacts_root = Path(artifacts_root or DEFAULT_ARTIFACTS_ROOT)
        normalized_root = str(artifacts_root.resolve())
        metadata = []
        with cls._cache_lock:
            for (root_path, db_name), bundle in cls._loaded_schema_cache.items():
                if root_path != normalized_root:
                    continue
                metadata.append(
                    {
                        "db_name": db_name,
                        "schema_version": bundle.get("schema_version"),
                        "table_count": bundle.get("table_count"),
                        "built_at_utc": bundle.get("built_at_utc"),
                    }
                )
        return metadata

    @classmethod
    def generate_schema_version(cls):
        return datetime.now(timezone.utc).strftime("v%Y%m%dT%H%M%SZ")

    @classmethod
    def get_db_artifact_dir(cls, db_name, artifacts_root=None):
        artifacts_root = Path(artifacts_root or DEFAULT_ARTIFACTS_ROOT)
        return artifacts_root / db_name

    @classmethod
    def get_active_version_path(cls, db_name, artifacts_root=None):
        return cls.get_db_artifact_dir(db_name, artifacts_root=artifacts_root) / "ACTIVE_VERSION"

    @classmethod
    def get_bundle_path(cls, db_name, version, artifacts_root=None):
        return (
            cls.get_db_artifact_dir(db_name, artifacts_root=artifacts_root)
            / "versions"
            / version
            / "schema_bundle.json"
        )

    @classmethod
    def _validate_bundle(cls, bundle, db_name, bundle_path):
        required_keys = {
            "db_name",
            "schema_version",
            "formatted_full_schema",
            "formatted_full_schema_json",
        }
        missing_keys = sorted(required_keys - set(bundle.keys()))
        if missing_keys:
            raise ValueError(
                f"Schema bundle is missing required keys {missing_keys}: {bundle_path}"
            )

        if bundle["db_name"] != db_name:
            raise ValueError(
                f"Schema bundle DB mismatch. Expected '{db_name}', got '{bundle['db_name']}'."
            )

        if not isinstance(bundle["formatted_full_schema_json"], dict):
            raise ValueError(
                f"Schema bundle formatted_full_schema_json must be a dict: {bundle_path}"
            )

    @classmethod
    def _build_schema_from_source(cls, db_name, db_path):
        db_root = Path(db_path) / db_name
        sqlite_path = db_root / f"{db_name}.sqlite"
        description_dir = db_root / "database_description"
        schema_csv_path = db_root / "schema.csv"

        if not sqlite_path.exists():
            raise FileNotFoundError(f"Database file not found: {sqlite_path}")
        if not description_dir.exists():
            raise FileNotFoundError(
                f"Database description directory not found: {description_dir}"
            )

        csv_files = sorted(description_dir.glob("*.csv"))
        if not csv_files:
            raise FileNotFoundError(
                f"No schema description CSV files found in: {description_dir}"
            )

        result = (
            f"The following schema from the {db_name} database outlines the table names "
            "and their respective columns. Each column is detailed in this order: "
            "column_name, is_PrimaryKey, data_type, column_description, "
            "value_description, and value_example. \n\n"
        )
        schema_json = {}

        with sqlite3.connect(str(sqlite_path)) as conn:
            cursor = conn.cursor()
            try:
                with open(schema_csv_path, "w", encoding="utf-8") as schema_file:
                    schema_file.write(result)

                    for csv_file in csv_files:
                        table = csv_file.stem
                        schema_file.write(f"\nTable: {table}\n")

                        table_info = pd.read_csv(csv_file)
                        table_info = table_info.drop(columns=["column_name"])
                        table_info = table_info.rename(
                            columns={"original_column_name": "column_name"}
                        )
                        table_info = table_info[
                            ["column_name", "column_description", "value_description"]
                        ]
                        table_info["column_name"] = (
                            table_info["column_name"].astype(str).str.strip()
                        )

                        cursor.execute(f"PRAGMA table_info({table});")
                        columns_info = cursor.fetchall()
                        columns_df = pd.DataFrame(
                            columns_info,
                            columns=[
                                "cid",
                                "name",
                                "type",
                                "notnull",
                                "dflt_value",
                                "pk",
                            ],
                        )
                        columns_df = columns_df[["name", "pk", "type"]]
                        columns_df = columns_df.rename(
                            columns={"name": "column_name", "type": "data_type"}
                        )
                        columns_df["pk"] = columns_df["pk"].apply(
                            lambda value: "Primary Key" if value == 1 else ""
                        )

                        cls.check_merge(
                            set(columns_df["column_name"]),
                            set(table_info["column_name"]),
                        )

                        table_info = pd.merge(
                            columns_df,
                            table_info,
                            on="column_name",
                            how="left",
                        )
                        table_info["value_examples"] = None

                        for column_name in table_info["column_name"]:
                            cursor.execute(
                                f"SELECT DISTINCT [{column_name}] FROM {table} "
                                f"LIMIT {cls.VALUE_SAMPLE_LIMIT};"
                            )
                            distinct_values = [row[0] for row in cursor.fetchall()]
                            table_info.loc[
                                table_info["column_name"] == column_name,
                                "value_examples",
                            ] = str(distinct_values)

                        table_info_str = table_info.to_csv(
                            sep=",",
                            index=False,
                            header=False,
                        )
                        schema_file.write(table_info_str)

                        result += f"\nTable: {table}\n{table_info_str}"
                        schema_json[table] = table_info.set_index("column_name").to_dict(
                            orient="index"
                        )
            finally:
                cursor.close()

        source_metadata = {
            "sqlite_path": str(sqlite_path.resolve()),
            "description_dir": str(description_dir.resolve()),
            "schema_csv_path": str(schema_csv_path.resolve()),
            "description_files": [csv_file.name for csv_file in csv_files],
        }
        return result, schema_json, source_metadata

    @staticmethod
    def check_merge(columns_in_columns_df, columns_in_table_info):
        missing_in_table_info = columns_in_columns_df - columns_in_table_info
        missing_in_columns_df = columns_in_table_info - columns_in_columns_df

        if missing_in_table_info or missing_in_columns_df:
            print("Column mismatch detected:")
            if missing_in_table_info:
                print(f" - Missing in table_info: {sorted(missing_in_table_info)}")
                raise ValueError(
                    "Column mismatch between table_info and columns_df. See printout above."
                )
            if missing_in_columns_df:
                print(
                    "There are redundant columns in database_description:: "
                    f"{sorted(missing_in_columns_df)}"
                )
