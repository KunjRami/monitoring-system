# Installation Guide

## 1. MongoDB

Install MongoDB somewhere every agent PC can reach **outbound**: on a
dedicated server, on one of the office machines, or use MongoDB Atlas if the
agent PCs are on networks that can't reach each other directly at all.

Agents connect straight to this instance (see `docs/ARCHITECTURE.md` for why)
— there's no separate "register the server" step for Mongo itself, agents
just need a reachable `mongodb://` URI.

### Securing MongoDB (do this before relying on this in production)

An unauthenticated `mongodb://host:27017/` connection string gives anyone who
can reach that port full read/write/delete access to every collection. At
minimum, enable authentication and create a scoped user for the agents:

```javascript
// in mongosh, connected as an admin user
use admin
db.createUser({
  user: "monitoring_agent",
  pwd: "CHANGE_ME_STRONG_PASSWORD",
  roles: [{ role: "readWrite", db: "amazon_monitoring" }]
})
```

Then update every agent's `config.yaml`:
```yaml
mongodb:
  uri: "mongodb://monitoring_agent:CHANGE_ME_STRONG_PASSWORD@192.168.2.153:27017/"
```
and enable auth enforcement on the MongoDB server itself (`security.authorization: enabled`
in `mongod.conf`, then restart `mongod`).

## 2. Server machine (Linux/Windows/anything with Python 3.11+)

This machine serves the dashboard; it reads from MongoDB but does not
receive anything from agents directly.

1. `cd server`
2. `python -m venv venv && source venv/bin/activate` (Windows: `venv\Scripts\activate`)
3. `pip install -r requirements.txt`
4. `cp config.yaml.example config.yaml` and edit:
   - `mongodb.uri` / `mongodb.database` — same Mongo the agents write to
   - `auth.username` / `auth.password` — the one dashboard login
   - `auth.jwt_secret` — any long random string
5. Run: `uvicorn app.main:app --host 0.0.0.0 --port 8000 --app-dir .`
6. Visit `http://<server-ip>:8000/login`.

For production, run behind a process manager (systemd/NSSM) and put Nginx or
Caddy in front for TLS. Note this port (8000) only needs to be reachable by
whoever is *viewing* the dashboard — it's unrelated to agent connectivity.

## 3. Each of the 20 Windows PCs

1. Install Python 3.11+ if not already present.
2. Copy the `agent/` folder to the PC (e.g. `C:\monitoring-agent`).
3. Open PowerShell in that folder:
   ```powershell
   python -m venv venv
   venv\Scripts\activate
   pip install -r requirements.txt
   ```
4. `copy config.yaml.example config.yaml`, then edit:
   - `machine_name` — must be unique, e.g. `PC-01` … `PC-20`
   - `chrome_instance_count` — 3, 5, 6, whatever this specific PC actually runs
   - `mongodb.uri` — the same central MongoDB connection string (with
     credentials, once you've secured it per the section above)
5. (Optional) enable OCR: install Tesseract OCR for Windows and make sure
   `tesseract.exe` is on PATH, then leave `detection.use_ocr: true`.
6. Run: `python main.py`. Leave the window/console open, or wrap it as a
   scheduled task (see below) so it survives reboots.

**Verifying agent → Mongo connectivity from a PC before running the full
agent**, useful if you hit connection issues:
```powershell
python -c "from pymongo import MongoClient; c = MongoClient('mongodb://192.168.2.153:27017/', serverSelectionTimeoutMS=5000); print(c.admin.command('ping'))"
```
A `{'ok': 1.0}` response confirms this machine can actually reach Mongo —
useful to isolate a connectivity problem from an application-level one
before starting `main.py`.

### Running the agent automatically on boot (Task Scheduler)

1. Open Task Scheduler → Create Task.
2. Trigger: "At startup" (and optionally "At log on").
3. Action: `Start a program`
   - Program: `C:\monitoring-agent\venv\Scripts\python.exe`
   - Arguments: `main.py`
   - Start in: `C:\monitoring-agent`
4. Check "Run whether user is logged on or not" if you want it running
   without an interactive session (note: window-title/screenshot detection
   needs an active desktop session, so for those signals a logged-in session
   is required; CPU/RAM/heartbeat still work headless).

## 4. Swapping in a replacement PC

No server-side, and no MongoDB-side, configuration is needed. On the new PC:
1. Repeat step 3 above with a `machine_name` that either reuses the retired
   PC's name (to continue its history) or a new one (it will simply appear
   as a new card on the dashboard).
2. Start the agent. It shows up automatically — this is the dynamic
   registration behavior described in `docs/ARCHITECTURE.md`.

## 5. Verifying it's working

- `GET http://<server-ip>:8000/health` should return `{"status": "ok"}`
  (confirms the dashboard server itself is up).
- The Mongo ping test in step 3 above confirms an individual agent can reach
  the database.
- After the first agent write (within `heartbeat_seconds`, default 30s), the
  machine should appear on the dashboard's Home/Machines view.
- Check `agent/logs/agent.log` on the PC if a machine doesn't appear — a
  `Heartbeat write failed` line there points at a Mongo connectivity or
  auth issue specifically, separate from the dashboard/server being up.
