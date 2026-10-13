"""QA for Shaked's live report (2026-10-13, qa-s78, Cyprus): raw-data
follow-up on the earlier "שניהם" fix. Confirmed the fix to
_post_flight_offer_answer's hardcoded yes-set was necessary but not
sufficient - the actual live turns showed post_flight_offer=null at the
exact moment the customer answered "שניהם":

  reply="נהדר, לינה או רכב שכור תרצי שאסדר גם?", post_flight_offer=null

Tinkerbell asked the lodging/car offer question in its own free text,
without the backend ever setting post_flight_offer - so "שניהם" had
nothing to resolve. Lodging only got activated later by an unrelated
"מלון" explicit-request match; car was never activated at all.

Fix: _infer_post_flight_offer_from_text derives which services were
offered directly from Ariella's own words (gated on an actual offer-shaped
cue, not just the service names appearing anywhere) whenever the backend's
own post_flight_offer bookkeeping is empty. Wired in right before
_post_flight_offer_answer is called in chat_clean().

Run: python3 tools/qa_post_flight_offer_inferred_from_text.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import ariella_chat_clean as chat

FAILED = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


# --- 1. The exact reported phrasing infers both offered services ---
exact_text = "נהדר, לינה או רכב שכור תרצי שאסדר גם?"
offered = chat._infer_post_flight_offer_from_text(exact_text)
check("exact Shaked phrasing infers lodging+car", set(offered) == {"lodging", "car"})

# --- 2. Full chain: inferred offer + "שניהם" settles BOTH services true ---
resolved = chat._post_flight_offer_answer("שניהם", {"post_flight_offer": offered})
check("'שניהם' against the inferred offer resolves both to True", resolved == {"lodging": True, "car": True})

# --- 3. Service names appearing without an offer-shaped cue must not
#        false-positive (e.g. a factual statement, not a question/offer) ---
no_cue = chat._infer_post_flight_offer_from_text("הלינה והרכב שהזמנת מוכנים")
check("service names without an offer cue -> no false positive", no_cue == [])

# --- 4. Unrelated text (no service names, no offer cue) ---
unrelated = chat._infer_post_flight_offer_from_text("מה התקציב שלך לטיסה?")
check("unrelated text -> empty", unrelated == [])

# --- 5. A single-service offer (route only) still infers correctly ---
single = chat._infer_post_flight_offer_from_text("תרצי שאמשיך גם עם תכנון מסלול?")
check("single-service offer (trip_planning) infers just that one", single == ["trip_planning"])

# --- 6. Backend-set post_flight_offer is never overridden by inference -
#        only an empty/unset one triggers the fallback (verified at the
#        chat_clean() call site's own guard: `if not trip_state.get(...)`,
#        not re-tested here since it requires the full Flask/session
#        harness - this only confirms the pure inference function itself
#        is conservative and returns [] when there's truly nothing to find). ---
empty_text = ""
check("empty text -> empty list, never crashes", chat._infer_post_flight_offer_from_text(empty_text) == [])

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL POST-FLIGHT-OFFER INFERENCE TESTS PASSED")
