"""QA for Shlomo's relay (20.10.2026, live finding on main@30e07e1, prior to
PR #91): r90b5, Zurich - trip_type flipped to "ski" mid-conversation with no
customer mention of skiing at all ("ציריך בינואר" - a plain city+month
mention, genuinely NOT a ski trip claim). The extractor's own trip_update
silently claimed trip_type="ski" with nothing in the customer's message to
justify it - the same unverified-overclaim pattern already fixed for
destination/dates, now mirrored for trip_type.

Fixed, following the exact precedent of destination_evidence/
_guard_destination_change_evidence:
- A new top-level JSON sibling "trip_type_evidence" (EXTRACTOR_SYSTEM),
  parsed by the new _parse_trip_type_evidence(text).
- A new _guard_ski_trip_type_evidence(trip_state, trip_update,
  trip_type_evidence, message): once trip_type is NOT already "ski", a new
  claimed switch TO "ski" is accepted only when either the existing
  deterministic ski-keyword detector (_deterministic_trip_type_facts)
  independently confirms it, or a genuine verbatim quote from the CURRENT
  message backs it up - otherwise trip_type reverts to its prior value.
  A prior trip_type of "ski" is never reverted (nothing to protect against
  a legitimate ongoing ski-trip conversation).
- A new "trip_type_ski_claim" diagnostic event source (structured
  prior/verified booleans only, never the customer's own message text).

Run: python3 tools/qa_zurich_ski_trip_type_evidence.py
"""
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import database
database.init_db()

import ariella_chat_clean as chat
import ai_usage

FAILED = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


# =====================================================================
# Schema / plumbing.
# =====================================================================
check("trip_type_ski_claim registered as a valid diagnostic event source",
      "trip_type_ski_claim" in ai_usage.DIAGNOSTIC_EVENT_SOURCES)
check("EXTRACTOR_SYSTEM documents trip_type_evidence as a top-level sibling of trip_update",
      '"trip_type_evidence"' in chat.EXTRACTOR_SYSTEM)
check("EXTRACTOR_SYSTEM names Zurich/January as an explicit non-ski counter-example",
      "ציריך בינואר" in chat.EXTRACTOR_SYSTEM)

# =====================================================================
# r90b5: unverified ski-type claim, direct unit test of the guard.
# =====================================================================
_zurich_state = {"trip_type": "regular", "destination": {"places": ["ציריך"]}}
_claimed_ski = {"trip_type": "ski", "destination": {"places": ["ציריך"]}}

_locked = chat._guard_ski_trip_type_evidence(_zurich_state, dict(_claimed_ski), None, "ציריך בינואר")
check("r90b5: an unverified ski-type claim ('ציריך בינואר', no evidence quote, no ski keyword) "
      "is reverted to the prior trip_type",
      _locked.get("trip_type") == "regular")

_ski_msg = "בציריך נרצה לגלוש על המדרונות המושלגים כמה ימים"
_genuine = chat._guard_ski_trip_type_evidence(
    _zurich_state, dict(_claimed_ski), "לגלוש על המדרונות המושלגים", _ski_msg
)
check("regression: a genuinely quoted ski claim (verbatim in the message, no exact ski-keyword match) "
      "is accepted, not reverted",
      _genuine.get("trip_type") == "ski")
check("sanity: the test message itself does not trip the deterministic ski-keyword detector "
      "(this check is isolating the evidence-quote path, not the keyword path)",
      chat._deterministic_trip_type_facts(_ski_msg).get("trip_type") != "ski")

_keyword_confirmed = chat._guard_ski_trip_type_evidence(
    _zurich_state, dict(_claimed_ski), None, "חופשת סקי בציריך"
)
check("regression: the existing deterministic ski-keyword detector alone (no evidence quote needed) "
      "also justifies the claim",
      _keyword_confirmed.get("trip_type") == "ski")

_no_prior_state = {"trip_type": None}
_first_time = chat._guard_ski_trip_type_evidence(_no_prior_state, dict(_claimed_ski), None, "סקי")
check("regression: the FIRST time trip_type is set to ski (nothing to protect yet) is never blocked",
      _first_time.get("trip_type") == "ski")

_already_ski_state = {"trip_type": "ski"}
_still_ski = chat._guard_ski_trip_type_evidence(_already_ski_state, {"trip_type": "ski"}, None, "ציריך בינואר")
check("regression: an ALREADY-ski prior trip_type is never reverted just because this turn's "
      "message doesn't repeat a ski keyword",
      _still_ski.get("trip_type") == "ski")

_non_ski_claim = chat._guard_ski_trip_type_evidence(_zurich_state, {"trip_type": "business"}, None, "נסיעת עסקים")
check("regression: a claimed switch to anything OTHER than 'ski' is never gated by this guard at all",
      _non_ski_claim.get("trip_type") == "business")

# =====================================================================
# Diagnostic event content (structured only, never raw customer text).
# =====================================================================
ai_usage.set_ai_usage_context(member_id=None, is_test=True)
chat._guard_ski_trip_type_evidence(_zurich_state, dict(_claimed_ski), None, "ציריך בינואר - זה סודי")
_rows = ai_usage.diagnostic_rows("trip_type_ski_claim", include_test=True)
check("trip_type_ski_claim: a row was written for the blocked attempt",
      bool(_rows) and json.loads(_rows[-1]["details"]).get("verified") is False)
check("no diagnostic row anywhere contains the customer's own message text",
      all("ציריך בינואר - זה סודי" not in (r.get("details") or "") for r in _rows))
ai_usage.clear_ai_usage_context()

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL ZURICH-SKI-TRIP-TYPE-EVIDENCE TESTS PASSED")
