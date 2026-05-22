"""
db.py — PostgreSQL connection factory.

RAC DB  → schema: racadm
Pricing DB → schema: prcadm
Payment DB → MySQL (ESBPAYADM01)
"""

import psycopg2
import psycopg2.extras
import mysql.connector
import pymysql
import pymysql.cursors
from auth import load_db_credentials

_RAC_SCHEMA = "racadm"
_PRC_SCHEMA = "prcadm"


def _build_conn(host: str, port: str, dbname: str,
                user: str, password: str, use_kerberos: bool):
    """
    Open a single psycopg2 connection.
    Sets search_path to the given schema so queries don't need schema prefixes.
    """
    params = {
        "host":            host,
        "port":            int(port),
        "dbname":          dbname,
        "user":            user,
        "connect_timeout": 10,
        "sslmode":         "prefer",
    }
    if use_kerberos:
        params["gssencmode"] = "prefer"
    else:
        params["password"] = password

    return psycopg2.connect(**params)


def get_connections():
    """
    Return (rac_conn, prc_conn) psycopg2 connection objects built from
    the saved DB credentials.  Raises RuntimeError with a helpful message
    on connectivity problems.
    """
    creds = load_db_credentials()
    if not creds:
        raise RuntimeError("DB credentials not found. Please log in first.")

    use_kerberos = creds.get("use_kerberos", False)

    rac_conn = None
    try:
        rac_conn = _build_conn(
            creds["rac_host"], creds["rac_port"], creds["rac_dbname"],
            creds["rac_user"], creds.get("rac_password", ""),
            use_kerberos,
        )
        prc_conn = _build_conn(
            creds["prc_host"], creds["prc_port"], creds["prc_dbname"],
            creds["prc_user"], creds.get("prc_password", ""),
            use_kerberos,
        )
    except psycopg2.OperationalError as e:
        if rac_conn:          # close rac if prc failed — prevent connection leak
            rac_conn.close()
        msg = str(e)
        raise RuntimeError(
            f"❌ Cannot connect to the database.\n\n"
            "**Please check:**\n"
            "- VPN is connected (hosts are on the internal network)\n"
            "- Host, port, and database name are correct\n"
            "- Kerberos: you are logged into Windows with your AD account\n\n"
            f"**Original error:** `{msg}`"
        ) from e

    return rac_conn, prc_conn


def execute_query(conn, sql: str, params: dict) -> list[dict]:
    """
    Execute a SELECT query and return results as a list of dicts.
    Uses psycopg2 named-parameter style: %(name)s
    """
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cursor:
        cursor.execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]


def get_config_connection():
    """
    Return a psycopg2 connection to the ConfigDB (schema: configadm).
    Requires dedicated ConfigDB credentials saved via Setup.
    Raises RuntimeError with a helpful message on connectivity problems.
    """
    from auth import load_config_db_credentials
    cfg_creds = load_config_db_credentials()

    if not cfg_creds:
        raise RuntimeError(
            "ConfigDB credentials not found. "
            "Please go to Setup and configure the Config Database connection."
        )

    host = cfg_creds["cfg_host"]
    port = cfg_creds["cfg_port"]
    dbname = cfg_creds["cfg_dbname"]
    user = cfg_creds["cfg_user"]
    password = cfg_creds.get("cfg_password", "")
    use_kerberos = cfg_creds.get("use_kerberos", False)

    try:
        conn = _build_conn(host, port, dbname, user, password, use_kerberos)
        return conn
    except psycopg2.OperationalError as e:
        raise RuntimeError(
            f"❌ Cannot connect to ConfigDB ({host}:{port}/{dbname}).\n"
            f"Check VPN, host/port, and credentials.\n"
            f"Original error: {e}"
        ) from e


def get_payment_connection():
    """
    Return a mysql.connector connection to the Payment DB (MySQL).
    Requires dedicated Payment DB credentials saved via Setup.
    Raises RuntimeError with a helpful message on connectivity problems.
    """
    from auth import load_payment_db_credentials
    pay_creds = load_payment_db_credentials()

    if not pay_creds:
        raise RuntimeError(
            "Payment DB credentials not found. "
            "Please go to Setup and configure the Payment Database connection."
        )

    password = pay_creds.get("pay_password", "")
    # Detect corrupted password (masked bullets stored instead of real password)
    if not password or any(ord(c) > 127 for c in password):
        raise RuntimeError(
            "Payment DB password is missing or corrupted. "
            "Please go to Setup and re-enter your Payment Database password."
        )

    # Try PyMySQL first (handles auth like JDBC/DBeaver)
    try:
        conn = pymysql.connect(
            host=pay_creds["pay_host"],
            port=int(pay_creds.get("pay_port", "3306")),
            user=pay_creds["pay_user"],
            password=password,
            database=pay_creds.get("pay_dbname") or None,
            connect_timeout=10,
            cursorclass=pymysql.cursors.DictCursor,
        )
        return conn
    except pymysql.Error as e:
        pymysql_error = e

    # Fallback: mysql-connector-python with multiple strategies
    connect_args = {
        "host": pay_creds["pay_host"],
        "port": int(pay_creds.get("pay_port", "3306")),
        "user": pay_creds["pay_user"],
        "password": pay_creds.get("pay_password", ""),
        "connect_timeout": 10,
        "use_pure": True,
    }
    if pay_creds.get("pay_dbname"):
        connect_args["database"] = pay_creds["pay_dbname"]

    # Try multiple connection strategies
    last_error = None
    for extra in [
        {"ssl_disabled": False},
        {"auth_plugin": "mysql_native_password", "ssl_disabled": False},
        {"auth_plugin": "mysql_native_password"},
        {"auth_plugin": "caching_sha2_password"},
        {},
    ]:
        try:
            conn = mysql.connector.connect(**connect_args, **extra)
            return conn
        except mysql.connector.Error as e:
            last_error = e
            continue

    raise RuntimeError(
        f"❌ Cannot connect to Payment DB ({pay_creds['pay_host']}:{pay_creds.get('pay_port','3306')}).\n"
        f"Check VPN, host/port, and credentials.\n"
        f"Original error (PyMySQL): {pymysql_error}\n"
        f"Original error (mysql-connector): {last_error}"
    )


def execute_mysql_query(conn, sql: str, params: dict) -> list[dict]:
    """
    Execute a SELECT query on a MySQL connection and return results as a list of dicts.
    Works with both PyMySQL and mysql-connector-python connections.
    Uses %(name)s style parameters.
    """
    if isinstance(conn, pymysql.connections.Connection):
        with conn.cursor(pymysql.cursors.DictCursor) as cursor:
            cursor.execute(sql, params)
            return [dict(row) for row in cursor.fetchall()]
    else:
        cursor = conn.cursor(dictionary=True)
        cursor.execute(sql, params)
        rows = [dict(row) for row in cursor.fetchall()]
        cursor.close()
        return rows
