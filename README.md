# Market Scanner

Read-only Longbridge ignition scanner prototype. No trades are placed.

This repository is currently PUBLIC. Never commit API keys or access tokens.

The service uses NASDAQ Trader symbol directories for broad U.S.-listed common-stock **discovery**, rotating through quote batches (not a real-time feed of every stock simultaneously). It promotes promising names to a smaller candle-scored hot watchlist, refreshed by the independent ~15-second hot loop. The ordinary quote discovery cycle is 60 seconds by default, so one complete sweep of the universe can take many cycles.

## Early volume breakout coverage
- Discovery includes first-seen +0.5% to +2% movers, established movers, and a reserved quiet-stock cohort.
- Minimum same-day turnover for initial *research discovery* is $20,000 (rather than $100,000). This is **not** an order-execution liquidity threshold.
- With at least three completed 5-minute bars and seven completed 1-minute bars, 2× current 5-minute volume versus median prior available bars plus +0.25% 5-minute price movement produces `EARLY_VOLUME_WATCH_2X`.
- With 4× volume, +0.25% 5-minute movement and +0.4% 15-minute movement, `VOLUME_IGNITION_4X` is emitted; existing stronger starter signals remain intact.
- A separate 2× sequential quote-volume-velocity trigger can elevate a candidate before a large price expansion.
- There is no daily gain ceiling for *discovery*, but every event is **provisional**, read-only, and is not a buy recommendation. Price extension, spread, halts, dilution/catalysts, liquidity, and execution risk must be checked independently.

The service requires Longport credentials in Render environment variables and is not a guaranteed 24/7 stream on Render Free. It does not transmit SMS/email alerts and does not place trades. It cannot guarantee catching a 5-minute spike in a symbol not yet visited during the rotating market sweep.

See `app.py`, `scoring.py`, `requirements.txt` and `render.yaml` for implementation.
