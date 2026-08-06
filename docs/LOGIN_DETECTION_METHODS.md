# Detecting Chrome / Login State Without Touching the Browser

You asked for a comparison of window title, OCR, screenshot analysis,
Accessibility API, and Windows UI Automation, plus a recommendation. Below is
the tradeoff table and the reasoning for what the Agent implements.

## Method comparison

| Method | How it works | Pros | Cons | Interference risk |
|---|---|---|---|---|
| **Window title parsing** | Read the title bar text of each Chrome top-level window via the Win32 API (`EnumWindows` + `GetWindowText`). Chrome sets the title to the page `<title>` + " - Google Chrome". | Extremely cheap (<1ms), zero risk of interfering, works even if Chrome is frozen (title is a cached window property), no extra dependencies beyond `pywin32`. | Coarse — can't see full URL, only whatever text the page put in `<title>`. Some pages (blank tab, some CAPTCHA pages) have generic/empty titles. | **None.** Reading a window's title is a passive OS query. |
| **Screenshot analysis (pixel/template matching)** | Periodically capture the screen region for each window with `mss`/`PIL.ImageGrab` and compare against reference templates (e.g. Amazon CAPTCHA layout, sign-in form layout). | Can distinguish visually similar pages that have similar titles; also doubles as a "same screenshot repeatedly" freeze signal. | Heavier (CPU/disk for image compare), templates need maintenance if Amazon changes page layouts, doesn't work if the window is minimized/occluded. | **None** if done with a pure screen-capture API — this reads pixels already on screen, it does not send anything to the window. |
| **OCR (Tesseract) on screenshot** | Run OCR over the captured screenshot to read visible text ("Sign in", "Enter the characters you see", etc.). | Most robust text-based signal, catches CAPTCHA/robot-check pages that generic titles don't reveal. | Slowest and most CPU-heavy of all methods; needs `pytesseract` + Tesseract binary; accuracy depends on font/zoom. | **None** — same passive screenshot, just processed further. |
| **UI Automation (UIA) / Accessibility API** | Use `pywinauto`'s UIA backend (or `uiautomation` package) to read the accessibility tree of the Chrome window — e.g. read the address-bar `Edit` control's value, or find text nodes matching "Sign in". | Can read the actual address bar text (closest thing to "the URL" without CDP), more structured than OCR, faster than OCR. | Slightly more fragile across Chrome versions (control IDs can shift), requires the window to be a normal top-level window (not fully occluded in some UIA backends), marginally higher overhead than title-only. | **Low, if read-only.** UIA supports both read-only property access (safe) and control invocation (click-equivalent — must never be used here). The agent only calls read-only property getters, never `.click()`/`.set_focus()`/`Invoke()`. |
| **Chrome DevTools Protocol (CDP)** — *not used* | Attach to Chrome's `--remote-debugging-port` and query `Target.getTargets` / `Page.getNavigationHistory` for the exact URL. | Would give the exact URL and DOM state — the most "complete" data. | This is the one method that is genuinely risky here: it requires Chrome to have remote debugging enabled, and if the scraper's own Selenium/Playwright session is *already* the CDP client, a second client attaching to the same port can cause connection contention, extra memory, or in some Chrome versions, session instability. It also blurs the "completely separate, read-only" boundary you asked for. | **Explicitly excluded** for this reason, even though it's technically the richest data source. |
| **CPU/window-message "hang" check** | Ask Windows "is this window responding?" via `IsHungAppWindow` (win32) — this is literally what Explorer uses to gray out a frozen window. | Purpose-built for exactly this, essentially free, doesn't touch Chrome's internals. | Only tells you responsive vs. not; no content info. | **None** — this is a read-only OS query, arguably even safer than reading the title. |

## What the Agent implements (recommended, layered approach)

1. **Primary signal — window title (Win32) + `IsHungAppWindow`.** Cheap,
   runs every poll cycle (default 15s), gives status for "responsive?" and a
   first-pass page classification (Sign-In / Robot Check / generic).
2. **Secondary signal — periodic screenshot + lightweight OCR** (default
   every 60–120s, configurable, and skippable entirely via config if you want
   zero screenshot overhead). Used only to disambiguate when the title is
   generic/blank, and to detect "frozen" via repeated-identical-frame
   comparison.
3. **UI Automation** is included as an optional, config-gated module
   (`agent/login_detector.py::read_address_bar_uia`) for sites/pages where
   title text alone is ambiguous, since it can read the address bar text
   read-only. It's off by default to keep the resource footprint minimal and
   because title+screenshot already covers the required status set; turn it
   on via `config.yaml` if you find title-only insufficient in practice.
4. **CDP is intentionally not implemented.** If you later decide the risk is
   acceptable (e.g. you control the scraper's remote-debugging port and can
   guarantee single-client-only, or the scraper exposes a read-only
   secondary port), it can be added as an additional opt-in module without
   touching anything else in this system.

## Frozen-browser detection specifically

Combines, in order of cost:
1. `IsHungAppWindow` — instant, authoritative "Windows thinks this is hung".
2. CPU usage pinned at 0% for the Chrome process tree for > N seconds while a
   scrape should be in progress (configurable threshold) — supporting signal.
3. Screenshot hash unchanged across M consecutive samples (default 3 samples
   / ~3 minutes) — catches "silently stuck" cases where Windows still
   considers the window responsive but the page truly isn't progressing.

Any one of #1 triggers `Frozen` immediately; #2 and #3 together (not alone,
to reduce false positives from a genuinely idle-but-fine page) escalate to
`Frozen` as well.

## Heartbeat / offline logic (reduced false positives)

- Agent sends a heartbeat every 30s (configurable).
- Server marks a machine `Warning` only after **2 consecutive missed**
  intervals (60s) and `Offline` after **4 consecutive missed** intervals
  (120s) — requiring consecutive misses (not just "no heartbeat since X")
  avoids flapping caused by a single dropped network packet.
- On the next successful heartbeat, status immediately reverts to `Healthy`
  (or whatever the reported Chrome-level status is).
