Place your unpacked database folders here.

Expected structure:

```text
MINIDEV/
  dev_databases/
    <database_name>/
      <database_name>.sqlite
      database_description/
        <table_name>.csv
        <another_table>.csv
```

Example:

```text
MINIDEV/
  dev_databases/
    formula_1/
      formula_1.sqlite
      database_description/
        drivers.csv
        results.csv
        races.csv
```

Notes:
- The backend currently reads from `MINIDEV/dev_databases`.
- `database_description` CSV files are required by `SchemaGenerator`.
- `schema.csv` is generated automatically by the app and does not need to be added manually.
