"""QA for dry-run 5c scenario B (Shlomo/Shaked, 22.10.2026, qa/reports/
2026-10-22-dryrun5c.md, Zadar/"לזדאק") - item 3 of the overnight root-cause
list. Three separate bugs, all reproduced from the real transcript
(qa-dryrun branch, qa/dryrun/2026-10-22-dr5c-typos/chat_resp_dr5b.jsonl):

1. Baggage self-pick/false-claim contradiction: turn 1's reply opened with
   "אוקיי, אז נלך על מזוודה בבטן המטוס לכל השלוש..." (a self-picked
   decision) even though flight.baggage was still genuinely empty and
   baggage had just correctly LOST the arbiter to the still-unresolved
   destination-gateway question ("לגבי לזדאק..."). The existing _guard_
   baggage_type_self_picked only fires when baggage IS the winning topic
   (misses this shape entirely - baggage lost, she addressed it anyway).
   New _guard_baggage_claimed_without_resolution catches this: flight.
   baggage still empty + winning kind is NOT guided/guided_mixed_baggage
   + the reply nonetheless claims a baggage decision -> forced retry,
   dropping the baggage claim.

2. The mixed-baggage yes/no interpreter misread an UNRELATED answer: "לא
   חובה" (not obligatory) genuinely answered the direct-flight-preference
   question Tinkerbell's own prior reply actually asked, but _mixed_
   baggage_uniform_choice_by_meaning, given only the bare message, read
   it as a "no" to the (long-pending, unrelated) uniform-baggage
   question - silently resolving baggage from a message that was never
   about it, and (per the real transcript) also meant Tinkerbell never
   actually reached the accessibility question at all; the leaked
   disclaimer "זה לגמרי לא חובה..." which belongs ONLY beside a genuine
   accessibility yes/no got threaded into an unrelated reply instead.
   Fixed: the classifier now receives Ariella's own last real message and
   returns "off_topic" when that message plainly wasn't the uniform-
   baggage question - the caller then leaves mixed_baggage_pending/
   current_question completely untouched and lets the turn's normal
   processing (the real topic) proceed.

3. Airport typo "לזדאק" (preposition "ל" + typo'd Zadar) was never
   recognized ("אני לא מכירה שדה תעופה בשם הזה"), even though plain
   "זדאר" worked one turn later - fixed with an explicit prompt note
   about a possible leading Hebrew preposition. Separately, once Zadar
   DID resolve, destination.places ended up "זאדאר" (an extra alef) -
   the EXTENDED catalog's own city_he for ZAD, which its own _about note
   explicitly marks unverified/matching-only ("never shown to the
   customer"). Fixed: _verified_catalog_display_name only ever uses
   city_he from the VERIFIED static catalog; an extended-catalog-only
   code falls back to city_en instead (never its own unverified city_he).

Run: python3 tools/qa_dryrun5c_scenario_b_zadar.py
"""
import os
import sys
import json
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


KEY = os.getenv("ANTHROPIC_API_KEY", "test-key-not-real")
MODEL = "claude-sonnet-5"

# =====================================================================
# Part 1: _verified_catalog_display_name - never the extended catalog's
# own unverified city_he.
# =====================================================================
check("ZAD (extended-catalog-only) falls back to city_en, never its own unverified city_he ('זאדאר')",
      chat._verified_catalog_display_name("ZAD") == "Zadar")
check("a static-catalog code (e.g. PFO/Paphos) still correctly uses the verified city_he",
      chat._verified_catalog_display_name("PFO") == "פאפוס")
check("an unknown code falls back to the code itself, never crashes",
      chat._verified_catalog_display_name("ZZZ") == "ZZZ")
check("empty/None code returns empty string, never crashes",
      chat._verified_catalog_display_name(None) == "" and chat._verified_catalog_display_name("") == "")


# =====================================================================
# Part 2: _destination_gateway_answer_by_meaning now uses the safe name
# when writing destination.places on a single verified match.
# =====================================================================
BASE_STATE = {
    "destination": {"places": ["לזדאק"], "mode": None, "status": "known"},
    "destination_airports": [],
    "requested_services": ["flights"],
    "service_decisions": {"flights": {"wanted": True}},
}


def _fake_zadar_classifier(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other", **kw):
    if source == "classifier":
        return json.dumps({"evidence": "זדאר", "candidates": [{"city_en": "Zadar", "iata_code": "ZAD"}]})
    return "{}"


with patch.object(chat, "_post_claude", side_effect=_fake_zadar_classifier):
    result = chat._destination_gateway_answer_by_meaning("זדאר מתאים לנו", [], BASE_STATE)
check("dr5c fix: destination.places is written as 'Zadar' (city_en), never the extended "
      "catalog's own unverified 'זאדאר'",
      result.get("destination", {}).get("places") == ["Zadar"])
check("destination_airports still correctly resolves to ZAD",
      result.get("destination_airports") == ["ZAD"])


# =====================================================================
# Part 3: the mixed-baggage uniform-choice classifier's off_topic signal.
# =====================================================================
GATEWAY_LAST_REPLY = "לגבי לזדאק - אני לא מכירה שדה תעופה בשם הזה. באיזה שדה תרצי לנחות בהלוך?"
DIRECT_FLIGHT_LAST_REPLY = "נרשם, תקציב של עד 1,100 ש\"ח לאדם. לגבי הטיסה - חשוב לך שתהיה ישירה?"
BAGGAGE_QUESTION_LAST_REPLY = "לפני שממשיכים - חשוב לדעת שבהזמנה אחת כולם צריכים לבחור את אותו סוג כבודה. רוצה שנבחר כבודה אחידה אחת לכל השלוש?"


def _fake_offtopic_classifier(answer):
    def _fake(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
        if source == "classifier":
            return answer
        return "{}"
    return _fake


with patch.object(chat, "_post_claude", side_effect=_fake_offtopic_classifier("offtopic")):
    result_offtopic = chat._mixed_baggage_uniform_choice_by_meaning(
        "לא חובה", [{"role": "assistant", "content": DIRECT_FLIGHT_LAST_REPLY}]
    )
check("dr5c fix: 'לא חובה' answering the UNRELATED direct-flight question (per Ariella's real "
      "last message) is classified as off_topic, not misread as a baggage 'no'",
      result_offtopic == "off_topic")

with patch.object(chat, "_post_claude", side_effect=_fake_offtopic_classifier("true")):
    result_genuine_yes = chat._mixed_baggage_uniform_choice_by_meaning(
        "כן", [{"role": "assistant", "content": BAGGAGE_QUESTION_LAST_REPLY}]
    )
check("regression: a genuine 'כן' answering the REAL uniform-baggage question still resolves True",
      result_genuine_yes is True)


# =====================================================================
# Part 4: the call site correctly leaves state untouched on off_topic,
# never emitting a confusing 'please answer yes/no about baggage' reply
# to a question that was never asked this turn.
# =====================================================================
STEPS = {"dates", "travelers", "baggage", "accessibility"}


def _state_mixed_pending():
    return {
        "requested_services": ["flights"],
        "travelers": {"adults": 3, "children": 0},
        "dates": {"departure": "2027-07-02", "return": "2027-07-06"},
        "flight": {"baggage": []},
        "destination": {"places": ["לזדאק"], "mode": None, "status": "known"},
        "destination_airports": ["ZAD"],
        "budget_per_person": {"amount": 1100, "currency": "ILS"},
        "guided": {"current_question": "baggage", "attempts": 0, "answered": ["dates", "travelers"], "mixed_baggage_pending": True},
    }


with patch.object(chat, "_post_claude", side_effect=_fake_offtopic_classifier("offtopic")), \
        patch.object(chat, "_guided_redirect_field", return_value=None), \
        patch.object(chat, "record_diagnostic_event"):
    trip_state_offtopic = _state_mixed_pending()
    out_offtopic = chat._handle_guided_extraction_turn(
        "k", "m", "לא חובה", [{"role": "assistant", "content": DIRECT_FLIGHT_LAST_REPLY}],
        trip_state_offtopic, dict(trip_state_offtopic), STEPS,
    )
_tu_offtopic = (out_offtopic or {}).get("trip_update", trip_state_offtopic)
check("dr5c fix: off_topic leaves mixed_baggage_pending untouched (still True - genuinely pending)",
      (_tu_offtopic.get("guided") or {}).get("mixed_baggage_pending") is True,
      )
check("dr5c fix: off_topic leaves flight.baggage untouched (still empty - nothing wrongly resolved)",
      not (_tu_offtopic.get("flight") or {}).get("baggage"))
check("dr5c fix: off_topic produces no confusing baggage-specific dynamic_hint for this turn",
      (out_offtopic or {}).get("dynamic_hint") is None)


# =====================================================================
# Part 5: _guard_baggage_claimed_without_resolution - the new false-claim
# guard, scoped to when baggage lost the arbiter (not its own turn).
# =====================================================================
SELF_PICK_REPLY = (
    "אוקיי, אז נלך על מזוודה בבטן המטוס לכל השלוש - זה יכסה גם את מי שהייתה מסתפקת בטרולי.\n\n"
    "לגבי לזדאק - אני לא מכירה שדה תעופה בשם הזה. באיזה שדה תרצי לנחות בהלוך?"
)
GENUINE_ASK_REPLY = "איזו כבודה תרצו לקחת?"

STATE_BAGGAGE_LOSES_ARBITER = {
    "guided": {"current_question": "baggage", "attempts": 0, "answered": ["dates", "travelers"], "mixed_baggage_pending": False},
    "flight": {"baggage": []},
    "destination": {"places": ["לזדאק"], "mode": "specific", "status": "known"},
    "destination_airports": [],
    "requested_services": ["flights"],
    "service_decisions": {"flights": {"wanted": True}},
}


def _fake_claim_classifier(claimed):
    def _fake(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
        if source == "classifier":
            return '{"claimed": %s}' % ("true" if claimed else "false")
        return "התשובה לדוגמה."
    return _fake


with patch.object(chat, "_post_claude", side_effect=_fake_claim_classifier(True)) as mock_claim:
    result_claim = chat._guard_baggage_claimed_without_resolution(
        SELF_PICK_REPLY, STATE_BAGGAGE_LOSES_ARBITER, KEY, MODEL, [], "כן",
    )
check("scenario B repro: a reply that self-picks/claims a baggage decision while it genuinely "
      "lost the arbiter triggers a retry (reply changes)",
      result_claim != SELF_PICK_REPLY)

with patch.object(chat, "_post_claude", side_effect=_fake_claim_classifier(False)) as mock_no_claim:
    result_no_claim = chat._guard_baggage_claimed_without_resolution(
        GENUINE_ASK_REPLY, STATE_BAGGAGE_LOSES_ARBITER, KEY, MODEL, [], "כן",
    )
check("regression: a reply that genuinely asks (no claim) passes through unchanged",
      result_no_claim == GENUINE_ASK_REPLY)

# Regression: baggage genuinely IS the winning topic this turn - this
# guard steps aside entirely (that's _guard_baggage_type_self_picked's
# own job, never double-checked here). Destination must already be
# resolved here too, or the destination-gateway question (still
# genuinely open in STATE_BAGGAGE_LOSES_ARBITER) would keep winning
# instead, same as the real live turn this whole guard exists for.
STATE_BAGGAGE_WINS_ARBITER = dict(
    STATE_BAGGAGE_LOSES_ARBITER,
    destination_airports=["ZAD"],
    _guided_ask_hint="שאלת כבודה רגילה",
)
with patch.object(chat, "_post_claude") as mock_unused:
    result_wins = chat._guard_baggage_claimed_without_resolution(
        SELF_PICK_REPLY, STATE_BAGGAGE_WINS_ARBITER, KEY, MODEL, [], "כן",
    )
check("regression: when baggage genuinely IS this turn's winning topic, this guard never fires "
      "(no classifier call - _guard_baggage_type_self_picked's own job instead)",
      result_wins == SELF_PICK_REPLY and not mock_unused.called)

# Regression: flight.baggage already genuinely set - nothing to falsely claim.
STATE_BAGGAGE_ALREADY_SET = dict(STATE_BAGGAGE_LOSES_ARBITER, flight={"baggage": ["checked_bag"]})
with patch.object(chat, "_post_claude") as mock_unused2:
    result_already_set = chat._guard_baggage_claimed_without_resolution(
        SELF_PICK_REPLY, STATE_BAGGAGE_ALREADY_SET, KEY, MODEL, [], "כן",
    )
check("regression: flight.baggage already genuinely set - nothing to falsely claim, no classifier call",
      result_already_set == SELF_PICK_REPLY and not mock_unused2.called)

# Regression: current_question isn't "baggage" at all - never this guard's job.
STATE_NOT_BAGGAGE_QUESTION = dict(STATE_BAGGAGE_LOSES_ARBITER, guided={"current_question": "accessibility", "attempts": 0, "answered": []})
with patch.object(chat, "_post_claude") as mock_unused3:
    result_not_baggage = chat._guard_baggage_claimed_without_resolution(
        SELF_PICK_REPLY, STATE_NOT_BAGGAGE_QUESTION, KEY, MODEL, [], "כן",
    )
check("regression: guided.current_question isn't 'baggage' - never this guard's job, no classifier call",
      result_not_baggage == SELF_PICK_REPLY and not mock_unused3.called)

# Shaked's static review of 6b1efab (22.10.2026): the reply-text keyword
# pre-filter ("כבודה"/"טרולי"/"מזוודה"/"תיק") missed the plain plural
# ("נלך על מזוודות לכולם" has no literal "מזוודה" substring) and is now
# removed entirely - the classifier runs unconditionally once the three
# structural gates above it pass, same as its sibling guards. A reply
# that genuinely never claims a baggage decision (gateway-only) still
# correctly passes through unchanged once the classifier itself says
# claimed=false - never because a keyword scan shortcut the call.
GATEWAY_ONLY_REPLY = "לגבי לזדאק - אני לא מכירה שדה תעופה בשם הזה. באיזה שדה תרצי לנחות בהלוך?"
with patch.object(chat, "_post_claude", side_effect=_fake_claim_classifier(False)) as mock_gateway_only:
    result_gateway_only = chat._guard_baggage_claimed_without_resolution(
        GATEWAY_ONLY_REPLY, STATE_BAGGAGE_LOSES_ARBITER, KEY, MODEL, [], "כן",
    )
check("Shaked's fix: the classifier call is unconditional once the three structural gates pass - "
      "no reply-text keyword pre-filter left to skip a gateway-only reply",
      mock_gateway_only.called and result_gateway_only == GATEWAY_ONLY_REPLY)

# Shaked's fix: a self-picked claim worded in the plain plural ("מזוודות")
# - which never matched the old gate's singular "מזוודה" substring - now
# correctly reaches the classifier and is caught.
PLURAL_SELF_PICK_REPLY = (
    "אוקיי, נלך על מזוודות לכולם.\n\n"
    "לגבי לזדאק - אני לא מכירה שדה תעופה בשם הזה. באיזה שדה תרצי לנחות בהלוך?"
)
with patch.object(chat, "_post_claude", side_effect=_fake_claim_classifier(True)) as mock_plural_claim:
    result_plural_claim = chat._guard_baggage_claimed_without_resolution(
        PLURAL_SELF_PICK_REPLY, STATE_BAGGAGE_LOSES_ARBITER, KEY, MODEL, [], "כן",
    )
check("Shaked's fix: a plural self-pick ('מזוודות', not a substring of the old gate's "
      "singular 'מזוודה') now reaches the classifier and is caught",
      mock_plural_claim.called and result_plural_claim != PLURAL_SELF_PICK_REPLY)


# =====================================================================
# Part 6: Shaked's scenario B ROOT CAUSE (her third static-review finding,
# 22.10.2026) - the mixed-baggage follow-up hint, produced on the SAME
# turn the yes/no is resolved, must keep tier-2 arbiter priority (same as
# the still-pending "guided_mixed_baggage" case) instead of falling to
# plain tier-3 "guided" and losing to a still-unresolved destination-
# gateway/ambiguous question - which is exactly what the live transcript
# showed: baggage "lost" the arbiter on the very turn its own yes/no was
# answered, even though that follow-up is a direct continuation of the
# customer's own message this turn. _guard_baggage_claimed_without_
# resolution (parts 1/5 above) is a retry-time safety net for when this
# happens anyway; this is the actual root-cause fix, in the arbiter
# itself.
# =====================================================================
check("_mixed_baggage_just_resolved alone (mixed_baggage_pending already cleared to False "
      "this same turn) still wins the arbiter at the guided_mixed_baggage tier",
      chat._turn_question_arbiter({
          "guided": {"mixed_baggage_pending": False},
          "_guided_ask_hint": "שאלת כבודה רגילה",
          "_mixed_baggage_just_resolved": True,
      }) == ("שאלת כבודה רגילה", "guided_mixed_baggage"))

check("regression: without _mixed_baggage_just_resolved, mixed_baggage_pending=False falls "
      "through to plain 'guided' priority exactly as before this fix",
      chat._turn_question_arbiter({
          "guided": {"mixed_baggage_pending": False},
          "_guided_ask_hint": "שאלת כבודה רגילה",
      }) == ("שאלת כבודה רגילה", "guided"))

# End-to-end scenario B repro: "כן" to the uniform-baggage question (no
# same-breath type named), while the destination gateway ("לזדאק") is
# STILL genuinely unresolved - exactly the live shape. _handle_guided_
# extraction_turn resolves baggage AND sets the one-turn marker; feeding
# the arbiter the SAME trip_update _call_tinkerbell receives live (see
# state_for_tinkerbell = trip_update at the real call site) now correctly
# keeps the baggage follow-up as this turn's question instead of losing
# to the gateway.
STATE_SCENARIO_B_ROOT_CAUSE = {
    "requested_services": ["flights"],
    "travelers": {"adults": 3, "children": 0},
    "dates": {"departure": "2027-07-02", "return": "2027-07-06"},
    "flight": {"baggage": []},
    "destination": {"places": ["לזדאק"], "mode": None, "status": "known"},
    "destination_airports": [],
    "budget_per_person": {"amount": 1100, "currency": "ILS"},
    "guided": {"current_question": "baggage", "attempts": 0, "answered": ["dates", "travelers"], "mixed_baggage_pending": True},
}

with patch.object(chat, "_post_claude", side_effect=_fake_offtopic_classifier("true")), \
        patch.object(chat, "record_diagnostic_event"):
    out_root_cause = chat._handle_guided_extraction_turn(
        "k", "m", "כן", [{"role": "assistant", "content": BAGGAGE_QUESTION_LAST_REPLY}],
        STATE_SCENARIO_B_ROOT_CAUSE, dict(STATE_SCENARIO_B_ROOT_CAUSE), STEPS,
    )
tu_root_cause = out_root_cause["trip_update"]
check("scenario B root-cause repro: _handle_guided_extraction_turn sets _mixed_baggage_just_resolved "
      "on the exact turn that resolves the yes/no",
      tu_root_cause.get("_mixed_baggage_just_resolved") is True)
tu_root_cause["_guided_ask_hint"] = out_root_cause.get("dynamic_hint")
_, winning_kind_root_cause = chat._turn_question_arbiter(tu_root_cause)
check("scenario B FIX: fed through the real call shape, the arbiter now keeps the baggage "
      "follow-up as this turn's question instead of losing to the still-unresolved "
      "destination-gateway question",
      winning_kind_root_cause == "guided_mixed_baggage")

# Regression: mixed_baggage_pending genuinely STILL pending (off_topic/
# None branches, which return before the marker is ever set) must be
# completely unaffected by this new marker.
check("regression: the marker is never set on the genuinely-still-pending (off_topic) branch",
      "_mixed_baggage_just_resolved" not in _tu_offtopic)


if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL DRYRUN5C-SCENARIO-B-ZADAR TESTS PASSED")
