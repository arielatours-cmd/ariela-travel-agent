"""QA for dry-run 4 finding 1 (C Bordeaux, 22.10; qa/reports/2026-10-22-
dryrun4.md on the shaked branch, raw log on qa-dryrun):

accessibility had already been answered (it was in guided.answered from
turn 2) but guided.current_question stayed "accessibility" for the rest of
the conversation. Turn 4, "לי מזוודה, לאמא מספיק טרולי", was therefore
extracted against accessibility again and never reached the baggage
extraction: "מעולה, נרשם", mixed=None - the payment-page explanation +
yes/no came only when baggage was asked again at turn 9.

Fix: an answered accessibility pointer is stale (accessibility's own branch
always moves on once answered) - it moves on to the next open field. Other
fields keep the pointer on an answered field on purpose (their correction
flow), so this is not generalized.

Offline (the guided extraction is stubbed). Run:
python3 tools/qa_dryrun4_mixed_while_accessibility.py
"""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")
os.environ.setdefault("SCHEDULER_ENABLED", "false")

import ariella_chat_clean as chat  # noqa: E402

FAILED = []


def check(name, cond):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        FAILED.append(name)


STEPS = {"dates", "travelers", "baggage", "accessibility"}
MIXED = {"status": "answered", "mixed_per_passenger": True, "confidence": "high", "also_mentioned": {}, "correction": None}
SINGLE = {"status": "answered", "mixed_per_passenger": False, "items": [{"type": "carry_on_only", "count": None}],
          "confidence": "high", "also_mentioned": {}, "correction": None}


def c_state(guided_extra=None):
    """Bordeaux C after turn 3: accessibility answered (practical need saved), the pointer still on it."""
    g = {"current_question": "accessibility", "attempts": 0, "answered": ["dates", "travelers", "accessibility"]}
    g.update(guided_extra or {})
    return {"requested_services": ["flights"], "travelers": {"adults": 2},
            "dates": {"departure": "2027-04-20", "return": "2027-04-25"},
            # exactly the dry-run 4 C state after turn 3 (chat_resp_dr4c.jsonl)
            "accessibility": {"announced": ["flights"], "asked": True, "needed": True, "needs": ["other"]},
            "flight": {"baggage": [], "connection_preference": "אין העדפה"}, "guided": g}


def run(state, message, baggage_result):
    asked = []

    def fake_extract(key, model, field, msg, history, s, guided_steps=None):
        asked.append(field)
        if field == "baggage":
            return baggage_result
        return {"status": "other_topic", "confidence": "low", "also_mentioned": {}, "correction": None}

    with patch.object(chat, "_guided_extract_answer", side_effect=fake_extract), \
            patch.object(chat, "_guided_redirect_field", return_value=None), \
            patch.object(chat, "record_diagnostic_event"):
        result = chat._handle_guided_extraction_turn("k", "m", message, [], state, dict(state), STEPS)
    # None = the dispatcher changed nothing (the pre-fix behavior here) - keep the checks failing, not crashing.
    return result or {"trip_update": dict(state), "dynamic_hint": None}, asked



# --- The C turn-4 repro ------------------------------------------------------------------------------------
r, asked = run(c_state(), "לי מזוודה, לאמא מספיק טרולי", MIXED)
g = r["trip_update"]["guided"]
check("C turn 4: the answer is extracted against baggage, not the stale accessibility pointer", asked[:1] == ["baggage"])
check("C turn 4: mixed is caught now - pending + baggage live", g.get("mixed_baggage_pending") is True and g.get("current_question") == "baggage")
check("C turn 4: the payment-page explanation + yes/no hint this turn", "בעמוד התשלום" in (r.get("dynamic_hint") or ""))
check("C turn 4: nothing saved", not (r["trip_update"].get("flight") or {}).get("baggage"))

# next turn: the yes/no is read by the pending branch (baggage stays live even though nothing is answered yet)
st2 = r["trip_update"]
with patch.object(chat, "_mixed_baggage_uniform_choice_by_meaning", return_value=False):
    r2 = chat._handle_guided_extraction_turn("k", "m", "לא", [], st2, dict(st2), STEPS)
check("next turn: 'לא' is read as the yes/no answer -> hand bag saved, pending cleared",
      (r2["trip_update"].get("flight") or {}).get("baggage") == ["personal_item"]
      and r2["trip_update"]["guided"].get("mixed_baggage_pending") is False)

# --- Unchanged behavior -------------------------------------------------------------------------------------
r, asked = run(c_state(), "טרולי לכל אחת", SINGLE)
check("a plain uniform answer with the stale pointer -> baggage saved normally",
      (r["trip_update"].get("flight") or {}).get("baggage") == ["carry_on_only"] and "baggage" in r["trip_update"]["guided"]["answered"])
open_acc = c_state({"answered": ["dates", "travelers"]})
open_acc["accessibility"] = {}
r, asked = run(open_acc, "לי מזוודה, לאמא מספיק טרולי", MIXED)
check("accessibility still OPEN (not answered) -> it stays the live question (no skipping an unanswered field)",
      asked[:1] == ["accessibility"])
pending = c_state({"current_question": "baggage", "answered": ["dates", "travelers", "accessibility", "baggage"],
                   "mixed_baggage_pending": True})
with patch.object(chat, "_mixed_baggage_uniform_choice_by_meaning", return_value=True) as yn:
    r3 = chat._handle_guided_extraction_turn("k", "m", "כן", [], pending, dict(pending), STEPS)
check("the mixed pending yes/no keeps baggage live even if baggage is listed answered", yn.call_count == 1)

# --- Bezalel's case: the yes/no is pending but the pointer shows accessibility ------------------------------
stale = c_state({"current_question": "accessibility", "answered": ["dates", "travelers"], "mixed_baggage_pending": True})
stale["accessibility"] = {}
with patch.object(chat, "_mixed_baggage_uniform_choice_by_meaning", return_value=False) as yn, \
        patch.object(chat, "_guided_extract_answer") as ex:
    r4 = chat._handle_guided_extraction_turn("k", "m", "לא", [], stale, dict(stale), STEPS)
check("pending yes/no while the pointer shows accessibility (still open): the reply is read as the yes/no",
      yn.call_count == 1 and ex.call_count == 0)
check("...hand bag saved, pending cleared, and accessibility (still open) is asked next with its own hint",
      (r4["trip_update"].get("flight") or {}).get("baggage") == ["personal_item"]
      and r4["trip_update"]["guided"].get("mixed_baggage_pending") is False
      and r4["trip_update"]["guided"].get("current_question") == "accessibility"
      and "נגישות" in (r4.get("dynamic_hint") or ""))

print()
print("ALL PASS" if not FAILED else f"{len(FAILED)} FAILED: {FAILED}")
sys.exit(1 if FAILED else 0)
