# Ariella QA — v9.7.107

PASS:
- BOTH alternative buttons perform a 48-hour DB inventory lookup before any API search.
- DB miss is explicitly recorded before the API path starts.
- Same destination / other dates considers any recent date for that destination, so an October request can immediately reuse a November deal already in the 48h DB.
- If DB has no match, the wider date scan now covers the requested month plus the following month (bounded, max two months).
- Same dates / other destination remains DB-first before its controlled wider scan.
- Existing waiting overlay, no-raw-500 handling, pinned results, +1/+2 and BOOKER preserved.
- Python compilation and Jinja validation passed.
