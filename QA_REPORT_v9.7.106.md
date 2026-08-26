# Ariella QA — v9.7.107

## Architecture
- PASS: First screen fully separates Regular Vacation and Ski Vacation.
- PASS: Regular route keeps the existing six-question questionnaire and has no ski option inside it.
- PASS: Ski route is a separate seven-question questionnaire.
- PASS: Inactive-route fields are disabled client-side, so answers cannot leak between questionnaires.

## Ski questionnaire
S1 resort/country: one / several / Ariella chooses.
S2 exact dates / month(s) / Ariella chooses ski period.
S3 travelers.
S4 skill level.
S5 airport transfer: up to 1.5h / up to 3h / no preference.
S6 ski priorities.
S7 flight budget.

## Ski DB
- Starter DB expanded to 31 resorts.
- Each resort stores country, gateway airports, transfer estimate, supported skill levels and internal ranking scores.
- Country selection is supported for users who do not know a resort name.
- Ski request is resolved through Ski DB first, then translated to relevant flight gateway airports.

## Regular-route fixes included
- Initial exact-date DB match is exact only. Same-month alternatives cannot appear until the customer explicitly requests other dates.
- QA fixtures enabled by default in this testing build unless qa_test_mode is explicitly set to 0.
- Per-person budget keeps the agreed 10% hard tolerance.
- Multiple-destination display and neutral nature image remain included.

## Static QA
- Python compile: PASS
- Jinja parse: PASS
- Required route selectors and ski fields: PASS
