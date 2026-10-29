# Market Scanner

Read-only Longbridge U.S. market ignition scanner: rotating quote discovery, completed-candle analysis, and a bounded 15-second hot-watch loop (when the Render process is running). The scanner **never places orders**.

This repository is PUBLIC. Never commit API keys, bearer tokens, or proprietary account data. Render Free can sleep and the current SQLite validation history is ephemeral.

## Earnings-catalyst shadow enrichment

Optional Alpha Vantage `EARNINGS_CALENDAR` support is integrated into the **same** scanner:

- Set `ALPHA_VANTAGE_API_KEY` as a secret in Render to enable a **single full-market 3-month CSV refresh every 12 hours** (no per-stock fan-out, no premium requirement). Without the key the feature is disabled and momentum scanning continues normally.
- An earnings report expected within one day previously to two days ahead contributes at most a **+6 discovery-priority bonus** to a stock **already passing the existing acceleration/buildup gate**. It cannot by itself create a new signal, tier upgrade, or trade recommendation.
- Upcoming report dates and *analyst EPS estimates* annotate the candidate's evidence. An estimated date is **not a confirmed earnings announcement**, and EPS estimate is **not actual EPS**; an earnings beat/miss or AI summary is **not** inferred from this feed.
- The calendar is ignored when missing, failed, or more than 36 hours stale; provider failures are fail-open and do not block market polling.
- Read-only `/status`, `/earnings`, and MCP `get_earnings_watchlist()` expose bounded diagnostics and current hot-watch context. No new alerts, orders or paid agents are activated.

**Deployment safety:** Render auto-deploys `main`. The live scanner's in-memory/SQLite validation history can be reset by a redeploy. Keep the change on its review branch until the existing history is exported or durable storage is enabled. The branch itself does not change the live scanner.

This is calendar-context **phase 1**. Earnings results versus estimates, release confirmations, SEC filing analysis, and AI transcripts require separately verified feeds and/or API access; do not label them available merely because the calendar is installed.

See `PROJECT_PROGRESS.md`, `app.py`, `earnings.py`, `pipeline.py`, and `tests/`.
