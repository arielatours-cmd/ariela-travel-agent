# Ariella QA — v9.7.101

## Retroactive +1/+2
Arrival-day badges no longer require a fresh scan.
- Explicit arrival dates remain authoritative.
- Legacy offers fall back to departure clock + total duration.
- If duration is absent, an arrival clock earlier than departure clock yields +1.
- Long-haul duration fallback can yield +2 as well.
- Applies independently to outbound and return.

Example regression:
23:55 departure + 160 minutes => +1, even when return_arrival_date is absent.

## Preserved
- v9.7.93 BOOKER recommended-supplier-only behavior.
- No competing booking marketplace fallback.
- Existing scanner persistence of arrival dates for new offers.

## QA
- Python compilation passed.
- Jinja parsing passed.
- Helper regression tests passed for same-day, +1 legacy, +1 duration, and +2 duration.
