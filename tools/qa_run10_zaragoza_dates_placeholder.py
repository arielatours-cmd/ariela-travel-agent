"""QA for run-10 #2 (Zaragoza, Shaked's full transcript, relayed by Shlomo
22.10.2026, qa/reports/2026-10-22-stage1-live-run10.md):

The final summary turn's structured block already represented the dates
via the literal {{DATES}} placeholder ("סרגוסה, {{DATES}}") - exactly the
mechanism _dates_truth_hint instructs Tinkerbell to use instead of ever
writing a calendar date herself. But _ensure_flight_summary_completeness's
own "is a date already mentioned" check only recognized a literal
DD.MM.YYYY digit pattern or a Hebrew month name - and this function runs
in _call_tinkerbell BEFORE _render_date_placeholders substitutes {{DATES}}
into real digits, so at the point this check ran, the text genuinely
contained neither. Dates got flagged as "missing" and a second, redundant
"תאריכים:" line was appended separately, right before the confirmation
sentence - even though the real date was already sitting right there in
the structured block, just not yet rendered.

Fix: the unresolved placeholder token itself (checked the same lenient
way _DATE_PLACEHOLDER_RE already does elsewhere) now also counts as
"dates are present" for this missing-check, alongside the existing
digit-pattern and Hebrew-month-name recognition.

Root-cause note: Shaked's transcript also showed the "כבודה: 2 מזוודות"
line not getting replaced by the canonical baggage line in the SAME
turn. Reproducing that specific symptom directly (baggage line on its
own clear line, no placeholder involved) did NOT reproduce the failure -
_ensure_flight_summary_completeness's baggage-replace logic worked
correctly in isolation. The real reply's one long, unverbatim paragraph
(redacted in Shaked's relay as "(a long paragraph)") may well contain
something (an unclosed parenthesis, an embedded "?" or ".") that shifts
_split_sentences's own sentence boundaries in a way this reproduction
can't capture without the real text - flagged separately, not fixed here.

Run: python3 tools/qa_run10_zaragoza_dates_placeholder.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import ariella_chat_clean as chat

FAILED = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


STATE = {
    "flight": {"baggage": ["checked_bag"], "baggage_detail": {"checked_bag": {"count": 2}},
               "connection_preference": "direct"},
    "budget_per_person": {"amount": 1500, "currency": "ILS"},
    "dates": {"departure": "2027-06-12", "return": "2027-06-17"},
    "travelers": {"adults": 2},
}

# =====================================================================
# 1. The Zaragoza shape: dates represented only via the unresolved
#    {{DATES}} placeholder - must NOT be treated as missing.
# =====================================================================
TEXT_WITH_PLACEHOLDER = (
    "סרגוסה, {{DATES}}\n"
    "יציאה: נתב\"ג (TLV) / נחיתה: סרגוסה, ספרד\n"
    "נוסעים: 2 מבוגרים\n"
    "כבודה: 2 מזוודות\n"
    "מעדיפים טיסה ישירה (בכפוף לזמינות בפועל)\n"
    "תקציב: עד 1,500 ש\"ח לאדם\n"
    "אם כל הפרטים נכונים, כתוב מאשר."
)
out = chat._ensure_flight_summary_completeness(TEXT_WITH_PLACEHOLDER, STATE)
check("dates via an unresolved {{DATES}} placeholder: no redundant 'תאריכים:' line appended",
      "תאריכים:" not in out)
check("...the placeholder itself is left untouched here (rendered later, by _render_date_placeholders)",
      "{{DATES}}" in out)
check("the baggage line is still correctly replaced with the canonical wording (unaffected by this fix)",
      'כבודה: מזוודה 20–23 ק"ג לכל נוסע (בהתאם לתנאי חברת התעופה)' in out)

# =====================================================================
# 2. {{DATE_OPTIONS}} (the pending-candidate variant) is recognized the
#    same way.
# =====================================================================
TEXT_WITH_DATE_OPTIONS = (
    "סרגוסה, {{DATE_OPTIONS}} - מתאים?\n"
    "נוסעים: 2 מבוגרים\n"
    "אם כל הפרטים נכונים, כתוב מאשר."
)
out2 = chat._ensure_flight_summary_completeness(TEXT_WITH_DATE_OPTIONS, STATE)
check("dates via an unresolved {{DATE_OPTIONS}} placeholder: no redundant 'תאריכים:' line either",
      "תאריכים:" not in out2)

# =====================================================================
# 3. Regression: genuinely missing dates (no placeholder, no digit, no
#    Hebrew month name anywhere) still get the canonical line appended -
#    this fix must not silently swallow a real omission.
# =====================================================================
TEXT_TRULY_MISSING = (
    "סרגוסה, יעד מעולה לזוג.\n"
    "נוסעים: 2 מבוגרים\n"
    "כבודה: 2 מזוודות\n"
    "אם כל הפרטים נכונים, כתוב מאשר."
)
out3 = chat._ensure_flight_summary_completeness(TEXT_TRULY_MISSING, STATE)
check("genuinely missing dates (no placeholder at all): the canonical line IS still appended",
      "תאריכים: 12.06.2027 – 17.06.2027" in out3)

# =====================================================================
# 4. Regression: the two pre-existing recognized forms (literal digits,
#    Hebrew month name) still work exactly as before.
# =====================================================================
TEXT_LITERAL_DIGITS = "סרגוסה, 12.06.2027–17.06.2027\nנוסעים: 2 מבוגרים\nאם כל הפרטים נכונים, כתוב מאשר."
check("literal DD.MM.YYYY dates already present: not flagged as missing (unchanged)",
      "תאריכים:" not in chat._ensure_flight_summary_completeness(TEXT_LITERAL_DIGITS, STATE))

TEXT_HEBREW_MONTH = "סרגוסה, 4 עד 10 ביוני\nנוסעים: 2 מבוגרים\nאם כל הפרטים נכונים, כתוב מאשר."
check("a Hebrew month-name date already present: not flagged as missing (unchanged)",
      "תאריכים:" not in chat._ensure_flight_summary_completeness(TEXT_HEBREW_MONTH, STATE))

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL RUN-10 ZARAGOZA DATES-PLACEHOLDER TESTS PASSED")
