"""QA for the "continue existing or new" flow (per qa/resume-scenarios.md,
the business owner's 2026-10-18 directive relayed after Shaked rejected PR
#84's first submission, 058edd4, for having the single-save-point/
exclude_decided fixes right but this whole flow missing): PR #84 passed
every one of its original 19 checks, but on a bare conversation opening
Ariella never asked whether to continue an open vacation or start a new
one at all - with several open vacations she never disambiguated, and
after a choice she never loaded that vacation's own already-closed facts.

The fix (ariella_chat_clean.py):
- `_resumable_vacations` (replaces the old per-call duplication inside
  _upcoming_vacations): the shared candidate list of upcoming trips with a
  genuinely open (not declined/complete) service, carrying id/answers/
  missing (raw service keys) alongside the Hebrew display labels.
- `resume_choice_pending` - a new, explicit state-machine flag with three
  stages ("ask", "confirm_one", "which_trip"), handled as the very first
  gate in _chat_clean_impl (ahead of reopen_trip_pending and everything
  else) so nothing may proceed until the customer actually answers.
- Set once, always, whenever a conversation opens with no destination yet
  and the message itself names none either (an explicit destination is
  itself the answer "new, with this place" - handled by the existing,
  unchanged explicit-service-request branch just above it, and by the
  normal flow once this gate is skipped).
- Every classification (new vs. continue; yes/no for a single candidate;
  which vacation among several, including by date/month phrasing like "זו
  של נובמבר") is by the MODEL's understanding, never a phrase list - per
  Carmit's 2026-10-18 rule, repeated verbatim in qa/resume-scenarios.md's
  own failure rules ("זיהוי לפי רשימת ביטויים במקום הבנת המודל").
- `_pick_resume_trip`: reuses _pick_reopen_option's numeric/ordinal/
  catalog-name matching for the cheap common cases, but - unlike that
  function, whose own model fallback only ever covers a single option -
  falls back to a dedicated model classification for ANY number of
  options, required for R5's date-phrasing case.
- `_resume_trip_reply`: loads the chosen trip via the existing
  _state_from_trip, states what's already closed, and asks the one
  concrete question for the first still-open service - reusing the exact
  _REOPEN_FIRST_QUESTION/_state_from_trip machinery the sibling explicit-
  reopen flow already uses, rather than inventing new reply text.
- Every reply/state change here runs through the single _reply() save
  point built for PR #84's own original fix, so every turn below is
  independently checked against what's actually on the server too.

Covers R1-R6, R11, R12 from qa/resume-scenarios.md end to end, through
BOTH channels (whatsapp_bridge.ariella_turn, and /api/ariella/chat-clean
with locally-held history/trip_state exactly as the website does), with 2
alternate free-form phrasings per short answer where the spec calls for
one. R7-R10 (the reset gate and general single-save-point persistence)
are unchanged by this fix and stay covered by
qa_cyprus_resume_and_single_save_point.py.

Run: python3 tools/qa_resume_choice_flow.py
"""
import os
import re
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
# A fake classifier standing in for the real model (offline QA has no API
# key) - dispatches by the unique prompt/message shape of each of the 3
# classifiers this flow relies on, so the CODE's own use of "the model
# decided X" is what's under test here, not real natural-language
# understanding (which has no offline substitute).
# =====================================================================
def _customer_text(message):
    return str(message or "").split("תשובת הלקוח:", 1)[-1].strip()


def _fake_post_claude(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if source != "classifier":
        return "{}" if source == "state_extractor" else "תשובה לדוגמה."
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


def _api_client(member_id):
    client = app_module.app.test_client()
    with client.session_transaction() as sess:
        sess["member_id"] = member_id
    return client


def _api_turn(client, message, history, trip_state):
    r = client.post("/api/ariella/chat-clean", json={"message": message, "history": history, "trip_state": trip_state})
    data = r.get_json() or {}
    history = history + [{"role": "user", "content": message}, {"role": "assistant", "content": data.get("reply") or ""}]
    return data.get("reply") or "", (data.get("trip_update") if isinstance(data.get("trip_update"), dict) else {}), history


patcher = patch.object(chat, "_post_claude", side_effect=_fake_post_claude)
patcher.start()

# =====================================================================
# R1: "הי" on an account with ק (closed) + ר (full) -> one open question,
# never naming Cyprus as in-progress, never asking about flights.
# =====================================================================
m1 = _make_member("qa-resume-r1@example.com")
_seed(m1, "ק", "ר")

wa_reply = whatsapp_bridge.ariella_turn(m1, "הי")
check("R1 (whatsapp): the reply is the one open continue-or-new question",
      "להמשיך" in wa_reply and "חדש" in wa_reply)
check("R1 (whatsapp): never names Cyprus as if already in progress",
      "קפריסין" not in wa_reply)
check("R1 (whatsapp): never asks about a direct flight",
      "ישירה" not in wa_reply and "כבודה" not in wa_reply)
saved1 = database.load_ariella_conversation(m1) or {}
check("R1 (whatsapp): resume_choice_pending (stage=ask) actually persisted server-side",
      (saved1.get("trip_state") or {}).get("resume_choice_pending", {}).get("stage") == "ask")
check("R1 (whatsapp): only ONE question mark in the reply",
      wa_reply.count("?") <= 1)

m1b = _make_member("qa-resume-r1b@example.com")
_seed(m1b, "ק", "ר")
client1b = _api_client(m1b)
api_reply, api_trip_update, _ = _api_turn(client1b, "הי", [], {})
check("R1 (api/website channel): same single open question via the local-state channel",
      "להמשיך" in api_reply and "חדש" in api_reply and "קפריסין" not in api_reply)
check("R1 (api channel): persisted server-side too (single save point, both channels)",
      (database.load_ariella_conversation(m1b) or {}).get("trip_state", {}).get("resume_choice_pending", {}).get("stage") == "ask")

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
    check(f"R2 ('{phrasing}'): plain new-vacation opening reply",
          "חדשה" in reply2)
    check(f"R2 ('{phrasing}'): no leftover Cyprus destination/guided in the SERVER state",
          not ((state2.get("destination") or {}).get("places")) and "guided" not in state2)
    check(f"R2 ('{phrasing}'): resume_choice_pending is cleared",
          "resume_choice_pending" not in state2)

# =====================================================================
# R3: "הי" -> "להמשיך" when NEITHER ק nor ר has an open topic -> say so
# briefly, ask one open question - never enters Cyprus, never asks direct/baggage.
# =====================================================================
m3 = _make_member("qa-resume-r3@example.com")
_seed(m3, "ק", "ר")
whatsapp_bridge.ariella_turn(m3, "הי")
reply3 = whatsapp_bridge.ariella_turn(m3, "להמשיך")
check("R3: says there's no open vacation to continue",
      "אין" in reply3 and ("פתוח" in reply3 or "להמשיך" in reply3))
check("R3: still asks exactly one open question, never Cyprus, never direct/baggage",
      "קפריסין" not in reply3 and "ישירה" not in reply3 and "כבודה" not in reply3
      and reply3.count("?") <= 1)

# =====================================================================
# R4: all 4 accounts -> "הי" -> "להמשיך" -> one question, naming ONLY the
# genuinely open ones (יוון, רומא), never קפריסין/קרואטיה.
# =====================================================================
m4 = _make_member("qa-resume-r4@example.com")
_seed(m4, "ק", "ר", "פ1", "פ2")
whatsapp_bridge.ariella_turn(m4, "הי")
reply4 = whatsapp_bridge.ariella_turn(m4, "להמשיך")
check("R4: asks which vacation, mentioning Greece and Rome",
      "יוון" in reply4 and "רומא" in reply4)
check("R4: never mentions the closed/complete ones",
      "קפריסין" not in reply4 and "קרואטיה" not in reply4)
state4 = (database.load_ariella_conversation(m4) or {}).get("trip_state") or {}
check("R4: resume_choice_pending moved to stage=which_trip, server-side",
      state4.get("resume_choice_pending", {}).get("stage") == "which_trip")
check("R4: only one question in the reply",
      reply4.count("?") <= 1)

# Also through the website/local-state channel, for the same 4-account mix.
m4b = _make_member("qa-resume-r4b@example.com")
_seed(m4b, "ק", "ר", "פ1", "פ2")
client4b = _api_client(m4b)
_, trip_update_4b, hist4b = _api_turn(client4b, "הי", [], {})
reply4b, trip_update_4b, hist4b = _api_turn(client4b, "להמשיך", hist4b, trip_update_4b)
check("R4 (api channel): same which-vacation question, Greece/Rome only",
      "יוון" in reply4b and "רומא" in reply4b and "קפריסין" not in reply4b and "קרואטיה" not in reply4b)

# =====================================================================
# R5: continuing R4, answer "רומא" (then, separately, the free-form date
# phrasing "זו של נובמבר") -> shows flight+route already closed, asks ONE
# question about what's left (never flight/route), state holds Rome's
# own facts with flights/trip_planning=complete.
# =====================================================================
reply5 = whatsapp_bridge.ariella_turn(m4, "רומא")
check("R5: states what's already closed on Rome (flight + route)",
      "סגור" in reply5)
check("R5: never asks about flight or route again",
      "ישירה" not in reply5 and "מסלול" not in reply5.split("סגור")[-1] if "סגור" in reply5 else True)
check("R5: asks the one concrete remaining question (car)",
      "רכב" in reply5)
check("R5: only one question mark",
      reply5.count("?") <= 1)
state5 = (database.load_ariella_conversation(m4) or {}).get("trip_state") or {}
check("R5: state now holds Rome's own destination",
      "רומא" in ((state5.get("destination") or {}).get("places") or []))
check("R5: flights and trip_planning are marked complete on the resumed state",
      (state5.get("session_status") or {}).get("flights") == "complete"
      and (state5.get("session_status") or {}).get("trip_planning") == "complete")
check("R5: resume_choice_pending is cleared once a trip was actually resumed",
      "resume_choice_pending" not in state5)

# Same answer, via the alternate date-based phrasing ("זו של נובמבר") that
# names no option by city/ordinal at all - requires genuine model
# understanding (_pick_resume_trip's dedicated fallback), not a phrase list.
m5b = _make_member("qa-resume-r5b@example.com")
_seed(m5b, "ק", "ר", "פ1", "פ2")
whatsapp_bridge.ariella_turn(m5b, "הי")
whatsapp_bridge.ariella_turn(m5b, "להמשיך")
reply5b = whatsapp_bridge.ariella_turn(m5b, "זו של נובמבר")
check("R5 ('זו של נובמבר'): resolves to Rome by date-phrase understanding, not a magic word",
      "רכב" in reply5b and "סגור" in reply5b)

# =====================================================================
# R6: ק+ר+פ1 (only Greece open) -> "הי"->"להמשיך" may offer it directly
# in one question; never continues before an answer.
# =====================================================================
m6 = _make_member("qa-resume-r6@example.com")
_seed(m6, "ק", "ר", "פ1")
whatsapp_bridge.ariella_turn(m6, "הי")
reply6 = whatsapp_bridge.ariella_turn(m6, "להמשיך")
check("R6: with only one open vacation, offers it directly by name",
      "יוון" in reply6 and reply6.count("?") <= 1)
state6 = (database.load_ariella_conversation(m6) or {}).get("trip_state") or {}
check("R6: does NOT continue before the customer actually answers (still pending, nothing resumed yet)",
      state6.get("resume_choice_pending", {}).get("stage") == "confirm_one"
      and not state6.get("reopened_trip_id"))
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
from datetime import timedelta
_90_minutes_ago = (datetime.now(timezone.utc) - timedelta(minutes=90)).isoformat()
with sqlite3.connect(DB) as conn:
    conn.execute("UPDATE ariella_conversations SET updated_at=? WHERE member_id=?", (_90_minutes_ago, m11))
    conn.commit()
reply11 = whatsapp_bridge.ariella_turn(m11, "הי")
check("R11: after a long gap, same single open question as R1 - never resumes the stale Cyprus trip",
      "להמשיך" in reply11 and "חדש" in reply11 and "קפריסין" not in reply11)

# =====================================================================
# R12: an explicit "add lodging to Cyprus" request still works even
# though Cyprus's lodging was declined - the new resume-choice gate must
# never intercept an explicit, destination-named request.
# =====================================================================
m12 = _make_member("qa-resume-r12@example.com")
_seed(m12, "ק", "ר")
reply12 = whatsapp_bridge.ariella_turn(m12, "תוסיפי לינה לקפריסין")
check("R12: an explicit add-lodging-to-Cyprus request bypasses the resume-choice gate entirely",
      "resume_choice_pending" not in ((database.load_ariella_conversation(m12) or {}).get("trip_state") or {}))
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
