# QA REPORT — Ariella v9.7.117

## Changes closed in this build
- Open-destination ranking changed to transparent points: each selected condition met = +1; seasonality = +1; deal score is tie-breaker only.
- Same-dates / other-destination alternatives now rank by request-match points first, so direct flight outranks a connection when direct was requested.
- Removed duplicate `Price` button from the lower flight-priority question; `Good price` remains in vacation preferences.
- Restored explicit `Connections are OK` option.
- Added regular-vacation cabin class: Economy / Premium Economy / Business / Any.
- Added ticket flexibility: Regular / Changeable / Refundable / Changeable & Refundable / Any.
- Cabin/flex selections are persisted and participate in point scoring.
- Personal vacation result list capped at 6 combined primary + alternative results.
- Lower “What matters” summary no longer repeats selected dates already shown in the card header.
- Follow-up alternative buttons are only shown when concrete dates/months exist and no date-flexibility was selected.
- Back navigation clears answers in all later wizard steps to prevent stale hidden state.
- QA fixture/test deals are disabled by default.

## Static QA
- Python compile: PASS (`public_site.py`, `app.py`).
- Jinja parse: PASS (24/24 templates).

## Live regression checks required after deploy
1. Same dates + another destination + Direct: direct result must rank before connection.
2. Back navigation: changing an earlier answer must clear all later answers.
3. New vacation card: no repeated dates; preferences shown once.
4. Open destination/time: verify point order on a real result set.
5. No-date/flexible-date search: no irrelevant “same dates / other dates” follow-up buttons.
6. Maximum six personal results.
7. Connections option visible again.
8. Cabin class and ticket-flexibility choices save and display/rank correctly.
9. Bucharest/Krakow destination images remain valid.
10. Tbilisi baggage data still requires separate supplier-data verification.
