"""QA for Shaked's live report (2026-10-12, Haifa->Bangkok, f73eef9): the
state was already fully correct (flights=complete, lodging/car/trip_planning
all declined via explicit_only_flights) but Tinkerbell's reply was "want
lodging too, or just the flight this time?" instead of the mandatory final
summary + מאשר/מאשרת - and no summary ever followed afterward either.

chat_clean() now detects this exact situation (every one of the four
domains complete/declined, but the reply contains neither "מאשר" nor the
route-approval farewell "חופשה נעימה") and retries once with a shallow-copy
state flagged "_force_final_summary_now", which _call_tinkerbell turns into
an extra explicit instruction in system_dynamic never to ask about
lodging/car/route again and to produce the final summary now.

This mocks _post_claude to capture system_dynamic without any real network
call, checking only the _call_tinkerbell half of the mechanism (the flag ->
instruction wiring) - the retry trigger itself lives inline in chat_clean()
and is exercised live by Shaked's QA, not unit-testable without a full
Flask/session harness.

Run: python3 tools/qa_missing_final_summary_retry.py
"""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import ariella_chat_clean as chat

captured = {}


def _fake_post_claude(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    captured["system_dynamic"] = system_dynamic
    return "הודעה לדוגמה."


MARKER = "אסור בשום אופן לשאול שוב על לינה/רכב/מסלול"

with patch.object(chat, "_post_claude", side_effect=_fake_post_claude):
    # --- 1. Flag set -> forced-summary instruction is injected ---
    state = {
        "session_status": {"flights": "complete", "lodging": "declined", "car": "declined", "trip_planning": "declined"},
        "_force_final_summary_now": True,
    }
    chat._call_tinkerbell("test-key-not-real", "claude-sonnet-5", [], "שלום", state)
    assert MARKER in captured["system_dynamic"], "forced-summary instruction missing when flag is set"
    print("PASS: _force_final_summary_now set -> forced-summary instruction injected into system_dynamic")

    # --- 2. Flag absent (ordinary turn) -> no forced-summary instruction ---
    captured.clear()
    state2 = {"session_status": {"flights": "complete", "lodging": "declined", "car": "declined", "trip_planning": "declined"}}
    chat._call_tinkerbell("test-key-not-real", "claude-sonnet-5", [], "שלום", state2)
    assert MARKER not in captured["system_dynamic"], "forced-summary instruction leaked into an ordinary turn"
    print("PASS: no flag -> no forced-summary instruction (ordinary turns unaffected)")

print("\nALL MISSING-FINAL-SUMMARY RETRY TESTS PASSED")
