# Insider Trading Tracker

Private web app that monitors OpenInsider's latest insider purchases feed, records the first time a filing appears there, verifies the filing against the SEC ownership XML, and tracks post-detection stock prices at fixed intervals.

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/rishavpunatar/insider-trading-tracker)

## What It Does

- Polls `http://openinsider.com/latest-insider-purchases-25k`
- Detects new purchase rows as they first appear on the page
- Stores the app's `first_seen_at` timestamp for each new filing
- Verifies the row against the linked SEC Form 4 XML
- Filters out non-stock instruments where possible
- Schedules quote snapshots for:
  - first seen
  - +30 minutes
  - +3 hours
  - +1, +2, +3, +4, +5 U.S. trading days
- Fetches quotes from two providers and marks each snapshot as:
  - `confirmed`
  - `pending_secondary`
  - `waiting_for_fresh_quote`
  - `disputed`
  - `failed`
- Stops scheduling after the fifth trading day but retains all stored history

## Important Constraints

- "Price when it was posted on the site itself" is approximated as the first time this app sees the row.
- If the app is offline when a snapshot becomes due, it will capture the next fresh quote it can get. It does not fabricate historical intraday prices.
- Free quote providers can rate-limit you. The app exposes those states instead of pretending the data is complete.
- The app is intended for private/internal use with your own API keys.

## Data Providers

- Discovery source: OpenInsider
- Filing verification: SEC EDGAR ownership XML
- Quote providers:
  - Twelve Data
  - Financial Modeling Prep

## Quick Start

1. Create a virtual environment and install dependencies:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

2. Copy the environment file and add your API keys:

```bash
cp .env.example .env
```

3. Run the app:

```bash
uvicorn insider_tracker.app:create_app --factory --reload
```

4. Open `http://127.0.0.1:8000`

## Deployment

This app needs a real app host, not GitHub Pages. It runs a FastAPI server plus background polling/scheduling in the same process.

Included deployment files:

- `render.yaml` for a Render Blueprint with managed Postgres
- `railway.toml` for Railway config-as-code
- `Dockerfile` for generic container hosts

Required production environment variables:

- `HTTP_USER_AGENT`
- `TWELVEDATA_API_KEY`
- `FMP_API_KEY`

The app can run without quote API keys, but scheduled snapshots will remain unconfirmed.

## Manual Controls

- `POST /api/admin/run-discovery`
- `POST /api/admin/run-due-snapshots`
- `GET /api/filings`
- `GET /health`

## Tests

```bash
pytest
```

## Architecture

See `docs/architecture.md`.
