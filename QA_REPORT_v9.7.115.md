# QA REPORT — Ariella v9.7.115

## Status
PASS for static/template and targeted ranking regression tests.

## Automated/static checks
- Python compile: PASS.
- Root Jinja templates: 24/24 PASS.
- Mirrored static Jinja templates: 24/24 PASS.
- Seasonal profiles: 30/30 current destinations covered.
- Open-destination beach + pleasant weather, March: Bangkok ranks above Athens.
- Same preference, July: Athens ranks above Bangkok.
- Direct-flight priority: direct itinerary receives a materially higher open-search rank than a comparable connection itinerary.
- Alternative fit: direct-flight match receives more condition points than a connection when direct was requested.
- Additional-choice summary no longer repeats destination/search mode already shown in the card title.
- Q4 date-priority UI is hidden + disabled when date mode is not exact/month, preventing stale checked state.
- Bucharest and Krakow use replacement destination-image URLs.

## Live regression checks to repeat
1. Same dates + another destination + direct requested: direct result must rank above connection alternatives.
2. Ariella chooses dates — one destination: Q4 must not show “selected dates”.
3. Ariella chooses dates — destination multi-select: Q4 must not show “selected dates”.
4. Ariella chooses destination/month with vacation preferences: order must reflect both preference and season.
5. My Vacations card: no repeated destination/dates/travelers/budget; preferences appear once.
6. Bucharest and Krakow: image visible.
