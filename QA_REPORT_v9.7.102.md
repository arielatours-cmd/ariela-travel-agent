# Ariella QA — v9.7.102

PASS:
- Both alternative buttons now query only 48-hour DB inventory first.
- API search runs only when DB has no usable match.
- Same destination / other dates: DB-first, then bounded wider date scan.
- Same dates / other destination: DB-first, then controlled 10-destination wider scan.
- Alternative search exceptions are contained; no raw Internal Server Error page.
- Fresh results are pinned to the existing vacation and displayed after redirect.
- Monkey/coconut waiting overlay appears immediately after either alternative button is clicked.
- Destination input fields enlarged for laptop use.
- Python compilation and Jinja parsing passed.
