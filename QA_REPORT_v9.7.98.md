# Ariella QA — v9.7.106

Root cause corrected:
`recent_offers()` normalized return times to top-level fields but did not normalize
outbound departure/arrival times. Public filtering and the card macro therefore
did not share one canonical representation.

Fix:
- Normalize outbound departure_time, arrival_time, duration alongside return fields.
- Keep the final strict public gate immediately before rendering both lists.
- Reject missing, blank, '-' and '—' values.
- Remove Jinja filtered-loop dependency; Python provides sanitized lists.
- Add HTML build marker ARIELA_BUILD:9.7.106 so live deployment can be verified.

QA: Python compile PASS; all Jinja templates parse PASS; canonical field mapping PASS.
