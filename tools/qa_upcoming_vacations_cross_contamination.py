"""QA for a bug Carmit found and confirmed live on the production site
(2026-10-14): mid-way through planning a brand new Croatia trip, right
after she gave exact dates for it ("11 לילות 19.9 עד 30.9"), Ariella
suddenly claimed "התאריכים האלה כבר קבועים לכם מהחופשה לקפריסין
(19.9-30.9.2027), כך שזה כבר יש לנו" - and when asked, Carmit confirmed
the real, unrelated Cyprus vacation on her account is actually in JUNE
with a 17-year-old daughter traveler, not September: Ariella had pulled
the Cyprus vacation's data and silently reattached it to the new trip's
September dates.

Root cause traced directly in _call_tinkerbell: the "upcoming_vacations"
hint (the customer's saved, still-incomplete future vacations) used to be
built and injected into every single Tinkerbell call as "source of truth"
the moment ANY such vacation existed on the account - regardless of
whether the CURRENT conversation's own destination had anything to do with
it. The only guard was a free-text instruction telling the model to rely
on it "when the customer talks about one of these destinations" - which
isn't reliable once an unrelated destination is already active (exactly
what happened here: Croatia conversation + a stray Cyprus fact list).

Fixed by gating the hint to the two cases it's actually needed for: (a) a
genuinely open conversation with no destination committed yet (so Ariella
can offer to continue it), and (b) the customer explicitly asking to check
their saved vacations. Reopening an existing vacation to add a missing
service is a separate, destination-matched mechanism
(_reopenable_trips/reopen_trip_pending) and is unaffected by this change.

Run: python3 tools/qa_upcoming_vacations_cross_contamination.py
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


UPCOMING = [
    {"name": "קפריסין", "window": "10.6.2027 - 20.6.2027", "travelers": "2 מבוגרים, 1 ילדים (גילאים 17)", "missing": ["לינה"]},
]


def _system_dynamic_seen(state, message, history=None):
    captured = {}

    def _fake_post_claude(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
        captured["system_dynamic"] = system_dynamic
        return "תשובה לדוגמה."

    with patch.object(chat, "_post_claude", side_effect=_fake_post_claude):
        chat._call_tinkerbell("test-key", "test-model", history or [], message, state)
    return captured.get("system_dynamic", "")


# --- 1. The exact live bug: an active, unrelated destination (Croatia)
#        already underway, customer gives exact dates for IT, an unrelated
#        Cyprus vacation sits in upcoming_vacations -> the Cyprus facts
#        must NOT be injected as "source of truth" into this turn ---
state_active_destination = {
    "destination": {"places": ["קרואטיה", "זאגרב", "דוברובניק"], "mode": "specific", "status": "known"},
    "upcoming_vacations": UPCOMING,
    "dates": {"departure": "2027-09-19", "return": "2027-09-30", "needs_confirmation": False},
}
sd = _system_dynamic_seen(state_active_destination, "11 לילות 19.9 עד 30.9")
check("Cyprus vacation facts are NOT injected while an unrelated destination is active",
      "קפריסין" not in sd and "17" not in sd)

# --- 2. Legitimate case A: no destination committed yet (open greeting) -
#        the hint MUST still be injected so Ariella can offer to continue
#        the saved vacation ---
state_no_destination = {
    "upcoming_vacations": UPCOMING,
}
sd_open = _system_dynamic_seen(state_no_destination, "היי")
check("hint IS injected on a genuinely open conversation with no destination yet",
      "קפריסין" in sd_open)

# --- 3. Legitimate case B: customer explicitly asks to check their saved
#        vacations even while mid-conversation about something else - the
#        hint must still be available then ---
sd_explicit = _system_dynamic_seen(state_active_destination, "תבדקי לי בחופשות שלי מה יש")
check("hint IS injected when the customer explicitly asks about their saved vacations",
      "קפריסין" in sd_explicit)

# --- 4. No upcoming vacations at all -> nothing to gate, no crash either way ---
sd_none = _system_dynamic_seen({"destination": {"places": ["יוון"]}}, "שלום")
check("no upcoming vacations at all -> no hint text, no crash", "קפריסין" not in sd_none)

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL UPCOMING-VACATIONS-CROSS-CONTAMINATION TESTS PASSED")
