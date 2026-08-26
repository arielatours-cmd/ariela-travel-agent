# Ariella QA — v9.7.105

Included:
- Isolated deterministic QA inventory: regular + ski. Fixtures never enter persistent offers/history.
- Q01 ski is now an independent add-on to one destination / several destinations / Ariella suggestions.
- Several-destination vacation card shows all selected destinations and uses a neutral green-mountain image (snow reserved for ski).
- Open/Ariella-suggestions DB-first no longer incorrectly requires global score >=65.
- Per-person budget is a hard filter with 10% tolerance.
- Q04 deterministic AND filters added for direct, baggage, dates, convenient times and ski proximity.
- Ranking hooks added for best price, maximize trip, ski proximity and balance.
- Choice cards keep fixed dimensions when selected; only the checkmark/state changes.
- Starter Ski Resort DB added at data/ski_resorts.json.

QA fixture test targets:
- Regular: SOF, November 2026 (exact 10–18 Nov available).
- Ski: January 2027 (SOF/TBS/GVA/MXP fixtures).

Static QA:
- Python compilation PASS.
- Jinja template parsing PASS.
- QA fixtures are gated by qa_test_mode only.
