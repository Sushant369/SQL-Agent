import csv
import re
import sqlite3
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from zipfile import ZipFile
import xml.etree.ElementTree as ET


MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
ODOC_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

WORKBOOK_PATH = Path("data/pgim_property_finance_dummy_data.xlsx")
DB_NAME = "pgim_property_finance"
OUTPUT_DIR = Path("MINIDEV/dev_databases") / DB_NAME
OUTPUT_DB = OUTPUT_DIR / f"{DB_NAME}.sqlite"
DESCRIPTION_DIR = OUTPUT_DIR / "database_description"


@dataclass
class CellValue:
    value: object
    is_date: bool = False


def excel_serial_to_date(serial_value):
    serial_int = int(float(serial_value))
    base_date = date(1899, 12, 30)
    return (base_date + timedelta(days=serial_int)).isoformat()


def column_index(column_ref):
    total = 0
    for char in column_ref:
        if char.isalpha():
            total = total * 26 + (ord(char.upper()) - 64)
    return total - 1


def load_workbook_structure(xlsx_path):
    with ZipFile(xlsx_path) as archive:
        shared_strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            shared_root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            for string_item in shared_root.findall(f"{{{MAIN_NS}}}si"):
                parts = []
                for text_node in string_item.iter(f"{{{MAIN_NS}}}t"):
                    parts.append(text_node.text or "")
                shared_strings.append("".join(parts))

        styles_root = ET.fromstring(archive.read("xl/styles.xml"))
        cell_xfs = styles_root.find(f"{{{MAIN_NS}}}cellXfs")
        date_style_ids = set()
        builtin_date_formats = {
            14, 15, 16, 17, 18, 19, 20, 21, 22, 45, 46, 47,
        }
        for idx, xf in enumerate(cell_xfs.findall(f"{{{MAIN_NS}}}xf")):
            num_fmt_id = int(xf.attrib.get("numFmtId", "0"))
            if num_fmt_id in builtin_date_formats:
                date_style_ids.add(idx)

        workbook_root = ET.fromstring(archive.read("xl/workbook.xml"))
        rels_root = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        rel_map = {
            relation.attrib["Id"]: relation.attrib["Target"].lstrip("/")
            for relation in rels_root.findall(f"{{{REL_NS}}}Relationship")
        }

        workbook = []
        for sheet in workbook_root.find(f"{{{MAIN_NS}}}sheets"):
            rel_id = sheet.attrib[f"{{{ODOC_REL_NS}}}id"]
            workbook.append(
                {
                    "name": sheet.attrib["name"],
                    "target": rel_map[rel_id],
                }
            )

        parsed_sheets = []
        for sheet in workbook:
            sheet_root = ET.fromstring(archive.read(sheet["target"]))
            rows = []
            for row in sheet_root.find(f"{{{MAIN_NS}}}sheetData").findall(
                f"{{{MAIN_NS}}}row"
            ):
                row_map = {}
                for cell in row.findall(f"{{{MAIN_NS}}}c"):
                    ref = cell.attrib.get("r", "")
                    col_ref = re.match(r"([A-Z]+)", ref)
                    idx = column_index(col_ref.group(1)) if col_ref else len(row_map)
                    cell_type = cell.attrib.get("t")
                    style_idx = int(cell.attrib.get("s", "0"))
                    raw_value_node = cell.find(f"{{{MAIN_NS}}}v")

                    if cell_type == "s" and raw_value_node is not None:
                        value = shared_strings[int(raw_value_node.text)]
                        row_map[idx] = CellValue(value=value)
                    elif cell_type == "inlineStr":
                        text_node = cell.find(f"{{{MAIN_NS}}}is/{{{MAIN_NS}}}t")
                        row_map[idx] = CellValue(value=text_node.text if text_node is not None else "")
                    elif raw_value_node is not None:
                        raw_value = raw_value_node.text
                        if style_idx in date_style_ids and raw_value not in (None, ""):
                            row_map[idx] = CellValue(
                                value=excel_serial_to_date(raw_value),
                                is_date=True,
                            )
                        else:
                            row_map[idx] = CellValue(value=raw_value)
                    else:
                        row_map[idx] = CellValue(value="")

                max_idx = max(row_map.keys()) if row_map else -1
                rows.append([row_map.get(i, CellValue("")).value for i in range(max_idx + 1)])

            parsed_sheets.append({"name": sheet["name"], "rows": rows})

        return parsed_sheets


def normalize_name(name):
    normalized = re.sub(r"[^0-9a-zA-Z_]+", "_", str(name).strip())
    normalized = re.sub(r"_+", "_", normalized).strip("_")
    return normalized or "unnamed_column"


def infer_sql_type(values, column_name):
    non_empty = [value for value in values if value not in ("", None)]
    if not non_empty:
        return "TEXT"

    lowered_name = column_name.lower()
    if "date" in lowered_name:
        return "TEXT"
    if lowered_name.endswith("_month") or lowered_name.endswith("_quarter"):
        return "TEXT"
    if any(token in lowered_name for token in ["comment", "uri", "name", "type", "status", "flag", "system", "reference", "memo", "reason", "methodology", "grade", "recommendation"]):
        return "TEXT"
    if lowered_name.endswith("_key") or lowered_name.endswith("_id") or lowered_name.endswith("_masked"):
        return "TEXT"

    integers_only = True
    numerics_only = True
    for value in non_empty:
        text_value = str(value).strip()
        try:
            numeric_value = float(text_value)
            if not numeric_value.is_integer():
                integers_only = False
        except ValueError:
            numerics_only = False
            integers_only = False
            break

    if numerics_only and integers_only:
        return "INTEGER"
    if numerics_only:
        return "REAL"
    return "TEXT"


def convert_value(value, sql_type):
    if value in ("", None):
        return None
    if sql_type == "INTEGER":
        return int(float(value))
    if sql_type == "REAL":
        return float(value)
    return str(value).strip()


def build_column_description(column_name):
    return (
        column_name.replace("_", " ")
        .replace("aum", "AUM")
        .replace("aua", "AUA")
        .replace("nav", "NAV")
        .replace("irr", "IRR")
        .replace("ltv", "LTV")
        .replace("dscr", "DSCR")
        .replace("sqft", "square feet")
        .strip()
        .capitalize()
    )


def build_value_description(column_name, sql_type):
    lowered = column_name.lower()
    if lowered.endswith("_flag"):
        return "Binary-style indicator such as Y or N."
    if "date" in lowered:
        return "Calendar date stored as ISO-8601 text."
    if lowered.endswith("_month"):
        return "Reporting month value."
    if lowered.endswith("_quarter"):
        return "Reporting quarter value."
    if sql_type == "INTEGER":
        return "Whole number measure or count."
    if sql_type == "REAL":
        return "Numeric measure that may include decimals."
    return "Categorical or identifier text value."


def write_description_csv(table_name, columns, column_types, sample_rows):
    output_path = DESCRIPTION_DIR / f"{table_name}.csv"
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "column_name",
                "original_column_name",
                "column_description",
                "value_description",
            ],
        )
        writer.writeheader()
        for idx, column in enumerate(columns):
            samples = []
            for row in sample_rows[:3]:
                if idx < len(row) and row[idx] not in ("", None):
                    samples.append(str(row[idx]))
            value_desc = build_value_description(column, column_types[idx])
            if samples:
                value_desc = f"{value_desc} Example values: {', '.join(samples[:3])}."
            writer.writerow(
                {
                    "column_name": column,
                    "original_column_name": column,
                    "column_description": build_column_description(column),
                    "value_description": value_desc,
                }
            )


def create_sqlite_database(parsed_sheets):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    DESCRIPTION_DIR.mkdir(parents=True, exist_ok=True)
    if OUTPUT_DB.exists():
        OUTPUT_DB.unlink()

    conn = sqlite3.connect(OUTPUT_DB)
    try:
        for sheet in parsed_sheets:
            raw_rows = sheet["rows"]
            if not raw_rows:
                continue

            table_name = normalize_name(sheet["name"])
            headers = [normalize_name(column) for column in raw_rows[0]]
            data_rows = raw_rows[1:]
            column_values = list(zip(*data_rows)) if data_rows else [[] for _ in headers]
            column_types = [
                infer_sql_type(list(values), header)
                for header, values in zip(headers, column_values)
            ]

            pk_column = headers[0] if headers and (
                headers[0].endswith("_key") or headers[0].endswith("_id")
            ) else None

            column_defs = []
            for header, column_type in zip(headers, column_types):
                if header == pk_column:
                    column_defs.append(f'"{header}" TEXT PRIMARY KEY')
                else:
                    column_defs.append(f'"{header}" {column_type}')

            conn.execute(f'DROP TABLE IF EXISTS "{table_name}"')
            conn.execute(f'CREATE TABLE "{table_name}" ({", ".join(column_defs)})')

            placeholders = ", ".join(["?"] * len(headers))
            quoted_headers = ", ".join([f'"{header}"' for header in headers])
            insert_sql = (
                f'INSERT INTO "{table_name}" ({quoted_headers}) '
                f"VALUES ({placeholders})"
            )

            converted_rows = []
            for row in data_rows:
                padded_row = list(row) + [""] * (len(headers) - len(row))
                converted_rows.append(
                    [
                        convert_value(value, column_type)
                        for value, column_type in zip(padded_row, column_types)
                    ]
                )

            conn.executemany(insert_sql, converted_rows)
            write_description_csv(table_name, headers, column_types, converted_rows)

        conn.commit()
    finally:
        conn.close()


def main():
    parsed_sheets = load_workbook_structure(WORKBOOK_PATH)
    create_sqlite_database(parsed_sheets)
    print(f"Created SQLite database at: {OUTPUT_DB}")
    print(f"Created schema description files at: {DESCRIPTION_DIR}")


if __name__ == "__main__":
    main()
