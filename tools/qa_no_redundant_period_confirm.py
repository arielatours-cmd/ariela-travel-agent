"""QA for Bezalel's task 2 (22.10): no redundant confirmation of a clear
period the customer already stated ("סוף נובמבר" -> no "מתכוונת לסוף
נובמבר 2026, נכון?" before the options are shown). Shaked: run-1 S5,
run-5 W5, run-6 V1.

Root cause: the guided dates extractor returns confidence "low" whenever
departure/return are still unknown, so a plain period answer went through
_guided_confirm_hint. Now a period-only "low" answer gets NO hint (the
question stays open; the period is saved) and the existing date-options
flow ({{DATE_OPTIONS}} / _dates_truth_hint, untouched) takes over.
A genuinely unclear answer, or a non-dates field, still gets the confirm
hint exactly as before.

Offline (the guided extractor call is stubbed). Run:
python3 tools/qa_no_redundant_period_confirm.py
"""
import json
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")
os.environ.setdefault("SCHEDULER_ENABLED", "false")

FAILED = []


def check(name, cond):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        FAILED.append(name)


import ariella_chat_clean as chat  # noqa: E402

CONFIRM_MARK = "לא בביטחון מלא"  # _guided_confirm_hint's own wording


def run(field, extracted, message, state_extra=None):
    def fake(key, model, system_static, system_dynamic, history, msg, max_tokens, include_history=True, source="other"):
        if source == "guided_extract":
            return json.dumps(extracted, ensure_ascii=False)
        return "{}"
    trip_state = {
        "guided": {"current_question": field, "attempts": 0, "answered": []},
        "destination": {"places": ["קרקוב"]},
        "requested_services": ["flights"],
        "dates": {}, "travelers": {"adults": None}, "flight": {"baggage": []},
    }
    trip_state.update(state_extra or {})
    trip_update = json.loads(json.dumps(trip_state))
    with patch.object(chat, "_post_claude", side_effect=fake):
        return chat._handle_guided_extraction_turn("key", "model", message, [], trip_state, trip_update,
                                                   {"dates", "travelers", "baggage"})


# --- The live case: "סוף נובמבר" -> period only, low --------------------------------
period_only = {"status": "answered", "departure": None, "return": None, "nights": None,
               "period": "סוף נובמבר 2026", "flexibility_days": None, "confidence": "low",
               "also_mentioned": {}, "correction": None}
r = run("dates", period_only, "בסוף החודש הבא, שבוע")
check("period only + low -> no confirm hint ('מתכוונת לסוף נובמבר 2026?' is gone)", r.get("dynamic_hint") is None)
check("the period is saved in state", (r["trip_update"].get("dates") or {}).get("period") == "סוף נובמבר 2026")
check("the dates question stays open (not marked answered)",
      r["trip_update"]["guided"]["current_question"] == "dates" and "dates" not in r["trip_update"]["guided"]["answered"])
check("no exact dates invented", not (r["trip_update"].get("dates") or {}).get("departure"))

# with nights given too (still no exact days) -> same
r = run("dates", dict(period_only, nights=7), "סוף נובמבר לשבוע")
check("period + nights, no exact day -> no confirm hint", r.get("dynamic_hint") is None)

# --- Unchanged: a genuinely unclear answer still gets the confirm hint ---------------
unclear_dates = {"status": "answered", "departure": "2026-11-24", "return": None, "nights": None,
                 "period": None, "flexibility_days": None, "confidence": "low",
                 "also_mentioned": {}, "correction": None}
r = run("dates", unclear_dates, "אולי ב-24 לחודש?")
check("an uncertain exact date (low) still gets the confirm hint", CONFIRM_MARK in (r.get("dynamic_hint") or ""))

# --- Unchanged: a non-dates field with low confidence --------------------------------
low_travelers = {"status": "answered", "adults": 2, "children": None, "child_ages": [], "child_genders": [],
                 "infants": None, "confidence": "low", "also_mentioned": {}, "correction": None}
r = run("travelers", low_travelers, "נראה לי שנהיה שניים")
check("travelers with low confidence still gets the confirm hint", CONFIRM_MARK in (r.get("dynamic_hint") or ""))

# --- Unchanged: high confidence path ----------------------------------------------------
exact = dict(unclear_dates, **{"return": "2026-12-01", "confidence": "high"})
r = run("dates", exact, "מ-24.11 עד 1.12")
check("exact dates with high confidence -> dates answered as before", "dates" in r["trip_update"]["guided"]["answered"])
check("...and no confirm hint", CONFIRM_MARK not in (r.get("dynamic_hint") or ""))

# The DATE_OPTIONS mechanism itself is untouched
src = open(os.path.join(os.path.dirname(__file__), "..", "ariella_chat_clean.py"), encoding="utf-8").read()
check("_DATE_OPTIONS_PLACEHOLDER / _dates_truth_hint still defined (not touched)",
      '_DATE_OPTIONS_PLACEHOLDER = "{{DATE_OPTIONS}}"' in src and "def _dates_truth_hint(state):" in src)

print()
print("ALL PASS" if not FAILED else f"{len(FAILED)} FAILED: {FAILED}")
sys.exit(1 if FAILED else 0)
