"""QA for run-11 main finding 2 (22.10, Bezalel's split; report
qa/reports/2026-10-22-stage1-live-run11.md on the shaked branch):
mixed per-passenger baggage (B Valencia, C Bordeaux, E Rovinj).

1. The baggage field description ended with "לעולם לא לשאול או להסביר על
   כבודה שונה לנוסעים שונים" - contradicting the 22.10 decision (explain
   the payment page + yes/no) and reaching the very turn the customer
   described it, through the redirect ack. Removed; never OPENING such a
   question stays in the ask hint.
2. C/E: the customer answered baggage while guided's live question was
   another field (accessibility). The redirect caught mixed_per_passenger
   but returned NO hint ("סבבה, קלטתי - לך טרולי..." / the baggage question
   again x5) and left current_question elsewhere, so the pending yes/no
   branch never ran and mixed_baggage_pending lingered (E). Now: the
   payment-time hint is returned that turn and baggage becomes the live
   question, so next turn's reply is read as the yes/no.
3. E: pending is cleared whenever the redirect saves a single baggage type.
4. B: a general path saved ['checked_bag','personal_item']. Safety net
   (_mixed_baggage_safety_net): several types written this turn and guided
   didn't settle baggage -> the guided baggage extractor (the model, by
   meaning) decides; mixed -> previous value restored, pending, the same
   explanation + yes/no. Uniform two items for everyone stays.
5. E: the redirect ack for accessibility used _guided_ask_hint, which has
   no accessibility description ("הפרט הבא לברר אצל הלקוח: accessibility",
   an open question) - now accessibility's own yes/no hint.
6. Destination hints: B the catalog airport fact was read out mid-chat; E
   Pula picked without the customer choosing, airport + baggage in one
   message. Hint wording only.

No regex on the output. Offline. Run: python3 tools/qa_run11_mixed_baggage.py
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


PAYMENT_MARK = "בעמוד התשלום"

# --- 1. The description no longer forbids explaining ----------------------------------------------
desc = chat._GUIDED_FIELD_HINT_DESCRIPTION["baggage"]
check("baggage description: no 'never ask or explain' clause", "להסביר" not in desc and "לעולם" not in desc)
check("baggage description: still one question, 3 options", "3 אפשרויות" in desc and "טרולי" in desc)
check("ask hint still never OPENS a per-passenger question", "לעולם אל תפתחי שאלה על הבדל בין נוסעים" in chat._guided_ask_hint("baggage", 0))
check("the payment-time hint explains and asks yes/no", PAYMENT_MARK in chat._mixed_baggage_payment_time_hint()
      and "כן/לא" in chat._mixed_baggage_payment_time_hint())


# --- 2/3/5. Redirect while accessibility is the live question ---------------------------------------
def state(extra_guided=None, baggage=None):
    g = {"current_question": "accessibility", "attempts": 0, "answered": ["dates", "travelers"]}
    g.update(extra_guided or {})
    return {"requested_services": ["flights"], "travelers": {"adults": 3},
            "dates": {"departure": "2027-05-01", "return": "2027-05-05"},
            "flight": {"baggage": baggage or []}, "guided": g}


STEPS = {"dates", "travelers", "baggage", "accessibility"}
HIST = [{"role": "assistant", "content": "איזו כבודה תרצו לקחת - תיק יד, טרולי או מזוודה?"}]


def run(baggage_result, msg="לי טרולי, לשתיים האחרות מזוודה", st=None):
    st = st or state()
    calls = []

    def fake_extract(key, model, field, message, history, s, guided_steps=None):
        calls.append(field)
        if field == "accessibility":
            return {"status": "other_topic", "confidence": "low", "also_mentioned": {}, "correction": None}
        return baggage_result

    with patch.object(chat, "_guided_extract_answer", side_effect=fake_extract), \
            patch.object(chat, "_guided_redirect_field", return_value="baggage"), \
            patch.object(chat, "record_diagnostic_event"):
        return chat._handle_guided_extraction_turn("k", "m", msg, HIST, st, dict(st), STEPS), calls


mixed = {"status": "answered", "mixed_per_passenger": True, "baggage": None, "confidence": "high",
         "also_mentioned": {}, "correction": None}
r, _ = run(mixed)
g = r["trip_update"]["guided"]
check("E/C: mixed via redirect -> the payment-page explanation + yes/no hint this turn",
      PAYMENT_MARK in (r.get("dynamic_hint") or ""))
check("E/C: baggage becomes the live question (next reply is read as the yes/no)",
      g.get("current_question") == "baggage" and g.get("mixed_baggage_pending") is True)
check("E/C: nothing saved, accessibility still unanswered (comes back after baggage)",
      not (r["trip_update"].get("flight") or {}).get("baggage") and "accessibility" not in g.get("answered"))

# next turn: "כן, טרולי לכל אחת" goes through the existing pending branch
st2 = r["trip_update"]
with patch.object(chat, "_mixed_baggage_uniform_choice_by_meaning", return_value=True):
    r2 = chat._handle_guided_extraction_turn("k", "m", "כן", [], st2, dict(st2), STEPS)
check("next turn: the yes/no is read by the pending branch and the flag is cleared",
      r2["trip_update"]["guided"].get("mixed_baggage_pending") is False)

# "no" -> baggage settled, next field is accessibility (before baggage in guided_order)
with patch.object(chat, "_mixed_baggage_uniform_choice_by_meaning", return_value=False):
    r3 = chat._handle_guided_extraction_turn("k", "m", "לא", [], st2, dict(st2), STEPS)
check("after the yes/no, the next field (accessibility) is asked with its own hint, not the raw field name",
      r3["trip_update"]["guided"].get("current_question") == "accessibility"
      and "accessibility" not in (r3.get("dynamic_hint") or "") and "נגישות" in (r3.get("dynamic_hint") or ""))

single = {"status": "answered", "mixed_per_passenger": False, "items": [{"type": "carry_on_only", "count": None}], "confidence": "high",
          "also_mentioned": {}, "correction": None}
r, _ = run(single, "טרולי לכל אחת", st=state({"mixed_baggage_pending": True}))
check("E: a single type saved via the redirect clears a lingering pending flag",
      r["trip_update"]["guided"].get("mixed_baggage_pending") is False)
check("E: accessibility ack uses its own hint - no raw English field name",
      "accessibility" not in (r.get("dynamic_hint") or "") and "נגישות" in (r.get("dynamic_hint") or ""))


# --- 4. Safety net (B) -----------------------------------------------------------------------------
def net(prior, now, extractor_result, guided_extra=None, statuses=None):
    trip_state = state(guided_extra, baggage=prior)
    trip_update = state(guided_extra, baggage=now)
    if statuses:
        trip_update["session_status"] = statuses
    with patch.object(chat, "_guided_extract_answer", return_value=extractor_result) as ex, \
            patch.object(chat, "record_diagnostic_event"):
        out = chat._mixed_baggage_safety_net("k", "m", "לי ולאשתי מזוודה, לתינוק מספיק תיק קטן", [], trip_state, trip_update, STEPS)
    return out, ex.call_count


out, n = net([], ["checked_bag", "personal_item"], mixed)
check("B: two types + the model says per-passenger -> nothing saved",
      (out.get("flight") or {}).get("baggage") == [] and n == 1)
check("B: pending + baggage live + the explanation/yes-no hint",
      out["guided"].get("mixed_baggage_pending") is True and out["guided"].get("current_question") == "baggage"
      and PAYMENT_MARK in (out.get("_guided_ask_hint") or ""))
out, _ = net([], ["carry_on_only", "checked_bag"], dict(single, mixed_per_passenger=False))
check("uniform two items for everyone (model: not mixed) -> kept as is",
      (out.get("flight") or {}).get("baggage") == ["carry_on_only", "checked_bag"] and "_guided_ask_hint" not in out)
out, n = net([], ["checked_bag"], mixed)
check("a single type -> no model call, untouched", n == 0 and (out.get("flight") or {}).get("baggage") == ["checked_bag"])
out, n = net([], ["checked_bag", "personal_item"], mixed, guided_extra={"answered": ["dates", "travelers", "baggage"]})
check("guided already settled baggage -> no second guess", n == 0)
out, n = net([], ["checked_bag", "personal_item"], mixed,
             statuses={"flights": "complete", "lodging": "declined", "car": "declined", "trip_planning": "declined"})
check("post-summary (guided doesn't run) -> net stays off (no stuck pending)", n == 0)
out, n = net(["checked_bag", "personal_item"], ["checked_bag", "personal_item"], mixed)
check("unchanged from the previous turn -> no model call", n == 0)

# --- 6. Destination hints ---------------------------------------------------------------------------
known = chat._destination_catalog_hint({"destination": {"places": ["ולנסיה"]}})
check("B: catalog fact is for the summary - not to be told mid-chat", (not known) or "אל תספרי ללקוח על שדה התעופה" in known)
unknown = chat._destination_catalog_hint({"destination": {"places": ["רוביני"]}})
check("E: several nearby airports -> the customer chooses, its own message, never picked by the model",
      "שאלי אותה כשאלה היחידה בהודעה" in unknown and "לעולם אל תבחרי שדה בעצמך" in unknown)

print()
print("ALL PASS" if not FAILED else f"{len(FAILED)} FAILED: {FAILED}")
sys.exit(1 if FAILED else 0)
