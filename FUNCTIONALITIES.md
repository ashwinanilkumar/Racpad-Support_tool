# Racpad Support Tool — Functionalities

This document lists the main user-facing features, backend endpoints, data shapes and operational notes for the Racpad Support Tool (Flask + HTML UI).

## High-level overview
- Single-page HTML/CSS/JS frontend (`templates/index.html`).
- Flask backend (`flask_app.py`) providing REST API endpoints for diagnostics, lookups and email sending.
- PostgreSQL connections to three databases via `db.py`: RAC DB, Pricing DB, Config DB.
- SMTP email integration via `email_sender.py` (SMTP credentials stored via keyring / environment at runtime).

## UI pages and features
- Pricing Alert (page `pricing`)
  - Fetch pricing for a PO / Store (`/api/pricing/fetch`).
  - Shows items and whether pricing exists.
  - Inline Send Notification Email card: recipient, CC, incident number, incident short description, subject (auto-generated), body (auto-built from unpriced items), send button (`/api/pricing/send-email`).
  - Legacy team alert removed from setup; per-item emails can be sent from the UI.

- PO622 - Receive PO Diagnostic (page `po622`)
  - Run diagnostics (`/api/po622/diagnose`) to collect overview, line items, timeline and duplicates.
  - Send Notification Email card (recipient, CC, incident fields, subject auto-generation) which calls `/api/po622/send-email`.
  - Subject includes optional incident number/description when provided.

- App Config Triage (page `appconfig`)
  - Lookup a config rule by name and scope (`/api/appconfig/lookup`).
  - Shows hierarchy chain and results table (effective value highlighted).
  - Auto-loads audit history timeline for the effective configuration row (GET `/api/appconfig/history`).
  - CSV export of current results (client-side).

- Network Connectivity (page `network`)
  - Tests connectivity to SMTP, RAC DB, Pricing DB and Config DB via `/api/diagnostics/connectivity`.
  - Presents reachable/unreachable status with details.

- Setup (page `setup`)
  - Configure SMTP credentials and database credentials (RAC, Pricing, Config).
  - Credentials are saved to keyring via `auth.py`. ConfigDB uses `racpad_config_db` keyring entry.

## Backend endpoints (select)
- GET `/` — serve index.
- GET `/api/status` — server and saved-credentials status.
- GET `/api/credentials/saved` — saved creds (masked passwords).
- POST `/api/setup/email` — save SMTP credentials.
- POST `/api/setup/db` — save DB creds (RAC, Pricing, Config).
- POST `/api/pricing/fetch` — get pricing details for a PO+Store.
- POST `/api/pricing/send-email` — send custom pricing notification (recipient + CC + incident fields).
- POST `/api/pricing/send-alert` — legacy bulk team alert (may be removed or kept for automation).
- POST `/api/po622/diagnose` — run PO622 diagnostic.
- POST `/api/po622/send-email` — send PO622 email (recipient + CC + incident fields).
- POST `/api/appconfig/lookup` — lookup config rule across hierarchy.
- POST `/api/appconfig/history` — fetch audit history for a param_config_list_of_value_id.
- POST `/api/diagnostics/connectivity` — connectivity checks for external services.

## Email behavior and templates
- Email sending utilities in `email_sender.py`:
  - `build_message` / `send_email` for general payloads.
  - `send_po622_receive_error_email` — sends PO622 messages; supports `cc_list`, `incident_number`, `incident_description`.
  - `send_pricing_notification_email` — custom pricing notification with subject override and CC.
- SMTP credentials are loaded from the saved keyring at send-time and temporarily injected into environment variables by `flask_app.py`.

## Data shapes (important request bodies)
- Pricing fetch: { po_number: string, store_number: string }
- Pricing send-email: { po_number, store_number, recipient_email, recipient_name, model_lines, email_body, cc, incident_number, incident_description }
- PO622 send-email: same shape as pricing send-email.
- AppConfig lookup: { rule_name, scope_type, scope_value }
- AppConfig history: { param_config_list_of_value_id }

## Error modes / edge cases
- Missing SMTP or DB credentials → endpoints return 400 with descriptive message.
- Invalid inputs (PO/store format) are validated client- and server-side.
- If no pricing records are found, UI shows an informative error.
- Audit history uses `param_config_list_of_value_id`; if missing, history panel is hidden.

## How to run (developer notes)
- Create and activate the virtualenv as documented in `README.md`.
- Install requirements: `pip install -r requirements.txt` (project uses `psycopg2`, `python-dotenv`, etc.).
- Start Flask (dev): use `run.bat` which validates the venv and runs `flask_app.py`.
- Use the `Setup` page to save SMTP and DB credentials before using email or DB features.

## Files of interest
- `flask_app.py` — routing, orchestration, credential injection.
- `email_sender.py` — email templates and send functions.
- `auth.py` — credential save/load via keyring.
- `db.py` — connection factory and query helper.
- `queries_config.py` / `queries.py` — SQL used by AppConfig and diagnostics.
- `templates/index.html` — all frontend UI and client-side logic.

## Next steps / recommendations
- Remove legacy `PRICING_TEAM_RECIPIENTS` usage if not needed anywhere else.
- Add unit tests for `email_sender` methods (mock SMTP) and for `flask_app` endpoints.
- Add a small E2E smoke-test that runs `api/pricing/fetch` with a known PO in a test DB.

---
Generated: May 14, 2026
