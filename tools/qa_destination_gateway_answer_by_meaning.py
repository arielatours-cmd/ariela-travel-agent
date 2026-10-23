"""QA for _destination_gateway_answer_by_meaning (ariella_chat_clean.py),
built for round 12 finding D (Shaked/Shlomo, 22.10.2026, Hallstatt/
Salzburg) - the same "fact stated while another question is in focus gets
dropped" class as dry-run 4 finding 1 (mixed baggage), but for the
destination-gateway open question (_destination_gateway_question_hint):
"זלצבורג מתאים לנו" (Salzburg suits us), said in the same message as
answering the dates question, never got written to destination_airports -
EXTRACTOR_SYSTEM's own instruction to capture this was the only mechanism,
with no deterministic backstop at all.

Fixed by mirroring _budget_answer_by_meaning/_baggage_answer_by_meaning's
pattern: gated on destination_airports still empty and the gateway
question still genuinely unresolved (_destination_gateway_unresolved_
places) - a single classifier call asks the model for the real city_en/
IATA code, verified against the catalog by _verify_catalog_airport_code.

Shlomo's refinement (22.10.2026, round 12 C/E - Paphos/Zadar): the first
version here ALSO required the last assistant turn to already be the open
gateway question - but live, the failure happens on the very FIRST
mention of the place (before any open question was ever asked). The gate
no longer requires a prior question at all - it fires on the very first
unresolved mention.

Dry-run 5b rewrite (22.10.2026, scenario E, "the most severe" per Shlomo's
relay): "ברגם" was silently resolved to Bergamo with NO question ever
asked, even though "ברגם" just as plausibly means Bergen - a genuine
resolve-the-wrong-country failure. The classifier's JSON schema changed:
- "evidence": a verbatim quote from the CUSTOMER'S CURRENT message,
  verified the same way destination_evidence/dates_evidence already are
  (_value_has_verbatim_evidence) - no quote, nothing resolves, regardless
  of what the model otherwise claims. This prevents resolving from stale
  context (the agent's own prior message) rather than the real message.
- "candidates": a list of 0-2 {city_en, iata_code} objects instead of a
  single city_en/iata_code pair. Exactly 1 verified candidate writes
  destination_airports AND destination.places (replacing the customer's
  typo'd string with the catalog's verified spelling). Exactly 2 distinct
  verified candidates write NOTHING yet - a one-turn _destination_
  ambiguous_hint names both real options so Tinkerbell asks ONE
  clarifying question between them, never silently picking one.

Per Shlomo's explicit condition: the QA must show how many times the
classifier call actually fires across representative scenarios (not just
that it works) - each scenario below counts calls tagged
source="classifier" whose prompt is this specific one (distinguished by
a marker substring unique to it), confirming it only fires in the narrow
window this guard is meant for, never on unrelated turns.

Run: python3 tools/qa_destination_gateway_answer_by_meaning.py
"""
import os
import sys
import json
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import ariella_chat_clean as chat

FAILED = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


_MARKER = "שאין לו שדה תעופה מאומת אצלנו"
GATEWAY_REPLY = (
    "היעד הלשטאט ככל הנראה חסר שדה תעופה מסחרי רשום משלו - "
    "באיזה שדה תרצו לנחות ולהמריא?"
)
UNRELATED_REPLY = "מה התקציב שלכם לאדם לטיסה?"

BASE_STATE = {
    "destination": {"places": ["הלשטאט"], "mode": None, "status": "known"},
    "destination_airports": [],
    "requested_services": ["flights"],
    "service_decisions": {"flights": {"wanted": True, "source": "destination_trip_intent"}},
}


def _counting_post_claude(calls):
    def fake(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other", **kw):
        if source == "classifier" and _MARKER in str(system_static or ""):
            calls.append(message)
            msg = str(message or "")
            if "זלצבורג" in msg:
                return json.dumps({"evidence": "זלצבורג", "candidates": [{"city_en": "Salzburg", "iata_code": "SZG"}]})
            if "פאפוס" in msg or "פפוס" in msg:
                return json.dumps({"evidence": "פפוס" if "פפוס" in msg else "פאפוס", "candidates": [{"city_en": "Paphos", "iata_code": "PFO"}]})
            if "זדאר" in msg:
                return json.dumps({"evidence": "זדאר", "candidates": [{"city_en": "Zadar", "iata_code": "ZAD"}]})
            if "ברגם" in msg:
                # Scenario E's exact ambiguous shape: two real, distinct meanings.
                return json.dumps({
                    "evidence": "ברגם",
                    "candidates": [
                        {"city_en": "Bergen", "iata_code": "BGO"},
                        {"city_en": "Bergamo", "iata_code": "BGY"},
                    ],
                })
            return json.dumps({"evidence": None, "candidates": []})
        return "{}"
    return fake


# =====================================================================
# Scenario D (the live repro, Hallstatt): gateway question was just
# asked, customer's message answers a DIFFERENT question (dates) but
# also names a real, catalogued gateway city in the same breath.
# =====================================================================
calls = []
with patch.object(chat, "_post_claude", side_effect=_counting_post_claude(calls)):
    result = chat._destination_gateway_answer_by_meaning(
        "2 עד 6 ביולי, וזלצבורג מתאים לנו",
        [{"role": "assistant", "content": GATEWAY_REPLY}],
        BASE_STATE,
    )
check("scenario D (Hallstatt repro): the named gateway city is resolved to a real code",
      result.get("destination_airports") == ["SZG"])
check("scenario D: destination.places is also updated to the verified spelling",
      result.get("destination", {}).get("places") == ["זלצבורג"])
check("scenario D: the classifier call fired exactly once",
      len(calls) == 1)

# =====================================================================
# Scenario (generic, 'A'-shape): gateway question open, but the customer's
# message is entirely unrelated and names no place at all - the call
# still fires (the narrow gate is on the QUESTION, not the answer), but
# writes nothing.
# =====================================================================
calls = []
with patch.object(chat, "_post_claude", side_effect=_counting_post_claude(calls)):
    result = chat._destination_gateway_answer_by_meaning(
        "עד 1500 שקל לאדם",
        [{"role": "assistant", "content": GATEWAY_REPLY}],
        BASE_STATE,
    )
check("unrelated answer while gateway question open: nothing written",
      result == {})
check("unrelated answer while gateway question open: the call still fired once "
      "(it has to check) - never silently guessed", len(calls) == 1)

# =====================================================================
# Scenario ('B'-shape): destination_airports already resolved - the call
# must never fire at all, regardless of what the last assistant message was.
# =====================================================================
calls = []
state_resolved = dict(BASE_STATE, destination_airports=["SZG"])
with patch.object(chat, "_post_claude", side_effect=_counting_post_claude(calls)):
    result = chat._destination_gateway_answer_by_meaning(
        "כן, זלצבורג מתאים",
        [{"role": "assistant", "content": GATEWAY_REPLY}],
        state_resolved,
    )
check("destination_airports already resolved: nothing written", result == {})
check("destination_airports already resolved: the call never fires (saves the cost)",
      len(calls) == 0)

# =====================================================================
# Scenario ('C'-shape, Shlomo's refinement, round 12 Paphos/Zadar): the
# VERY FIRST mention of the place, no gateway question has ever been
# asked yet (the last assistant turn was about something else entirely,
# or there is no history at all) - the call must STILL fire and resolve,
# same turn, before Tinkerbell ever drafts a reply claiming "no airport".
# =====================================================================
calls = []
with patch.object(chat, "_post_claude", side_effect=_counting_post_claude(calls)):
    result = chat._destination_gateway_answer_by_meaning(
        "לפפוס, לקפריסין",
        [{"role": "assistant", "content": UNRELATED_REPLY}],
        dict(BASE_STATE, destination={"places": ["פפוס"], "mode": None, "status": "known"}),
    )
check("first mention (no gateway question ever asked yet): the call still "
      "fires and resolves 'פפוס' to PFO via the model's own recognition",
      result.get("destination_airports") == ["PFO"] and len(calls) == 1)

calls = []
with patch.object(chat, "_post_claude", side_effect=_counting_post_claude(calls)):
    result = chat._destination_gateway_answer_by_meaning(
        "לזלצבורג",
        [],
        BASE_STATE,
    )
check("first mention with NO history at all (empty conversation) - the "
      "call still fires and resolves",
      result.get("destination_airports") == ["SZG"] and len(calls) == 1)

# =====================================================================
# Dry-run 5, scenario A (Shlomo/Shaked, 22.10.2026, Paphos): requested_
# services still empty (not yet set by the later destination-trip-intent
# fallback) must still fire.
# =====================================================================
calls = []
state_requested_services_not_yet_set = dict(BASE_STATE, requested_services=[], service_decisions={})
with patch.object(chat, "_post_claude", side_effect=_counting_post_claude(calls)):
    result = chat._destination_gateway_answer_by_meaning(
        "זלצבורג מתאים לנו",
        [{"role": "assistant", "content": GATEWAY_REPLY}],
        state_requested_services_not_yet_set,
    )
check("dry-run 5 fix: requested_services still empty (not yet set by the later fallback) - the call still fires",
      result.get("destination_airports") == ["SZG"] and len(calls) == 1)

# =====================================================================
# Scenario ('E'-shape): flights genuinely, explicitly declined this trip -
# the only real signal that nothing should be resolved here at all.
# =====================================================================
calls = []
state_flights_declined = dict(BASE_STATE, requested_services=[], service_decisions={"flights": {"wanted": False}})
with patch.object(chat, "_post_claude", side_effect=_counting_post_claude(calls)):
    result = chat._destination_gateway_answer_by_meaning(
        "זלצבורג מתאים לנו",
        [{"role": "assistant", "content": GATEWAY_REPLY}],
        state_flights_declined,
    )
check("flights explicitly declined (nothing to resolve): the call never fires",
      len(calls) == 0)

# =====================================================================
# Regression: an unrecognized/uncatalogued name the customer volunteers
# writes nothing - never a guess, the open question stays open.
# =====================================================================
calls = []
with patch.object(chat, "_post_claude", side_effect=_counting_post_claude(calls)):
    result = chat._destination_gateway_answer_by_meaning(
        "משהו שלא קיים בשום קטלוג",
        [{"role": "assistant", "content": GATEWAY_REPLY}],
        BASE_STATE,
    )
check("regression: an unrecognized place name writes nothing (never a guess)",
      result == {})


# =====================================================================
# Dry-run 5b item 1 (scenario E, "most severe"): genuine real-world
# ambiguity ("ברגם" = Bergen or Bergamo) asks ONE question naming both,
# never silently picks one.
# =====================================================================
calls = []
state_bergen = dict(BASE_STATE, destination={"places": ["ברגם"], "mode": None, "status": "known"})
with patch.object(chat, "_post_claude", side_effect=_counting_post_claude(calls)):
    result_bergen = chat._destination_gateway_answer_by_meaning(
        "ברגם מתאים לנו",
        [{"role": "assistant", "content": UNRELATED_REPLY}],
        state_bergen,
    )
check("scenario E fix: an ambiguous real-world name writes NO destination_airports yet",
      not result_bergen.get("destination_airports"))
check("scenario E fix: destination.places is never silently overwritten either",
      "destination" not in result_bergen)
check("scenario E fix: a one-turn _destination_ambiguous_hint names BOTH real options",
      "Bergen" in result_bergen.get("_destination_ambiguous_hint", "")
      or "ברגן" in result_bergen.get("_destination_ambiguous_hint", ""))
check("scenario E fix: the hint also names the other real option (Bergamo)",
      "Bergamo" in result_bergen.get("_destination_ambiguous_hint", "")
      or "ברגמו" in result_bergen.get("_destination_ambiguous_hint", ""))
check("scenario E fix: the hint explicitly forbids Tinkerbell from picking one herself",
      "לעולם אל תבחרי אחד מהם בעצמך" in result_bergen.get("_destination_ambiguous_hint", ""))


# =====================================================================
# Dry-run 5b item 1: the evidence requirement itself - no verbatim quote
# from the CURRENT message means nothing resolves, however confident the
# model's candidates otherwise look (prevents resolving from stale
# context/the agent's own prior message instead of the real one).
# =====================================================================
def _fake_no_evidence(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other", **kw):
    if source == "classifier" and _MARKER in str(system_static or ""):
        return json.dumps({"evidence": "מילה שלא נמצאת בהודעה בכלל", "candidates": [{"city_en": "Salzburg", "iata_code": "SZG"}]})
    return "{}"


with patch.object(chat, "_post_claude", side_effect=_fake_no_evidence):
    result_no_evidence = chat._destination_gateway_answer_by_meaning(
        "זלצבורג מתאים לנו",
        [{"role": "assistant", "content": GATEWAY_REPLY}],
        BASE_STATE,
    )
check("evidence gate: a fabricated/invented quote that isn't genuinely in the message -> nothing resolves",
      result_no_evidence == {})


def _fake_null_evidence(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other", **kw):
    if source == "classifier" and _MARKER in str(system_static or ""):
        return json.dumps({"evidence": None, "candidates": [{"city_en": "Salzburg", "iata_code": "SZG"}]})
    return "{}"


with patch.object(chat, "_post_claude", side_effect=_fake_null_evidence):
    result_null_evidence = chat._destination_gateway_answer_by_meaning(
        "זלצבורג מתאים לנו",
        [{"role": "assistant", "content": GATEWAY_REPLY}],
        BASE_STATE,
    )
check("evidence gate: null evidence with a confident-looking candidate -> nothing resolves either",
      result_null_evidence == {})


# =====================================================================
# Two candidates returned but only ONE actually verifies against the
# catalog (the other is a model hallucination/uncatalogued) - resolves
# as a single verified match, not treated as ambiguous.
# =====================================================================
def _fake_one_of_two_verifies(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other", **kw):
    if source == "classifier" and _MARKER in str(system_static or ""):
        return json.dumps({
            "evidence": "זלצבורג",
            "candidates": [
                {"city_en": "Salzburg", "iata_code": "SZG"},
                {"city_en": "Nonexistentville", "iata_code": "ZZZ"},
            ],
        })
    return "{}"


with patch.object(chat, "_post_claude", side_effect=_fake_one_of_two_verifies):
    result_one_verifies = chat._destination_gateway_answer_by_meaning(
        "זלצבורג מתאים לנו",
        [{"role": "assistant", "content": GATEWAY_REPLY}],
        BASE_STATE,
    )
check("only one of two claimed candidates actually verifies against the catalog -> "
      "resolved directly as a single match, never treated as ambiguous",
      result_one_verifies.get("destination_airports") == ["SZG"]
      and "_destination_ambiguous_hint" not in result_one_verifies)


# =====================================================================
# Two candidates returned, both resolve to the SAME verified code (model
# redundancy) - deduped to a single match, never a spurious ambiguous ask.
# =====================================================================
def _fake_duplicate_candidate(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other", **kw):
    if source == "classifier" and _MARKER in str(system_static or ""):
        return json.dumps({
            "evidence": "זלצבורג",
            "candidates": [
                {"city_en": "Salzburg", "iata_code": "SZG"},
                {"city_en": "Salzburg", "iata_code": "SZG"},
            ],
        })
    return "{}"


with patch.object(chat, "_post_claude", side_effect=_fake_duplicate_candidate):
    result_dup = chat._destination_gateway_answer_by_meaning(
        "זלצבורג מתאים לנו",
        [{"role": "assistant", "content": GATEWAY_REPLY}],
        BASE_STATE,
    )
check("two candidates that verify to the SAME code are deduped - a single match, never ambiguous",
      result_dup.get("destination_airports") == ["SZG"]
      and "_destination_ambiguous_hint" not in result_dup)


# =====================================================================
# More than 2 candidates in the model's own (malformed) output - only the
# first 2 are ever considered, per the explicit "never more than two" rule.
# =====================================================================
def _fake_three_candidates(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other", **kw):
    if source == "classifier" and _MARKER in str(system_static or ""):
        return json.dumps({
            "evidence": "ברגם",
            "candidates": [
                {"city_en": "Bergen", "iata_code": "BGO"},
                {"city_en": "Bergamo", "iata_code": "BGY"},
                {"city_en": "Zadar", "iata_code": "ZAD"},
            ],
        })
    return "{}"


with patch.object(chat, "_post_claude", side_effect=_fake_three_candidates):
    result_three = chat._destination_gateway_answer_by_meaning(
        "ברגם מתאים לנו",
        [{"role": "assistant", "content": UNRELATED_REPLY}],
        dict(BASE_STATE, destination={"places": ["ברגם"], "mode": None, "status": "known"}),
    )
check("more than 2 claimed candidates: only the first 2 are ever considered (never 3-way ambiguity)",
      "Zadar" not in result_three.get("_destination_ambiguous_hint", "")
      and "ZAD" not in result_three.get("_destination_ambiguous_hint", ""))


# =====================================================================
# _verify_catalog_airport_code: the verification primitive directly.
# =====================================================================
check("a real code + its real catalog city_en -> verified",
      chat._verify_catalog_airport_code("SZG", "Salzburg") == "SZG")
check("case-insensitive city_en match still verifies",
      chat._verify_catalog_airport_code("szg", "salzburg") == "SZG")
check("a real code but the WRONG city attributed to it -> rejected "
      "(never trust the code alone)",
      chat._verify_catalog_airport_code("SZG", "Vienna") is None)
check("a code that doesn't exist in the catalog at all -> rejected",
      chat._verify_catalog_airport_code("ZZZ", "Nowhere") is None)
check("empty code or city -> rejected, never crashes",
      chat._verify_catalog_airport_code("", "Salzburg") is None
      and chat._verify_catalog_airport_code("SZG", "") is None
      and chat._verify_catalog_airport_code(None, None) is None)

# =====================================================================
# The business owner's own live example (22.10): "פפוס" (missing the א of
# "פאפוס") must still resolve, via the model's own recognition - not a
# Hebrew alias table. The model is expected to recognize it regardless of
# the customer's exact Hebrew spelling and return the real English name.
# =====================================================================
calls = []
state_paphos = dict(BASE_STATE, destination={"places": ["פפוס"], "mode": None, "status": "known"})
with patch.object(chat, "_post_claude", side_effect=_counting_post_claude(calls)):
    result = chat._destination_gateway_answer_by_meaning(
        "פפוס מתאים לנו",
        [{"role": "assistant", "content": GATEWAY_REPLY}],
        state_paphos,
    )
check("business owner's example: 'פפוס' (no א) still resolves to PFO via the "
      "model's own recognition, not a Hebrew alias table",
      result.get("destination_airports") == ["PFO"])
check("business owner's example: destination.places is updated to the catalog's verified spelling",
      result.get("destination", {}).get("places") == ["פאפוס"])

# =====================================================================
# Round 12 finding E (Zadar) + Ido's own explicit warning (22.10.2026,
# cross-session relay): ZAD only exists in the EXTENDED catalog (Ido's 020
# stage B, data/airports_extended.json), not the verified static one -
# _verify_catalog_airport_code must check _catalog_airport_by_code (the
# verified catalog, then the extended one as fallback), never
# _load_airports() alone, or this guard would keep rejecting Zadar/ZAD
# despite the catalog merge, exactly the live "אין שדה תעופה מסחרי" claim
# this whole mechanism exists to prevent.
# =====================================================================
calls_zadar = []
state_zadar = dict(BASE_STATE, destination={"places": ["זדאר"], "mode": None, "status": "known"})
with patch.object(chat, "_post_claude", side_effect=_counting_post_claude(calls_zadar)):
    result_zadar = chat._destination_gateway_answer_by_meaning(
        "זדאר מתאים לנו",
        [{"role": "assistant", "content": GATEWAY_REPLY}],
        state_zadar,
    )
check("round 12 finding E: 'זדאר' resolves to ZAD via the extended catalog "
      "(_catalog_airport_by_code), not just the verified static one",
      result_zadar.get("destination_airports") == ["ZAD"])
check("direct: _verify_catalog_airport_code itself recognizes ZAD/Zadar "
      "(extended-catalog-only airport)",
      chat._verify_catalog_airport_code("ZAD", "Zadar") == "ZAD")

# =====================================================================
# Full-pipeline wiring: the new call is actually merged into trip_update
# by the main turn-processing path, not just a standalone function; the
# ambiguous hint is wired into the single-question arbiter at the same
# priority tier as the generic gateway question.
# =====================================================================
_SOURCE = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                             "ariella_chat_clean.py"), encoding="utf-8").read()
check("the new classifier is wired into the main merge pipeline (source present)",
      "_destination_gateway_answer_by_meaning(message, history, trip_update)" in _SOURCE)
check("_destination_ambiguous_hint is wired into _turn_question_arbiter",
      '"_destination_ambiguous_hint"' in _SOURCE and '"destination_ambiguous"' in _SOURCE)

# =====================================================================
# Dry-run 5f (23.10.2026, Shaked's LIVE finding, 4th recurrence): "ברגם"
# was STILL silently resolved to Bergamo (BGY) with no question asked,
# even with the structural catalog signal in place - because the model
# was still free to satisfy the ordinary "evidence" field with nothing
# more than the destination name itself, then simply pick ONE of the two
# structurally-ambiguous candidates. Verified locally by Shaked:
# _reresolve_ambiguous_fresh_destination correctly left it unresolved, so
# the live bug was here, in this function's single-candidate trust path.
# Fixed: when the catalog's own near_cities signal already proved a real
# 2-way ambiguity but the model verified only ONE candidate, that pick is
# no longer trusted unless backed by disambiguating_evidence - a SEPARATE
# verbatim quote, genuinely distinct from the destination name itself.
# =====================================================================
def _fake_bergen_single_pick_no_disambiguation(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other", **kw):
    if source == "classifier" and _MARKER in str(system_static or ""):
        # The exact live failure shape: evidence is just the raw typo'd
        # name itself, no genuinely distinguishing quote supplied.
        return json.dumps({
            "evidence": "ברגם",
            "candidates": [{"city_en": "Bergamo", "iata_code": "BGY"}],
            "disambiguating_evidence": None,
        })
    return "{}"


with patch.object(chat, "_post_claude", side_effect=_fake_bergen_single_pick_no_disambiguation):
    result_bergen_unsupported = chat._destination_gateway_answer_by_meaning(
        "ברגם מתאים לנו",
        [{"role": "assistant", "content": UNRELATED_REPLY}],
        state_bergen,
    )
check("dry-run 5f FIX: a single-candidate pick (Bergamo) with NO genuine "
      "disambiguating evidence is no longer trusted - destination_airports stays empty",
      not result_bergen_unsupported.get("destination_airports"))
check("dry-run 5f FIX: the structural signal forces BOTH real catalog candidates into the hint",
      ("Bergen" in result_bergen_unsupported.get("_destination_ambiguous_hint", "")
       or "ברגן" in result_bergen_unsupported.get("_destination_ambiguous_hint", ""))
      and ("Bergamo" in result_bergen_unsupported.get("_destination_ambiguous_hint", "")
           or "ברגמו" in result_bergen_unsupported.get("_destination_ambiguous_hint", "")))


def _fake_bergen_single_pick_echo_disambiguation(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other", **kw):
    if source == "classifier" and _MARKER in str(system_static or ""):
        # The model echoes the SAME bare name into disambiguating_evidence
        # too (no genuinely new information) - must still be rejected.
        return json.dumps({
            "evidence": "ברגם",
            "candidates": [{"city_en": "Bergamo", "iata_code": "BGY"}],
            "disambiguating_evidence": "ברגם",
        })
    return "{}"


with patch.object(chat, "_post_claude", side_effect=_fake_bergen_single_pick_echo_disambiguation):
    result_bergen_echo = chat._destination_gateway_answer_by_meaning(
        "ברגם מתאים לנו",
        [{"role": "assistant", "content": UNRELATED_REPLY}],
        state_bergen,
    )
check("dry-run 5f FIX regression: disambiguating_evidence that merely echoes the "
      "destination name itself (no new information) is also rejected - still forced ambiguous",
      not result_bergen_echo.get("destination_airports"))


# =====================================================================
# Shaked's own review of 6f52bd07 (23.10.2026): the exact-string-equality
# echo check above only catches an IDENTICAL echo - it let through a quote
# that's still nothing but the same name wrapped in a preposition, trailing
# punctuation, irrelevant context, or date noise. Four cases she named
# directly, each of which must STILL be rejected.
# =====================================================================
def _make_fake_bergen_disambiguation(evidence_text):
    def fake(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other", **kw):
        if source == "classifier" and _MARKER in str(system_static or ""):
            return json.dumps({
                "evidence": "ברגם",
                "candidates": [{"city_en": "Bergamo", "iata_code": "BGY"}],
                "disambiguating_evidence": evidence_text,
            })
        return "{}"
    return fake


for noisy_evidence, label in [
    ("לברגם", "same word with a ל prefix"),
    ("ברגם,", "same word with trailing punctuation"),
    ("בן שנה לברגם", "irrelevant context, no real distinguishing content"),
    ("לברגם, 12 עד 17 ביוני", "dates added, nothing actually distinguishing"),
]:
    message_with_evidence = f"{noisy_evidence} מתאים לנו"
    with patch.object(chat, "_post_claude", side_effect=_make_fake_bergen_disambiguation(noisy_evidence)):
        result_noisy = chat._destination_gateway_answer_by_meaning(
            message_with_evidence,
            [{"role": "assistant", "content": UNRELATED_REPLY}],
            state_bergen,
        )
    check(f"dry-run 5f FIX (Shaked's review): disambiguating_evidence {noisy_evidence!r} "
          f"({label}) is still rejected as non-genuine - forced ambiguous",
          not result_noisy.get("destination_airports"))


# =====================================================================
# Shaked's SECOND review (23.10.2026, of 9419b02e): the stopword-based
# design above still let through unrelated context words it never saw
# before ("אשתי", "התינוק", "בעלי" - none are place names at all, so the
# edit-distance-to-the-name check alone let them "survive"). Six exact
# quotes she tested directly, all of which must STILL be rejected now
# that the check is catalog-verified (country_he / same-country city_he)
# rather than word-list-based.
# =====================================================================
for noisy_evidence, label in [
    ("אני, אשתי והתינוק שלנו בן שנה לברגם", "family context, no real place name"),
    ("והתינוק שלנו בן שנה לברגם", "family context, no real place name"),
    ("שלנו בן שנה לברגם", "family context, no real place name"),
    ("אשתי והתינוק", "unrelated context, no place name at all"),
    ("ובעלי לברגם", "unrelated context plus the name itself"),
    ("אני ובעלי", "unrelated context, no place name at all"),
]:
    message_with_evidence = f"{noisy_evidence} מתאים לנו"
    with patch.object(chat, "_post_claude", side_effect=_make_fake_bergen_disambiguation(noisy_evidence)):
        result_noisy2 = chat._destination_gateway_answer_by_meaning(
            message_with_evidence,
            [{"role": "assistant", "content": UNRELATED_REPLY}],
            state_bergen,
        )
    check(f"dry-run 5f FIX (Shaked's 2nd review): disambiguating_evidence {noisy_evidence!r} "
          f"({label}) is still rejected - no real country/city match, forced ambiguous",
          not result_noisy2.get("destination_airports"))


def _make_fake_bergen_candidate_disambiguation(candidate_en, candidate_code, evidence_text):
    def fake(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other", **kw):
        if source == "classifier" and _MARKER in str(system_static or ""):
            return json.dumps({
                "evidence": "ברגם",
                "candidates": [{"city_en": candidate_en, "iata_code": candidate_code}],
                "disambiguating_evidence": evidence_text,
            })
        return "{}"
    return fake


for candidate_en, candidate_code, genuine_evidence, label in [
    ("Bergamo", "BGY", "באיטליה", "the candidate's own real country"),
    ("Bergamo", "BGY", "ליד מילאנו", "a DIFFERENT real catalog city (Milan) in the same country"),
    ("Bergen", "BGO", "בנורווגיה", "the OTHER candidate's own real country"),
]:
    message_with_evidence = f"ברגם {genuine_evidence} מתאים לנו"
    with patch.object(chat, "_post_claude",
                       side_effect=_make_fake_bergen_candidate_disambiguation(candidate_en, candidate_code, genuine_evidence)):
        result_genuine = chat._destination_gateway_answer_by_meaning(
            message_with_evidence,
            [{"role": "assistant", "content": UNRELATED_REPLY}],
            state_bergen,
        )
    check(f"dry-run 5f FIX (Shaked's 2nd review): disambiguating_evidence {genuine_evidence!r} "
          f"({label}) is catalog-verified as genuine - resolves directly to {candidate_en}",
          result_genuine.get("destination_airports") == [candidate_code]
          and "_destination_ambiguous_hint" not in result_genuine)


def _fake_bergen_single_pick_fabricated_disambiguation(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other", **kw):
    if source == "classifier" and _MARKER in str(system_static or ""):
        # A disambiguating quote that ISN'T actually in the message at all
        # (fabricated) - the verbatim-evidence gate must still catch it.
        return json.dumps({
            "evidence": "ברגם",
            "candidates": [{"city_en": "Bergamo", "iata_code": "BGY"}],
            "disambiguating_evidence": "באיטליה",
        })
    return "{}"


with patch.object(chat, "_post_claude", side_effect=_fake_bergen_single_pick_fabricated_disambiguation):
    result_bergen_fabricated = chat._destination_gateway_answer_by_meaning(
        "ברגם מתאים לנו",  # the message never actually mentions a country
        [{"role": "assistant", "content": UNRELATED_REPLY}],
        state_bergen,
    )
check("dry-run 5f FIX regression: a disambiguating quote that isn't genuinely in the "
      "CURRENT message (fabricated) is rejected by the same verbatim-evidence gate - still forced ambiguous",
      not result_bergen_fabricated.get("destination_airports"))

_AI_USAGE_SOURCE = open(
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "ai_usage.py"),
    encoding="utf-8").read()
check("dry-run 5f FIX: a new destination_ambiguity_override diagnostic event is registered",
      "destination_ambiguity_override" in _AI_USAGE_SOURCE)


# =====================================================================
# Dry-run 5g (23.10.2026, Shaked's LIVE finding on 0f78d081, scenarios E1
# and E2): the raw unresolved place can legitimately still carry its
# leading ל/ב/מ preposition exactly as the extractor captured it (e.g.
# "לברגם" from "...לברגם, 12 עד..."). near_cities was computed only on
# that raw form - edit distance 2, not 1, to either real city - so it came
# back EMPTY, the whole dry-run 5f/5g disambiguation-evidence requirement
# never engaged at all, and the single verified candidate was blindly
# trusted exactly like the original (pre-dry-run-5c) bug, through this
# gap. E2 additionally got stuck in an 8x open-question loop, since with
# no catalog_candidates_text nudge the model couldn't confidently name
# even one candidate either.
# =====================================================================
state_bergen_lamed = dict(BASE_STATE, destination={"places": ["לברגם"], "mode": None, "status": "known"})

check("dry-run 5g FIX: near_cities on the raw ל-prefixed place alone is still empty "
      "(confirms the gap existed before the fix)",
      chat._catalog_near_neighbor_cities("לברגם") == {})
check("dry-run 5g FIX: near_cities on the ל-stripped form correctly finds both real candidates",
      set(chat._catalog_near_neighbor_cities("ברגם").keys()) == {"ברגן", "ברגמו"})


def _fake_lamed_bergam_single_pick(candidate_en, candidate_code, disambiguating_evidence):
    def fake(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other", **kw):
        if source == "classifier" and _MARKER in str(system_static or ""):
            return json.dumps({
                "evidence": "לברגם",
                "candidates": [{"city_en": candidate_en, "iata_code": candidate_code}],
                "disambiguating_evidence": disambiguating_evidence,
            })
        return "{}"
    return fake


# E1's repro message, exactly as Shaked ran it live: a single confident
# pick with NO genuine disambiguating evidence must now be forced
# ambiguous (this is the live bug - it was silently resolving to Bergamo).
with patch.object(chat, "_post_claude", side_effect=_fake_lamed_bergam_single_pick("Bergamo", "BGY", None)):
    result_e1 = chat._destination_gateway_answer_by_meaning(
        "אני, אשתי והתינוק שלנו בן שנה לברגם, 12 עד 17 ביוני",
        [{"role": "assistant", "content": UNRELATED_REPLY}],
        state_bergen_lamed,
    )
check("dry-run 5g FIX (E1 repro, ל-prefixed place, no genuine evidence): "
      "no longer silently resolves to Bergamo - forced ambiguous",
      not result_e1.get("destination_airports") and "_destination_ambiguous_hint" in result_e1)

# E2's repro message: with the gap fixed, the model gets the structural
# nudge and (no genuine evidence this time) must still be forced ambiguous
# rather than stalling with 0 candidates in an open-question loop.
with patch.object(chat, "_post_claude", side_effect=_fake_lamed_bergam_single_pick("Bergen", "BGO", None)):
    result_e2_no_evidence = chat._destination_gateway_answer_by_meaning(
        "אני ובעלי לברגם בנורווגיה",
        [{"role": "assistant", "content": UNRELATED_REPLY}],
        state_bergen_lamed,
    )
check("dry-run 5g FIX (E2 repro, ל-prefixed place, no genuine evidence): forced ambiguous, "
      "not left stuck with 0 candidates",
      not result_e2_no_evidence.get("destination_airports") and "_destination_ambiguous_hint" in result_e2_no_evidence)

# E2 with the customer's own genuine country evidence ("בנורווגיה") present
# in the message - must now resolve directly to Bergen.
with patch.object(chat, "_post_claude", side_effect=_fake_lamed_bergam_single_pick("Bergen", "BGO", "בנורווגיה")):
    result_e2_genuine = chat._destination_gateway_answer_by_meaning(
        "אני ובעלי לברגם בנורווגיה",
        [{"role": "assistant", "content": UNRELATED_REPLY}],
        state_bergen_lamed,
    )
check("dry-run 5g FIX (E2 repro, ל-prefixed place, genuine 'בנורווגיה' evidence): "
      "resolves directly to Bergen",
      result_e2_genuine.get("destination_airports") == ["BGO"]
      and "_destination_ambiguous_hint" not in result_e2_genuine)

# The exact message text from Shaked's dry-run 5g report
# (qa/reports/2026-10-23-dryrun5g.md, branch shaked): "לברגם בנורווגיה".
with patch.object(chat, "_post_claude", side_effect=_fake_lamed_bergam_single_pick("Bergen", "BGO", "בנורווגיה")):
    result_e2_exact_repro = chat._destination_gateway_answer_by_meaning(
        "לברגם בנורווגיה", [], state_bergen_lamed,
    )
check("dry-run 5g FIX (E2 EXACT repro text 'לברגם בנורווגיה'): resolves directly to Bergen",
      result_e2_exact_repro.get("destination_airports") == ["BGO"]
      and "_destination_ambiguous_hint" not in result_e2_exact_repro)


# =====================================================================
# Shlomo's own investigation (23.10.2026) of E1's real input (qa-dryrun
# branch, chat_log_dr5g1.jsonl): E1's actual turn-0 message was NEVER bare
# "ברגם" - it was "אני, אשתי והתינוק שלנו בן שנה לברגם, 12 עד 17 ביוני",
# the exact same ל-prefixed root cause as E2. Same fix (bbf7d990),
# verified directly against the real message text.
# =====================================================================
MSG_E1_EXACT = "אני, אשתי והתינוק שלנו בן שנה לברגם, 12 עד 17 ביוני"

with patch.object(chat, "_post_claude", side_effect=_fake_lamed_bergam_single_pick("Bergamo", "BGY", None)):
    result_e1_exact_no_evidence = chat._destination_gateway_answer_by_meaning(
        MSG_E1_EXACT, [{"role": "assistant", "content": UNRELATED_REPLY}], state_bergen_lamed,
    )
check("dry-run 5g FIX (E1 EXACT repro text, turn 0, no genuine evidence): "
      "no longer silently resolves to Bergamo - forced ambiguous",
      not result_e1_exact_no_evidence.get("destination_airports")
      and "_destination_ambiguous_hint" in result_e1_exact_no_evidence)

# _reresolve_ambiguous_fresh_destination (the sibling function) on this
# same exact message - confirms it was always correct in isolation, as
# Shaked found; the gap was only in the gateway function's near_cities.
_e1_prior_state = {"destination_airports": []}
_e1_fresh_update = {"destination_airports": ["BGY"], "destination": {"places": ["ברגמו"], "mode": "specific", "status": "known"}}
result_e1_reresolve = chat._reresolve_ambiguous_fresh_destination(_e1_prior_state, _e1_fresh_update, "לברגם", MSG_E1_EXACT)
check("dry-run 5g: _reresolve_ambiguous_fresh_destination on the exact E1 message "
      "correctly reverts a fresh same-turn resolution (already worked before this fix)",
      result_e1_reresolve.get("destination_airports") == [])

# Turn 1 of E1's live scenario: the customer answers the (now correctly
# asked) ambiguous question with "ברגן, בנורווגיה" - must resolve to Bergen.
def _fake_turn1_answer(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other", **kw):
    if source == "classifier" and _MARKER in str(system_static or ""):
        return json.dumps({
            "evidence": "ברגן, בנורווגיה",
            "candidates": [{"city_en": "Bergen", "iata_code": "BGO"}],
            "disambiguating_evidence": "בנורווגיה",
        })
    return "{}"


state_turn1_unresolved = dict(BASE_STATE, destination={"places": ["ברגם"], "mode": None, "status": "known"})
with patch.object(chat, "_post_claude", side_effect=_fake_turn1_answer):
    result_e1_turn1 = chat._destination_gateway_answer_by_meaning(
        "ברגן, בנורווגיה", [{"role": "assistant", "content": UNRELATED_REPLY}], state_turn1_unresolved,
    )
check("dry-run 5g: once turn 0 correctly stays ambiguous, the customer's own next-turn answer "
      "('ברגן, בנורווגיה') resolves cleanly to Bergen",
      result_e1_turn1.get("destination_airports") == ["BGO"])

# Shlomo's defense-in-depth question: is _guard_destination_change_evidence
# itself the reason an explicit later correction doesn't overwrite an
# already-resolved (wrong) destination? Verified directly: the guard lets
# the change through whenever destination_evidence verifies, and only
# reverts when it does not - this is the guard working exactly as
# designed, not a bug in it. (Separately: if EXTRACTOR_SYSTEM itself fails
# to supply destination_evidence for this kind of correction, that is a
# distinct, NOT-yet-investigated prompt-level gap - out of scope here.)
_prior_state_bgy = {"destination_airports": ["BGY"], "destination": {"places": ["ברגמו"]}}
_trip_update_correction = {"destination_airports": ["BGO"], "destination": {"places": ["ברגן"]}}
_correction_message = "לא, זה בעצם ברגן, בנורווגיה"
result_guard_with_evidence = chat._guard_destination_change_evidence(
    _prior_state_bgy, _trip_update_correction, "ברגן, בנורווגיה", _correction_message)
check("dry-run 5g: _guard_destination_change_evidence itself is NOT the bug - it lets an "
      "explicit correction through when the extractor supplies a verified destination_evidence quote",
      result_guard_with_evidence.get("destination_airports") == ["BGO"])
result_guard_without_evidence = chat._guard_destination_change_evidence(
    _prior_state_bgy, _trip_update_correction, None, _correction_message)
check("dry-run 5g: REGRESSION GUARD - without destination_evidence, the guard correctly keeps "
      "reverting to the prior value (working as designed, not a bug)",
      result_guard_without_evidence.get("destination_airports") == ["BGY"])


# =====================================================================
# Shaked's follow-up static review of bbf7d990 (23.10.2026, non-blocking
# but a real gap): checking the raw form first and only falling back to
# the stripped form when the raw form found NOTHING missed the case where
# the raw form finds a NEAR (non-exact) match - stopping the search
# before the stripped form's own EXACT match ever gets a chance. Her named
# example: "במקאו" (with the ב prefix) - the raw form lands near an
# unrelated city ("במקו"), while the stripped form "מקאו" is an exact
# match to the real catalog city. Fixed: an exact match on ANY form wins,
# checked across every form before any near match is trusted.
# =====================================================================
check("dry-run 5g FIX (Shaked's ordering review): the raw ב-prefixed 'במקאו' alone "
      "produces a (wrong) 2-way near-match set, not the real exact match",
      set(chat._catalog_near_neighbor_cities("במקאו").keys()) == {"במקו", "מקאו"})
check("dry-run 5g FIX (Shaked's ordering review): the ב-stripped 'מקאו' is a real exact match",
      chat._catalog_near_neighbor_cities("מקאו", max_distance=0) == {"מקאו": ["MFM"]})

_MACAU_CITY_EN = (chat._catalog_airport_by_code("MFM") or {}).get("city_en")


def _fake_macau(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other", **kw):
    if source == "classifier" and _MARKER in str(system_static or ""):
        return json.dumps({"evidence": "במקאו", "candidates": [{"city_en": _MACAU_CITY_EN, "iata_code": "MFM"}]})
    return "{}"


state_macau = dict(BASE_STATE, destination={"places": ["במקאו"], "mode": None, "status": "known"})
with patch.object(chat, "_post_claude", side_effect=_fake_macau):
    result_macau = chat._destination_gateway_answer_by_meaning(
        "אני רוצה לטוס במקאו", [], state_macau,
    )
check("dry-run 5g FIX (Shaked's ordering review): 'במקאו' now resolves decisively via the "
      "stripped form's exact match, never treated as a false 2-way ambiguity",
      result_macau.get("destination_airports") == ["MFM"]
      and "_destination_ambiguous_hint" not in result_macau)

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL DESTINATION-GATEWAY-ANSWER-BY-MEANING TESTS PASSED")
