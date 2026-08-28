# QA Report — Ariella v9.7.122

## Passed before packaging
- Python compile: 46 files.
- Jinja parse: 50 templates/embedded dashboards.
- Check #2 runtime regression: PASS.
  - Paris September direct = primary/full match.
  - Madrid October = alternative (requested month missed).
  - Amsterdam/Zagreb/Barcelona September with connection = alternatives (direct missed).
- Four-deal customer scenario: PASS.
  - LCA Nov = 10 points.
  - ZRH Nov = 6 points.
  - CDG Sep = 6 points.
  - TBS Dec = 3 points.
  - Tie ZRH/CDG resolved by existing deal-quality score.
- Destination-condition matrix: 30/30 configured destinations; every condition key explicit.
- QA fixture inventory disabled; persisted QA AIR / qa_test_deal rows purged on init; qa_test_mode reset to off.
- Admin: scan filter/sort + origin filter/sort (TLV/HFA); scan details show origin → destination.
- Admin headings/filter controls enlarged.
- Wide-scan job planning includes both TLV and HFA.
- Baggage prices removed from deal cards and WhatsApp formatter; inclusion only.
- Open-destination account image uses curated random image pool.
- Root/static mirrors verified identical for changed files.

## Still requires live production proof
- HFA remains NOT PASSED until an actual HFA-origin deal is found and visible in the production admin dashboard.
