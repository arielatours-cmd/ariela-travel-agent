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


def _fake_bergen_single_pick_genuine_disambiguation(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other", **kw):
    if source == "classifier" and _MARKER in str(system_static or ""):
        # A genuinely distinguishing quote, verbatim in the message, that
        # is NOT the destination name itself - e.g. the country.
        return json.dumps({
            "evidence": "ברגם",
            "candidates": [{"city_en": "Bergamo", "iata_code": "BGY"}],
            "disambiguating_evidence": "באיטליה",
        })
    return "{}"


with patch.object(chat, "_post_claude", side_effect=_fake_bergen_single_pick_genuine_disambiguation):
    result_bergen_genuine = chat._destination_gateway_answer_by_meaning(
        "ברגם באיטליה מתאים לנו",
        [{"role": "assistant", "content": UNRELATED_REPLY}],
        state_bergen,
    )
check("dry-run 5f FIX regression: a GENUINE disambiguating quote (the country, "
      "verbatim in the message, distinct from the destination name) still resolves directly",
      result_bergen_genuine.get("destination_airports") == ["BGY"]
      and "_destination_ambiguous_hint" not in result_bergen_genuine)


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

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL DESTINATION-GATEWAY-ANSWER-BY-MEANING TESTS PASSED")
