"""QA for Shlomo's relay of Carmit's work order item 1 (20.10.2026): "קישור
ללוח בוואטסאפ לפי בקשה: המודל מזהה את הכוונה לפי ציטוט, ומצב החיפוש נקבע לפי
ה-state." Mirrors qa/stage-scenarios.md's own section, "בקשת קישור ללוח או
לחופשה":

מקור: לקוחה ביקשה "תשלחי לי שוב קישור ללוח?". אריאלה ענתה "אין לי אפשרות
לשלוח קישורים מפה - החיפוש רץ ברקע...", אף שהחיפוש הסתיים כבר ב-19.10.

Design: the model's extractor call only recognizes the INTENT (link_request/
link_request_evidence, a new sibling pair folded into the same JSON output as
restart_request/dates_evidence/etc - same verbatim-quote evidence gate, never
a phrase list). The code - never the model - then decides from trip_state
alone whether there is something to link to, and never describes whether the
search is still running or already finished (that fact lives only in the DB,
invisible to this conversational state - asserting it either way risked being
exactly the wrong one, as the live finding was).

Driven through the real /api/ariella/chat-clean endpoint (same pattern as
tools/qa_gender_registration_wins_over_approval_word.py), with a mocked
_post_claude whose state_extractor branch returns link_request=true and a
genuine verbatim link_request_evidence for each of Shaked's 5 test phrasings.

Run: python3 tools/qa_link_request.py
"""
import os
import sys
import sqlite3
from datetime import datetime, timezone
from unittest.mock import patch
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import database
database.init_db()

import ariella_chat_clean as chat
import app as app_module
from werkzeug.security import generate_password_hash

DB = database.DB_PATH
client = app_module.app.test_client()

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
            "INSERT INTO members (full_name,email,password_hash,created_at,status,whatsapp_opt_in,preferred_airports,gender) "
            "VALUES(?,?,?,?,?,?,?,?)",
            ("QA Link Request", email, generate_password_hash("Test1234!"),
             datetime.now(timezone.utc).isoformat(), "active", 0, "[]", "female"),
        )
        return cur.lastrowid


# A vacation whose flight search was already confirmed/approved - there IS a
# real vacation to link to, whether or not the async scan itself has already
# finished (a fact this conversational state never knows either way).
def _confirmed_state():
    return {
        "trip_type": "standard",
        "destination": {"places": ["ליסבון"], "mode": "specific", "status": "known"},
        "destination_airports": ["LIS"],
        "departure_airport": "TLV",
        "travelers": {"adults": 2, "children": 0},
        "dates": {"departure": "2027-03-05", "return": "2027-03-10", "needs_confirmation": False},
        "budget_per_person": {"status": "unlimited"},
        "flight": {"connection_preference": "any", "cabin": "economy", "baggage": ["checked_bag"]},
        "requested_services": ["flights"],
        "service_decisions": {"flights": {"wanted": True}},
        "session_status": {"flights": "active", "lodging": "declined", "car": "declined", "trip_planning": "declined"},
        "active_session": "flights",
        "search_confirmed": True,
    }


# A brand-new, still-being-gathered vacation - nothing has ever been
# approved/launched, so there is genuinely no vacation page to send yet.
def _not_confirmed_state():
    return {
        "trip_type": "standard",
        "destination": {"places": ["ליסבון"], "mode": "specific", "status": "known"},
        "destination_airports": ["LIS"],
        "travelers": {"adults": 2, "children": 0},
        "dates": {"departure": None, "return": None},
        "requested_services": ["flights"],
        "service_decisions": {"flights": {"wanted": True}},
        "session_status": {"flights": "active", "lodging": "pending", "car": "pending", "trip_planning": "pending"},
        "active_session": "flights",
        "search_confirmed": False,
    }


def _send(email, message, trip_state):
    member = _make_member(email)
    with client.session_transaction() as sess:
        sess["member_id"] = member

    def _quiet_post_claude(key, model, system_static, system_dynamic, history, message_, max_tokens, include_history=True, source="other"):
        if source == "state_extractor":
            return json.dumps({
                "trip_update": {}, "restart_request": False, "restart_evidence": None,
                "dates_evidence": None, "destination_evidence": None, "trip_type_evidence": None,
                "link_request": True, "link_request_evidence": message,
            })
        if source == "guided_extract":
            return json.dumps({"status": "other_topic", "field": None, "evidence": None})
        if source == "tinkerbell_reply":
            return "לא אמורה להגיע לכאן - התשובה הדטרמיניסטית אמורה ליירט קודם."
        return "{}"

    with patch.object(chat, "_post_claude", side_effect=_quiet_post_claude):
        r = client.post("/api/ariella/chat-clean", json={
            "message": message,
            "history": [{"role": "assistant", "content": "קלטתי, ממשיכים."}],
            "trip_state": trip_state,
        })
    return r.get_json()


_FORBIDDEN_PHRASES = ("אין לי אפשרות לשלוח קישורים", "לא יכולה לשלוח קישור", "אי אפשר לשלוח קישור")
_STATUS_CLAIMS = ("החיפוש רץ ברקע", "החיפוש עדיין רץ", "סיימתי את החיפוש", "החיפוש הסתיים")

# =====================================================================
# Shaked's exact 5 test phrasings, against a vacation with a confirmed
# search - each must set open_existing_flights=True (the mechanism that
# actually attaches/navigates to the real link on both channels) and the
# reply must never use the forbidden "I can't send links" framing or make
# a specific running/finished claim that could mismatch the real state.
# =====================================================================
_PHRASINGS = [
    "תשלחי לי שוב קישור ללוח?",
    "איפה אני רואה את הטיסות?",
    "אפשר את הלינק לחופשה?",
    "שלחי לינק לדף שלי",
    "לא מוצאת את מה שמצאת לי, איפה זה?",
]

for phrasing in _PHRASINGS:
    data = _send(f"qa-link-{abs(hash(phrasing))}@example.com", phrasing, _confirmed_state())
    check(f"'{phrasing}' -> open_existing_flights=True (a confirmed vacation exists)",
          data.get("open_existing_flights") is True)
    reply = str(data.get("reply") or "")
    check(f"'{phrasing}' -> reply never uses the forbidden 'can't send links' framing",
          not any(p in reply for p in _FORBIDDEN_PHRASES))
    check(f"'{phrasing}' -> reply never asserts a specific running/finished search-status claim",
          not any(p in reply for p in _STATUS_CLAIMS))

# =====================================================================
# Same request, but nothing was ever confirmed/launched for this vacation -
# there is genuinely no link to hand over yet. Must still never use the
# forbidden framing, and must not set open_existing_flights (there is no
# real trip to navigate to).
# =====================================================================
data_none = _send("qa-link-nothing-confirmed@example.com", "תשלחי לי שוב קישור ללוח?", _not_confirmed_state())
check("nothing confirmed yet -> open_existing_flights is not set (no real vacation to link to)",
      not data_none.get("open_existing_flights"))
reply_none = str(data_none.get("reply") or "")
check("nothing confirmed yet -> reply never uses the forbidden 'can't send links' framing either",
      not any(p in reply_none for p in _FORBIDDEN_PHRASES))
check("nothing confirmed yet -> reply never asserts a running/finished search-status claim",
      not any(p in reply_none for p in _STATUS_CLAIMS))

# =====================================================================
# Regression: a plain message with no genuine link-request evidence must
# never trigger this path (the fail-safe source above always returns
# link_request_evidence=message, so this checks the evidence-verification
# gate itself, via _value_has_verbatim_evidence directly).
# =====================================================================
check("regression: _value_has_verbatim_evidence rejects an evidence quote "
      "that isn't actually present in the message (no false trigger from "
      "an unverifiable model claim)",
      not chat._value_has_verbatim_evidence("תשלחי לי קישור", "מה שלומך?"))

# =====================================================================
# EXTRACTOR_SYSTEM + parser wiring.
# =====================================================================
check("EXTRACTOR_SYSTEM documents link_request/link_request_evidence as a "
      "sibling pair of restart_request, evidence-gated the same way",
      "link_request" in chat.EXTRACTOR_SYSTEM and "link_request_evidence" in chat.EXTRACTOR_SYSTEM)

check("_parse_link_request_signal reads link_request/link_request_evidence "
      "out of the raw extractor JSON",
      chat._parse_link_request_signal(json.dumps({"link_request": True, "link_request_evidence": "x"}))
      == (True, "x"))
check("_parse_link_request_signal defaults to (False, None) on unparseable input",
      chat._parse_link_request_signal("not json") == (False, None))

check("TINKERBELL_SYSTEM forbids the 'I can't send links' framing",
      "אין לך אפשרות לשלוח קישורים" in chat.TINKERBELL_SYSTEM
      or "לשלוח קישורים" in chat.TINKERBELL_SYSTEM)

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL LINK-REQUEST TESTS PASSED")
