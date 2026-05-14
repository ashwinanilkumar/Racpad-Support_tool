<<<<<<< HEAD
# Racpad-Support_tool
=======
# Racpad Support Tool (Pricing & PO Diagnostics)

Quick instructions to get the app running locally on Windows.

Requirements
```markdown
# Racpad Support Tool (Pricing & PO Diagnostics)

Quick instructions to get the app running locally on Windows.

Requirements
- Windows 10 / 11
- Python 3.10 or newer (must be on PATH)
- Network access to your RAC / Pricing databases (VPN if required)

1) Setup (one-time)

- Open a PowerShell or Command Prompt in the project folder.
- Run the setup batch to create a virtual environment and install dependencies:

   setup.bat

2) Run the app

- Start the Flask server with the provided run script:

   run.bat

- Open your browser at: http://127.0.0.1:8501

3) First-time configuration (in the app)

- Open the **Setup** page and configure SMTP (email) and DB connection info.
- DB credentials use Kerberos (no password required) — only host, port, dbname and user are needed.

Notes
- Credentials are stored in the OS credential manager (Windows Credential Manager).
- If you need to reset stored credentials use the **Clear Credentials** button in the Setup page.

Distribution
- Share this folder with teammates. They only need Python installed and to run `setup.bat` then `run.bat`.

Troubleshooting
- If the browser cannot reach the app, confirm the server is running and no firewall blocks port 8501.
- If DB connections fail, verify VPN/network and the values entered on the Setup page.

License / Contact
- Internal tool — share only within the team. For issues, contact the tool owner.

```
