# QA Report v9.7.126 — Check #2

## Scenario
Open destination / September 2026 / good price / direct flight / unlimited budget.

## Fixed
- One authoritative stop-count resolver is used for matching.
- Legacy/provider offers with NULL `stops` but explicit empty connection arrays are normalized to direct instead of being shown as direct while rejected by matching.
- Round-trip direct matching checks both legs when return stop data exists.
- Unknown stop data is no longer rendered as "direct" on the deal card.
- Good price remains a +1 ranking condition only; it is not a full-match gate.

## Regression results
- Multiple September direct deals remain in the primary group: PASS.
- A direct September deal without the good-price point remains in the primary group: PASS.
- Connection deal goes below divider: PASS.
- October deal goes below divider: PASS.
- Mixed provider encodings: `0`, `"0"`, and empty connection arrays: PASS.
