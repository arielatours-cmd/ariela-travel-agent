# QA REPORT v9.7.131 — Regular Vacation No Results

## Code fixes
- My Vacations is resilient: one malformed trip row cannot crash the whole page.
- Exact-date alternative destination matching respects date flexibility (0–3 days).
- No Results UI now follows the agreed matrix:
  1. Fixed destination + exact dates (with/without flex): same destination/other dates OR other destination/same dates.
  2. Fixed destination + month (with/without flex): same destination/other month OR other destination/same month.
  3. Fixed destination + anytime: choose another destination only.
  4. Open destination + exact dates: try other dates only.
  5. Open destination + month: try another month only.
- A failed external scan is treated as no-result state and redirects to My Vacations; raw 500 is not intended.
- Other-destination action is rejected safely when destination was already open.

## Verification
- Python compile: PASS
- ZIP integrity: PASS
- Static assertions for all five No Results branches: PASS
- Full live Flask/API execution: NOT RUN in this environment; requires deployment QA.
