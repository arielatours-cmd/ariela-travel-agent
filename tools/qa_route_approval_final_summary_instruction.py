"""QA for Shaked's live report (2026-10-12, c8e371c round, Barcelona
scenario, qa-s13): a customer approved the day-by-day route exactly when
flights were already complete and lodging/car already declined - the
FOURTH and final domain closing right now - but Ariella ended with the old
"I'll send the info to your vacation card... have a nice trip!" sign-off
instead of the required combined summary + מאשר/מאשרת request. Per the
product owner: once ALL FOUR domains (flights/trip_planning/lodging/car)
are complete/declined, that is always the one real summary/approval
moment, no exceptions - including when trip_planning is the domain that
closes last.

Root cause: _call_tinkerbell's route_handoff instruction only switched
away from the old sign-off text when `trip_planning_settled` was already
True in state - but trip_planning's own status is only flipped to
"complete" in post-processing, AFTER this reply is drafted, so on the
exact message that approves the route, trip_planning still reads
"active" even though the customer's current message is the approval
itself. The old sign-off fired whenever no OTHER domain was pending,
regardless of whether trip_planning itself was the last thing to close.
Fixed by checking flights/lodging/car's state directly (not
trip_planning_settled) to decide whether this is actually the final
combined-summary moment.

This mocks _post_claude to capture system_dynamic without any network
call, and checks which route_handoff instruction got injected.

Run: python3 tools/qa_route_approval_final_summary_instruction.py
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


OLD_SIGNOFF_MARKER = "מאחלת לך חופשה נעימה"
FINAL_SUMMARY_MARKER = "רגע הסיכום הסופי המשולב"

with patch.object(chat, "_post_claude", side_effect=_fake_post_claude):
    # --- 1. Route is the LAST domain closing (flights/lodging/car already
    # resolved) - must get the final-summary instruction, not the old sign-off ---
    state_final = {
        "active_session": "trip_planning",
        "session_status": {"flights": "complete", "lodging": "declined", "car": "declined", "trip_planning": "active"},
    }
    chat._call_tinkerbell("test-key-not-real", "claude-sonnet-5", [], "מעולה, זה המסלול", state_final)
    assert FINAL_SUMMARY_MARKER in captured["system_dynamic"], "final-summary instruction missing when flights/lodging/car are all already resolved"
    assert OLD_SIGNOFF_MARKER not in captured["system_dynamic"], "stale sign-off instruction leaked in despite everything else being resolved"
    print("PASS: flights/lodging/car already resolved -> final-summary instruction injected, old sign-off suppressed")

    # --- 2. A genuinely standalone trip_planning-only case (flights still
    # pending) keeps the old sign-off, since nothing else needs a summary yet ---
    captured.clear()
    state_standalone = {
        "active_session": "trip_planning",
        "session_status": {"flights": "pending", "lodging": "pending", "car": "pending", "trip_planning": "active"},
    }
    chat._call_tinkerbell("test-key-not-real", "claude-sonnet-5", [], "מעולה, זה המסלול", state_standalone)
    assert OLD_SIGNOFF_MARKER in captured["system_dynamic"], "old sign-off should still apply when other domains are still genuinely open"
    assert FINAL_SUMMARY_MARKER not in captured["system_dynamic"]
    print("PASS: flights/lodging/car still pending -> old sign-off instruction unaffected")

    # --- 3. trip_planning already settled with another domain genuinely
    # still open -> hand back to that open domain (unchanged behavior) ---
    captured.clear()
    state_handoff = {
        "active_session": "lodging",
        "session_status": {"flights": "complete", "lodging": "active", "car": "pending", "trip_planning": "complete"},
    }
    chat._call_tinkerbell("test-key-not-real", "claude-sonnet-5", [], "מעולה", state_handoff)
    assert "ואין עוד סשן פתוח שממתין להשלמה" not in captured["system_dynamic"] or "יש עוד תחום/ים בחופשה" in captured["system_dynamic"]
    assert "יש עוד תחום/ים בחופשה" in captured["system_dynamic"], "hand-back-to-open-domain instruction should still apply"
    print("PASS: trip_planning already settled with another open domain -> hand-back instruction unaffected")

print("\nALL ROUTE-APPROVAL FINAL-SUMMARY INSTRUCTION TESTS PASSED")
