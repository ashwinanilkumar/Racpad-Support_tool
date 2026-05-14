"""
Email Automation Script
Sends templated emails with dynamic fields like inventory number, store number, etc.
"""

import smtplib
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from dataclasses import dataclass, field
from typing import List, Optional
from string import Template
from dotenv import load_dotenv

load_dotenv()


# ──────────────────────────────────────────────
# Configuration
# ──────────────────────────────────────────────

SMTP_HOST     = os.getenv("SMTP_HOST", "smtp.office365.com")
SMTP_PORT     = int(os.getenv("SMTP_PORT", 587))

# ⚠️  Do NOT cache SMTP_USER / SMTP_PASSWORD at module level.
# Read them lazily at call-time so the app can inject credentials
# at runtime without relying on os.environ being set before import.
def _smtp_user()     -> str: return os.environ.get("SMTP_USER", "")
def _smtp_password() -> str: return os.environ.get("SMTP_PASSWORD", "")

TEAM_RECIPIENTS: List[str] = os.getenv("TEAM_RECIPIENTS", "").split(",")
PRICING_TEAM_RECIPIENTS: List[str] = os.getenv("PRICING_TEAM_RECIPIENTS", "").split(",")


# ──────────────────────────────────────────────
# Email Template
# ──────────────────────────────────────────────

EMAIL_SUBJECT_TEMPLATE = Template(
    "Alert: Inventory Issue — Store #$store_number | Inventory #$inventory_number"
)

EMAIL_BODY_TEMPLATE = Template(
    """
Hi Team,

This is an automated notification regarding the following item:

  • Store Number    : $store_number
  • Inventory Number: $inventory_number
  • Item Description: $item_description
  • Status          : $status
  • Reported At     : $reported_at

$additional_notes

Please take the necessary action as soon as possible.

Regards,
Automated Notification System
"""
)

# ──────────────────────────────────────────────
# Pricing Alert Email Template
# ──────────────────────────────────────────────

PRICING_ALERT_SUBJECT_TEMPLATE = Template(
    "Pricing Not Found — PO: $po_number | RMS Item: $rms_item_number | Store: $store_number"
)

PRICING_ALERT_BODY_TEMPLATE = Template(
    """Hi @Pricing,

Regarding PO: $po_number, the CW is currently unable to receive the RMS item $rms_item_number and is encountering the following error message:

    Unable to receive purchase order. Please try again later.
    Outbound Message: Pricing details not found for the rms item id $rms_item_number

PO           : $po_number
RMSItemNumber: $rms_item_number
Model        : $model_number
Store        : $store_number

Regards,
Racpad Support Team
"""
)


# ──────────────────────────────────────────────
# PO622 Receive Error Email Template
# ──────────────────────────────────────────────

PO622_RECEIVE_ERROR_SUBJECT = Template(
    "Unable to Receive PO $po_number — Store $store_number"
)

PO622_RECEIVE_ERROR_BODY = Template(
    """Hi $recipient_name,

The store $store_number is trying to receive PO $po_number but they are getting the below error:

    "Received count exceeds quantity ordered"

$model_lines

The store would now like to receive this item. Could you please advise on the appropriate next steps.

Regards,
Racpad Support Team
"""
)


def send_po622_receive_error_email(
    po_number: str,
    store_number: str,
    model_lines: str,
    recipient_email: str,
    recipient_name: str,
    body_override: str | None = None,
    cc_list: Optional[List[str]] = None,
    incident_number: str = "",
    incident_description: str = "",
) -> bool:
    """Send the 'Unable to Receive PO' email to the specified recipient."""
    if incident_number:
        subject = f"Regarding {incident_number} - {incident_description}" if incident_description else f"Regarding {incident_number}"
    else:
        subject = PO622_RECEIVE_ERROR_SUBJECT.substitute(
            po_number=po_number,
            store_number=store_number,
        )
    body = body_override or PO622_RECEIVE_ERROR_BODY.substitute(
        recipient_name=recipient_name,
        store_number=store_number,
        po_number=po_number,
        model_lines=model_lines,
    )

    cc = [c.strip() for c in (cc_list or []) if c.strip()]
    all_recipients = [recipient_email] + cc

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = _smtp_user()
    msg["To"]      = recipient_email
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(_smtp_user(), _smtp_password())
            server.sendmail(_smtp_user(), all_recipients, msg.as_string())
        return True
    except Exception as e:
        print(f"[email_sender] send_po622_receive_error_email failed: {e}")
        return False


def send_pricing_notification_email(
    po_number: str,
    store_number: str,
    model_lines: str,
    recipient_email: str,
    recipient_name: str,
    email_body: str,
    subject: str,
    cc_list: Optional[List[str]] = None,
) -> bool:
    """Send a custom pricing notification email to the specified recipient."""
    cc = [c.strip() for c in (cc_list or []) if c.strip()]
    all_recipients = [recipient_email] + cc

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = _smtp_user()
    msg["To"]      = recipient_email
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg.attach(MIMEText(email_body, "plain"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(_smtp_user(), _smtp_password())
            server.sendmail(_smtp_user(), all_recipients, msg.as_string())
        return True
    except Exception as e:
        print(f"[email_sender] send_pricing_notification_email failed: {e}")
        return False



@dataclass
class EmailPayload:
    store_number: str
    inventory_number: str
    item_description: str
    status: str
    reported_at: str
    additional_notes: str = ""
    recipients: List[str] = field(default_factory=list)   # override per-email; falls back to TEAM_RECIPIENTS
    cc: Optional[List[str]] = None
    bcc: Optional[List[str]] = None


@dataclass
class PricingAlertPayload:
    po_number: str
    rms_item_number: str
    model_number: str
    store_number: str
    recipients: List[str] = field(default_factory=list)   # falls back to PRICING_TEAM_RECIPIENTS
    cc: Optional[List[str]] = None


# ──────────────────────────────────────────────
# Core Functions
# ──────────────────────────────────────────────

def build_message(payload: EmailPayload) -> MIMEMultipart:
    """Construct the MIME email from the payload."""
    msg = MIMEMultipart("alternative")

    substitutions = {
        "store_number":     payload.store_number,
        "inventory_number": payload.inventory_number,
        "item_description": payload.item_description,
        "status":           payload.status,
        "reported_at":      payload.reported_at,
        "additional_notes": payload.additional_notes,
    }

    subject = EMAIL_SUBJECT_TEMPLATE.safe_substitute(substitutions)
    body    = EMAIL_BODY_TEMPLATE.safe_substitute(substitutions)

    to_list  = payload.recipients if payload.recipients else TEAM_RECIPIENTS
    cc_list  = payload.cc  or []
    bcc_list = payload.bcc or []

    msg["Subject"] = subject
    msg["From"]    = _smtp_user()
    msg["To"]      = ", ".join(to_list)
    if cc_list:
        msg["Cc"]  = ", ".join(cc_list)

    msg.attach(MIMEText(body, "plain"))

    # Optional: add an HTML version of the body
    html_body = body.replace("\n", "<br>")
    msg.attach(MIMEText(f"<pre style='font-family:sans-serif'>{html_body}</pre>", "html"))

    return msg, to_list + cc_list + bcc_list   # all recipients for sendmail


def send_email(payload: EmailPayload) -> bool:
    """
    Build and send a single email.
    Returns True on success, False on failure.
    """
    user, pwd = _smtp_user(), _smtp_password()
    if not user or not pwd:
        raise EnvironmentError(
            "SMTP_USER and SMTP_PASSWORD must be set in the environment or .env file."
        )

    msg, all_recipients = build_message(payload)

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(user, pwd)
            server.sendmail(user, all_recipients, msg.as_string())
        print(f"[OK] Email sent → {all_recipients} | Store: {payload.store_number} | Inv: {payload.inventory_number}")
        return True
    except smtplib.SMTPException as exc:
        print(f"[ERROR] Failed to send email: {exc}")
        return False


def send_bulk_emails(payloads: List[EmailPayload]) -> None:
    """
    Send emails for a list of payloads in a single SMTP session.
    """
    user, pwd = _smtp_user(), _smtp_password()
    if not user or not pwd:
        raise EnvironmentError(
            "SMTP_USER and SMTP_PASSWORD must be set in the environment or .env file."
        )

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.ehlo()
        server.starttls()
        server.login(user, pwd)

        for payload in payloads:
            msg, all_recipients = build_message(payload)
            try:
                server.sendmail(user, all_recipients, msg.as_string())
                print(f"[OK] Store: {payload.store_number} | Inv: {payload.inventory_number}")
            except smtplib.SMTPException as exc:
                print(f"[ERROR] Store: {payload.store_number} | {exc}")


# ──────────────────────────────────────────────
# Pricing Alert Functions
# ──────────────────────────────────────────────

def send_pricing_alert(payload: PricingAlertPayload) -> bool:
    """
    Send a pricing-not-found alert email for a single RMS item.
    Returns True on success, False on failure.
    """
    user, pwd = _smtp_user(), _smtp_password()
    if not user or not pwd:
        raise EnvironmentError(
            "SMTP_USER and SMTP_PASSWORD must be set in the environment or .env file."
        )

    substitutions = {
        "po_number":       str(payload.po_number),
        "rms_item_number": str(payload.rms_item_number),
        "model_number":    payload.model_number or "N/A",
        "store_number":    str(payload.store_number),
    }

    msg = MIMEMultipart("alternative")
    msg["Subject"] = PRICING_ALERT_SUBJECT_TEMPLATE.safe_substitute(substitutions)
    msg["From"]    = user

    to_list = payload.recipients if payload.recipients else PRICING_TEAM_RECIPIENTS
    cc_list = payload.cc or []

    msg["To"] = ", ".join(to_list)
    if cc_list:
        msg["Cc"] = ", ".join(cc_list)

    body = PRICING_ALERT_BODY_TEMPLATE.safe_substitute(substitutions)
    msg.attach(MIMEText(body, "plain"))
    msg.attach(MIMEText(f"<pre style='font-family:sans-serif'>{body}</pre>", "html"))

    all_recipients = to_list + cc_list

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(user, pwd)
            server.sendmail(user, all_recipients, msg.as_string())
        print(f"[OK] Pricing alert sent → PO: {payload.po_number} | RMS: {payload.rms_item_number} | Store: {payload.store_number}")
        return True
    except smtplib.SMTPException as exc:
        print(f"[ERROR] Failed to send pricing alert: {exc}")
        return False


def process_po_pricing_result(result: dict) -> None:
    """
    Process the output of get_po_pricing_details() and send a pricing alert
    email for every item that has no pricing (has_pricing=False).

    Expected result format:
    {
        "po_number": 123456,
        "store_number": "0001",
        "items": [
            {"item": 100234, "model_number": "XPS-15", "has_pricing": True,  "details": {...}},
            {"item": 100235, "model_number": None,      "has_pricing": False, "details": None},
        ]
    }
    """
    po_number    = result.get("po_number")
    store_number = result.get("store_number")
    items        = result.get("items", [])

    if not po_number or not store_number:
        print("[WARN] process_po_pricing_result: missing po_number or store_number in result.")
        return

    unpriced = [item for item in items if not item.get("has_pricing")]

    if not unpriced:
        print(f"[INFO] All items for PO {po_number} have pricing. No alerts needed.")
        return

    print(f"[INFO] {len(unpriced)} unpriced item(s) found for PO {po_number}. Sending alerts…")

    user, pwd = _smtp_user(), _smtp_password()
    if not user or not pwd:
        raise EnvironmentError(
            "SMTP_USER and SMTP_PASSWORD must be set before calling process_po_pricing_result."
        )

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.ehlo()
        server.starttls()
        server.login(user, pwd)

        for item in unpriced:
            payload = PricingAlertPayload(
                po_number=str(po_number),
                rms_item_number=str(item["item"]),
                model_number=item.get("model_number") or "N/A",
                store_number=str(store_number),
            )

            substitutions = {
                "po_number":       payload.po_number,
                "rms_item_number": payload.rms_item_number,
                "model_number":    payload.model_number,
                "store_number":    payload.store_number,
            }

            msg = MIMEMultipart("alternative")
            msg["Subject"] = PRICING_ALERT_SUBJECT_TEMPLATE.safe_substitute(substitutions)
            msg["From"]    = user

            to_list = PRICING_TEAM_RECIPIENTS
            msg["To"] = ", ".join(to_list)

            body = PRICING_ALERT_BODY_TEMPLATE.safe_substitute(substitutions)
            msg.attach(MIMEText(body, "plain"))
            msg.attach(MIMEText(f"<pre style='font-family:sans-serif'>{body}</pre>", "html"))

            try:
                server.sendmail(user, to_list, msg.as_string())
                print(f"[OK] Alert sent → RMS: {payload.rms_item_number} | Model: {payload.model_number}")
            except smtplib.SMTPException as exc:
                print(f"[ERROR] RMS: {payload.rms_item_number} | {exc}")




# ──────────────────────────────────────────────
# PO622 Alert Email
# ──────────────────────────────────────────────

PO622_CAUSE_COLORS = {
    "ALREADY_FULLY_RECEIVED": "#f8d7da",   # red
    "STUCK_REVERSAL":         "#fff3cd",   # orange / amber
    "DUPLICATE_SERIAL_NUMBER": "#f8d7da",  # red
    "CONCURRENT_RECEIVE":     "#fff3cd",   # yellow
    "NO_ISSUE_FOUND":         "#d4edda",   # green
}


def send_po622_alert(po_number: str, store_number: str,
                     root_causes: list[dict],
                     recipients: list[str]) -> bool:
    """
    Send an HTML email summarising the PO622 root-cause analysis.
    Returns True on success.
    """
    user, pwd = _smtp_user(), _smtp_password()
    if not user or not pwd:
        raise EnvironmentError(
            "SMTP_USER and SMTP_PASSWORD must be set in the environment."
        )

    subject = f"PO622 Alert - PO {po_number} Store {store_number}"

    rows_html = ""
    for cause in root_causes:
        bg = PO622_CAUSE_COLORS.get(cause["type"], "#ffffff")
        rows_html += (
            f"<tr style='background:{bg}'>"
            f"<td style='padding:6px;border:1px solid #ccc'>{cause['type']}</td>"
            f"<td style='padding:6px;border:1px solid #ccc'>{cause.get('item') or '—'}</td>"
            f"<td style='padding:6px;border:1px solid #ccc'>{cause.get('detail', '')}</td>"
            f"<td style='padding:6px;border:1px solid #ccc'>{cause.get('action', '')}</td>"
            f"</tr>"
        )

    html_body = f"""
    <html><body>
    <h2>PO622 Diagnostic Alert</h2>
    <p><b>PO Number:</b> {po_number} &nbsp; | &nbsp; <b>Store:</b> {store_number}</p>
    <table style='border-collapse:collapse;width:100%'>
      <thead>
        <tr style='background:#343a40;color:#fff'>
          <th style='padding:8px;border:1px solid #ccc'>Type</th>
          <th style='padding:8px;border:1px solid #ccc'>Item</th>
          <th style='padding:8px;border:1px solid #ccc'>Detail</th>
          <th style='padding:8px;border:1px solid #ccc'>Suggested Action</th>
        </tr>
      </thead>
      <tbody>{rows_html}</tbody>
    </table>
    <br><p style='color:#888;font-size:12px'>Automated PO622 Diagnostic — Racpad Support Tool</p>
    </body></html>
    """

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(html_body, "html"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(user, pwd)
            server.sendmail(user, recipients, msg.as_string())
        print(f"[OK] PO622 alert sent → PO {po_number} Store {store_number}")
        return True
    except smtplib.SMTPException as exc:
        print(f"[ERROR] PO622 alert failed: {exc}")
        return False


def should_send_email(record: dict) -> bool:
    """
    Define the conditions under which an email should be triggered.
    Customize this function to match your business logic.
    """
    # Example conditions:
    # 1. Status must be one of the critical statuses
    critical_statuses = {"MISSING", "DAMAGED", "OVERDUE", "FLAGGED"}
    if record.get("status", "").upper() not in critical_statuses:
        return False

    # 2. Store number must be present
    if not record.get("store_number"):
        return False

    # 3. Inventory number must be present
    if not record.get("inventory_number"):
        return False

    return True


def process_records(records: List[dict]) -> None:
    """
    Process a list of records and send emails for those that meet the conditions.

    Each record dict should have keys matching EmailPayload fields.
    """
    payloads = []
    for record in records:
        if should_send_email(record):
            payloads.append(
                EmailPayload(
                    store_number=record["store_number"],
                    inventory_number=record["inventory_number"],
                    item_description=record.get("item_description", "N/A"),
                    status=record["status"],
                    reported_at=record.get("reported_at", "N/A"),
                    additional_notes=record.get("additional_notes", ""),
                    recipients=record.get("recipients", []),   # optional per-record override
                    cc=record.get("cc"),
                    bcc=record.get("bcc"),
                )
            )

    if payloads:
        print(f"Sending {len(payloads)} email(s)…")
        send_bulk_emails(payloads)
    else:
        print("No records met the email trigger conditions.")


# ──────────────────────────────────────────────
# Entry Point — Example Usage
# ──────────────────────────────────────────────

if __name__ == "__main__":
    from datetime import datetime

    sample_records = [
        {
            "store_number": "STR-042",
            "inventory_number": "INV-100123",
            "item_description": "65-inch Smart TV",
            "status": "MISSING",
            "reported_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "additional_notes": "Last seen in aisle 3 during last cycle count.",
        },
        {
            "store_number": "STR-007",
            "inventory_number": "INV-200456",
            "item_description": "Laptop - Dell XPS 15",
            "status": "ACTIVE",              # will NOT trigger email
            "reported_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        },
        {
            "store_number": "STR-019",
            "inventory_number": "INV-300789",
            "item_description": "Refrigerator - LG 28 cu ft",
            "status": "OVERDUE",
            "reported_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "additional_notes": "Customer rental period exceeded by 14 days.",
            "cc": ["manager@example.com"],
        },
    ]

    process_records(sample_records)
