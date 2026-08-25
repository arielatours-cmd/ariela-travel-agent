# Ariella QA — v9.7.104

## Previous-deals leak fixed
Live QA on v9.7.95 showed incomplete legacy Wizz offers still rendering under "Previous deals".

v9.7.104 hardens the gate at three levels:
1. Candidate offers are localized/mapped first, then filtered through the public-bookability rule.
2. Both `offers` and `previous_offers` independently re-check the same rule at the split point.
3. The previous-deals template loop also refuses rows without return departure/arrival times.

A public deal requires:
- outbound and return dates
- outbound departure and arrival times
- return departure and arrival times
- a recommended supplier / airline
- an actionable stored booking_request for BOOKER

## Preserved
- BOOKER recommended supplier only.
- Retroactive +1/+2.
- Personal-vacation complete-roundtrip checks.

## QA
- Python compilation passed.
- Jinja parsing passed.
- Previous-deals route and template guards verified.
