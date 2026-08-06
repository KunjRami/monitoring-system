# Architecture Overview

## Goals & Non-Negotiable Constraints

- The monitoring system is **fully separate** from the existing Python scraper.
- It **never** injects code into Chrome, never attaches a debugger/CDP session to
  the scraper's Chrome instances, never sends keyboard/mouse/window events, and
  never touches the scraper's process, files, or profile directories.
- It only **reads** OS-level and window-level information that is already
  visible to any process on the machine (process list, window titles,
  screenshots of the whole screen, resource counters). Reading this
  information cannot affect the target process in any way — it is the same
  class of operation Task Manager performs.

## High-Level Data Flow

Agents write **directly** to MongoDB rather than sending heartbeats over HTTP
to the server. This was a deliberate change: on the actual office network
this was deployed to, one machine's Windows Firewall was configured with
`LocalFirewallRules: N/A (GPO-store only)` on its active profile, which
silently ignores any locally-created inbound allow rule (`New-NetFirewallRule`
succeeds and looks correct, but is never consulted). Rather than depend on
an inbound HTTP port being reachable into a specific machine, agents only
need *outbound* reachability to MongoDB's port, which is unaffected by that
kind of inbound-only block.

```
 Windows PC #1 (unchanged scraper + new read-only Agent)
      Scraper (untouched)        Agent (new, read-only)
              |                        |
              |                        |  direct MongoDB write every 30s
              |                        |  (outbound only, no inbound port
              |                        |   needed on the Mongo host)
   ... x20 machines --------------------
                                         |
                                         v
                               +-------------------+
                               |     MongoDB        |
                               | machines, chrome,  |
                               | status_history,     |
                               | heartbeats, alerts   |
                               | (TTL indexes keep    |
                               |  history bounded)     |
                               +---------+---------+
                                         ^
                                         | reads only
                                         |
                               +-------------------+
                               |   FastAPI Server    |
                               |  (dashboard API +    |
                               |   background sweep:   |
                               |   offline detection,   |
                               |   alert derivation)     |
                               +---------+---------+
                                         |
                                         v
                               +-------------------+
                               |   Web Dashboard      |
                               | (polls REST API,      |
                               |  auto-refresh)          |
                               +-------------------+
```

**Tradeoff worth knowing:** this removes the API-key-authenticated HTTP layer
that previously validated/authorized each heartbeat. Every agent now needs
direct MongoDB credentials, so those credentials should be scoped to a
restricted, write-only database user per the security guidance in
`docs/INSTALLATION.md` rather than shared as a wide-open admin connection
string.

## Why this design never touches the scraper

| Concern | How it's avoided |
|---|---|
| Injecting code | Agent has no code path that writes into Chrome's memory, extensions, or profile. |
| Attaching Chrome DevTools Protocol | Deliberately **not used** — see LOGIN_DETECTION_METHODS.md. Attaching a second CDP client to a remote-debugging port the scraper already uses can destabilize the existing session, so it's out of scope entirely, even though it's the "easy" way to read the current URL. |
| Clicking / typing | Agent never calls any input-simulation API (no pyautogui.click/press, no SendInput, no click-type SendMessage codes). |
| Killing / restarting processes | Agent has no code path that terminates or restarts the scraper. It only reports; remediation stays a human/ops decision (or a future opt-in auto-heal module, disabled by default). |

## Components

1. **Monitoring Agent** (`agent/`) — one instance per Windows PC, runs as a
   normal Python process (or Windows service later). Polls local OS/window
   state, computes a status, and POSTs a heartbeat to the server.
2. **Central Server** (`server/`) — FastAPI app exposing:
   - `POST /api/v1/heartbeat` — agents push status
   - `GET /api/v1/dashboard/summary` — aggregate counts
   - `GET /api/v1/machines` — per-machine/per-Chrome detail
   - `GET /api/v1/alerts` — active + historical alerts
   - `POST /api/v1/auth/login` — simple single-user login, returns a token
   A background task marks agents `Warning`/`Offline` if no heartbeat is seen
   within the configured timeout.
3. **MongoDB** — stores `machines`, `chrome_instances`, `status_history`,
   `heartbeats`, `alerts`, `config`.
4. **Dashboard** — static HTML/CSS/JS served by FastAPI, polls the REST API
   every few seconds and re-renders. No build step required.

## Dynamic machine registration

Machines are **not** hardcoded anywhere. Any agent that POSTs a heartbeat with
a `machine_name` the server hasn't seen before is auto-registered. Swapping a
dead PC for a replacement is just: install the agent, point its `config.yaml`
at the server, start it — it appears on the dashboard automatically. Machines
that stop sending heartbeats simply age into `Offline` status; they are never
deleted automatically (so history isn't lost), but can be archived/removed
from the dashboard's Settings page.

## Extensibility for alerting

`server/app/services/alert_service.py` defines an `AlertChannel` interface.
`ConsoleAlertChannel` and `WebhookAlertChannel` (generic HTTP POST — works for
Slack/Teams incoming webhooks with no code changes) are implemented. Adding
real Slack/Teams/Email later means writing one small class and registering it
in config — no changes to detection logic.
