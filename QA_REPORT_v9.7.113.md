# QA Report — Ariella v9.7.113

## Changes verified
- Open-destination vacation preferences (`holiday_priorities`) now affect destination ranking.
- Vacation preferences are shown in My Vacations under `מה מחפשים בחופשה`.
- Duplicate `חיפוש יעד` summary removed from vacation card.
- Additional-choice typography enlarged; yellow chip background removed.
- Initial alternative deals are capped to ±1 month for each requested leg.
- Separate outbound/return months are evaluated independently.
- When `התאריכים שבחרתם` is selected, date match receives stronger alternative-ranking weight.
- `אריאלה תבחר` / `לא משנה` hides and clears `התאריכים שבחרתם`.
- `תנו לאריאלה לבחור` remains exclusive against the other flight priorities.

## QA
- Python compile: PASS
- Jinja templates: 24/24 PASS
- Logic regression: PASS
  - Nature preference ranks Tbilisi above Athens when deal quality is otherwise equal.
  - Adjacent-month alternative accepted.
  - Three-month-away alternative rejected in initial result set.
  - Separate Feb outbound / Mar return request accepts Jan/Apr boundary but rejects December.
  - Vacation preferences displayed; duplicate destination-search row absent.

## Manual regression to repeat after deploy
1. Same dates + different destination (previous error case).
2. Ariella chooses dates -> `התאריכים שבחרתם` must not appear.
3. Specific dates + mark dates important -> exact/near-date offers must rank above looser alternatives.
4. Ariella chooses destination + select vacation preferences -> shown destination should reflect those preferences.
5. My Vacations card -> no duplicated data; vacation preferences visible; no yellow backgrounds.
