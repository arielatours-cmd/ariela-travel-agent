"""QA for Bezalel's task 1 (22.10): drop "(בכפוף לזמינות בפועל בחיפוש)" from
the summary (stage-1 run-8, Santorini; the business owner approved removing
it). The prompt already forbids it, but the model still wrote it, so
_strip_summary_availability_hedges removes it from any summary reply - the
approval-request summary and an updated "סיכום" alike - and never touches
ordinary conversation.

Offline. Run: python3 tools/qa_summary_availability_hedge.py
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

strip = chat._strip_summary_availability_hedges

# The exact live line (run-8, T2 Santorini), inside an updated summary
santorini = ("הנה הסיכום המעודכן:\n"
             "יעד: סנטוריני\n"
             "תאריכים: 02.06.2027 – 07.06.2027\n"
             "מעדיפים טיסה ישירה (בכפוף לזמינות בפועל בחיפוש)\n"
             "כבודה: טרולי לכל נוסע")
out = strip(santorini)
check("run-8 Santorini: hedge removed from the updated summary", "בכפוף לזמינות" not in out)
check("run-8 Santorini: the direct-flight fact itself stays", "מעדיפים טיסה ישירה\n" in out)
check("run-8 Santorini: every other line unchanged",
      out == santorini.replace(" (בכפוף לזמינות בפועל בחיפוש)", ""))

# The approval-request summary, other phrasings the prompt names
approval = "סיכום החופשה:\nטיסה: ישירה, בהתאם לזמינות בפועל.\nתקציב: עד 1500 ₪ לאדם.\nאם הכל נכון, כתוב מאשר."
out = strip(approval)
check("', בהתאם לזמינות בפועל' removed", out == "סיכום החופשה:\nטיסה: ישירה.\nתקציב: עד 1500 ₪ לאדם.\nאם הכל נכון, כתוב מאשר.")
out = strip("טיסה ישירה - בכפוף לזמינות\nאם הכל נכון, כתבי מאשרת.")
check("' - בכפוף לזמינות' at the end of a line removed", out == "טיסה ישירה\nאם הכל נכון, כתבי מאשרת.")
out = strip("טיסה ישירה (כפוף לזמינות באתר)\nכתוב מאשר")
check("'(כפוף לזמינות באתר)' removed", out == "טיסה ישירה\nכתוב מאשר")

# Not a summary -> untouched
chat_line = "בסדר, אחפש טיסות ישירות בהתאם לזמינות בפועל, ואחזור אלייך עם אפשרויות."
check("ordinary conversation is never touched", strip(chat_line) == chat_line)
check("a summary without any hedge is unchanged", strip(approval.replace(", בהתאם לזמינות בפועל", "")) == approval.replace(", בהתאם לזמינות בפועל", ""))
check("empty / None safe", strip("") == "" and strip(None) is None)

# Wired into the reply pipeline right after the summary completeness step
src = open(os.path.join(os.path.dirname(__file__), "..", "ariella_chat_clean.py"), encoding="utf-8").read()
check("step is in the Tinkerbell reply pipeline",
      "reply = _ensure_flight_summary_completeness(reply, state)\n    reply = _strip_summary_availability_hedges(reply)" in src)
check("the code-built fallback summary never writes the hedge", "בכפוף לזמינות" not in src.split("def _final_summary_fallback_text", 1)[1].split("\ndef ", 1)[0])

print()
print("ALL PASS" if not FAILED else f"{len(FAILED)} FAILED: {FAILED}")
sys.exit(1 if FAILED else 0)
