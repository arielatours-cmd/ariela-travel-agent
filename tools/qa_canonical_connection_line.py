"""QA for PR #129 (22.10, second rework). The business owner rejected any
filtering of the model's text by words/patterns. The summary's
connection-preference line now works exactly like "כבודה:"/"תאריכים:":

  - it has a fixed literal label, "העדפת טיסה:" (_CONNECTION_SUMMARY_LABEL);
  - _ensure_flight_summary_completeness finds it ONLY by that literal label
    and replaces it with the line built from state (_flight_connection_
    summary_line), or drops it when the preference isn't known;
  - content is used only to decide whether the fact is MISSING (to add the
    line, never duplicate) - never to choose what to replace;
  - the static prompt asks Tinkerbell to write the line with that label.

Santorini (run-8): "העדפת טיסה: מעדיפים טיסה ישירה (בכפוף לזמינות בפועל
בחיפוש)" -> "העדפת טיסה: מעדיפים טיסה ישירה".

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
LABEL = "העדפת טיסה:"


def state(pref):
    flight = {"baggage": ["carry_on_only"]}
    if pref is not None:
        flight["connection_preference"] = pref
    return {"flight": flight, "budget_per_person": {"amount": 1500, "currency": "ILS"},
            "travelers": {"adults": 2}, "dates": {}}


def summary(connection_line):
    return ("הנה הסיכום המעודכן:\n- יעד: סנטוריני\n"
            f"- {connection_line}\n"
            "- כבודה: טרולי\n- 2 מבוגרים, תקציב לאדם 1500 ₪\nאם הכל נכון, כתוב מאשר.")


# --- The labelled line ------------------------------------------------------------------------------
line = chat._flight_connection_summary_line
check("label is the fixed literal 'העדפת טיסה:'", chat._CONNECTION_SUMMARY_LABEL == LABEL)
check("direct -> 'העדפת טיסה: מעדיפים טיסה ישירה'", line({"connection_preference": "direct"}) == "העדפת טיסה: מעדיפים טיסה ישירה")
check("no preference -> 'העדפת טיסה: אין העדפה לטיסה ישירה'",
      line({"connection_preference": "אין העדפה"}) == "העדפת טיסה: אין העדפה לטיסה ישירה")
check("unknown -> None", line({}) is None)
check("value function unchanged ('מעדיפים טיסה ישירה')", chat._flight_connection_line({"connection_preference": "direct"}) == "מעדיפים טיסה ישירה")

# --- Santorini: found by the label, rebuilt from state -----------------------------------------------
out = ensure(summary("העדפת טיסה: מעדיפים טיסה ישירה (בכפוף לזמינות בפועל בחיפוש)"), state("direct"))
check("Santorini: the labelled line is rebuilt from state, no hedge",
      "- העדפת טיסה: מעדיפים טיסה ישירה\n" in out and "זמינות" not in out)
check("Santorini: every other line untouched", out.startswith("הנה הסיכום המעודכן:\n- יעד: סנטוריני\n")
      and "- 2 מבוגרים, תקציב לאדם 1500 ₪" in out and out.rstrip().endswith("כתוב מאשר."))
out = ensure(summary("העדפת טיסה: מעדיפים טיסה ישירה"), state("אין העדפה"))
check("a labelled line that contradicts state -> state wins", "- העדפת טיסה: אין העדפה לטיסה ישירה\n" in out)
out = ensure(summary("העדפת טיסה: מעדיפים טיסה ישירה (בכפוף לזמינות)"), state(None))
check("unknown preference -> the labelled line is dropped entirely (no stray bullet)",
      LABEL not in out and "\n-\n" not in out and "- יעד: סנטוריני\n- כבודה:" in out)
out = ensure(summary("העדפת טיסה: מעדיפים טיסה ישירה"), state("direct"))
check("already canonical -> unchanged", out.count(LABEL) == 1 and "- העדפת טיסה: מעדיפים טיסה ישירה\n" in out)

# --- No content detection: an UNLABELLED line is never chosen for replacement ------------------------
unlabelled = summary("מעדיפים טיסה ישירה (בכפוף לזמינות בפועל בחיפוש)")
out = ensure(unlabelled, state("direct"))
check("an unlabelled line is never rewritten (no content-based selection)",
      "- מעדיפים טיסה ישירה (בכפוף לזמינות בפועל בחיפוש)\n" in out)
check("...and since the fact IS mentioned, no duplicate line is added", LABEL not in out)

# --- Missing -> the labelled line is added ---------------------------------------------------------------
out = ensure("סיכום:\n- יעד: סנטוריני\n- כבודה: טרולי\n- 2 מבוגרים, תקציב לאדם 1500 ₪\nכתוב מאשר.", state("direct"))
check("a summary with no connection line gets the labelled canonical line", "העדפת טיסה: מעדיפים טיסה ישירה" in out)

# --- Code-built summaries carry the label too -------------------------------------------------------------
check("_flight_summary_text uses the labelled line",
      "העדפת טיסה: מעדיפים טיסה ישירה" in chat._flight_summary_text({"flight": {"connection_preference": "direct"}}))

# --- The prompt asks for the label; the content regexes are gone -------------------------------------------
check("TINKERBELL_SYSTEM asks for the 'העדפת טיסה:' line",
      'העדפת טיסה: מעדיפים טיסה ישירה' in chat.TINKERBELL_SYSTEM and 'העדפת טיסה: אין העדפה לטיסה ישירה' in chat.TINKERBELL_SYSTEM)
src = open(os.path.join(os.path.dirname(__file__), "..", "ariella_chat_clean.py"), encoding="utf-8").read()
check("_CONNECTION_LINE_MARKERS / _OTHER_SUMMARY_FACT_MARKERS / _replace_connection_summary_line removed",
      "_CONNECTION_LINE_MARKERS" not in src and "_OTHER_SUMMARY_FACT_MARKERS" not in src
      and "_replace_connection_summary_line" not in src)
check("the earlier word-list hedge filter is gone too", "availability_hedge" not in src.lower())

print()
print("ALL PASS" if not FAILED else f"{len(FAILED)} FAILED: {FAILED}")
sys.exit(1 if FAILED else 0)
