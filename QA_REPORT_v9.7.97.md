# Ariella QA — v9.7.103

## Root-cause hardening: partial legacy deals
Live production on v96 still rendered legacy Wizz cards with em-dash return times.

v97 adds a final rendering gate independent of earlier scan/list classification:
- strict validation of all six round-trip date/time fields
- rejects None, blank, dash and em-dash values
- sanitizes BOTH current and previous lists immediately before render
- template itself independently refuses cards missing any flight-time field
- regression fixtures reproduce the exact production defect (missing / em-dash return times)

This is intentionally defense-in-depth so stale legacy database payloads cannot leak into the public UI even if earlier classification changes.

## Preserved
BOOKER recommended supplier, +1/+2, personal vacation logic.

## QA PASS
Python compilation, Jinja parsing, good complete offer accepted, broken None offer rejected, broken em-dash offer rejected.
