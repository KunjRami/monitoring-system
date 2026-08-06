# Amazon Scope-2 Centralized Monitoring System

A fully separate, **passive/read-only** monitoring system for the 20-PC /
100-Chrome-instance Amazon PDP scraping fleet. It never touches, injects into,
or interacts with the existing Python scraper or Chrome — it only observes
and reports.

See `docs/ARCHITECTURE.md` for the full design and
`docs/LOGIN_DETECTION_METHODS.md` for the detection-method tradeoff analysis
you asked for (window title vs OCR vs screenshot analysis vs UI Automation vs
why Chrome DevTools Protocol is deliberately excluded).

## Project layout

```
monitoring-system/
  agent/          Monitoring Agent -- runs on each of the 20 Windows PCs
  server/         FastAPI + MongoDB central server
  dashboard/      Static HTML/CSS/JS dashboard (served by the FastAPI server)
  docs/           Architecture, detection-method analysis, install guide
```

## Architecture note: agents write directly to MongoDB

Agents do **not** send heartbeats over HTTP to the FastAPI server. They
connect straight to the central MongoDB and write their status there; the
FastAPI server only **reads** from that same database to serve the
dashboard. This means an agent only ever needs *outbound* reachability to
Mongo's port — no inbound firewall rule is required on any machine for an
HTTP heartbeat port. See `docs/ARCHITECTURE.md` for the full data-flow
diagram and the reasoning (this was a deliberate change after hitting a
Windows Firewall policy that silently ignored locally-created inbound allow
rules on one office network — see the connectivity troubleshooting notes in
`docs/INSTALLATION.md`).

⚠️ If you're using an unauthenticated `mongodb://host:27017/` connection
string (no username/password), anyone who can reach that port has full
read/write/delete access to the whole database. Fine for getting started;
add MongoDB authentication before relying on this in production — see
`docs/INSTALLATION.md` § Securing MongoDB.

## Quick start

### 1. MongoDB
Run MongoDB somewhere reachable by every agent machine (a central server on
the office network, or MongoDB Atlas if agents are on networks that can't
reach each other directly).

### 2. Server (reads Mongo, serves the dashboard)
```bash
cd server
python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp config.yaml.example config.yaml
# edit config.yaml: mongodb.uri, auth.username/password, auth.jwt_secret
uvicorn app.main:app --host 0.0.0.0 --port 8000 --app-dir .
```
Then open `http://<server-host>:8000/login` and sign in with the credentials
from `config.yaml`. (Note: viewing the dashboard from another machine still
needs this port reachable, same as any web app — that's a separate concern
from agent connectivity, which no longer needs an inbound HTTP port at all.)

### 3. Agent (installed on each of the 20 Windows PCs)
```powershell
cd agent
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
copy config.yaml.example config.yaml
# edit config.yaml: machine_name (unique per PC), mongodb.uri
python main.py
```
Repeat on all 20 PCs with a unique `machine_name` each time. New/replacement
machines just need the same 4 steps — nothing to configure on the server
side, they register automatically (see docs/ARCHITECTURE.md § Dynamic
machine registration).

Full step-by-step instructions, including running the agent as a Windows
service/scheduled task so it survives reboots, are in
`docs/INSTALLATION.md`.

## Performance targets

Agent is designed to stay under ~2% CPU / ~150MB RAM on each PC: it uses
cheap window-title + `IsHungAppWindow` checks every poll cycle, and only runs
the heavier screenshot+OCR path on a much slower interval (default 90s,
configurable, and can be disabled entirely).

## Security

- Agents authenticate to the server with a shared API key (`X-API-Key`
  header) — set `server.api_key` (agent) / `api.api_key` (server) to the same
  secret.
- The dashboard uses a single internal username/password (`auth.username` /
  `auth.password` in the server config) exchanged for a short-lived JWT.
- No secrets are hardcoded in source — everything lives in `config.yaml`
  files (gitignored; only `config.yaml.example` templates are committed).

## Future enhancements

- Real Slack/Microsoft Teams/Email alert channels (the `AlertChannel`
  interface in `server/app/services/alert_service.py` is already pluggable —
  a generic webhook channel, which Slack/Teams incoming webhooks both accept
  as-is, is implemented today).
- Screenshot thumbnails stored to disk/S3 and shown in the dashboard's
  "Screenshots" view (schema already reserves a `screenshots` collection).
- Optional opt-in auto-heal actions (e.g. notify-only vs. "restart machine"),
  kept strictly separate from the read-only detection path and off by
  default.
- Historical trend charts (CPU/RAM over time, alert frequency by machine).
- Windows Service wrapper (`pywin32`'s `win32serviceutil`) so agents start
  automatically on boot without a logged-in session.
