# Ariella QA — v9.7.108

## Included in this build

### Regular vacation fixes
- Removed "Convenient flight times".
- Removed "Best price" and "Best balance" from the selected-destination Q04 screen.
- "Maximize the trip" is now a ranking preference, not a hard filter:
  - arrival by 10:00 gets strongest preference;
  - return departure from 20:00 gets strongest preference.
- Budget behavior from 107 is preserved.
- Missing destination image coverage added for Zurich, Krakow, Larnaca and Athens, with generic fallback still active.
- Customer-selected IATA destinations are no longer restricted to Ariella's curated discovery list.

### Fallback flow
- "Same destination — other dates" always checks the 48h DB first.
- If DB is empty, it runs a fresh controlled scan of the same selected destination(s).
- The original requested dates are restored after that alternative scan.
- If the alternative-date scan also finds nothing, the same question is not shown again; only "same dates — another destination" remains.
- "Same dates — another destination" checks the 48h DB first.
- If there is no full DB match, Ariella displays up to 3 closest existing DB offers ranked by the number of customer conditions they satisfy (even one condition is enough).
- The account monkey/wait overlay remains attached to explicit alternative-search form submits.

### Business flight route
- New third entry card: Business flight.
- Completely separate six-step business questionnaire:
  B1 destination(s)
  B2 exact dates + optional flexibility ±1/±2/±3 days; if flexible, time constraints are hidden
  B3 traveler count
  B4 cabin class
  B5 customer flight conditions
  B6 budget
- Airport field supports one or multiple airports, with an explicit helper note.
- If no date flexibility and an arrival deadline exists, the search may also inspect departure one day earlier.
- Business results are NOT hard-filtered by preferences.
- Each selected/entered condition met by an offer earns one point.
- Results are sorted by points first, then total duration, then price.
- Under each business deal, `display_reasons` contains only the conditions that flight satisfies.

### Ski safeguard
- Fixed ski mode detection to use `vacation_type == ski`.
- Ski gateway codes can use the ski-airport list even when not in the regular discovery list.

### Destination Intelligence
- Manifest included for the v0.1 Destination Intelligence DB.
- It is intentionally NOT activated in this build until regular-route regression QA is complete.

## Static QA
- Python compilation: PASS
- Jinja template parsing: PASS
- Business route present in frontend and backend: PASS
- Removed regular Q04 options absent: PASS
- Fallback state flags present: PASS
- Business destination multi-select picker support: PASS

## Live QA required after deployment
1. Regression: exact dates, multi-destination, Ariella chooses, budget fallback, direct-flight filter, baggage.
2. Re-test failed case: several destinations -> same destinations / other dates -> DB empty -> monkey -> API scan.
3. Re-test destination images: Zurich / Krakow / Larnaca.
4. Test maximize ranking with at least two offers whose arrival/return times differ.
5. Test business flow and business point ranking.
