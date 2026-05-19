import os
from typing import Any, Dict, List, Optional

try:
    import pyodbc
except ImportError:  # pragma: no cover - dependency may not be installed yet
    pyodbc = None


DEFAULT_FABRIC_DRIVER = "{ODBC Driver 18 for SQL Server}"


def _ensure_pyodbc_available():
    if pyodbc is None:
        raise ImportError(
            "pyodbc is required for Microsoft Fabric database connectivity. "
            "Install it with `pip install pyodbc` and ensure an ODBC SQL Server "
            "driver is installed on the host."
        )


def build_fabric_connection_string(
    data_source: str,
    initial_catalog: Optional[str] = None,
    user_id: Optional[str] = None,
    authentication: str = "ActiveDirectoryInteractive",
    driver: str = DEFAULT_FABRIC_DRIVER,
    pooling: str = "False",
    encrypt: str = "yes",
    trust_server_certificate: str = "no",
    extra_options: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Build an ODBC connection string for a Microsoft Fabric SQL database.

    Example:
    Driver={ODBC Driver 18 for SQL Server};
    Data Source=tcp:<server>.database.fabric.microsoft.com,1433;
    Initial Catalog=<database_name>;
    Authentication=ActiveDirectoryInteractive;
    Pooling=False;
    Encrypt=yes;
    TrustServerCertificate=no;
    """
    parts = [f"Driver={driver}", f"Data Source={data_source}"]

    if initial_catalog:
        parts.append(f"Initial Catalog={initial_catalog}")
    if user_id:
        parts.append(f"User ID={user_id}")

    parts.extend(
        [
            f"Pooling={pooling}",
            f"Authentication={authentication}",
            f"Encrypt={encrypt}",
            f"TrustServerCertificate={trust_server_certificate}",
        ]
    )

    for key, value in (extra_options or {}).items():
        if value is None:
            continue
        parts.append(f"{key}={value}")

    return ";".join(parts) + ";"


def get_fabric_connection_string(
    connection_string: Optional[str] = None,
    data_source: Optional[str] = None,
    initial_catalog: Optional[str] = None,
    user_id: Optional[str] = None,
    authentication: str = "ActiveDirectoryInteractive",
    driver: str = DEFAULT_FABRIC_DRIVER,
) -> str:
    """
    Resolve a Fabric connection string from the explicit argument or environment.

    Supported env vars:
    - FABRIC_CONNECTION_STRING
    - FABRIC_DATA_SOURCE
    - FABRIC_DATABASE
    - FABRIC_USER_ID
    - FABRIC_AUTHENTICATION
    - FABRIC_DRIVER
    """
    if connection_string:
        return connection_string

    env_connection_string = os.getenv("FABRIC_CONNECTION_STRING")
    if env_connection_string:
        return env_connection_string

    resolved_data_source = data_source or os.getenv("FABRIC_DATA_SOURCE")
    resolved_initial_catalog = initial_catalog or os.getenv("FABRIC_DATABASE")
    resolved_user_id = user_id or os.getenv("FABRIC_USER_ID")
    resolved_authentication = (
        os.getenv("FABRIC_AUTHENTICATION") or authentication
    )
    resolved_driver = os.getenv("FABRIC_DRIVER") or driver

    if not resolved_data_source:
        raise ValueError(
            "Fabric connection details are missing. Provide a connection string or "
            "set FABRIC_DATA_SOURCE (and typically FABRIC_DATABASE)."
        )

    return build_fabric_connection_string(
        data_source=resolved_data_source,
        initial_catalog=resolved_initial_catalog,
        user_id=resolved_user_id,
        authentication=resolved_authentication,
        driver=resolved_driver,
    )


def execute_fabric_query(
    sql_query: str,
    connection_string: Optional[str] = None,
    include_columns: bool = False,
    timeout: int = 60,
):
    """
    Execute a SQL query against a Microsoft Fabric SQL database via ODBC.

    This intentionally returns the same shape as the current SQLite helper:
    - rows only when include_columns=False
    - {"columns": [...], "rows": [...]} when include_columns=True
    """
    _ensure_pyodbc_available()

    resolved_connection_string = get_fabric_connection_string(
        connection_string=connection_string
    )
    connection = pyodbc.connect(resolved_connection_string, timeout=timeout)
    cursor = connection.cursor()

    try:
        cursor.execute(sql_query)

        if cursor.description:
            columns = [description[0] for description in cursor.description]
            rows = cursor.fetchall()
        else:
            columns = []
            rows = []

        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        cursor.close()
        connection.close()

    if include_columns:
        return {
            "columns": columns,
            "rows": rows,
        }

    return rows
