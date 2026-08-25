# Ariella QA — v9.7.104

PASS:
- Initial personal-vacation request checks database only.
- No automatic SerpAPI search occurs when there is no DB match.
- No-match vacation is saved with status `no_database_match`.
- My Vacations can immediately show the two agreed choices.
- A new search can start only after an explicit customer choice.
- Existing DB match behavior remains unchanged.
- Python compilation and Jinja parsing passed.
