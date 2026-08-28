# QA Report — Ariella v9.7.124

Final regular-vacation regression bundle.

- Ranking test #2: primary results are filtered by objective restrictions and open-destination results are ordered by +1-per-selected-condition, with deal score only as tie-breaker.
- Exact dates + ±1/2/3 flexibility: shared 48h DB is checked first using the selected window; an external personal scan is allowed only if no DB match exists.
- Date-priority choice is hidden/cleared when the customer selected exact-date flexibility.
- Personal external scan offers remain in the shared offers inventory; startup cleanup removes QA fixtures only, not `trip_id` offers.
- Public deals use the live shared 48h DB: 70+ first, then 65–69 only to fill, then 60–64 only if still needed; never below 60.
- Hourly scheduler job now re-evaluates the public feed from DB only and makes zero external search calls.
- Old hourly external scanner schedule removed.
- One daily wide external discovery scan remains and covers both configured origins (TLV + HFA), then immediately refreshes the public feed.
- Admin origin/scan filters and QA cleanup from v122/v123 retained.
