# Ariella QA — v9.7.106

PASS:
- Month-mode "same destination, other dates" now performs a bounded search instead of silently returning.
- It uses four representative 7-night windows in the selected month.
- Fresh offers created by the alternative search are pinned to the vacation before redirect, so My Vacations displays them immediately.
- Initial vacation creation remains DB-only: no SerpAPI call occurs until the customer explicitly clicks one of the two alternatives.
- Existing exact-date alternative behavior preserved.
- Python compilation and Jinja parsing passed.
