"""QA for PR #129 rework (22.10): the business owner rejected the word-list
hedge filter for "מעדיפים טיסה ישירה (בכפוף לזמינות בפועל בחיפוש)"
(Santorini, run-8). Instead the summary's connection-preference line is
rebuilt from state - like the baggage and dates lines - by
_ensure_flight_summary_completeness, using _flight_connection_line:
"מעדיפים טיסה ישירה" / "אין העדפה לטיסה ישירה", and no line at all when the
preference isn't known.

Offline. Run: python3 tools/qa_canonical_connection_line.py
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

ensure = chat._ensure_flight_summary_completeness


def state(pref):
    flight = {"baggage": ["carry_on_only"]}
    if pref is not None:
        flight["connection_preference"] = pref
    return {"flight": flight, "budget_per_person": {"amount": 1500, "currency": "ILS"},
            "travelers": {"adults": 2}, "dates": {}}


def summary(connection_text):
    return ("הנה הסיכום המעודכן:\n- יעד: סנטוריני\n"
            f"- {connection_text}\n"
            "- כבודה: טרולי\n- 2 מבוגרים, תקציב לאדם 1500 ₪\nאם הכל נכון, כתוב מאשר.")


# --- _flight_connection_line: the prompt's own summary wording --------------------------------
line = chat._flight_connection_line
check("direct -> 'מעדיפים טיסה ישירה'", line({"connection_preference": "direct"}) == "מעדיפים טיסה ישירה")
check("known no-preference -> 'אין העדפה לטיסה ישירה'", line({"connection_preference": "אין העדפה"}) == "אין העדפה לטיסה ישירה")
check("no_direct_route sentinel unchanged", line({"connection_preference": "no_direct_route"}) == "טיסה עם עצירה (אין טיסה ישירה ליעד)")
check("unknown -> None", line({}) is None and line(None) is None)

# --- The live Santorini case ------------------------------------------------------------------------
out = ensure(summary("מעדיפים טיסה ישירה (בכפוף לזמינות בפועל בחיפוש)"), state("direct"))
check("Santorini: the line is rebuilt from state - no availability hedge", "- מעדיפים טיסה ישירה\n" in out and "זמינות" not in out)
check("Santorini: the bullet is kept, every other line untouched",
      out.startswith("הנה הסיכום המעודכן:\n- יעד: סנטוריני\n- מעדיפים טיסה ישירה\n")
      and "- 2 מבוגרים, תקציב לאדם 1500 ₪" in out and out.rstrip().endswith("כתוב מאשר."))

# --- Any other wording on that line is replaced too ----------------------------------------------
for model_line, pref, expected in (
        ("טיסה: ישירה, בהתאם לזמינות בפועל", "direct", "מעדיפים טיסה ישירה"),
        ("ישירה או עם קונקשן - מה שיצא זול יותר", "אין העדפה", "אין העדפה לטיסה ישירה"),
        ("מעדיפים טיסה ישירה", "אין העדפה", "אין העדפה לטיסה ישירה"),  # contradicts state -> state wins
):
    out = ensure(summary(model_line), state(pref))
    check(f"{model_line!r} with {pref!r} -> '{expected}'", f"- {expected}\n" in out and model_line not in out)
check("exactly one connection line after replacement",
      ensure(summary("טיסה: ישירה, בהתאם לזמינות בפועל"), state("direct")).count("ישיר") == 1)

# --- Unknown preference -> no line at all -------------------------------------------------------------
out = ensure(summary("מעדיפים טיסה ישירה (בכפוף לזמינות)"), state(None))
check("unknown preference -> the model's connection line is dropped", "ישיר" not in out and "- יעד: סנטוריני" in out)

# --- A line combining several facts is never rewritten (nothing else lost) -----------------------------
combined = "סיכום: יעד רומא, 2 מבוגרים, טיסה ישירה בלבד. אם הכל נכון, כתבי מאשרת."
check("a multi-fact line is left as it is", "יעד רומא, 2 מבוגרים, טיסה ישירה בלבד" in ensure(combined, state("direct")))

# --- Missing line still added (existing behaviour, new wording) ---------------------------------------
out = ensure("סיכום:\n- יעד: סנטוריני\n- כבודה: טרולי\n- 2 מבוגרים, תקציב לאדם 1500 ₪\nכתוב מאשר.", state("direct"))
check("a summary with no connection line gets the canonical one", "מעדיפים טיסה ישירה" in out)

# --- The word-list filter is gone ------------------------------------------------------------------------
src = open(os.path.join(os.path.dirname(__file__), "..", "ariella_chat_clean.py"), encoding="utf-8").read()
check("_strip_summary_availability_hedges and its regex are removed", "availability_hedge" not in src.lower() and "AVAILABILITY_HEDGE" not in src)

print()
print("ALL PASS" if not FAILED else f"{len(FAILED)} FAILED: {FAILED}")
sys.exit(1 if FAILED else 0)
