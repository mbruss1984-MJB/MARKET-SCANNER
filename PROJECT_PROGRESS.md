# Market Scanner — Project Progress and Handoff

Updated: 2026-10-09 (UTC). This is the canonical, version-controlled project checkpoint.

## Quick access
- Code: https://github.com/mbruss1984-MJB/MARKET-SCANNER
- Render service: https://dashboard.render.com/web/srv-db4h46nlk1mc73813jhg
- Live status: https://longbridge-ignition-scanner.onrender.com/status
- Fast signal CSV: https://longbridge-ignition-scanner.onrender.com/fast-signals.csv
- General signal CSV: https://longbridge-ignition-scanner.onrender.com/signals.csv

## Goal and constraints
Detect early U.S. equity price/volume acceleration, including low-priced stocks, before a move becomes a chase. Human decides all trades. No automatic orders, margin borrowing, or paid services without approval. Do not publish credentials. Existing hourly broad-market ChatGPT automation is a separate fallback and should remain enabled until this scanner is validated.

## Implemented
- Python FastAPI service on free Render; Longbridge market data through server-side credentials.
- Nasdaq Trader symbol discovery (~5,560 eligible symbols at latest startup); rotating quote batches and ranked detailed candle analysis.
- Independent hot-watch quote polling at nominal 15-second intervals, limited to a subset of symbols.
- Fast candidate logic: two consecutive qualifying windows, each with >=0.25% price change and >=1,000 additional shares; provisional, not executable.
- SQLite signal event history, 1/5/15-minute observed forward returns, and CSV endpoints.
- /status JSON reports universe progress, hot-watch metrics, errors and candidate history.

## Latest observed status (2026-10-09 19:34 UTC, user-provided)
- connected=true; error=null; hot_loop_error=null
- universe_size=5560; cycle=2; sweep_progress_pct=8.6; quote_batch_size=256
- hot_loop_symbols=20; hot_poll_seconds=15; quote_history_size=376
- fast_candidate_count=0; fast_signal_summary.n=0
- FSLY broad quote comparison: +0.505% with 49,509 additional shares over ~65 seconds; hot loop then 0.0%/15 seconds. This is NOT a confirmed entry.
- No confirmed fast signals or proven positive expectancy yet.
- The user explicitly manually restarted the service, explaining the reset cycle/history; do not characterize that reset as a crash.

## Known limitations / risks
1. Render Free may sleep; nominal 15-second polling is not guaranteed continuous.
2. SQLite defaults to /tmp/ignition_signals.sqlite3: data can be lost on restart/redeploy. This checkpoint preserves project knowledge, NOT live signal rows.
3. Only the hot-watch subset gets fast monitoring; the whole universe is NOT scanned every 15 seconds.
4. A detected ticker can leave the hot-watch list before 1/5/15-minute outcomes are recorded, biasing validation.
5. Broad cycle includes processing time PLUS a >=60-second sleep; sweep completion timing must be measured, not assumed.
6. Fast-signal triggers are experimental and do not verify executable spread, catalyst, liquidity or supply risk.
7. Existing README previously described an older watchlist-only prototype; this document supersedes that architecture summary.

## Next engineering steps (in order)
1. Persist signal records outside ephemeral Render filesystem, without incurring costs or exposing private credentials. Assess safe, rate-limited GitHub Actions artifact/archive or another free durable storage option before implementing. Do NOT commit tokens or proprietary data to public repo.
2. Add diagnostics for single qualifying hot-loop windows that fail second confirmation, with bounded counts and timestamps.
3. Keep detected symbols in a bounded outcome-tracking set for >=15 minutes, independent of rotating hot-watch ranking.
4. Add a simple read-only dashboard for signals, progress, errors and outcomes.
5. Validate 30–50 genuine, independently qualified executable signals; record detection time/price, subsequent quotes, spreads, adverse/favorable excursion, and observed slippage. Avoid treating provisional fast events as trade recommendations.

## Operating guidance
- Do not manually restart unless necessary; it clears in-memory histories.
- /status is a point-in-time snapshot. /fast-signals.csv is downloadable, but can be empty.
- ChatGPT scheduled monitoring has a minimum one-hour interval. Faster alerts would need an alert mechanism running on the server, requiring explicit approval and setup.
- No trade execution is enabled.

## Deployment notes
- Repo: mbruss1984-MJB/MARKET-SCANNER, main.
- Render service ID: srv-db4h46nlk1mc73813jhg.
- Most recently verified running code: v1.4.0, commit b632204f59cddf04429e661946c12d13a5fda9fe.
- Credentials must remain in Render environment variables, never in GitHub files.


## Validation checkpoint — 2026-10-09 19:49 UTC (user-provided live status)
- Connected; no general or hot-loop errors. Broad cycle 16, 69.1% of 5,560-symbol sweep, 20 hot-watch symbols.
- First SIX fast events recorded; four have 1-minute returns, three have 5-minute returns, zero have 15-minute returns.
- 5-minute returns: QSI +2.468354%, OFAL +1.741002%, FRGT -0.807018%. These are observed price returns, NOT executable net trading results.
- Other fast events: PDSB detected $1.37, 1-minute -0.291971%; VEEA detected $5.67, subsequent latest $5.69; WFF detected $11.88, latest $11.88.
- At snapshot, two active provisional fast candidates: WFF +2.679% / 15 sec with 35,013 additional shares and 2 consecutive qualifying windows; VEEA +0.353% / 15 sec with 1,444 additional shares and 3 qualifying windows.
- Broad candle lifecycle: PICS active early starter at $13.71 (prior PICS event invalidated); QSI prior early starter invalidated. These are a SEPARATE signal ledger from fast events and should not be double-counted.
- Six detected events is progress, but not six qualified executable trades; performance validation is still insufficient.
- Note: FRGT's last observation is at 19:41:16 UTC, 5m after detection, illustrating that 15m follow-up may be missing when a ticker leaves hot-watch. Preserve detected symbols for outcome tracking.
