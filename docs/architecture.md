# Architecture And Execution Plan

## Goal

Build a private tracker that watches OpenInsider's latest insider purchases page, detects newly posted filings, verifies them against the SEC, and records post-detection price performance for eligible public stocks.

## Execution Plan

### 1. Discovery

- Poll OpenInsider at a configurable interval.
- Parse the latest results table.
- Use the SEC filing URL as the primary unique fingerprint.
- For any unseen filing:
  - record `openinsider_first_seen_at`
  - persist the raw row
  - verify the row against the linked SEC Form 4 XML
  - classify whether the symbol represents an eligible stock
  - create the full snapshot schedule if eligible

### 2. Verification

- Fetch the linked SEC ownership XML using a declared user agent.
- Verify:
  - issuer trading symbol
  - transaction code includes `P`
  - trade date
  - weighted average transaction price
  - total shares and value, where possible
- Store a verification status instead of assuming the page is correct.

### 3. Eligibility Filtering

- Use SEC ticker-exchange reference data to confirm the symbol is publicly traded.
- Use provider reference data plus naming heuristics to exclude common non-stock instruments:
  - ETFs
  - mutual funds
  - trusts
  - closed-end funds
  - warrants
  - rights
  - units
  - preferred shares
- If classification is uncertain, keep the filing but mark it ineligible or low-confidence instead of silently including it.

### 4. Snapshot Scheduling

- Schedule the following targets from `openinsider_first_seen_at`:
  - `site_seen`
  - `plus_30m`
  - `plus_3h`
  - `plus_1d`
  - `plus_2d`
  - `plus_3d`
  - `plus_4d`
  - `plus_5d`
- The day-based intervals are trading-day offsets on the NYSE calendar.
- The stored target time remains the first-seen wall-clock time in U.S. Eastern.

### 5. Quote Capture

- A background dispatcher scans for due snapshots.
- When a snapshot becomes due:
  - fetch the first available Yahoo Finance 1-minute bar at or after the target timestamp
  - store the observation independently
- A snapshot is `confirmed` when:
  - Yahoo Finance returned a usable bar
  - the selected bar timestamp is at or after the target

### 6. Backfill Logic

- Quote selection is based on historical minute bars, not the wall-clock fetch time.
- If a target lands during a closed period, the tracker chooses the first minute bar at or after the target.
- If Yahoo Finance has not yet published a qualifying bar, the snapshot stays `waiting_for_source_bar` and is retried.

### 7. Persistence

- SQLite stores filings, snapshot targets, quote observations, and security classification cache.
- The scheduler is database-driven, so the app can restart without losing due work.
- The tracker stops scheduling new work after `plus_5d`, but historical records remain available.

### 8. Web UI

- Dashboard view with:
  - filing summary cards
  - tracked filings table
  - snapshot states
  - failed snapshot visibility
  - manual refresh controls
- Detail view per filing with:
  - OpenInsider row
  - SEC verification details
  - scheduled targets
  - quote observations

## Red-Team Review

### Risk: OpenInsider Markup Changes

- Impact: discovery can break suddenly.
- Mitigation:
  - parse by table headers and SEC links, not brittle positional CSS alone
  - log parse failures
  - keep fixture-based parser tests

### Risk: "Posted Time" Is Not Published By OpenInsider

- Impact: exact site-post timestamp is unknowable historically.
- Mitigation:
  - define `site_seen` as the first time this app observed the row
  - expose that approximation clearly in UI and docs

### Risk: Free Unofficial Quote Source

- Impact: Yahoo Finance can change behavior, throttle requests, or provide incomplete extended-hours coverage.
- Mitigation:
  - event-driven capture instead of continuous polling by symbol
  - provider-specific error storage
  - explicit `waiting_for_source_bar` and `failed` states

### Risk: After-Hours And Closed-Market Targets

- Impact: some targets may not have a minute bar exactly at the requested time.
- Mitigation:
  - select the first available minute bar at or after the target
  - retry if no qualifying bar exists yet
  - store `captured_at` and provider quote timestamps separately

### Risk: Security Classification Ambiguity

- Impact: funds or other non-stock instruments might slip in.
- Mitigation:
  - combine SEC exchange map, provider metadata, and conservative name heuristics
  - default to exclusion on high-risk non-stock labels

### Risk: SEC Blocking

- Impact: SEC requests may be rejected without a proper user agent.
- Mitigation:
  - require a declared user agent in configuration
  - cache reference data locally where possible

## Final Architecture Choice

Best approach for this build:

- FastAPI web app
- server-rendered Jinja UI
- SQLite persistence
- background worker threads inside the app process
- OpenInsider discovery adapter
- SEC verification adapter
- One zero-cost quote adapter backed by Yahoo Finance
- NYSE trading calendar scheduling

This choice is better than a static site or serverless deployment because the product's core requirement is durable scheduled work tied to live page updates.
