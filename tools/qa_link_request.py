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

Second version (per Shaked's review of the first, 20.10): the first attempt
short-circuited with a fixed-sentence reply right after extraction, before
the rest of the turn's normal processing - which silently discarded any
OTHER fact the same message also carried (e.g. "שלחי לי את הלינק, ואגב
התקציב עד 1000" lost the budget), and skipped the open question entirely
when there was nothing to link to yet. Now the turn runs its full normal
pipeline exactly as any other message would; a transient
"_link_request_pending" hint ("has_vacation"/"no_vacation_yet") tells
Tinkerbell to acknowledge the request in her own words (never "הנה הקישור"
herself - the real link is attached separately via open_existing_flights,
which the code sets at the very end from state alone) and, when there's
nothing to link to yet, to continue straight to the next open question in
the SAME message.

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


# =====================================================================
# Direct hint-injection tests (mirrors tools/qa_stale_reset_greeting.py's
# own pattern exactly): _call_tinkerbell's system_dynamic must carry the
# right instruction for each of the two "_link_request_pending" values,
# and must carry nothing at all when the flag isn't set.
# =====================================================================
captured = {}


def _fake_post_claude(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    captured["system_dynamic"] = system_dynamic
    return "הודעה לדוגמה."


HAS_VACATION_MARKER = "יש לו חופשה פעילה לקשר אליה"
NO_VACATION_MARKER = "אבל עדיין אין חופשה שאפשר לקשר אליה"

with patch.object(chat, "_post_claude", side_effect=_fake_post_claude):
    base_state = {"session_status": {"flights": "pending", "lodging": "pending", "car": "pending", "trip_planning": "pending"}}

    captured.clear()
    chat._call_tinkerbell("test-key-not-real", "claude-sonnet-5", [], "תשלחי לי קישור", dict(base_state, _link_request_pending="has_vacation"))
    check("_link_request_pending='has_vacation' -> Tinkerbell told a vacation exists to link to, never to write the link herself",
          HAS_VACATION_MARKER in captured["system_dynamic"] and "הנה הקישור" not in captured["system_dynamic"].split(HAS_VACATION_MARKER)[0][-200:])
    check("_link_request_pending='has_vacation' -> never asserts a running/finished search-status claim in the hint itself",
          "לעולם אל תתארי אם החיפוש עדיין רץ או כבר הסתיים" in captured["system_dynamic"])

    captured.clear()
    chat._call_tinkerbell("test-key-not-real", "claude-sonnet-5", [], "תשלחי לי קישור", dict(base_state, _link_request_pending="no_vacation_yet"))
    check("_link_request_pending='no_vacation_yet' -> Tinkerbell told there's nothing to link to yet and to continue to the next open question",
          NO_VACATION_MARKER in captured["system_dynamic"]
          and "המשיכי ישירות לשאלה הפתוחה הבאה" in captured["system_dynamic"])
    check("_link_request_pending='no_vacation_yet' -> forbids the 'I can't send links' framing",
          "אין לי אפשרות לשלוח קישורים" in captured["system_dynamic"])

    captured.clear()
    chat._call_tinkerbell("test-key-not-real", "claude-sonnet-5", [], "שלום", dict(base_state))
    check("no _link_request_pending flag -> no link-request hint leaks into an ordinary turn",
          HAS_VACATION_MARKER not in captured["system_dynamic"] and NO_VACATION_MARKER not in captured["system_dynamic"])


# =====================================================================
# End-to-end through the real endpoint: the open_existing_flights flag
# itself is still decided purely from state, and - the actual regression
# this version fixes - another fact in the SAME message is no longer lost.
# =====================================================================
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


def _confirmed_state():
    return {
        "trip_type": "standard",
        "destination": {"places": ["ליסבון"], "mode": "specific", "status": "known"},
        "destination_airports": ["LIS"],
        "departure_airport": "TLV",
        "travelers": {"adults": 2, "children": 0},
        "dates": {"departure": "2027-03-05", "return": "2027-03-10", "needs_confirmation": False},
        "budget_per_person": {"status": "unknown"},
        "flight": {"connection_preference": "any", "cabin": "economy", "baggage": ["checked_bag"]},
        "requested_services": ["flights"],
        "service_decisions": {"flights": {"wanted": True}},
        "session_status": {"flights": "active", "lodging": "declined", "car": "declined", "trip_planning": "declined"},
        "active_session": "flights",
        "search_confirmed": True,
    }


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


def _send(email, message, trip_state, extra_trip_update=None):
    member = _make_member(email)
    with client.session_transaction() as sess:
        sess["member_id"] = member

    def _quiet_post_claude(key, model, system_static, system_dynamic, history, message_, max_tokens, include_history=True, source="other"):
        if source == "state_extractor":
            return json.dumps({
                "trip_update": extra_trip_update or {}, "restart_request": False, "restart_evidence": None,
                "dates_evidence": None, "destination_evidence": None, "trip_type_evidence": None,
                "link_request": True, "link_request_evidence": message,
            })
        if source == "guided_extract":
            return json.dumps({"status": "other_topic", "field": None, "evidence": None})
        if source == "tinkerbell_reply":
            return "קלטתי, ממשיכים."
        return "{}"

    with patch.object(chat, "_post_claude", side_effect=_quiet_post_claude):
        r = client.post("/api/ariella/chat-clean", json={
            "message": message,
            "history": [{"role": "assistant", "content": "קלטתי, ממשיכים."}],
            "trip_state": trip_state,
        })
    return r.get_json()


# =====================================================================
# Shaked's exact 5 test phrasings, against a vacation with a confirmed
# search - each must set open_existing_flights=True.
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

# =====================================================================
# Nothing confirmed yet -> open_existing_flights must not fire.
# =====================================================================
data_none = _send("qa-link-nothing-confirmed@example.com", "תשלחי לי שוב קישור ללוח?", _not_confirmed_state())
check("nothing confirmed yet -> open_existing_flights is not set (no real vacation to link to)",
      not data_none.get("open_existing_flights"))

# =====================================================================
# THE regression this version fixes: another fact given in the SAME
# message as the link request must not be lost to an early return.
# =====================================================================
data_with_budget = _send(
    "qa-link-preserves-other-facts@example.com",
    "שלחי לי את הלינק, ואגב התקציב עד 1000 שקל לכרטיס",
    _confirmed_state(),
    extra_trip_update={"budget_per_person": {"amount": 1000, "currency": "ILS", "status": "known"}},
)
check("open_existing_flights still fires when the message also carries another fact",
      data_with_budget.get("open_existing_flights") is True)
check("regression: a budget mentioned in the SAME message as the link request is NOT discarded by an early return",
      (data_with_budget.get("trip_update") or {}).get("budget_per_person", {}).get("amount") == 1000)

# =====================================================================
# Regression: a plain message with no genuine link-request evidence must
# never trigger this path.
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
