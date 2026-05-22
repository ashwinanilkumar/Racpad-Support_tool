"""
auth.py — Secure credential storage using the OS keyring (Windows Credential Manager).

Credentials are stored per service key so they persist across sessions.
On first login the user fills in the form; afterwards they are loaded silently.
"""

import keyring
import json
from typing import Optional

# ── Service keys (shown in Windows Credential Manager) ────────────────────────
_EMAIL_SERVICE  = "racpad_email"
_DB_SERVICE     = "racpad_db"
_CONFIG_DB_SERVICE = "racpad_config_db"
_PAYMENT_DB_SERVICE = "racpad_payment_db"
_CRED_USERNAME  = "racpad_user"   # fixed username key used for all entries


# ──────────────────────────────────────────────────────────────────────────────
# Email credentials  (SMTP_USER + SMTP_PASSWORD)
# ──────────────────────────────────────────────────────────────────────────────

def save_email_credentials(smtp_user: str, smtp_password: str) -> None:
    """Persist email credentials to the OS keyring."""
    payload = json.dumps({"smtp_user": smtp_user, "smtp_password": smtp_password})
    keyring.set_password(_EMAIL_SERVICE, _CRED_USERNAME, payload)


def load_email_credentials() -> Optional[dict]:
    """
    Return {"smtp_user": ..., "smtp_password": ...} if saved, else None.
    """
    raw = keyring.get_password(_EMAIL_SERVICE, _CRED_USERNAME)
    if raw:
        return json.loads(raw)
    return None


def clear_email_credentials() -> None:
    """Remove saved email credentials (logout)."""
    try:
        keyring.delete_password(_EMAIL_SERVICE, _CRED_USERNAME)
    except keyring.errors.PasswordDeleteError:
        pass


# ──────────────────────────────────────────────────────────────────────────────
# DB credentials  (RAC DB + Pricing DB)
# ──────────────────────────────────────────────────────────────────────────────

def save_db_credentials(
    rac_host: str, rac_port: str, rac_dbname: str, rac_user: str, rac_password: str,
    prc_host: str, prc_port: str, prc_dbname: str, prc_user: str, prc_password: str,
    use_kerberos: bool = False,
) -> None:
    """Persist both PostgreSQL DB connection details to the OS keyring.
    Schemas are fixed: racadm for RAC DB, prcadm for Pricing DB.
    """
    payload = json.dumps({
        "rac_host": rac_host, "rac_port": rac_port,
        "rac_dbname": rac_dbname, "rac_user": rac_user, "rac_password": rac_password,
        "prc_host": prc_host, "prc_port": prc_port,
        "prc_dbname": prc_dbname, "prc_user": prc_user, "prc_password": prc_password,
        "use_kerberos": use_kerberos,
    })
    keyring.set_password(_DB_SERVICE, _CRED_USERNAME, payload)


def load_db_credentials() -> Optional[dict]:
    """
    Return the DB credential dict if saved, else None.
    Keys: rac_host, rac_port, rac_dbname, rac_user, rac_password,
          prc_host, prc_port, prc_dbname, prc_user, prc_password,
          use_kerberos
    """
    raw = keyring.get_password(_DB_SERVICE, _CRED_USERNAME)
    if raw:
        return json.loads(raw)
    return None


def clear_db_credentials() -> None:
    """Remove saved DB credentials (logout)."""
    try:
        keyring.delete_password(_DB_SERVICE, _CRED_USERNAME)
    except keyring.errors.PasswordDeleteError:
        pass


# ──────────────────────────────────────────────────────────────────────────────
# Config DB credentials  (ConfigDB — schema: configadm)
# ──────────────────────────────────────────────────────────────────────────────

def save_config_db_credentials(
    cfg_host: str, cfg_port: str, cfg_dbname: str,
    cfg_user: str, cfg_password: str,
    use_kerberos: bool = False,
) -> None:
    """Persist ConfigDB connection details to the OS keyring."""
    payload = json.dumps({
        "cfg_host": cfg_host, "cfg_port": cfg_port,
        "cfg_dbname": cfg_dbname, "cfg_user": cfg_user,
        "cfg_password": cfg_password,
        "use_kerberos": use_kerberos,
    })
    keyring.set_password(_CONFIG_DB_SERVICE, _CRED_USERNAME, payload)


def load_config_db_credentials() -> Optional[dict]:
    """Return ConfigDB credential dict if saved, else None."""
    raw = keyring.get_password(_CONFIG_DB_SERVICE, _CRED_USERNAME)
    if raw:
        return json.loads(raw)
    return None


def clear_config_db_credentials() -> None:
    """Remove saved ConfigDB credentials."""
    try:
        keyring.delete_password(_CONFIG_DB_SERVICE, _CRED_USERNAME)
    except keyring.errors.PasswordDeleteError:
        pass


# ──────────────────────────────────────────────────────────────────────────────
# Payment DB credentials  (MySQL — schema: ESBPAYADM01)
# ──────────────────────────────────────────────────────────────────────────────

def save_payment_db_credentials(
    pay_host: str, pay_port: str, pay_dbname: str,
    pay_user: str, pay_password: str,
) -> None:
    """Persist Payment DB (MySQL) connection details to the OS keyring."""
    payload = json.dumps({
        "pay_host": pay_host, "pay_port": pay_port,
        "pay_dbname": pay_dbname, "pay_user": pay_user,
        "pay_password": pay_password,
    })
    keyring.set_password(_PAYMENT_DB_SERVICE, _CRED_USERNAME, payload)


def load_payment_db_credentials() -> Optional[dict]:
    """Return Payment DB credential dict if saved, else None."""
    raw = keyring.get_password(_PAYMENT_DB_SERVICE, _CRED_USERNAME)
    if raw:
        return json.loads(raw)
    return None


def clear_payment_db_credentials() -> None:
    """Remove saved Payment DB credentials."""
    try:
        keyring.delete_password(_PAYMENT_DB_SERVICE, _CRED_USERNAME)
    except keyring.errors.PasswordDeleteError:
        pass


# ──────────────────────────────────────────────────────────────────────────────
# Convenience helpers
# ──────────────────────────────────────────────────────────────────────────────

def is_fully_configured() -> bool:
    """True when both email AND DB credentials are already saved."""
    return load_email_credentials() is not None and load_db_credentials() is not None


def clear_all_credentials() -> None:
    """Wipe everything — used by the 'Logout / Reset' button."""
    clear_email_credentials()
    clear_db_credentials()
    clear_config_db_credentials()
    clear_payment_db_credentials()
