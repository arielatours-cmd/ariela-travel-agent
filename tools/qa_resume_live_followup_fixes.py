"""QA for Shaked's live-site follow-up findings on #84 (18.10.2026,
qa/reports/2026-10-18-resume-live.md, branch shaked @d980699), relayed by
Shlomo as a separate PR on top of the merged main (897152c):

1. R8: `_reset_intent` (ariella_chat_clean.py) was a fixed phrase list, so
   "רגע, אני רוצה להתחיל טיול אחר" ("wait, I want to start a different
   trip") on an active Prague conversation was never recognized as a
   restart request at all - guided kept right on asking about the flight
   budget. Per the business owner's 18.10 directive (understanding by the
   model, never a phrase list) and Shaked's explicit instruction: this
   REPLACES the list as the actual source of truth for the reset-
   confirmation gate, not another phrase added to it. The old list is
   kept only as a zero-risk, latency-saving short-circuit for the
   phrasings it already matches - it can only ever confirm a restart
   faster, never suppress one the model would have caught, since the
   model is still consulted for anything the list doesn't already
   resolve. Only consulted when _has_vacation_progress is true.

2. L1: the opening question to a brand-new customer ("מה בא לך לתכנן
   הפעם: חופשה רגילה, נסיעת עסקים, או אולי חופשת סקי?") is an "X, Y או Z"
   question - TINKERBELL_SYSTEM's own instruction named all three
   categories right next to "ask one open question of your own", handing
   Tinkerbell the exact words to enumerate back. Fixed at the source: the
   instruction now explicitly forbids naming any category inside the
   question itself, while still telling her (separately, for her own
   classification) what the three categories are.

3. L3: "באיזה חודש בערך אתם חושבים לצאת, ולכמה ימים?" bundles two
   questions (when + how many days) into one message.
   _GUIDED_FIELD_HINT_DESCRIPTION["dates"] described BOTH facts ("מתי
   הלקוח רוצה לטוס, ולכמה לילות") as the one thing to find out next,
   handing Tinkerbell material for both halves. Fixed: the description
   now names only the one fact (when); duration is picked up naturally by
   the same extraction schema whenever the customer volunteers it
   unprompted, exactly like any other "also_mentioned" fact.

4. Finding #4: "שתי שאלות קטנות לפני שנסגור את הטיסה: איזו כבודה
   תצטרכו?" announces two questions while asking exactly one - the same
   "one question" principle violated by the preamble, not the question
   itself. Fixed: TINKERBELL_SYSTEM's own first-and-most-important
   principle now explicitly covers the preamble too.

General: _guided_ask_hint (the hint-building function behind EVERY 014a
guided field, not just dates) now explicitly tells Tinkerbell that any
example values in a field's own description are for her understanding
only, never material to enumerate inside the question - the same root
cause (a description naming options) that caused L1's trip_type
violation can recur for any other guided field (e.g. lodging_type's own
"מלון, דירה, וילה או צימר" description) without this general guard.

No keyword-based enforcement was added anywhere for items 2-4, per
Shaked's explicit instruction that this approach has already failed
twice (_enforce_guided_question_matches_field, both reverted) - every
fix here is to the SOURCE instruction/hint text Tinkerbell composes from.

Run: python3 tools/qa_resume_live_followup_fixes.py
"""
import os
import sys
import json
import sqlite3
from datetime import datetime, timezone
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import database
database.init_db()

import ariella_chat_clean as chat
import whatsapp_bridge
from werkzeug.security import generate_password_hash

DB = database.DB_PATH
FAILED = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


def _make_member(email):
    with sqlite3.connect(DB) as conn:
        conn.execute("DELETE FROM members WHERE email=?", (email,))
        conn.commit()
        cur = conn.execute(
            "INSERT INTO members (full_name,email,password_hash,created_at,status,whatsapp_opt_in,preferred_airports) "
            "VALUES(?,?,?,?,?,?,?)",
            ("QA Resume Live", email, generate_password_hash("Test1234!"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
        )
        return cur.lastrowid


# =====================================================================
# 1a. Source text checks: items 2-4 fixed at the instruction/hint level,
#     never via keyword enforcement.
# =====================================================================
check("item 2: TINKERBELL_SYSTEM's trip-type instruction forbids naming any category inside the question itself",
      "לעולם לא \"חופשה רגילה, נסיעת עסקים, או חופשת סקי?\"" in chat.TINKERBELL_SYSTEM
      or "חופשה רגילה, נסיעת עסקים, או חופשת סקי?" not in chat.TINKERBELL_SYSTEM.split("השאלה הראשונה שנשאלת")[1][:400])
check("item 2: the instruction still asks for ONE open, general question with no options listed",
      "שאלה פתוחה אחת וכללית" in chat.TINKERBELL_SYSTEM)
check("item 2: the three categories are still named SOMEWHERE, for Tinkerbell's own classification of the free answer",
      "חופשה רגילה, נסיעת עסקים, או חופשת סקי" in chat.TINKERBELL_SYSTEM)

check("item 3: the 'dates' field hint description no longer bundles duration into the same ask",
      "לילות" not in chat._GUIDED_FIELD_HINT_DESCRIPTION["dates"])
check("item 3: the 'dates' description still names the one real fact (when to fly)",
      "מתי" in chat._GUIDED_FIELD_HINT_DESCRIPTION["dates"])

check("item 4: the main one-question principle explicitly forbids announcing N questions while asking fewer",
      "לעולם אל תכריזי על מספר פרטים/שאלות שעוד נותרו" in chat.TINKERBELL_SYSTEM)

check("general: _guided_ask_hint tells Tinkerbell never to enumerate a field's own example values as options",
      "לעולם אל תמני אותן כאפשרויות בתוך השאלה עצמה" in chat._guided_ask_hint("dates", 0)
      and "לעולם אל תמני אותן כאפשרויות בתוך השאלה עצמה" in chat._guided_ask_hint("lodging_type", 1))


# =====================================================================
# 1b. Unit: _reset_intent's own phrase list is UNCHANGED (still the
#     short-circuit for phrasings it already covers) - only the model
#     consultation is new, not a replacement regex.
# =====================================================================
check("regression: _reset_intent itself still matches its existing fixed phrases",
      chat._reset_intent("חופשה חדשה") is True)
check("_reset_intent alone still does NOT recognize 'טיול אחר' phrasing (confirms the gap this fix addresses)",
      chat._reset_intent("רגע, אני רוצה להתחיל טיול אחר") is False)


# =====================================================================
# 2. End-to-end repro of R8: an active Prague-shaped conversation,
#    "רגע, אני רוצה להתחיל טיול אחר" must now reach the reset-confirmation
#    gate via the model classifier, even though the fixed phrase list
#    alone would have missed it.
# =====================================================================
def _customer_text(message):
    return str(message or "").split("תשובת הלקוח:", 1)[-1].strip()


def _fake_post_claude(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if source == "tinkerbell_reply":
        return "תשובה כלשהי."
    if source == "state_extractor":
        return "{}"
    if source != "classifier":
        return "{}"
    text = _customer_text(message)
    if "question_kind=new_vacation" in str(message or ""):
        if any(w in text for w in ("חדש", "אחר")):
            return "NEW"
        if any(w in text for w in ("להמשיך", "קיים", "שכבר")):
            return "KEEP"
        return "UNCLEAR"
    return "UNCLEAR"


m8 = _make_member("qa-resume-live-r8@example.com")
prague_state = {
    "destination": {"places": ["פראג"], "mode": "specific", "status": "known"},
    "destination_airports": ["PRG"],
    "travelers": {"adults": 2},
    "session_status": {"flights": "active", "lodging": "pending", "car": "pending", "trip_planning": "pending"},
    "active_session": "flights",
    "guided": {"current_question": "baggage", "attempts": 0, "answered": ["dates", "travelers"]},
}
database.save_ariella_conversation(m8, [
    {"role": "user", "content": "פראג, זוג, ביולי"},
    {"role": "assistant", "content": "קלטתי - פראג. איזו כבודה תצטרכו?"},
], prague_state)

with patch.object(chat, "_post_claude", side_effect=_fake_post_claude):
    reply_r8_1 = whatsapp_bridge.ariella_turn(m8, "רגע, אני רוצה להתחיל טיול אחר")
state_r8_1 = (database.load_ariella_conversation(m8) or {}).get("trip_state") or {}
check("R8 repro: 'רגע, אני רוצה להתחיל טיול אחר' now reaches the reset-confirmation gate (via the model, not the old list)",
      bool(state_r8_1.get("reset_pending")))
check("R8 repro: the gate does NOT silently clear Prague - it only asks for confirmation first",
      "פראג" in ((state_r8_1.get("destination") or {}).get("places") or []))

with patch.object(chat, "_post_claude", side_effect=_fake_post_claude):
    reply_r8_2 = whatsapp_bridge.ariella_turn(m8, "לא, נשאיר את פראג")
state_r8_2 = (database.load_ariella_conversation(m8) or {}).get("trip_state") or {}
check("R8 repro: answering 'no' keeps Prague and clears reset_pending",
      not state_r8_2.get("reset_pending") and "פראג" in ((state_r8_2.get("destination") or {}).get("places") or []))


# =====================================================================
# 3. Regression: an ordinary continuing message (no restart intent at
#    all) must NOT falsely trigger the reset-confirmation gate - the
#    model classifier only fires on an actual "new" classification,
#    never on "unclear".
# =====================================================================
m_ok = _make_member("qa-resume-live-noreset@example.com")
database.save_ariella_conversation(m_ok, [
    {"role": "user", "content": "פראג, זוג, ביולי"},
    {"role": "assistant", "content": "קלטתי - פראג. איזו כבודה תצטרכו?"},
], dict(prague_state))
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude):
    reply_ok = whatsapp_bridge.ariella_turn(m_ok, "טרולי לכל אחד")
state_ok = (database.load_ariella_conversation(m_ok) or {}).get("trip_state") or {}
check("regression: an ordinary continuing answer never falsely triggers the reset-confirmation gate",
      not state_ok.get("reset_pending"))

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL RESUME-LIVE-FOLLOWUP-FIXES TESTS PASSED")
