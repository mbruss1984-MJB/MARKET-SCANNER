# Market Scanner

Read-only Longbridge ignition scanner prototype. No trades are placed.

This repository is currently PUBLIC. Never commit API keys or access tokens.

The service polls a configured watchlist (not the full U.S. market) using 1-minute and 5-minute completed candles. It requires Longport credentials in Render environment variables and is not a guaranteed 24/7 stream on Render Free.

See `app.py`, `scoring.py`, `requirements.txt` and `render.yaml` for implementation.
