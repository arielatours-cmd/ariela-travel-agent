"""QA for Shaked's live report (2026-10-13, qa-s82, Cyprus), two bugs from
the same family as _budget_answer_by_meaning (already in production):
deterministic phrase lists kept failing on perfectly clear but unlisted
phrasings.

1. "מזוודה לכל אחד" (a suitcase for everyone - a direct answer to the
   baggage question) matched none of _deterministic_baggage_facts's
   patterns (they all require a more specific shape like "בבטן המטוס" or
   "גדולה"), so flight.baggage stayed empty and the question was asked
   again. Added _baggage_answer_by_meaning, gated exactly like
   _budget_answer_by_meaning: only when baggage is still unknown and the
   last question was genuinely about it.

2. "יפה מאוד, מאשרים את המסלול" is an unambiguous route approval, but
   matched none of _is_itinerary_acceptance's curated positives - the
   inflected "מאשרים" (plural) vs the listed "מאשר"/"מאשרת", and "יפה
   מאוד" isn't one of the listed synonyms. Added
   _itinerary_acceptance_by_meaning as a fallback, only ever consulted
   from within chat_clean()'s already-gated planning_accept context (a
   real day-by-day route was just proposed), never elsewhere.

This mocks _post_claude (no real network call) and tests both functions
directly, plus their gating (never calling the model when the fact is
already known or the context doesn't match).

Run: python3 tools/qa_baggage_and_itinerary_acceptance_by_meaning.py
"""
import json
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


BAGGAGE_HISTORY = [{"role": "assistant", "content": "יש לכם רק טרולי, גם מזוודה בבטן המטוס, או רק תיק קטן?"}]

# --- 1. Exact Shaked phrasing resolves via meaning ---
def fake_checked_bag(key, model, s, d, h, m, mt, include_history=True, source="other"):
    return json.dumps({"baggage": "checked_bag"})
with patch.object(chat, "_post_claude", side_effect=fake_checked_bag):
    resolved = chat._baggage_answer_by_meaning("מזוודה לכל אחד", BAGGAGE_HISTORY, {"flight": {"baggage": None}})
check("'מזוודה לכל אחד' resolves to checked_bag via meaning", resolved == {"flight": {"baggage": ["checked_bag"]}})

# --- 2. Already-known baggage -> never calls the model ---
called = {"n": 0}
def fake_counter(*a, **kw):
    called["n"] += 1
    return "{}"
with patch.object(chat, "_post_claude", side_effect=fake_counter):
    resolved2 = chat._baggage_answer_by_meaning("מזוודה לכל אחד", BAGGAGE_HISTORY, {"flight": {"baggage": ["carry_on_only"]}})
check("baggage already known -> skipped entirely, no model call", resolved2 == {} and called["n"] == 0)

# --- 3. Last question wasn't about baggage at all -> skipped, no call ---
called2 = {"n": 0}
with patch.object(chat, "_post_claude", side_effect=fake_counter):
    resolved3 = chat._baggage_answer_by_meaning("לרנקה", [{"role": "assistant", "content": "באיזה שדה תעופה תרצו לנחות?"}], {"flight": {"baggage": None}})
check("last question unrelated to baggage -> skipped, no model call", resolved3 == {} and called2["n"] == 0)

# --- 4. Model returns null (doesn't answer the baggage question at all) ---
def fake_null(key, model, s, d, h, m, mt, include_history=True, source="other"):
    return json.dumps({"baggage": None})
with patch.object(chat, "_post_claude", side_effect=fake_null):
    resolved4 = chat._baggage_answer_by_meaning("אולי", BAGGAGE_HISTORY, {"flight": {"baggage": None}})
check("model says null -> nothing resolved", resolved4 == {})

# --- 5. Itinerary acceptance: exact Shaked phrasing, true ---
def fake_true(key, model, s, d, h, m, mt, include_history=True, source="other"):
    return "true"
with patch.object(chat, "_post_claude", side_effect=fake_true):
    accepted = chat._itinerary_acceptance_by_meaning("יפה מאוד, מאשרים את המסלול")
check("'יפה מאוד, מאשרים את המסלול' resolves to True via meaning", accepted is True)

# --- 6. Itinerary acceptance: a real change request must resolve false ---
def fake_false(key, model, s, d, h, m, mt, include_history=True, source="other"):
    return "false"
with patch.object(chat, "_post_claude", side_effect=fake_false):
    rejected = chat._itinerary_acceptance_by_meaning("אפשר לשנות את יום 2?")
check("a change request resolves to False, never guessed as acceptance", rejected is False)

# --- 7. No API key -> safe default False, never crashes ---
import importlib
old_key = os.environ.pop("ANTHROPIC_API_KEY", None)
try:
    result_no_key = chat._itinerary_acceptance_by_meaning("מאשרים")
finally:
    if old_key is not None:
        os.environ["ANTHROPIC_API_KEY"] = old_key
check("no API key configured -> safe False default, no crash", result_no_key is False)

# --- 8. The deterministic function _is_itinerary_acceptance itself still
#        correctly rejects a genuine change request (sanity check that the
#        new fallback doesn't replace the existing fast, free path) ---
check("_is_itinerary_acceptance still rejects an explicit change request",
      chat._is_itinerary_acceptance("אפשר לשנות את יום 2?") is False)

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL BAGGAGE/ITINERARY-ACCEPTANCE-BY-MEANING TESTS PASSED")
