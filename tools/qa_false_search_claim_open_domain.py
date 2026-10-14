"""QA for Shaked's live report (2026-10-13, Cyprus real-scan test, qa-s75):
the customer wrote the exact approval word "מאשרת" right after a summary
that presented lodging and car as already resolved and ended in the real
מאשר/מאשרת request - which is exactly what _approval_trigger's recent-
assistant-text fallback treats as proof the approval gate was reached. But
the authoritative session_status disagreed (lodging stayed "active", car
stayed "pending"), so start_flight_search later stayed False (it requires
trip_planning/lodging/car to all be complete/declined) while chat_clean()'s
own hardcoded approval-success reply still claimed "הבקשה אושרה ואני יוצאת
עכשיו לחיפוש המלא..." - a false execution claim that slipped past the
deceptive-success safety net entirely, because that net only ever runs
`elif not approval:` (approval was True here).

Root cause: the "if approval:" success branch in chat_clean() assumed (by
construction, per its own prior comment) that reaching it with no flight
gap left means every domain is genuinely decided - true whenever
_approval_trigger fired via ready_for_summary, but NOT necessarily true
when it fired via the recent-assistant-text fallback instead (exactly this
scenario).

Fix: a new pure helper, _flight_approval_still_has_open_domain, is checked
before the success branch ships its reply. When it finds a genuinely
undecided non-flight domain, chat_clean() re-opens that domain and asks the
real next question instead of claiming the search is running. This tests
the helper directly (the inline wiring itself is exercised live by Shaked's
QA, not unit-testable without a full Flask/session harness - same
convention as qa_missing_final_summary_retry.py).

Run: python3 tools/qa_false_search_claim_open_domain.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

from ariella_chat_clean import _flight_approval_still_has_open_domain

# --- 1. Exact Shaked/qa-s75 shape: lodging "active", car "pending" ---
statuses_a = {"flights": "complete", "trip_planning": "complete", "lodging": "active", "car": "pending"}
assert _flight_approval_still_has_open_domain(statuses_a) == "trip_planning" or \
       _flight_approval_still_has_open_domain(statuses_a) in ("lodging", "car"), statuses_a
# trip_planning is complete, so the first genuinely-open domain in fixed
# order (trip_planning, lodging, car) must be lodging.
assert _flight_approval_still_has_open_domain(statuses_a) == "lodging", statuses_a
print("PASS: lodging='active'/car='pending' (Shaked's exact report) -> flagged as still-open (lodging first)")

# --- 2. Everything genuinely decided -> no open domain, success path is safe ---
statuses_b = {"flights": "complete", "trip_planning": "declined", "lodging": "complete", "car": "declined"}
assert _flight_approval_still_has_open_domain(statuses_b) is None, statuses_b
print("PASS: trip_planning/lodging/car all complete or declined -> no open domain, real success claim is safe")

# --- 3. Only car left open ---
statuses_c = {"flights": "complete", "trip_planning": "declined", "lodging": "declined", "car": "pending"}
assert _flight_approval_still_has_open_domain(statuses_c) == "car", statuses_c
print("PASS: only car still pending -> flagged as the open domain")

# --- 4. A domain key missing entirely from the dict (never even set) counts as open ---
statuses_d = {"flights": "complete", "trip_planning": "declined"}
assert _flight_approval_still_has_open_domain(statuses_d) == "lodging", statuses_d
print("PASS: lodging/car missing from statuses dict entirely -> still treated as open, not silently skipped")

print("\nALL FALSE-SEARCH-CLAIM-ON-OPEN-DOMAIN TESTS PASSED")
