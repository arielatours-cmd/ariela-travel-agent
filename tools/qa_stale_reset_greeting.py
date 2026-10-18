"""QA for Shaked's live report (2026-10-12): the stale-session auto-reset
(fd6eb52) correctly clears unfinished vacation state after a 60+ minute
silent gap, but the customer sees the whole old chat on screen and Ariella
just asked everything from scratch with no explanation at all - e.g. the
customer answered "2 מבוגרים" and Ariella replied "זו חופשה רגילה, נסיעת
עסקים, או חופשת סקי?" out of nowhere.

Per the product owner's decision (relayed by Shaked): keep the auto-reset,
but when it fires, Ariella must open with a short welcome-back greeting
before continuing to the normal opening question.

chat_clean() now sets a transient (non-persisted) "_stale_reset_just_happened"
flag on a SHALLOW COPY of trip_update passed to _call_tinkerbell only for
that one turn - never on trip_update itself, which is what actually gets
returned to the client and persisted. _call_tinkerbell injects a welcome-back
instruction into system_dynamic only when that flag is present.

This mocks _post_claude to capture system_dynamic without any real network
call, and checks the prompt instruction is present/absent correctly.

Run: python3 tools/qa_stale_reset_greeting.py
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


MARKER = "חזר עכשיו אחרי הפסקה ארוכה"
# Per Shaked's live report (qa-s73, 2026-10-13): the welcome-back reply used
# the masculine imperative "בוא נתחיל" for a customer whose profile gender is
# female ("בואי" was needed). Rather than trust the model to pick the right
# gendered form every time, the instruction now tells it to avoid the
# gendered imperative entirely in that part of the message.
GENDER_NEUTRAL_MARKER = "בוא נתחיל\"/\"בואי נתחיל"

with patch.object(chat, "_post_claude", side_effect=_fake_post_claude):
    # --- 1. Flag set -> welcome-back instruction is injected ---
    state = {"session_status": {"flights": "pending", "lodging": "pending", "car": "pending", "trip_planning": "pending"},
              "_stale_reset_just_happened": True}
    chat._call_tinkerbell("test-key-not-real", "claude-sonnet-5", [], "שלום", state)
    assert MARKER in captured["system_dynamic"], "welcome-back instruction missing when flag is set"
    assert GENDER_NEUTRAL_MARKER in captured["system_dynamic"], "gender-neutral-phrasing guard missing when flag is set"
    print("PASS: stale-reset flag set -> welcome-back instruction injected into system_dynamic")
    print("PASS: stale-reset flag set -> gendered-imperative guard (בוא/בואי נתחיל) injected too")

    # --- 2. Flag absent (ordinary turn) -> no welcome-back instruction ---
    captured.clear()
    state2 = {"session_status": {"flights": "pending", "lodging": "pending", "car": "pending", "trip_planning": "pending"}}
    chat._call_tinkerbell("test-key-not-real", "claude-sonnet-5", [], "שלום", state2)
    assert MARKER not in captured["system_dynamic"], "welcome-back instruction leaked into an ordinary turn"
    print("PASS: no stale-reset flag -> no welcome-back instruction (ordinary turns unaffected)")

    # --- 3. Flag explicitly False -> no welcome-back instruction ---
    captured.clear()
    state3 = {"session_status": {"flights": "pending", "lodging": "pending", "car": "pending", "trip_planning": "pending"},
              "_stale_reset_just_happened": False}
    chat._call_tinkerbell("test-key-not-real", "claude-sonnet-5", [], "שלום", state3)
    assert MARKER not in captured["system_dynamic"]
    print("PASS: flag explicitly False -> no welcome-back instruction")

print("\nALL STALE-RESET WELCOME-BACK GREETING TESTS PASSED")
