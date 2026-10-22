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
mention of the place (before any open question was ever asked), where
Tinkerbell confidently claimed "no commercial airport" instead of
recognizing her own uncertainty (root cause: _destination_catalog_hint's
deterministic catalog match uses Hebrew spelling normalization, which
does not bridge "פפוס" (missing א) to the catalog's "פאפוס" - the model's
own real-world knowledge does). The gate no longer requires a prior
question at all - it fires on the very first unresolved mention, so this
guard can resolve the field (same turn, before the reply is drafted)
before Tinkerbell ever has to say anything about it.

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
            if "זלצבורג" in str(message or ""):
                return '{"city_en": "Salzburg", "iata_code": "SZG"}'
            if "פאפוס" in str(message or "") or "פפוס" in str(message or ""):
                return '{"city_en": "Paphos", "iata_code": "PFO"}'
            if "זדאר" in str(message or ""):
                return '{"city_en": "Zadar", "iata_code": "ZAD"}'
            return '{"city_en": null, "iata_code": null}'
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
# Dry-run 5, scenario A (Shlomo/Shaked, 22.10.2026, Paphos): the gate used
# to require "flights" already IN requested_services - but on the VERY
# FIRST turn (destination+dates+travelers all named together), that list
# only gets "flights" added by the destination-trip-intent fallback the
# caller runs AFTER this classifier, so the gate read false exactly when
# it most needed to read true and the guard never fired at all - the live
# bug (destination_airports stayed unresolved, Tinkerbell claimed "no
# commercial airport"). Fixed: mirrors that same fallback's own condition
# (a destination was named and flights were never explicitly declined),
# which needs nothing computed later in the turn to already exist - so an
# EMPTY requested_services alone, with no explicit decline either, must
# still fire.
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
# by the main turn-processing path, not just a standalone function.
# =====================================================================
check("the new classifier is wired into the main merge pipeline (source present)",
      "_destination_gateway_answer_by_meaning(message, history, trip_update)" in
      open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                         "ariella_chat_clean.py"), encoding="utf-8").read())

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL DESTINATION-GATEWAY-ANSWER-BY-MEANING TESTS PASSED")
