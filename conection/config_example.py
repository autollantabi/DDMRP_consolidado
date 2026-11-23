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


def get_engine_postgres_dwh(schema="core"):
    """Motor SQLAlchemy del DWH, con los datos de POSTGRES (lo usan los export_excel_*.py)."""
    from urllib.parse import quote_plus
    from sqlalchemy import create_engine
    c = POSTGRES
    url = (f"postgresql+psycopg2://{quote_plus(str(c['user']))}:{quote_plus(str(c['password']))}"
           f"@{c['host']}:{c['port']}/{c['dbname']}")
    return create_engine(url, pool_pre_ping=True, connect_args={"options": f"-c search_path={schema}"})
