"""
flask_app.py — Flask entry point for the Racpad Support Tool.
Replaces the Streamlit UI with a proper HTML/CSS/JS frontend.
All business logic (auth.py, db.py, email_sender.py, diagnostics.py) is unchanged.
"""

from flask import Flask, render_template, request, jsonify
import os
import re
import socket
import json
import traceback

import auth
from db import get_connections, execute_query, get_config_connection, get_payment_connection, execute_mysql_query
from email_sender import (
    process_po_pricing_result,
    send_pricing_notification_email,
    PRICING_TEAM_RECIPIENTS,
    SMTP_HOST,
    SMTP_PORT,
    send_po622_receive_error_email,
)
from diagnostics import PO622Diagnostic

app = Flask(__name__)
app.secret_key = os.urandom(24)
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0  # Disable static file caching in dev

# ── Helpers ───────────────────────────────────────────────────────────────────

def _apply_email_env(creds: dict):
    os.environ["SMTP_USER"]     = creds["smtp_user"]
    os.environ["SMTP_PASSWORD"] = creds["smtp_password"]


def _clear_email_env():
    os.environ.pop("SMTP_USER",     None)
    os.environ.pop("SMTP_PASSWORD", None)


def _serialize(obj):
    """JSON serialiser that handles datetime / Decimal objects."""
    if hasattr(obj, "isoformat"):
        return obj.isoformat()
    return str(obj)


def _fetch_pricing(rac_conn, prc_conn, po_number: str, store_number: str) -> dict:
    query1 = """
        SELECT DISTINCT
          rim.rms_item_number,
          mmm.manufacturer_model_number AS model_number
        FROM racadm.purchase_order po
        JOIN racadm.purchase_order_detail pod ON po.purchase_order_id = pod.purchase_order_id
        JOIN racadm.rms_item_master rim       ON pod.rms_item_master_id = rim.rms_item_master_id
        LEFT JOIN racadm.manufacturer_model_master mmm
          ON rim.rms_item_master_id = mmm.rms_item_master_id
        WHERE po.purchase_order_number = %(po_number)s
          AND po.ship_to_store         = %(store_number)s
    """
    items = execute_query(rac_conn, query1,
                          {"po_number": po_number, "store_number": store_number})
    if not items:
        return {"error": "PO not found in RAC DB for the given store."}

    rms_item_numbers = [row["rms_item_number"] for row in items]
    model_map        = {row["rms_item_number"]: row["model_number"] for row in items}

    query2 = """
        SELECT
          pp.rms_item_number,
          z.zone_number,
          pp.pricing_type,
          pp.weekly_rate,
          pp.monthly_rate,
          pp.cash_price,
          pp.sac_days
        FROM prcadm.zone_store zs
        JOIN prcadm.zone z ON zs.zone_id = z.zone_id
        JOIN prcadm.product_price pp
          ON pp.zone_id = zs.zone_id
         AND pp.rms_item_number = ANY(%(rms_item_numbers)s)
         AND (pp.end_time IS NULL OR pp.end_time > CURRENT_TIMESTAMP)
        WHERE zs.store_number = %(store_number)s
          AND (zs.end_date IS NULL OR zs.end_date > CURRENT_DATE)
    """
    pricing = execute_query(prc_conn, query2,
                            {"store_number": store_number,
                             "rms_item_numbers": rms_item_numbers})

    pricing_map = {row["rms_item_number"]: row for row in pricing}

    result_items = []
    for item_num in rms_item_numbers:
        if item_num in pricing_map:
            result_items.append({
                "item":         item_num,
                "model_number": model_map[item_num],
                "has_pricing":  True,
                "details":      dict(pricing_map[item_num]),
            })
        else:
            result_items.append({
                "item":         item_num,
                "model_number": model_map[item_num],
                "has_pricing":  False,
                "details":      None,
            })

    return {"po_number": po_number, "store_number": store_number, "items": result_items}


# ── Page ──────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


# ── Status / Credentials ──────────────────────────────────────────────────────

@app.route("/api/status")
def api_status():
    email_creds = auth.load_email_credentials()
    db_creds    = auth.load_db_credentials()
    pay_creds   = auth.load_payment_db_credentials()
    return jsonify({
        "email_configured":   email_creds is not None,
        "db_configured":      db_creds    is not None,
        "email_user":         email_creds["smtp_user"] if email_creds else None,
        "rac_info":           (f"{db_creds['rac_user']}@{db_creds['rac_host']}"
                               f"/{db_creds['rac_dbname']}") if db_creds else None,
        "prc_info":           (f"{db_creds['prc_user']}@{db_creds['prc_host']}"
                               f"/{db_creds['prc_dbname']}") if db_creds else None,
        "config_db_configured": auth.load_config_db_credentials() is not None,
        "payment_db_configured": pay_creds is not None,
        "pricing_recipients": PRICING_TEAM_RECIPIENTS,
        "smtp_host":          SMTP_HOST,
        "smtp_port":          str(SMTP_PORT),
    })


@app.route("/api/credentials/saved", methods=["GET"])
def api_get_saved_creds():
    """Return all saved credentials with passwords masked."""
    result = {}
    email_creds = auth.load_email_credentials()
    if email_creds:
        result["smtp_user"] = email_creds.get("smtp_user", "")
        result["smtp_password"] = "••••••••" if email_creds.get("smtp_password") else ""
    result["smtp_host"] = SMTP_HOST
    result["smtp_port"] = str(SMTP_PORT)
    result["pricing_recipients"] = ", ".join(PRICING_TEAM_RECIPIENTS) if PRICING_TEAM_RECIPIENTS else ""

    db_creds = auth.load_db_credentials()
    if db_creds:
        result["rac_host"] = db_creds.get("rac_host", "")
        result["rac_port"] = db_creds.get("rac_port", "5432")
        result["rac_dbname"] = db_creds.get("rac_dbname", "racdb")
        result["rac_user"] = db_creds.get("rac_user", "")
        result["rac_password"] = "••••••••" if db_creds.get("rac_password") else ""
        result["prc_host"] = db_creds.get("prc_host", "")
        result["prc_port"] = db_creds.get("prc_port", "5432")
        result["prc_dbname"] = db_creds.get("prc_dbname", "prcdb")
        result["prc_user"] = db_creds.get("prc_user", "")
        result["prc_password"] = "••••••••" if db_creds.get("prc_password") else ""

    cfg_creds = auth.load_config_db_credentials()
    if cfg_creds:
        result["cfg_host"] = cfg_creds.get("cfg_host", "")
        result["cfg_port"] = cfg_creds.get("cfg_port", "5432")
        result["cfg_dbname"] = cfg_creds.get("cfg_dbname", "configdb")
        result["cfg_user"] = cfg_creds.get("cfg_user", "")
        result["cfg_password"] = "••••••••" if cfg_creds.get("cfg_password") else ""

    pay_creds = auth.load_payment_db_credentials()
    if pay_creds:
        result["pay_host"] = pay_creds.get("pay_host", "")
        result["pay_port"] = pay_creds.get("pay_port", "3306")
        result["pay_dbname"] = pay_creds.get("pay_dbname", "")
        result["pay_user"] = pay_creds.get("pay_user", "")
        result["pay_password"] = "••••••••" if pay_creds.get("pay_password") else ""

    return jsonify(result)


# ── Setup ─────────────────────────────────────────────────────────────────────

@app.route("/api/setup/email", methods=["POST"])
def api_setup_email():
    data         = request.json or {}
    smtp_user    = data.get("smtp_user", "").strip()
    smtp_password = data.get("smtp_password", "").strip()
    smtp_host    = data.get("smtp_host", "smtp.office365.com").strip()
    smtp_port    = data.get("smtp_port", "587").strip()
    pricing_rec  = data.get("pricing_recipients", "").strip()

    if not smtp_user or not smtp_password:
        return jsonify({"error": "Email and password are required."}), 400

    auth.save_email_credentials(smtp_user, smtp_password)
    os.environ["SMTP_HOST"] = smtp_host
    os.environ["SMTP_PORT"] = smtp_port
    if pricing_rec:
        os.environ["PRICING_TEAM_RECIPIENTS"] = pricing_rec

    return jsonify({"success": True, "message": "Email credentials saved!"})


@app.route("/api/setup/db", methods=["POST"])
def api_setup_db():
    data     = request.json or {}
    rac_user = data.get("rac_user", "").strip()
    prc_user = data.get("prc_user", "").strip()
    cfg_user = data.get("cfg_user", "").strip()

    if not rac_user or not prc_user:
        return jsonify({"error": "RAC and Pricing DB usernames are required."}), 400

    auth.save_db_credentials(
        data.get("rac_host",    ""),
        data.get("rac_port",    "5432"),
        data.get("rac_dbname",  "racdb"),
        rac_user,
        data.get("rac_password", ""),
        data.get("prc_host",    ""),
        data.get("prc_port",    "5432"),
        data.get("prc_dbname",  "prcdb"),
        prc_user,
        data.get("prc_password", ""),
        use_kerberos=data.get("use_kerberos", True),
    )

    # Save ConfigDB credentials if provided
    if cfg_user:
        auth.save_config_db_credentials(
            data.get("cfg_host",    ""),
            data.get("cfg_port",    "5432"),
            data.get("cfg_dbname",  "configdb"),
            cfg_user,
            data.get("cfg_password", ""),
            use_kerberos=data.get("use_kerberos", True),
        )

    # Save Payment DB (MySQL) credentials if provided
    pay_user = data.get("pay_user", "").strip()
    if pay_user:
        pay_password = data.get("pay_password", "")
        # If masked or empty, keep existing password
        if not pay_password or "••••" in pay_password:
            existing = auth.load_payment_db_credentials()
            pay_password = existing.get("pay_password", "") if existing else ""
        auth.save_payment_db_credentials(
            data.get("pay_host", ""),
            data.get("pay_port", "3306"),
            data.get("pay_dbname", ""),
            pay_user,
            pay_password,
        )

    return jsonify({"success": True, "message": "DB credentials saved!"})


@app.route("/api/credentials", methods=["DELETE"])
def api_clear_credentials():
    auth.clear_all_credentials()
    return jsonify({"success": True, "message": "Credentials cleared."})


# ── Pricing Alert ─────────────────────────────────────────────────────────────

@app.route("/api/pricing/fetch", methods=["POST"])
def api_pricing_fetch():
    data         = request.json or {}
    po_number    = (data.get("po_number")    or "").strip()
    store_number = (data.get("store_number") or "").strip()

    if not po_number or not store_number:
        return jsonify({"error": "Both PO Number and Store Number are required."}), 400
    if not re.match(r"^\d{1,12}$", po_number):
        return jsonify({"error": "PO Number must be numeric (up to 12 digits)."}), 400
    if not re.match(r"^\d{1,10}$", store_number):
        return jsonify({"error": "Store Number must be numeric (up to 10 digits)."}), 400

    try:
        rac_conn, prc_conn = get_connections()
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 503
    except Exception as e:
        return jsonify({"error": f"Unexpected connection error: {e}"}), 503

    try:
        result = _fetch_pricing(rac_conn, prc_conn, po_number, store_number)
    except Exception as e:
        return jsonify({"error": f"Query failed: {e}"}), 500
    finally:
        rac_conn.close()
        prc_conn.close()

    if "error" in result:
        return jsonify(result), 404

    return jsonify(json.loads(json.dumps(result, default=_serialize)))


@app.route("/api/pricing/send-alert", methods=["POST"])
def api_pricing_send_alert():
    data   = request.json or {}
    result = data.get("result")

    if not result:
        return jsonify({"error": "No pricing result provided."}), 400

    email_creds = auth.load_email_credentials()
    if not email_creds:
        return jsonify({"error": "No email credentials found. Please complete setup."}), 400

    if not email_creds.get("smtp_user") or not email_creds.get("smtp_password"):
        return jsonify({"error": "SMTP username or password is empty."}), 400

    recipients = [r for r in PRICING_TEAM_RECIPIENTS if r.strip()]
    if not recipients:
        return jsonify({"error": "No recipients configured. Set PRICING_TEAM_RECIPIENTS in .env."}), 400

    try:
        _apply_email_env(email_creds)
        process_po_pricing_result(result)
        unpriced_count = len([i for i in result.get("items", []) if not i.get("has_pricing")])
        return jsonify({
            "success": True,
            "message": f"Pricing alert(s) sent for {unpriced_count} item(s) to: {', '.join(recipients)}",
        })
    except Exception as e:
        return jsonify({"error": f"Failed to send email: {e}",
                        "traceback": traceback.format_exc()}), 500
    finally:
        _clear_email_env()


@app.route("/api/pricing/send-email", methods=["POST"])
def api_pricing_send_email():
    data                 = request.json or {}
    po_number            = data.get("po_number",            "")
    store_number         = data.get("store_number",         "")
    recipient_email      = data.get("recipient_email",      "").strip()
    recipient_name       = data.get("recipient_name",       "").strip()
    email_body           = data.get("email_body",           "").strip()
    model_lines          = data.get("model_lines",          "").strip()
    cc_raw               = data.get("cc",                   "").strip()
    incident_number      = data.get("incident_number",      "").strip()
    incident_description = data.get("incident_description", "").strip()

    if not recipient_email or "@" not in recipient_email:
        return jsonify({"error": "Please enter a valid recipient email address."}), 400

    cc_list = [c.strip() for c in cc_raw.split(",") if c.strip()] if cc_raw else []

    if incident_number:
        subject = f"Regarding {incident_number} - {incident_description}" if incident_description else f"Regarding {incident_number}"
    else:
        subject = f"Pricing Alert — PO {po_number} | Store {store_number}"

    email_creds = auth.load_email_credentials()
    if not email_creds:
        return jsonify({"error": "No email credentials configured."}), 400

    try:
        _apply_email_env(email_creds)
        ok = send_pricing_notification_email(
            po_number=po_number,
            store_number=store_number,
            model_lines=model_lines,
            recipient_email=recipient_email,
            recipient_name=recipient_name,
            email_body=email_body,
            subject=subject,
            cc_list=cc_list,
        )
        if ok:
            msg = f"Email sent to {recipient_email}"
            if cc_list:
                msg += f" (CC: {', '.join(cc_list)})"
            return jsonify({"success": True, "message": msg})
        return jsonify({"error": "Failed to send email. Check SMTP credentials."}), 500
    except Exception as e:
        return jsonify({"error": f"Email error: {e}"}), 500
    finally:
        _clear_email_env()


# ── PO622 Diagnostic ──────────────────────────────────────────────────────────

@app.route("/api/po622/diagnose", methods=["POST"])
def api_po622_diagnose():
    data         = request.json or {}
    po_number    = (data.get("po_number")    or "").strip()
    store_number = (data.get("store_number") or "").strip()

    if not po_number or not store_number:
        return jsonify({"error": "Both PO Number and Store Number are required."}), 400

    try:
        rac_conn, prc_conn = get_connections()
        prc_conn.close()
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 503
    except Exception as e:
        return jsonify({"error": f"Connection error: {e}"}), 503

    try:
        diag   = PO622Diagnostic(rac_conn)
        result = diag.run(po_number, store_number)
    except Exception as e:
        return jsonify({"error": f"Diagnostic query failed: {e}",
                        "traceback": traceback.format_exc()}), 500
    finally:
        rac_conn.close()

    return jsonify(json.loads(json.dumps(result, default=_serialize)))


@app.route("/api/po622/send-email", methods=["POST"])
def api_po622_send_email():
    data                 = request.json or {}
    po_number            = data.get("po_number",            "")
    store_number         = data.get("store_number",         "")
    recipient_email      = data.get("recipient_email",      "").strip()
    recipient_name       = data.get("recipient_name",       "").strip()
    email_body           = data.get("email_body",           "").strip()
    model_lines          = data.get("model_lines",          "").strip()
    cc_raw               = data.get("cc",                   "").strip()
    incident_number      = data.get("incident_number",      "").strip()
    incident_description = data.get("incident_description", "").strip()

    if not recipient_email or "@" not in recipient_email:
        return jsonify({"error": "Please enter a valid recipient email address."}), 400
    if not model_lines:
        return jsonify({"error": "Please enter the model number(s)."}), 400

    cc_list = [c.strip() for c in cc_raw.split(",") if c.strip()] if cc_raw else []

    email_creds = auth.load_email_credentials()
    if not email_creds:
        return jsonify({"error": "No email credentials configured."}), 400

    try:
        _apply_email_env(email_creds)
        ok = send_po622_receive_error_email(
            po_number=po_number,
            store_number=store_number,
            model_lines=model_lines,
            recipient_email=recipient_email,
            recipient_name=recipient_name,
            body_override=email_body or None,
            cc_list=cc_list,
            incident_number=incident_number,
            incident_description=incident_description,
        )
        if ok:
            msg = f"Email sent to {recipient_email}"
            if cc_list:
                msg += f" (CC: {', '.join(cc_list)})"
            return jsonify({"success": True, "message": msg})
        return jsonify({"error": "Failed to send email. Check SMTP credentials."}), 500
    except Exception as e:
        return jsonify({"error": f"Email error: {e}"}), 500
    finally:
        _clear_email_env()


# ── Network Diagnostics ───────────────────────────────────────────────────────

@app.route("/api/diagnostics/connectivity", methods=["POST"])
def api_connectivity():
    db_creds = auth.load_db_credentials()
    checks   = []

    try:
        s = socket.create_connection((SMTP_HOST, SMTP_PORT), timeout=5)
        s.close()
        checks.append({"label": f"SMTP  {SMTP_HOST}:{SMTP_PORT}", "ok": True})
    except OSError:
        checks.append({"label": f"SMTP  {SMTP_HOST}:{SMTP_PORT}", "ok": False,
                       "message": "blocked or unreachable (check VPN / firewall)"})

    if db_creds:
        for label, host, port in [
            ("RAC DB",     db_creds["rac_host"], db_creds["rac_port"]),
            ("Pricing DB", db_creds["prc_host"], db_creds["prc_port"]),
        ]:
            try:
                s = socket.create_connection((host, int(port)), timeout=5)
                s.close()
                checks.append({"label": f"{label}  {host}:{port}", "ok": True})
            except OSError:
                checks.append({"label": f"{label}  {host}:{port}", "ok": False,
                               "message": "blocked (check VPN)"})

    # ConfigDB connectivity
    cfg_creds = auth.load_config_db_credentials()
    if cfg_creds:
        cfg_host = cfg_creds.get("cfg_host", "")
        cfg_port = cfg_creds.get("cfg_port", 5432)
        label = f"Config DB  {cfg_host}:{cfg_port}"
        try:
            s = socket.create_connection((cfg_host, int(cfg_port)), timeout=5)
            s.close()
            checks.append({"label": label, "ok": True})
        except OSError:
            checks.append({"label": label, "ok": False,
                           "message": "blocked (check VPN)"})
    else:
        checks.append({"label": "Config DB", "ok": False,
                       "message": "credentials not configured — go to Setup"})

    # Payment DB connectivity
    pay_creds = auth.load_payment_db_credentials()
    if pay_creds:
        pay_host = pay_creds.get("pay_host", "")
        pay_port = pay_creds.get("pay_port", 3306)
        label = f"Payment DB  {pay_host}:{pay_port}"
        try:
            s = socket.create_connection((pay_host, int(pay_port)), timeout=5)
            s.close()
            checks.append({"label": label, "ok": True})
        except OSError:
            checks.append({"label": label, "ok": False,
                           "message": "blocked (check VPN)"})
    else:
        checks.append({"label": "Payment DB", "ok": False,
                       "message": "credentials not configured — go to Setup"})

    return jsonify({"checks": checks})


# ── DB Browser ────────────────────────────────────────────────────────────────

@app.route("/api/db/databases", methods=["POST"])
def api_db_databases():
    data      = request.json or {}
    db_target = data.get("db_target", "rac")
    if not auth.load_db_credentials():
        return jsonify({"error": "No DB credentials saved yet."}), 400
    try:
        rac_conn, prc_conn = get_connections()
        conn        = rac_conn if db_target == "rac" else prc_conn
        close_other = prc_conn if db_target == "rac" else rac_conn
        close_other.close()
        meta = execute_query(conn, "SELECT current_database() AS connected_to", {})
        dbs  = execute_query(conn, """
            SELECT datname AS database_name
            FROM pg_catalog.pg_database
            WHERE datistemplate = false
            ORDER BY datname
        """, {})
        conn.close()
        return jsonify({
            "connected_to": meta[0]["connected_to"],
            "databases":    [r["database_name"] for r in dbs],
        })
    except Exception as e:
        return jsonify({"error": f"Connection failed: {e}"}), 500


@app.route("/api/db/schemas", methods=["POST"])
def api_db_schemas():
    data      = request.json or {}
    db_target = data.get("db_target", "rac")
    if not auth.load_db_credentials():
        return jsonify({"error": "No DB credentials saved yet."}), 400
    try:
        rac_conn, prc_conn = get_connections()
        conn        = rac_conn if db_target == "rac" else prc_conn
        close_other = prc_conn if db_target == "rac" else rac_conn
        close_other.close()
        meta = execute_query(conn, "SELECT current_database() AS db", {})
        rows = execute_query(conn, """
            SELECT n.nspname AS schema, c.relname AS table
            FROM pg_catalog.pg_class c
            JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relkind = 'r'
              AND n.nspname NOT IN ('pg_catalog', 'information_schema', 'pg_toast')
            ORDER BY n.nspname, c.relname
        """, {})
        conn.close()
        schemas = sorted({r["schema"] for r in rows})
        return jsonify({
            "connected_to": meta[0]["db"],
            "schemas":      schemas,
            "tables":       rows,
        })
    except Exception as e:
        return jsonify({"error": f"Connection failed: {e}"}), 500


# ── App Config Triage ─────────────────────────────────────────────────────────

@app.route("/api/appconfig/diagnose", methods=["POST"])
def api_appconfig_diagnose():
    """
    Diagnostic endpoint: connect to ConfigDB and return the actual database name,
    all schemas, and all tables in any schema whose name contains 'config' (case-insensitive).
    Use this to verify the connection is correct and find the real schema/table names.
    """
    try:
        conn = get_config_connection()
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 503

    try:
        db_name = execute_query(conn, "SELECT current_database() AS db, current_user AS usr, version() AS ver", {})
        schemas = execute_query(conn, """
            SELECT nspname AS schema_name
            FROM pg_catalog.pg_namespace
            WHERE nspname NOT IN ('pg_catalog','information_schema','pg_toast')
            ORDER BY nspname
        """, {})
        tables = execute_query(conn, """
            SELECT n.nspname AS schema_name, c.relname AS table_name
            FROM pg_catalog.pg_class c
            JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
            WHERE c.relkind = 'r'
              AND lower(n.nspname) LIKE '%%config%%'
            ORDER BY n.nspname, c.relname
        """, {})
        return jsonify({
            "connection": db_name[0] if db_name else {},
            "all_schemas": [r["schema_name"] for r in schemas],
            "config_tables": tables,
        })
    except Exception as e:
        return jsonify({"error": str(e), "traceback": traceback.format_exc()}), 500
    finally:
        conn.close()


@app.route("/api/appconfig/lookup", methods=["POST"])
def api_appconfig_lookup():
    from queries_config import SCOPE_QUERY_MAP, VALIDATE_RULE_NAME

    data       = request.json or {}
    rule_name  = (data.get("rule_name")  or "").strip()
    scope_type = (data.get("scope_type") or "").strip().upper()
    scope_value = (data.get("scope_value") or "").strip()

    if not rule_name:
        return jsonify({"error": "Rule name is required."}), 400
    if not scope_type:
        return jsonify({"error": "Scope type (hierarchy level) is required."}), 400
    if not scope_value:
        return jsonify({"error": "Scope value is required."}), 400

    # Compound types (COMPANY+STATE, LOB+COUNTRY) are not directly queryable
    if scope_type in ("COMPANY+STATE", "LOB+COUNTRY"):
        return jsonify({
            "error": (
                f"{scope_type} is a compound level only available via the STORE hierarchy lookup. "
                "Please select STORE and enter the store number to see all levels including compound ones."
            )
        }), 400

    if scope_type not in SCOPE_QUERY_MAP:
        return jsonify({"error": f"Unsupported scope type: {scope_type}"}), 400

    try:
        conn = get_config_connection()
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 503

    try:
        # Validate rule name exists
        check = execute_query(conn, VALIDATE_RULE_NAME, {"rule_name": rule_name})
        if not check:
            return jsonify({"error": f"Rule name '{rule_name}' not found in configadm.param_key."}), 404

        query, param_key = SCOPE_QUERY_MAP[scope_type]
        params = {"rule_name": rule_name, param_key: scope_value}
        rows = execute_query(conn, query, params)

        if not rows:
            return jsonify({
                "rows": [],
                "message": f"No config found for rule '{rule_name}' at {scope_type} = '{scope_value}'."
            })

        return jsonify(json.loads(json.dumps({
            "rows": rows,
            "scope_type": scope_type,
            "scope_value": scope_value,
            "rule_name": rule_name,
        }, default=_serialize)))

    except Exception as e:
        return jsonify({"error": f"Query failed: {e}",
                        "traceback": traceback.format_exc()}), 500
    finally:
        conn.close()


@app.route("/api/appconfig/export-csv", methods=["POST"])
def api_appconfig_export_csv():
    """Return CSV text from the provided rows."""
    import csv
    import io

    data = request.json or {}
    rows = data.get("rows", [])
    if not rows:
        return jsonify({"error": "No data to export."}), 400

    cols = [
        "current_value", "previous_value", "param_key_name", "param_group_name",
        "param_category_name", "hierarchy_level", "priority", "is_effective",
        "association_ref_code", "parent_association_ref_code", "active",
        "start_date", "end_date", "created_by", "created_date",
        "last_modified_by", "last_modified_date", "prev_modified_by", "prev_modified_date",
    ]

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)

    from flask import Response
    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=appconfig_export.csv"},
    )


@app.route("/api/appconfig/history", methods=["POST"])
def api_appconfig_history():
    """Return full audit history for a param_config_list_of_value_id."""
    data = request.json or {}
    plov_id = data.get("param_config_list_of_value_id")
    if not plov_id:
        return jsonify({"error": "param_config_list_of_value_id is required."}), 400

    HISTORY_SQL = """
        SELECT
            param_value,
            active,
            last_modified_by,
            last_modified_date,
            created_by,
            created_date,
            aud_param_config_list_of_value_id
        FROM configadm.aud_param_config_list_of_value
        WHERE param_config_list_of_value_id = %(id)s
        ORDER BY last_modified_date DESC NULLS LAST
    """
    try:
        conn = get_config_connection()
        rows = execute_query(conn, HISTORY_SQL, {"id": plov_id})
        conn.close()

        # Serialize datetime objects
        for row in rows:
            for k, v in row.items():
                if hasattr(v, "isoformat"):
                    row[k] = v.isoformat()

        return jsonify({"history": rows})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


# ── Entry ─────────────────────────────────────────────────────────────────────

# ── Customer Payment ──────────────────────────────────────────────────────────

@app.route("/api/payment/lookup", methods=["POST"])
def api_payment_lookup():
    """Look up payment transactions and declined transactions for a customer."""
    data = request.json or {}
    customer_id = (data.get("customer_id") or "").strip()
    customer_name = (data.get("customer_name") or "").strip()
    card_last4 = (data.get("card_last4") or "").strip()
    transaction_date = (data.get("transaction_date") or "").strip()
    # table_choice: "both" | "transactions" | "declined"
    table_choice = (data.get("table_choice") or "both").strip()

    if not customer_id and not customer_name:
        return jsonify({"error": "Customer ID or Customer Name is required."}), 400

    try:
        conn = get_payment_connection()
    except RuntimeError as e:
        return jsonify({"error": str(e)}), 503

    try:
        # Set a 120-second query execution timeout on the MySQL session
        try:
            execute_mysql_query(conn, "SET SESSION MAX_EXECUTION_TIME=120000", {})
        except Exception:
            pass  # Not all MySQL versions support this — ignore silently
        transactions = []
        declined = []
        search_method = ""

        # Build common optional filters
        extra_where = []
        extra_params = {}
        if card_last4:
            extra_where.append("RIGHT(TRANSACTIONCOMMAND, 4) = %(card_last4)s")
            extra_params["card_last4"] = card_last4
        if transaction_date:
            extra_where.append("DATE(TRANSACTIONDTS) = %(transaction_date)s")
            extra_params["transaction_date"] = transaction_date

        DECLINED_COLS = """
            TRANSACTIONDTS, STATUSMESSAGE, STATUSCODE,
            ACCOUNTLOCATIONNUMBER AS Store, ACCOUNTNUMBER, AMOUNT,
            AUTHORIZATIONNUMBER, CARDTYPE, CREATEDBY, CUSTOMERID, ENTRY_METHOD,
            EXTERNALTRANSACTIONID, FIRSTNAME, GLOBALCUSTOMERID, LASTNAME,
            MERCHANTID, PAYMENTCLIENTID, PAYMENTMETHODID, PAYMENTPLATFORM,
            PAYMENTTYPE, PAYMENT_NETWORK, PINLESS_CONVERTED,
            PINLESS_RESPONSE_CODE, RECORDID, TRANSACTIONCOMMAND, TRANSACTIONID
        """

        # ── Transactions only ────────────────────────────────────────────────
        if table_choice in ("both", "transactions"):
            if customer_id:
                where_clauses = ["CUSTOMERID = %(customer_id)s"] + extra_where
                params = {"customer_id": customer_id, **extra_params}
                payment_sql = f"""
                    SELECT
                      TRANSACTIONDTS, CUSTOMERID,
                      ACCOUNTLOCATIONNUMBER AS Store,
                      PAYMENTCLIENTID, STATUSMESSAGE, AMOUNT,
                      RIGHT(TRANSACTIONCOMMAND, 4) AS CardLast4,
                      MERCHANTID, EXTERNALTRANSACTIONID,
                      PINLESS_CONVERTED, PINLESS_RESPONSE_CODE, TRANSACTIONID
                    FROM ESBPAYADM01.PAYMENTTRANSACTION
                    WHERE {' AND '.join(where_clauses)}
                    ORDER BY TRANSACTIONDTS DESC
                """
                transactions = execute_mysql_query(conn, payment_sql, params)
                search_method = f"Customer ID: {customer_id} — Payment Transactions"

            if not transactions and customer_name:
                # Split name into first/last — supports "First Last" or just one word
                name_parts = customer_name.strip().split()
                firstname = name_parts[0] if len(name_parts) >= 1 else ""
                lastname  = name_parts[1] if len(name_parts) >= 2 else ""

                name_where = []
                name_params = {**extra_params}
                if firstname and lastname:
                    name_where = ["FIRSTNAME = %(firstname)s", "LASTNAME = %(lastname)s"]
                    name_params.update({"firstname": firstname, "lastname": lastname})
                elif firstname:
                    name_where = ["FIRSTNAME = %(firstname)s"]
                    name_params.update({"firstname": firstname})

                where_clauses = name_where + extra_where
                if where_clauses:
                    payment_sql = f"""
                        SELECT
                          TRANSACTIONDTS, CUSTOMERID,
                          ACCOUNTLOCATIONNUMBER AS Store,
                          PAYMENTCLIENTID, STATUSMESSAGE, AMOUNT,
                          RIGHT(TRANSACTIONCOMMAND, 4) AS CardLast4,
                          MERCHANTID, EXTERNALTRANSACTIONID,
                          PINLESS_CONVERTED, PINLESS_RESPONSE_CODE, TRANSACTIONID
                        FROM ESBPAYADM01.PAYMENTTRANSACTION
                        WHERE {' AND '.join(where_clauses)}
                        ORDER BY TRANSACTIONDTS DESC
                    """
                    try:
                        transactions = execute_mysql_query(conn, payment_sql, name_params)
                    except Exception:
                        transactions = []
                search_method = f"Customer Name: {customer_name} — Payment Transactions"

        # ── Declined only ────────────────────────────────────────────────────
        if table_choice == "declined" or (table_choice == "both" and not transactions):
            declined_where = []
            declined_params = {**extra_params}
            if customer_id:
                declined_where.append("CUSTOMERID = %(customer_id)s")
                declined_params["customer_id"] = customer_id
            elif customer_name:
                dec_name_parts = customer_name.strip().split()
                dec_firstname = dec_name_parts[0] if len(dec_name_parts) >= 1 else ""
                dec_lastname  = dec_name_parts[1] if len(dec_name_parts) >= 2 else ""
                if dec_firstname and dec_lastname:
                    declined_where += ["FIRSTNAME = %(dec_firstname)s", "LASTNAME = %(dec_lastname)s"]
                    declined_params.update({"dec_firstname": dec_firstname, "dec_lastname": dec_lastname})
                elif dec_firstname:
                    declined_where.append("FIRSTNAME = %(dec_firstname)s")
                    declined_params["dec_firstname"] = dec_firstname

            if declined_where:
                all_where = declined_where + extra_where
                declined_sql = f"""
                    SELECT {DECLINED_COLS}
                    FROM ESBPAYADM01.PAYMENT_TRANSACTION_DECLINED
                    WHERE {' AND '.join(all_where)}
                """
                declined = execute_mysql_query(conn, declined_sql, declined_params)
                if table_choice == "declined":
                    search_method = f"{'Customer ID: ' + customer_id if customer_id else 'Customer Name: ' + customer_name} — Declined Transactions"
                elif not search_method:
                    search_method = "Declined table lookup (no results in Payment Transactions)"

        # ── Both: also fetch declined when transactions found ────────────────
        elif table_choice == "both" and transactions and customer_id:
            declined_sql = f"""
                SELECT {DECLINED_COLS}
                FROM ESBPAYADM01.PAYMENT_TRANSACTION_DECLINED
                WHERE CUSTOMERID = %(customer_id)s
            """
            declined = execute_mysql_query(conn, declined_sql, {"customer_id": customer_id})

    except Exception as e:
        return jsonify({"error": f"Query failed: {e}"}), 500
    finally:
        conn.close()

    result = {
        "customer_id": customer_id,
        "customer_name": customer_name,
        "search_method": search_method,
        "table_choice": table_choice,
        "transactions": transactions,
        "declined": declined,
    }
    return jsonify(json.loads(json.dumps(result, default=_serialize)))


if __name__ == "__main__":
    app.run(debug=True, port=8501, use_reloader=False)
