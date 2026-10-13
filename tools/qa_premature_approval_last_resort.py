"""QA for Shaked's live report (2026-10-13, qa-s78, Cyprus): the model's
retried reply (after the premature-מאשרת guard already tried a flight-gap
question, a post-flight offer, and an active-domain re-ask through
Tinkerbell) STILL contained a full summary ending in "כתבי מאשרת", even
though active_session was correctly "car" with real missing_required gaps
(pickup/return) - nothing re-checked that retried text before accepting it
as "handled". Per Shaked: "צריך חסימה בקוד שלא תאפשר 'כתבי מאשרת' כשיש
missing_required" (need a code-level block).

chat_clean() now re-checks the reply one final time after every other
mitigation in that block, and falls back to _premature_approval_fallback_text
(a loose substring match, not the three exact hardcoded sentences used
earlier in the same block) whenever the reserved phrase is still present.
This tests the fallback-text helper directly - the inline re-check itself
is exercised live by Shaked's QA, not unit-testable without a full Flask/
session harness (same convention as qa_missing_final_summary_retry.py).

Run: python3 tools/qa_premature_approval_last_resort.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import ariella_chat_clean as chat

FORBIDDEN = ("כתבי מאשרת", "כתוב מאשר", "מאשר/מאשרת")

# --- 1. Exact Shaked/qa-s78 shape: active_session="car" with real gaps ---
text_a = chat._premature_approval_fallback_text({"active_session": "car", "next_session": None})
assert "השכרת רכב" in text_a, text_a
assert not any(p in text_a for p in FORBIDDEN), text_a
print("PASS: active_session='car' -> names car, never contains the reserved approval phrase")

# --- 2. active_session unset, next_session names the open domain instead ---
text_b = chat._premature_approval_fallback_text({"active_session": None, "next_session": "lodging"})
assert "לינה" in text_b, text_b
assert not any(p in text_b for p in FORBIDDEN), text_b
print("PASS: next_session='lodging' -> names lodging, never contains the reserved approval phrase")

# --- 3. Neither known (flights itself, or an unrecognized domain) -> still
#        a safe, honest fallback with no forbidden phrase and no crash ---
text_c = chat._premature_approval_fallback_text({"active_session": None, "next_session": None})
assert text_c, "fallback text must never be empty"
assert not any(p in text_c for p in FORBIDDEN), text_c
print("PASS: nothing identifiable open -> still a safe generic fallback, no reserved phrase")

# --- 4. Garbage/non-dict input must not crash (defensive) ---
text_d = chat._premature_approval_fallback_text(None)
assert text_d and not any(p in text_d for p in FORBIDDEN), text_d
print("PASS: non-dict input handled defensively, no crash, no reserved phrase")

print("\nALL PREMATURE-APPROVAL LAST-RESORT TESTS PASSED")
