# ---------------------------------------------------------------------------
# SQL Server -> DWH (origen)
# ---------------------------------------------------------------------------
SQLSERVER = {
    "driver":   "",
    "server":   "",
    "database": "",
    "user":     "",
    "password": "",
}

# ---------------------------------------------------------------------------
# PostgreSQL -> dwh (destino)
# ---------------------------------------------------------------------------
POSTGRES = {
    "host":     "",
    "port":     5432,
    "dbname":   "",
    "user":     "",
    "password": "",
}


# ---------------------------------------------------------------------------
# SAP HANA (SAP Business One) -> origen de stock por bodega
# ---------------------------------------------------------------------------
HANA = {
    "address":  "",
    "port":     4444,
    "user":     "",
    "password": "",
}


def sqlserver_conn_str(cfg=SQLSERVER):
    """Cadena de conexión ODBC para pyodbc."""
    return (
        f"DRIVER={{{cfg['driver']}}};"
        f"SERVER={cfg['server']};"
        f"DATABASE={cfg['database']};"
        f"UID={cfg['user']};PWD={cfg['password']};"
    )
