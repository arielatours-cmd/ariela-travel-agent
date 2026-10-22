"""QA for Bezalel's task 3 (22.10): the summary's baggage line is always the
canonical one built from state, in the three approved final wordings, and
replaces whatever "כבודה:" line the model wrote (including "2 מזוודות").

Why it looked "not built" in Corfu/Bali (run-7: "כבודה: 2 מזוודות") and
Heraklion (run-6: "3 מזוודות"): the #108 canonical line WAS built from
state - but its old label turned baggage_detail.checked_bag.count into
"N מזוודות". The approved wording has no count/size, by the highest tier.

Offline. Run: python3 tools/qa_canonical_baggage_line.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")
os.environ.setdefault("SCHEDULER_ENABLED", "false")

FAILED = []


def check(name, cond):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        FAILED.append(name)


import ariella_chat_clean as chat  # noqa: E402

CHECKED = 'כבודה: מזוודה 20–23 ק"ג לכל נוסע (בהתאם לתנאי חברת התעופה)'
TROLLEY = 'כבודה: טרולי 8–10 ק"ג לכל נוסע (בהתאם לתנאי חברת התעופה)'
HAND = 'כבודה: תיק יד לכל נוסע (בהתאם לתנאי חברת התעופה)'
line = chat._flight_baggage_line

# --- The three approved wordings -----------------------------------------------------------
check("checked bag -> approved wording", line({"baggage": ["checked_bag"]}) == CHECKED)
check("carry-on -> approved wording", line({"baggage": ["carry_on_only"]}) == TROLLEY)
check("hand bag -> approved wording", line({"baggage": ["personal_item"]}) == HAND)

# --- The live cases: a count in state never becomes "N מזוודות" -----------------------------
for count, where in ((2, "Corfu/Bali run-7"), (3, "Heraklion run-6")):
    f = {"baggage": ["checked_bag"], "baggage_detail": {"checked_bag": {"count": count, "size": "גדולה"}}}
    check(f"{where}: count={count} in state -> still the uniform per-passenger line", line(f) == CHECKED)
check("carry-on with a count -> no count either",
      line({"baggage": ["carry_on_only"], "baggage_detail": {"carry_on_only": {"count": 4}}}) == TROLLEY)

# --- Highest tier, uniform ----------------------------------------------------------------------
check("carry-on + checked -> the checked line (highest tier)", line({"baggage": ["carry_on_only", "checked_bag"]}) == CHECKED)
check("hand bag + carry-on -> the carry-on line", line({"baggage": ["personal_item", "carry_on_only"]}) == TROLLEY)
check("legacy 'checked' / 'carry_on' values map too",
      line({"baggage": ["checked"]}) == CHECKED and line({"baggage": ["carry_on"]}) == TROLLEY)
check("'none' (no baggage at all) -> the hand-bag line every ticket includes", line({"baggage": ["none"]}) == HAND)
check("nothing known -> None (no line invented)", line({"baggage": []}) is None and line({}) is None and line(None) is None)

# --- Replaces whatever the model wrote, in place ---------------------------------------------
state = {"flight": {"baggage": ["checked_bag"], "baggage_detail": {"checked_bag": {"count": 2}},
                    "connection_preference": "direct"},
         "budget_per_person": {"amount": 1500, "currency": "ILS"},
         "travelers": {"adults": 2}, "dates": {}}
reply = ("הנה הסיכום:\nיעד: קורפו\nכבודה: 2 מזוודות\nמעדיפים טיסה ישירה\nתקציב לאדם: 1500 ₪\n"
         "אם הכל נכון, כתבי מאשרת.")
out = chat._ensure_flight_summary_completeness(reply, state)
check("model's 'כבודה: 2 מזוודות' replaced by the canonical line", CHECKED in out and "2 מזוודות" not in out)
check("...in the same place, exactly once", out.count("כבודה:") == 1 and out.index(CHECKED) < out.index("מעדיפים טיסה ישירה"))
reply2 = "סיכום: כבודה: מזוודה אחת לכל נוסע ותיק קטן. תקציב לאדם: 1500 ₪. כתבי מאשרת."
check("any other model baggage wording is replaced too", CHECKED in chat._ensure_flight_summary_completeness(reply2, state))
missing = chat._ensure_flight_summary_completeness("סיכום: יעד קורפו. תקציב לאדם: 1500 ₪. ישירה. כתבי מאשרת.", state)
check("a summary with no baggage at all gets the canonical line added", CHECKED in missing)

# --- The code-built summaries use the same line ----------------------------------------------
summary = chat._flight_summary_text({"flight": {"baggage": ["carry_on_only"]}, "destination": {"places": ["קורפו"]}}) \
    if hasattr(chat, "_flight_summary_text") else ""
check("_flight_summary_text uses the canonical line", not summary or TROLLEY in summary)

print()
print("ALL PASS" if not FAILED else f"{len(FAILED)} FAILED: {FAILED}")
sys.exit(1 if FAILED else 0)
