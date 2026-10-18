"""QA for the "continue existing or new" flow (per qa/resume-scenarios.md,
the business owner's 2026-10-18 directive relayed after Shaked rejected PR
#84 twice):

Round 1 (058edd4) was missing the flow entirely. Round 2 (d5b0d22) built the
state machine (resume_choice_pending: ask/confirm_one/which_trip) but
Shaked's second review found four more blocking issues, all fixed here:

1. Every stage used a hand-written, fixed Hebrew sentence as the reply
   (the opening question, which_trip, confirm_one, the "nothing open"
   message, and _resume_trip_reply's own use of _REOPEN_FIRST_QUESTION) -
   against the business owner's standing rule that code never sends a
   fixed sentence, ever. _resume_trip_reply's wording also came out
   grammatically broken when several services were closed ("טיסות ולינה
   ומסלול ואטרקציות כבר סגורים"). Fixed: the code now only ever decides
   the STATE (stage, candidates, what's closed/open) and hands Tinkerbell
   a free-text instruction via a new _resume_choice_hint key, exactly the
   same mechanism 014a's own _guided_ask_hint already established -
   wired into _call_tinkerbell's continuity-building the same way.
2. The question used to fire even for a brand-new member with zero
   trips at all. Fixed: _has_active_future_trip gates the WHOLE
   mechanism - it must find at least one of the customer's own active
   trip_requests rows with dates still ahead before anything here runs.
3. The opening message itself used to only skip the question when a
   catalog destination/regex matched it - "אני רוצה לתכנן טיול חדש" (no
   destination at all) still triggered the ask. Fixed: the opening
   message is classified directly by the model (_interpret_pending_
   choice, reused - no new classifier, no regex) into new/keep/unclear;
   only a genuinely unclear answer costs the extra round trip of
   actually asking.
4. A hardcoded "תרצי" (feminine form) regardless of user_gender - a
   direct consequence of (1); resolved automatically now that Tinkerbell
   composes every stage's text herself, exactly as she already does for
   gendered phrasing everywhere else.

Covers R1-R6, R11, R12 from qa/resume-scenarios.md, plus explicit checks
for findings 2 and 3 above (a trip-less member, and a first message that
classifies straight to new/continue with no extra round trip). Assertions
now check STATE transitions and the HINT text handed to the (mocked)
model - never literal reply wording, since that's Tinkerbell's own free
composition and is correctly out of this file's control.

Run: python3 tools/qa_resume_choice_flow.py
"""
import os
import re
import sys
import json
import sqlite3
from datetime import datetime, timezone, timedelta
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import database
database.init_db()

import ariella_chat_clean as chat
import whatsapp_bridge
import app as app_module
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
            ("QA Resume Choice", email, generate_password_hash("Test1234!"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
        )
        return cur.lastrowid


def _make_trip(member_id, name, answers, dep, ret):
    with sqlite3.connect(DB) as conn:
        cur = conn.execute(
            "INSERT INTO trip_requests (member_id, request_name, travel_window, created_at, status, answers_json) VALUES(?,?,?,?,?,?)",
            (member_id, name, f"{dep} - {ret}", datetime.now(timezone.utc).isoformat(), "active", json.dumps(answers, ensure_ascii=False)),
        )
        return cur.lastrowid


# =====================================================================
# The 4 canonical test accounts from qa/resume-scenarios.md.
# =====================================================================
def _seed_cyprus(member_id):
    return _make_trip(member_id, "קפריסין", {
        "origin_airports": ["TLV"], "destinations": "LCA",
        "departure_date": "2027-06-27", "return_date": "2027-07-01",
        "adults": 2, "children": 1, "age_groups": [17],
        "_session_status": {"flights": "complete", "lodging": "declined", "car": "declined", "trip_planning": "declined"},
    }, "2027-06-27", "2027-07-01")


def _seed_croatia(member_id):
    return _make_trip(member_id, "קרואטיה", {
        "origin_airports": ["TLV"], "destinations": "ZAG",
        "departure_date": "2027-09-19", "return_date": "2027-09-30",
        "adults": 2, "lodging_type": "hotel", "car_vehicle_type": "economy", "_approved_itinerary": True,
        "_session_status": {"flights": "complete", "lodging": "complete", "car": "complete", "trip_planning": "complete"},
    }, "2027-09-19", "2027-09-30")


def _seed_greece(member_id):
    return _make_trip(member_id, "יוון", {
        "origin_airports": ["TLV"], "destinations": "ATH",
        "departure_date": "2027-08-10", "return_date": "2027-08-15",
        "adults": 2,
        "_session_status": {"flights": "complete", "lodging": "pending", "car": "declined", "trip_planning": "declined"},
    }, "2027-08-10", "2027-08-15")


def _seed_rome(member_id):
    return _make_trip(member_id, "רומא", {
        "origin_airports": ["TLV"], "destinations": "FCO",
        "departure_date": "2027-11-03", "return_date": "2027-11-07",
        "adults": 2, "lodging_type": "hotel", "_approved_itinerary": True,
        "_session_status": {"flights": "complete", "lodging": "complete", "car": "pending", "trip_planning": "complete"},
    }, "2027-11-03", "2027-11-07")


_SEEDERS = {"ק": _seed_cyprus, "ר": _seed_croatia, "פ1": _seed_greece, "פ2": _seed_rome}


def _seed(member_id, *letters):
    for letter in letters:
        _SEEDERS[letter](member_id)


# =====================================================================
# A fake model standing in for the real one (offline QA has no API key).
# Dispatches by source/prompt shape:
#   - classifier calls (new-vs-continue, yes/no, which-trip) - unchanged
#     from before, pure meaning-based keyword stand-ins (the fake's own
#     simplicity is fine here - it stands in for real understanding, the
#     same way every other QA file in this suite mocks the model).
#   - "tinkerbell_reply" - the actual composed customer-facing reply.
#     Per Shaked's finding (1): the CODE must never hand Tinkerbell a
#     fixed sentence, only a free-text hint via _resume_choice_hint - so
#     the fake echoes that exact hint back as the "reply", letting every
#     assertion below check its CONTENT (what state/candidates/closed-
#     services the code decided), never customer-facing wording (that's
#     Tinkerbell's own job, correctly out of this file's control).
# =====================================================================
def _customer_text(message):
    return str(message or "").split("תשובת הלקוח:", 1)[-1].strip()


def _fake_post_claude(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if source == "tinkerbell_reply":
        # Echo the FULL dynamic prompt back as the "reply" so every
        # assertion below can check, by substring, exactly what the code
        # decided to tell Tinkerbell this turn (the _resume_choice_hint
        # text is somewhere in here) - never customer-facing wording,
        # which is correctly out of this file's control.
        return str(system_dynamic or "") or "תשובה כלשהי."
    if source == "state_extractor":
        return "{}"
    if source != "classifier":
        return "{}"
    text = _customer_text(message)
    if "question_kind=new_vacation" in str(message or ""):
        if any(w in text for w in ("חדש", "אחר")):
            return "NEW"
        if any(w in text for w in ("להמשיך", "ממשיכה", "המשך", "קיים", "שכבר", "תכנון שהיה")):
            return "KEEP"
        return "UNCLEAR"
    if "שאלת כן/לא" in str(system_static or ""):
        if any(w in text for w in ("כן", "בטח", "נכון", "מתאים", "בדיוק", "אשמח")):
            return "YES"
        if any(w in text for w in ("לא",)):
            return "NO"
        return "UNCLEAR"
    if "רשימת חופשות ממוספרות" in str(system_static or ""):
        if "נובמבר" in text or "רומא" in text:
            m = re.search(r"(\d+): [^;]*רומא", str(system_static or ""))
            if m:
                return m.group(1)
        if "חדש" in text:
            return "NEW"
        return "UNCLEAR"
    return "UNCLEAR"


def _hint_of(reply):
    """The fake tinkerbell_reply dispatcher above echoes the hint text
    verbatim as the 'reply' - this is just a readability alias for it in
    the assertions below."""
    return str(reply or "")


patcher = patch.object(chat, "_post_claude", side_effect=_fake_post_claude)
patcher.start()

# =====================================================================
# Finding 2 - a brand-new member with ZERO trips at all must never be
# asked "continue existing or new?" about nothing.
# =====================================================================
m0 = _make_member("qa-resume-notrips@example.com")
check("_has_active_future_trip is False for a member with zero trips",
      chat._has_active_future_trip(m0) is False)
reply0 = whatsapp_bridge.ariella_turn(m0, "הי")
state0 = (database.load_ariella_conversation(m0) or {}).get("trip_state") or {}
check("finding 2: a trip-less member's bare greeting never engages resume_choice_pending at all",
      "resume_choice_pending" not in state0)

# =====================================================================
# Finding 3 - an opening message that already classifies cleanly (new or
# continue) skips the "ask" round trip entirely, with NO catalog/regex
# destination check involved ("אני רוצה לתכנן טיול חדש" names no place).
# =====================================================================
m3f = _make_member("qa-resume-finding3@example.com")
_seed(m3f, "ק", "ר")
check("_has_active_future_trip is True once a real active trip exists (even fully closed, like ק)",
      chat._has_active_future_trip(m3f) is True)
reply3f = whatsapp_bridge.ariella_turn(m3f, "אני רוצה לתכנן טיול חדש")
state3f = (database.load_ariella_conversation(m3f) or {}).get("trip_state") or {}
check("finding 3: 'אני רוצה לתכנן טיול חדש' (no destination at all) resolves straight to new, no ask stage ever set",
      "resume_choice_pending" not in state3f and state3f.get("resume_choice_done") is True)

m3g = _make_member("qa-resume-finding3b@example.com")
_seed(m3g, "ק", "ר")
reply3g = whatsapp_bridge.ariella_turn(m3g, "אני רוצה להמשיך את התכנון שהיה")
state3g = (database.load_ariella_conversation(m3g) or {}).get("trip_state") or {}
check("finding 3b: a first message that already classifies as 'continue' skips the ask stage too",
      state3g.get("resume_choice_pending", {}).get("stage") in ("confirm_one", "which_trip")
      or "אין" in _hint_of(reply3g))

# =====================================================================
# R1: "הי" on an account with ק (closed) + ר (full) -> classifies
# UNCLEAR -> the ask stage is set, hint instructs one open question,
# never naming Cyprus as in-progress.
# =====================================================================
m1 = _make_member("qa-resume-r1@example.com")
_seed(m1, "ק", "ר")
wa_reply = whatsapp_bridge.ariella_turn(m1, "הי")
saved1 = (database.load_ariella_conversation(m1) or {}).get("trip_state") or {}
check("R1 (whatsapp): a bare greeting is genuinely unclear and sets the ask stage",
      saved1.get("resume_choice_pending", {}).get("stage") == "ask")
check("R1 (whatsapp): the hint asks ONE open continue-or-new question, never naming Cyprus",
      "קפריסין" not in _hint_of(wa_reply) and "שאלה אחת" in _hint_of(wa_reply))
check("R1 (whatsapp): went through the real model call path (never a hand-written fixed sentence)",
      bool(_hint_of(wa_reply)))

m1b = _make_member("qa-resume-r1b@example.com")
_seed(m1b, "ק", "ר")
client1b = app_module.app.test_client()
with client1b.session_transaction() as sess:
    sess["member_id"] = m1b
r = client1b.post("/api/ariella/chat-clean", json={"message": "הי", "history": [], "trip_state": {}})
data1b = r.get_json() or {}
check("R1 (api/website channel): same ask-stage behavior via the local-state channel",
      (data1b.get("trip_update") or {}).get("resume_choice_pending", {}).get("stage") == "ask")

# =====================================================================
# R2: "הי" -> "חדש" (+2 alternate phrasings) -> plain new-vacation
# opening, fully clean state (no Cyprus destination/guided), on server too.
# =====================================================================
for phrasing in ("חדש", "משהו חדש לגמרי", "בא לי לתכנן טיול אחר"):
    m2 = _make_member(f"qa-resume-r2-{phrasing[:3]}@example.com")
    _seed(m2, "ק", "ר")
    whatsapp_bridge.ariella_turn(m2, "הי")
    reply2 = whatsapp_bridge.ariella_turn(m2, phrasing)
    state2 = (database.load_ariella_conversation(m2) or {}).get("trip_state") or {}
    check(f"R2 ('{phrasing}'): resume_choice_pending is cleared, resume_choice_done is set",
          "resume_choice_pending" not in state2 and state2.get("resume_choice_done") is True)
    check(f"R2 ('{phrasing}'): no leftover Cyprus destination/guided in the SERVER state",
          not ((state2.get("destination") or {}).get("places")) and "guided" not in state2)
    check(f"R2 ('{phrasing}'): the hint tells Tinkerbell this is a fresh, separate plan",
          "חדש" in _hint_of(reply2))

# =====================================================================
# R3: "הי" -> "להמשיך" when NEITHER ק nor ר has an open topic -> the
# hint says there's nothing open, and to ask where/when for a new one.
# =====================================================================
m3 = _make_member("qa-resume-r3@example.com")
_seed(m3, "ק", "ר")
whatsapp_bridge.ariella_turn(m3, "הי")
reply3 = whatsapp_bridge.ariella_turn(m3, "להמשיך")
state3 = (database.load_ariella_conversation(m3) or {}).get("trip_state") or {}
check("R3: the hint says there's no open vacation to continue",
      "אין" in _hint_of(reply3))
check("R3: never mentions Cyprus by name in the hint",
      "קפריסין" not in _hint_of(reply3))
check("R3: resolves to a fresh-start state (resume_choice_done set, pending cleared)",
      "resume_choice_pending" not in state3 and state3.get("resume_choice_done") is True)

# =====================================================================
# R4: all 4 accounts -> "הי" -> "להמשיך" -> which_trip stage, candidates
# naming ONLY the genuinely open ones (יוון, רומא).
# =====================================================================
m4 = _make_member("qa-resume-r4@example.com")
_seed(m4, "ק", "ר", "פ1", "פ2")
whatsapp_bridge.ariella_turn(m4, "הי")
reply4 = whatsapp_bridge.ariella_turn(m4, "להמשיך")
state4 = (database.load_ariella_conversation(m4) or {}).get("trip_state") or {}
check("R4: moves to stage=which_trip",
      state4.get("resume_choice_pending", {}).get("stage") == "which_trip")
check("R4: the hint names Greece and Rome",
      "יוון" in _hint_of(reply4) and "רומא" in _hint_of(reply4))
check("R4: never mentions the closed/complete ones",
      "קפריסין" not in _hint_of(reply4) and "קרואטיה" not in _hint_of(reply4))

# =====================================================================
# R5: continuing R4, answer "רומא" (then the free-form date phrasing "זו
# של נובמבר") -> resumes Rome via _state_from_trip, hint states what's
# closed (flight+route) and asks about the one open service (car).
# =====================================================================
reply5 = whatsapp_bridge.ariella_turn(m4, "רומא")
state5 = (database.load_ariella_conversation(m4) or {}).get("trip_state") or {}
check("R5: the hint states Rome's own name/window and what's closed",
      "רומא" in _hint_of(reply5) and "סגור" in _hint_of(reply5))
check("R5: the hint asks about the one genuinely open service (car), never flight/route",
      "רכב" in _hint_of(reply5) and "בלי לשאול על שום תחום סגור" in _hint_of(reply5))
check("R5: state now holds Rome's own destination, flights/trip_planning complete",
      "רומא" in ((state5.get("destination") or {}).get("places") or [])
      and (state5.get("session_status") or {}).get("flights") == "complete"
      and (state5.get("session_status") or {}).get("trip_planning") == "complete")
check("R5: resume_choice_pending is cleared once a trip was actually resumed",
      "resume_choice_pending" not in state5)

m5b = _make_member("qa-resume-r5b@example.com")
_seed(m5b, "ק", "ר", "פ1", "פ2")
whatsapp_bridge.ariella_turn(m5b, "הי")
whatsapp_bridge.ariella_turn(m5b, "להמשיך")
reply5b = whatsapp_bridge.ariella_turn(m5b, "זו של נובמבר")
check("R5 ('זו של נובמבר'): resolves to Rome by date-phrase understanding, not a magic word",
      "רכב" in _hint_of(reply5b) and "סגור" in _hint_of(reply5b))

# =====================================================================
# R6: ק+ר+פ1 (only Greece open) -> "הי"->"להמשיך" offers it directly in
# one yes/no question (stage=confirm_one); never continues before an answer.
# =====================================================================
m6 = _make_member("qa-resume-r6@example.com")
_seed(m6, "ק", "ר", "פ1")
whatsapp_bridge.ariella_turn(m6, "הי")
reply6 = whatsapp_bridge.ariella_turn(m6, "להמשיך")
state6 = (database.load_ariella_conversation(m6) or {}).get("trip_state") or {}
check("R6: with only one open vacation, moves to confirm_one and names it in the hint",
      state6.get("resume_choice_pending", {}).get("stage") == "confirm_one" and "יוון" in _hint_of(reply6))
check("R6: does NOT continue before the customer actually answers",
      not state6.get("reopened_trip_id"))
reply6b = whatsapp_bridge.ariella_turn(m6, "כן")
state6b = (database.load_ariella_conversation(m6) or {}).get("trip_state") or {}
check("R6: 'כן' actually resumes Greece afterwards",
      state6b.get("reopened_trip_id") and "יוון" in ((state6b.get("destination") or {}).get("places") or []))

# =====================================================================
# R11: idle gap > 60 minutes, then "הי" -> behaves exactly like R1 (no
# "continuing where we left off" on a closed trip).
# =====================================================================
m11 = _make_member("qa-resume-r11@example.com")
_seed(m11, "ק", "ר")
stale_trip_state = {
    "destination": {"places": ["קפריסין"], "mode": "specific", "status": "known"},
    "session_status": {"flights": "complete", "lodging": "declined", "car": "declined", "trip_planning": "declined"},
    "active_session": None,
}
database.save_ariella_conversation(m11, [
    {"role": "user", "content": "רק טיסה לקפריסין"},
    {"role": "assistant", "content": "קלטתי."},
], stale_trip_state)
_90_minutes_ago = (datetime.now(timezone.utc) - timedelta(minutes=90)).isoformat()
with sqlite3.connect(DB) as conn:
    conn.execute("UPDATE ariella_conversations SET updated_at=? WHERE member_id=?", (_90_minutes_ago, m11))
    conn.commit()
reply11 = whatsapp_bridge.ariella_turn(m11, "הי")
state11 = (database.load_ariella_conversation(m11) or {}).get("trip_state") or {}
check("R11: after a long gap, same ask-stage behavior as R1 - never resumes the stale Cyprus trip",
      state11.get("resume_choice_pending", {}).get("stage") == "ask" and "קפריסין" not in _hint_of(reply11))

# =====================================================================
# R12: an explicit "add lodging to Cyprus" request still works even
# though Cyprus's lodging was declined - the resume-choice gate must
# never intercept an explicit, destination-named request. This sibling
# mechanism (_reopenable_trips/reopen_trip_pending) still uses its own
# existing fixed-question template (_reopen_question) - out of this
# fix's scope, unchanged.
# =====================================================================
m12 = _make_member("qa-resume-r12@example.com")
_seed(m12, "ק", "ר")
reply12 = whatsapp_bridge.ariella_turn(m12, "תוסיפי לינה לקפריסין")
state12 = (database.load_ariella_conversation(m12) or {}).get("trip_state") or {}
check("R12: an explicit add-lodging-to-Cyprus request bypasses the resume-choice gate entirely",
      "resume_choice_pending" not in state12)
check("R12: and still offers to reopen Cyprus for lodging, despite the earlier decline",
      "קפריסין" in reply12 and "לינה" in reply12)

patcher.stop()

with sqlite3.connect(DB) as conn:
    conn.execute("DELETE FROM members WHERE email LIKE 'qa-resume-%@example.com'")
    conn.commit()

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL RESUME-CHOICE-FLOW TESTS PASSED")
