# QA Report — Ariella v9.7.125

## Regular vacation — critical regression #2
- Good price is a soft +1 point only; it is not part of the hard/full-match gate.
- September/month and Direct remain objective customer restrictions when selected.
- Direct-flight detection accepts provider variants: `0`, `"0"`, `direct`, `nonstop`, `non-stop`; unknown stop data is not silently treated as direct.
- Open-destination results are diversified by destination before duplicate variants are allowed to fill remaining slots.
- Synthetic regression: CDG, BCN, AMS and ZAG direct September offers all remain above the divider; an October direct offer and a September connection do not.

## Exact dates + flexibility — DB first
- `date_flex_days` is applied by `_offer_matches_trip(... exact_dates=True)` for ±1/±2/±3 days.
- The shared 48h DB is evaluated before `run_customer_trip_search` is allowed.
- External customer scan runs only when no DB match exists for a specific/several destination request.

## Ski questionnaire
- One manual option: "לבחירת אתר סקי / מדינה" plus "אריאלה תבחר עבורי".
- Manual selection is a writable typeahead with multi-select tags and a curated resort/country list.
- Switching to Ariella-choice clears typed text and selected ski targets.
- Added typical ski-season guard: blocks clearly out-of-season selected resort/country combinations and warns on mixed/partial suitability.
- Ski family age-group choices now mirror the regular-vacation family choices.
- Added curated ski resort data file (40 resorts across major ski countries) including typical season months and gateway airports.

## Static QA
- Python compile: PASS
- Jinja parsing (regular + static templates): PASS
- DB-first ordering assertion: PASS
- Ski UI structural assertions: PASS
