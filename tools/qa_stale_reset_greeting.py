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

20.10.2026, Shlomo's relay of Carmit's work order item 3 (qa/stage-
scenarios.md P1, "חזרה אחרי יותר משעה ('הי')"): the welcome-back greeting
itself must be PERSONAL and address the customer by name - not just a
generic "welcome back". _member_profile already resolves the customer's
real first name into trip_update["profile"]["first_name"] on every turn
(well before this hint is built); the hint-building code below now reads
it straight off `state["profile"]` (the same dict _call_tinkerbell already
receives) and, when present, makes using it mandatory for this one
greeting - unlike the general, merely-optional first-name rule elsewhere
in TINKERBELL_SYSTEM, which only covers a genuinely brand-new
conversation's own opening message.

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

    # --- 4. Flag set + a real registered first name -> using it by name is
    # made mandatory for this one greeting (Carmit's P1 scenario) ---
    captured.clear()
    state4 = {"session_status": {"flights": "pending", "lodging": "pending", "car": "pending", "trip_planning": "pending"},
              "_stale_reset_just_happened": True,
              "profile": {"first_name": "דנה", "gender": "female"}}
    chat._call_tinkerbell("test-key-not-real", "claude-sonnet-5", [], "הי", state4)
    assert MARKER in captured["system_dynamic"], "welcome-back instruction missing with a known first name"
    assert 'שם הלקוח הפרטי האמיתי הוא "דנה"' in captured["system_dynamic"], \
        "the customer's real first name was not injected into the welcome-back instruction"
    assert "חובה (לא רשות הפעם)" in captured["system_dynamic"], \
        "using the name was not made mandatory for this greeting"
    print("PASS: stale-reset flag + known first name -> name injected and its use made mandatory")

    # --- 5. Flag set but NO registered first name -> no name instruction is
    # fabricated (never invent a name that isn't actually known) ---
    captured.clear()
    state5 = {"session_status": {"flights": "pending", "lodging": "pending", "car": "pending", "trip_planning": "pending"},
              "_stale_reset_just_happened": True,
              "profile": {"first_name": "", "gender": None}}
    chat._call_tinkerbell("test-key-not-real", "claude-sonnet-5", [], "הי", state5)
    assert MARKER in captured["system_dynamic"], "welcome-back instruction missing when no first name is known"
    assert "שם הלקוח הפרטי האמיתי הוא" not in captured["system_dynamic"], \
        "a name-instruction was injected even with no registered first name"
    print("PASS: stale-reset flag + no registered first name -> greeting still fires, but no name is fabricated")

    # --- 6. No 'profile' key at all (defensive) -> never raises, no name ---
    captured.clear()
    state6 = {"session_status": {"flights": "pending", "lodging": "pending", "car": "pending", "trip_planning": "pending"},
              "_stale_reset_just_happened": True}
    chat._call_tinkerbell("test-key-not-real", "claude-sonnet-5", [], "הי", state6)
    assert MARKER in captured["system_dynamic"]
    assert "שם הלקוח הפרטי האמיתי הוא" not in captured["system_dynamic"]
    print("PASS: stale-reset flag + missing 'profile' key entirely -> no crash, no fabricated name")

print("\nALL STALE-RESET WELCOME-BACK GREETING TESTS PASSED")
