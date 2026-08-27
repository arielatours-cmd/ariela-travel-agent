# QA Report — Ariella v9.7.110

## Automated / static checks
- Python compile: PASS — config.py, database.py, scanner.py, public_site.py, admin.py.
- Jinja parse: PASS — 24/24 templates.
- DB migration: PASS — scan_type, trip_id, api_requests created and persisted.
- Public fallback: PASS — scores 68,67,66,64,62 return five best; score 59 excluded.
- Month crossover ranking: PASS — Feb→Mar is retained as an alternative and marked as missing only return-month condition.
- Direct-flight soft mismatch: PASS — exact dates + connection remains an alternative when direct was requested.
- Date flexibility: PASS — ±2 day exact-date scenario matches.
- Group availability notice: PASS — 6-passenger request receives supplier availability warning without changing per-person price semantics.
- SerpAPI 429 retry simulation: PASS — two 429 responses followed by success completed on attempt 3.
- My Vacations DB regression simulation: PASS — recent Milan Feb→Mar/baggage mismatch renders as alternative; page does not crash.
- Destination images current catalog: PASS — 30/30 configured broad-scan destinations have curated image mappings.

## Live regression required after deploy
1. Bangkok exact dates + direct-only: connection deal appears under closest alternatives, not empty screen.
2. Multi-destination + Milan dates + baggage: Milan deal appears as alternative when baggage is the only mismatch.
3. Milan February request + return in March: deal appears and ranks below full matches.
4. Same dates → another destination: no error; new destination state renders cleanly.
5. My Vacations opens after repeated searches and latest vacation is present.
6. "Ariella chooses" clears the other three flight-priority selections.
7. "Anytime" hides/clears "selected dates" priority.
8. Regular and ski exact-date flexibility ±1/2/3 works in live search.
9. Admin scan table shows personal_standard / personal_ski / personal_business and API request count.
10. Wide scan encountering a transient 429 retries and continues; final error details are visible if all retries fail.

## Environment limitation
The container has no network access and Flask is not installed, so a real HTTP/Render smoke test cannot be performed here. Route-level account behavior was simulated against a real temporary SQLite schema with Flask interfaces stubbed. Final HTTP/live verification is required on Render.
