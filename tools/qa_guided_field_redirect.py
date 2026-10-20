"""QA for the general fix to stage-3 run-3 item (a) (Madrid V1 + Milano V2,
qa/reports/2026-10-18-stage3-run3.md) - built per the business owner's own
explicit spec, relayed by Shlomo after her follow-up to #83's partial fix:

PR #83's first pass only extended _BUNDLED_AND_QUESTION_RE with "וזה"/"וזאת"
for Madrid (reverted - see below) and left Milano's actual bug unfixed. A
deterministic topic-keyword enforcer on Ariella's own composed question
text (_enforce_guided_question_matches_field) was tried for Milano and then
fully reverted after the regression sweep proved it unsafe (same lesson as
_enforce_one_option_question's own history: keyword matching on free text
is as unreliable as the free generation it tries to police).

Shlomo's follow-up (18.10) overturned both: (1) "וזה"/"וזאת" is itself a
phrase-list growth the business owner's directive rules out - reverted,
_BUNDLED_AND_QUESTION_RE is back to its pre-#83 shape; (2) the real fix for
both Madrid and Milano (same root: the text Ariella's own reply actually
asked can drift from guided.current_question, since Tinkerbell composes
her questions freely from a hint, never a fixed sentence) belongs on the
INTAKE side: the guided extractor, once the live field (current_question)
rejects a message as other_topic, now gets Ariella's own LAST REAL sent
message (the literal text, not a hint) plus every other still-open guided
field, and the MODEL (never a phrase list) decides which of them the reply
actually answers - saved there with a verbatim evidence quote, exactly
like every other evidence-gated value in this codebase. current_question
itself is left untouched (it's still genuinely due) - "stays the next one
in queue", per the business owner's own wording. Whenever this redirect
succeeds, the dynamic hint explicitly tells Tinkerbell what was just
captured and that she must never call it unrelated, so there's no vacuum
left for her to improvise a rejection into (exactly what happened live in
Milano: "סליחה, זה נשמע כמו העדפת מיקום ולא קשור לתקציב ללילה").

New: _guided_redirect_field (the classifier itself) and its wiring into
_handle_guided_extraction_turn's other_topic branch.

Run: python3 tools/qa_guided_field_redirect.py
"""
import os
import sys
import json
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import database
database.init_db()

import ariella_chat_clean as chat

FAILED = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


# =====================================================================
# 0. Regression: the "וזה"/"וזאת" phrase-list growth from #83's first
#    pass is reverted - _BUNDLED_AND_QUESTION_RE is back to its original
#    shape (still catches every form it already covered before).
# =====================================================================
check("'וזה' is no longer matched (the phrase-list growth was reverted)",
      not chat._BUNDLED_AND_QUESTION_RE.search(
          "קיבלתי, חדר זוגי אחד - וזה מאשר גם שהלינה תהיה באזור מרכז העיר, כמו שהצעתי?"
      ))
check("regression: the pre-existing fused forms (וגם/ואם/האם, comma-anchored) still match",
      bool(chat._BUNDLED_AND_QUESTION_RE.search("ספרו לי מה אתם אוהבים לעשות, וגם האם חשוב לכם קצב רגוע?"))
      and bool(chat._BUNDLED_AND_QUESTION_RE.search("תוכלו לספר לי מה אתם אוהבים לעשות בחופשה ואם חשוב לכם קצב רגוע?")))


# =====================================================================
# 1. Unit: _guided_redirect_field itself.
# =====================================================================
def _fake_redirect_match(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    return json.dumps({"field": "lodging_locations", "evidence": "קרוב לתחבורה ציבורית"})


def _fake_redirect_fabricated_evidence(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    return json.dumps({"field": "lodging_locations", "evidence": "משהו שהלקוח לא אמר בכלל"})


def _fake_redirect_none(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    return json.dumps({"field": None, "evidence": None})


HIST = [{"role": "assistant", "content": "באיזה אזור תרצו שהלינה תהיה?"}]

with patch.object(chat, "_post_claude", side_effect=_fake_redirect_match):
    check("matches a candidate field with real verbatim evidence",
          chat._guided_redirect_field("k", "m", HIST, "קרוב לתחבורה ציבורית", ["lodging_locations", "lodging_budget_or_level"])
          == "lodging_locations")
    check("returns None when the model's field isn't in the candidate list",
          chat._guided_redirect_field("k", "m", HIST, "קרוב לתחבורה ציבורית", ["lodging_budget_or_level"]) is None)

with patch.object(chat, "_post_claude", side_effect=_fake_redirect_fabricated_evidence):
    check("rejects a fabricated (non-verbatim) evidence quote, even with a listed field",
          chat._guided_redirect_field("k", "m", HIST, "קרוב לתחבורה ציבורית", ["lodging_locations"]) is None)

with patch.object(chat, "_post_claude", side_effect=_fake_redirect_none):
    check("returns None when the model itself finds no match",
          chat._guided_redirect_field("k", "m", HIST, "משהו אחר לגמרי", ["lodging_locations", "lodging_budget_or_level"]) is None)

check("returns None with no API key, no network call needed",
      chat._guided_redirect_field("", "m", HIST, "קרוב לתחבורה ציבורית", ["lodging_locations"]) is None)
check("returns None with an empty candidate list",
      chat._guided_redirect_field("k", "m", HIST, "קרוב לתחבורה ציבורית", []) is None)
check("returns None when there's no prior assistant message to anchor on",
      chat._guided_redirect_field("k", "m", [], "קרוב לתחבורה ציבורית", ["lodging_locations"]) is None)


# =====================================================================
# 2. End-to-end: Milano's exact live transcript (V2, Shaked's report) -
#    current_question has drifted to budget, Ariella's real last message
#    asked about area, the customer's area answer is correctly captured
#    there instead of being rejected as unrelated.
# =====================================================================
def _dispatch_milano(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if 'field="lodging_budget_or_level"' in system_static and "שלחה ללקוח" not in system_static:
        return json.dumps({"status": "other_topic", "budget": None, "level": None, "confidence": "low", "also_mentioned": {}, "correction": None})
    if "שלחה ללקוח את ההודעה הזו ממש" in system_static:
        return json.dumps({"field": "lodging_locations", "evidence": "קרוב לתחבורה ציבורית"})
    if 'field="lodging_locations"' in system_static:
        return json.dumps({"status": "answered", "value": "קרוב לתחבורה ציבורית", "confidence": "high", "also_mentioned": {}, "correction": None})
    return "{}"


milano_history = [{"role": "assistant", "content": "באיזה אזור תרצו שהלינה תהיה?"}]
milano_trip_update = {
    "requested_services": ["flights", "lodging"],
    "guided": {"current_question": "lodging_budget_or_level", "attempts": 0,
               "answered": ["lodging_type", "lodging_rooms", "lodging_bathrooms"]},
}
with patch.object(chat, "_post_claude", side_effect=_dispatch_milano):
    milano_result = chat._handle_guided_extraction_turn(
        "test-key", "test-model", "קרוב לתחבורה ציבורית", milano_history,
        milano_trip_update, dict(milano_trip_update), ("lodging",),
    )

check("Milano repro: the area answer is captured (lodging.details.locations), not dropped",
      milano_result is not None
      and (milano_result.get("trip_update", {}).get("lodging", {}).get("details", {}) or {}).get("locations")
      == "קרוב לתחבורה ציבורית")
check("Milano repro: lodging_locations is marked answered",
      "lodging_locations" in (milano_result.get("trip_update", {}).get("guided", {}).get("answered") or []))
check("Milano repro: current_question stays at budget - it's still genuinely due, never skipped",
      milano_result.get("trip_update", {}).get("guided", {}).get("current_question") == "lodging_budget_or_level")
check("Milano repro: the hint explicitly forbids Tinkerbell from framing this as unrelated",
      "לעולם אל תגידי שזו תשובה לא קשורה" in (milano_result.get("dynamic_hint") or ""))
check("Milano repro: the hint still asks the genuinely-open next question (budget)",
      "תקציב" in (milano_result.get("dynamic_hint") or ""))


# =====================================================================
# 3. End-to-end: Madrid-style repro - a bundled confirm-and-ask reply
#    ("...חדר זוגי אחד - וזה מאשר גם שהלינה תהיה באזור מרכז העיר, כמו
#    שהצעתי?") already drifted current_question past lodging_locations
#    to budget by the time it was sent; the customer's plain "כן"
#    confirms the area, not the budget question current_question points
#    to - must still be captured as lodging_locations, never rejected.
# =====================================================================
def _dispatch_madrid(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if 'field="lodging_budget_or_level"' in system_static and "שלחה ללקוח" not in system_static:
        return json.dumps({"status": "other_topic", "budget": None, "level": None, "confidence": "low", "also_mentioned": {}, "correction": None})
    if "שלחה ללקוח את ההודעה הזו ממש" in system_static:
        return json.dumps({"field": "lodging_locations", "evidence": "כן"})
    if 'field="lodging_locations"' in system_static:
        return json.dumps({"status": "answered", "value": "מרכז העיר", "confidence": "high", "also_mentioned": {}, "correction": None})
    return "{}"


madrid_history = [{"role": "assistant", "content": "קיבלתי, חדר זוגי אחד - וזה מאשר גם שהלינה תהיה באזור מרכז העיר, כמו שהצעתי?"}]
madrid_trip_update = {
    "requested_services": ["flights", "lodging"],
    "guided": {"current_question": "lodging_budget_or_level", "attempts": 0,
               "answered": ["lodging_type", "lodging_rooms", "lodging_bathrooms"]},
}
with patch.object(chat, "_post_claude", side_effect=_dispatch_madrid):
    madrid_result = chat._handle_guided_extraction_turn(
        "test-key", "test-model", "כן", madrid_history,
        madrid_trip_update, dict(madrid_trip_update), ("lodging",),
    )

check("Madrid repro: the bundled area confirmation is captured as lodging_locations, not dropped",
      madrid_result is not None
      and (madrid_result.get("trip_update", {}).get("lodging", {}).get("details", {}) or {}).get("locations") == "מרכז העיר")
check("Madrid repro: current_question still stays at budget afterward",
      madrid_result.get("trip_update", {}).get("guided", {}).get("current_question") == "lodging_budget_or_level")


# =====================================================================
# 4. Regression: a genuinely unrelated message (no candidate field
#    matches at all) behaves exactly as before the fix - no hint, no
#    crash, current_question untouched.
# =====================================================================
def _dispatch_truly_unrelated(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if 'field="lodging_budget_or_level"' in system_static and "שלחה ללקוח" not in system_static:
        return json.dumps({"status": "other_topic", "budget": None, "level": None, "confidence": "low", "also_mentioned": {}, "correction": None})
    if "שלחה ללקוח את ההודעה הזו ממש" in system_static:
        return json.dumps({"field": None, "evidence": None})
    return "{}"


unrelated_history = [{"role": "assistant", "content": "מה התקציב שלכם ללילה?"}]
unrelated_trip_update = {
    "requested_services": ["flights", "lodging"],
    "guided": {"current_question": "lodging_budget_or_level", "attempts": 0,
               "answered": ["lodging_type", "lodging_rooms", "lodging_bathrooms", "lodging_locations"]},
}
with patch.object(chat, "_post_claude", side_effect=_dispatch_truly_unrelated):
    unrelated_result = chat._handle_guided_extraction_turn(
        "test-key", "test-model", "מה שלום הכלב שלכם?", unrelated_history,
        unrelated_trip_update, dict(unrelated_trip_update), ("lodging",),
    )

check("regression: a truly unrelated message still gets no hint (dynamic_hint=None), exactly as before this fix",
      unrelated_result is None or unrelated_result.get("dynamic_hint") is None)
check("regression: nothing gets wrongly marked answered for a truly unrelated message",
      "lodging_budget_or_level" not in ((unrelated_result or {}).get("trip_update", {}).get("guided", {}).get("answered") or []))

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL GUIDED-FIELD-REDIRECT TESTS PASSED")
