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
exact pattern: gated on destination_airports still empty, the gateway
question still genuinely unresolved, and the last assistant message
actually being that open gateway question (topic-word gate, same as the
siblings) - then one classifier call extracts ONLY the free-text place
name (never a guessed code), resolved through the existing deterministic,
never-substring _match_city_exact.

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


_MARKER = "שדה התעופה/העיר הקרובים ביותר"
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
# Scenario ('C'-shape): gateway question was NOT the last thing asked
# (a completely different topic was) - the call must not fire even
# though destination_airports happens to still be empty.
# =====================================================================
calls = []
with patch.object(chat, "_post_claude", side_effect=_counting_post_claude(calls)):
    result = chat._destination_gateway_answer_by_meaning(
        "זלצבורג מתאים לנו",
        [{"role": "assistant", "content": UNRELATED_REPLY}],
        BASE_STATE,
    )
check("gateway question was not actually the last thing asked: the call never fires",
      len(calls) == 0)
check("gateway question was not actually the last thing asked: nothing written "
      "(even though the customer's text happens to name a real city)",
      result == {})

# =====================================================================
# Scenario ('E'-shape): destination genuinely resolved some other way this
# turn (e.g. a route got approved) - _destination_gateway_unresolved_places
# itself returns empty, so the call must not fire.
# =====================================================================
calls = []
state_no_flights = dict(BASE_STATE, requested_services=[], service_decisions={})
with patch.object(chat, "_post_claude", side_effect=_counting_post_claude(calls)):
    result = chat._destination_gateway_answer_by_meaning(
        "זלצבורג מתאים לנו",
        [{"role": "assistant", "content": GATEWAY_REPLY}],
        state_no_flights,
    )
check("flights not even requested (nothing to resolve): the call never fires",
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
