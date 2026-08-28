# QA v9.7.127 — Ski questionnaire ready

- Ski autocomplete uses real resort rows; search matches resort, country (Hebrew/English), and optional region fields.
- Typing "צרפת" matches all 8 French resorts currently in the ski DB.
- Multi-select renders selected resorts as removable tags with × and keeps the hidden multi-select state in sync.
- Manual ski destination requires at least one selected resort; open/Ariella mode clears stale selections.
- Season guard now runs in both manual and Ariella-chooses modes.
- May: 6 resorts in the current DB include May in their season; UI shows a limited-season warning and backend searches only those resorts.
- June–September: no current DB resort is in season; UI blocks continuation and backend also rejects the dates.
- Airport transfer "לא משנה לי" hides/disables the later proximity priority.
- Ski choice-card text is centered.
- Final CTA changed to "תמליץ לי על חופשת סקי".
- Ski requests are saved as "חופשת סקי — <selected resort(s)>" in My Vacations; open mode is "חופשת סקי — אריאלה תבחר אתר סקי".
- Ski search resolves resorts -> in-season resort rows -> gateway airports, then ranks offers by fulfilled ski conditions.
- Open ski mode may trigger the focused external search when DB has no match; it is no longer DB-only.
- Existing v126 regular-vacation/check #2 code retained unchanged except shared helpers where required by ski integration.

Static QA: Python compilation passed; Jinja templates parsed successfully. Full Flask runtime not available in this local environment.
