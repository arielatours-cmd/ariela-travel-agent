# Ariella QA — v9.7.107

## Critical legacy-deal blocker fixed
QA found legacy Wizz records with missing return departure/arrival times while the public site still presented them as bookable.

Fix:
- Public deals now require a complete round trip: outbound/return dates plus all four departure/arrival times.
- Public deal cards also require a recommended supplier and stored actionable booking_request.
- Home-page deal cards use the same bookability gate.
- `/book/<offer>` fails closed for incomplete legacy records instead of sending a customer to an invalid booking flow.
- Personal-vacation matching already required complete round trips and remains unchanged.

## Preserved regressions
- v9.7.94 retroactive +1/+2.
- v9.7.93 BOOKER recommended-supplier-only behavior.
- No competing supplier marketplace fallback.

## QA
- Python compilation passed.
- Jinja parsing passed.
- Static route/filter checks passed.
