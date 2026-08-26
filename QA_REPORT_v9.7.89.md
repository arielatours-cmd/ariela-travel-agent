# Ariella QA Report — v9.7.106

## Fixes added after live v9.7.88 test
- Fixed false `failed` status on long healthy scans: stale-scan detection now uses a progress heartbeat instead of scan start time.
- Scan progress continues to count attempted destinations, so errors do not make a completed batch look stuck.
- Added admin QA Test Mode. Production threshold remains 70; Test Mode temporarily exposes 65+ deals so downstream flows can be tested without changing the production rule.
- Inherited v9.7.88 fixes remain: clean API-cap stop, 220-request wide-scan safety cap, shorter external timeout, booking-reliability scoring, admin scoring diagnostics.

## QA checks passed
- Python compilation
- Jinja parsing
- scan heartbeat migration/update
- 30 attempted + errors => `partial`, not `failed`
- production threshold remains 70
- QA Test Mode threshold is 65
- strong bootstrap-quality deal can cross 70
- weak deal remains below 70

## Next live regression
Do NOT burn another wide scan first. Enable QA Test Mode and use the already-found 65–69 deals to test:
1. Deals page rendering and filters
2. My Vacations DB-first exact match
3. No-match state and both alternative-search buttons
4. Baggage display
5. Direct booking handoff
6. Mobile/English regression

Only after those pass should another 30-destination scan be used to verify the heartbeat fix live.
