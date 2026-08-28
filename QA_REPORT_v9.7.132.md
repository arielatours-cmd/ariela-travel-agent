# QA REPORT v9.7.132 — My Vacations crash

## Root cause
`_closest_condition_matches()` in public_site.py called `_customer_destination_codes()`.
That function exists in scanner.py but is not imported into public_site.py.
When a No Results action set `_show_closest_fallback=True`, opening /account
executed that function and raised NameError, which produced HTTP 500.

## Fix
- Replaced the undefined function call with the local `_trip_destination_codes(trip)`.
- Added a try/except around closest-fallback calculation so a future fallback error
  cannot take down the whole My Vacations page.
- Existing saved vacations with `_show_closest_fallback=True` require no deletion;
  after deployment they should load normally.

## Static verification
- Python compilation: PASS
- Undefined reference `_customer_destination_codes` in public_site.py: REMOVED
- Fallback calculation guard: PRESENT
- ZIP integrity: PASS

Full live Flask execution still requires deployment QA.
