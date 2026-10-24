"""QA: a change request to a vacation that already went out to a scan (live
round 13 D, Hamburg; the business owner, 24.10, via Shlomo): "אי אפשר לשנות
חופשה שיצאה לסריקה אלא אם משלמים מנוי".

Live: after "מאשרת" the customer moved to her personal area and wrote "אפשר
לדחות את כל הטיסה ביום אחד?" in a fresh conversation (empty state). The
classifier had no idea any vacation existed, a date was proposed on an empty
state, and on "כן" the resume path found nothing OPEN (every service settled)
and said "לא נותרה לך אף חופשה פתוחה".

Now:
- the opening classifier is told which vacations exist (context), so a change
  request to one of them is KEEP, never a new conversation;
- with nothing open to continue, the model decides (change_existing) whether
  the customer is asking to CHANGE a detail of an existing vacation; if so the
  brief names the vacation, explains the subscription rule and points to it -
  no dates, no questions, no scan;
- a plain "continue" with nothing open keeps the R3 answer (nothing open, no
  vacation named).

Every understanding is the (fake) model's; asserts check the brief handed to
the reply model and the state - never wording. Offline. Run:
python3 tools/qa_scanned_trip_change_subscription.py
"""
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")
os.environ.setdefault("SCHEDULER_ENABLED", "false")

import database  # noqa: E402
database.init_db()

import ariella_chat_clean as chat  # noqa: E402
import whatsapp_bridge  # noqa: E402
from werkzeug.security import generate_password_hash  # noqa: E402

FAILED = []
CLASSIFIER_CALLS = []


def check(name, cond):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        FAILED.append(name)


def member(email):
    with sqlite3.connect(database.DB_PATH) as conn:
        conn.execute("DELETE FROM members WHERE email=?", (email,))
        mid = conn.execute(
            "INSERT INTO members (full_name,email,password_hash,created_at,status,whatsapp_opt_in,preferred_airports) VALUES(?,?,?,?,?,?,?)",
            ("QA", email, generate_password_hash("x"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]")).lastrowid
        conn.commit()
    return mid


def scanned_trip(member_id, name, code, dep, ret, subscription="none"):
    answers = {"origin_airports": ["TLV"], "destinations": code, "departure_date": dep, "return_date": ret, "adults": 2,
               "_flight_search_finished": True,
               "_session_status": {"flights": "complete", "lodging": "declined", "car": "declined", "trip_planning": "declined"}}
    with sqlite3.connect(database.DB_PATH) as conn:
        tid = conn.execute(
            "INSERT INTO trip_requests (member_id, request_name, travel_window, created_at, status, answers_json, subscription_status) VALUES(?,?,?,?,?,?,?)",
            (member_id, name, f"{dep} - {ret}", datetime.now(timezone.utc).isoformat(), "active", json.dumps(answers, ensure_ascii=False), subscription)).lastrowid
        conn.commit()
    return tid


def _customer(message):
    return str(message or "").split("תשובת הלקוח:", 1)[-1].strip()


def fake(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    """Stands in for the model's understanding (offline)."""
    if source == "tinkerbell_reply":
        return str(system_dynamic or "") or "תשובה."
    if source != "classifier":
        return "{}"
    text, full = _customer(message), str(message or "")
    if "question_kind=new_vacation" in full:
        CLASSIFIER_CALLS.append(("new_vacation", full))
        if "חדש" in text:
            return "NEW"
        # A change to an existing vacation is understood as KEEP only when the model knows one exists.
        if "להמשיך" in text or ("לדחות" in text and "ללקוח יש חופשות קיימות" in full):
            return "KEEP"
        return "UNCLEAR"
    if "question_kind=change_existing" in full:
        CLASSIFIER_CALLS.append(("change_existing", full))
        return "CHANGE" if ("לדחות" in text or "מזוודה" in text) else "OTHER"
    return "UNCLEAR"


with patch.object(chat, "_post_claude", side_effect=fake):
    # --- D: Hamburg, every service settled, scanned, no subscription -------------------------------------
    m = member("qa-scanned-change-d@example.com")
    scanned_trip(m, "המבורג", "HAM", "2027-05-06", "2027-05-10")
    reply = whatsapp_bridge.ariella_turn(m, "אפשר לדחות את כל הטיסה ביום אחד?")
    state = (database.load_ariella_conversation(m) or {}).get("trip_state") or {}
    first = [c for k, c in CLASSIFIER_CALLS if k == "new_vacation"]
    check("the opening classifier is told the existing vacation (context), so a change request is understood as KEEP",
          first and "ללקוח יש חופשות קיימות: המבורג" in first[-1])
    check("the model is asked whether this is a change to an existing vacation",
          any(k == "change_existing" and "המבורג" in c for k, c in CLASSIFIER_CALLS))
    check("the brief names the existing vacation and forbids 'no open vacation'",
          "המבורג" in reply and "לעולם אל תאמרי שאין לו חופשה פתוחה" in reply)
    check("the brief explains the rule and points to the paid daily-tracking subscription",
          "מנוי המעקב היומי בתשלום" in reply and "מעקב יומי בתשלום" in reply)
    check("no dates offered, no questions, no new search/planning",
          "אל תציעי תאריכים" in reply and "אל תשאלי שום שאלה" in reply and "אל תתחילי חיפוש" in reply)
    check("state: the trip isn't touched and no fresh start (no reset, nothing pending)",
          state.get("resume_choice_done") is True and not state.get("resume_choice_pending") and not state.get("destination"))

    # The rest of the live D script: further change requests in the same conversation.
    for later in ("ובעצם אפשר לצאת ב-9.5 ולחזור ב-13.5? לדחות", "ונעדיף בעצם מזוודה לכל אחד"):
        r = whatsapp_bridge.ariella_turn(m, later)
        st = (database.load_ariella_conversation(m) or {}).get("trip_state") or {}
        check(f"later change request ('{later[:22]}...') -> the same subscription brief, never a new trip on an empty state",
              "המבורג" in r and "מנוי המעקב היומי בתשלום" in r and not st.get("destination") and not st.get("dates"))

    # --- the same, via the ask stage ("הי" -> the change request) ------------------------------------------
    m2 = member("qa-scanned-change-ask@example.com")
    scanned_trip(m2, "המבורג", "HAM", "2027-05-06", "2027-05-10")
    whatsapp_bridge.ariella_turn(m2, "הי")
    reply2 = whatsapp_bridge.ariella_turn(m2, "ונעדיף בעצם מזוודה לכל אחד, להמשיך עם החופשה")
    check("via the ask stage too: the change request gets the subscription brief, never 'no open vacation'",
          "המבורג" in reply2 and "מנוי המעקב היומי בתשלום" in reply2)

    # --- R3 regression: a plain "continue" with nothing open ------------------------------------------------
    m3 = member("qa-scanned-change-r3@example.com")
    scanned_trip(m3, "קפריסין", "LCA", "2027-06-27", "2027-07-01")
    whatsapp_bridge.ariella_turn(m3, "הי")
    reply3 = whatsapp_bridge.ariella_turn(m3, "להמשיך")
    check("R3 unchanged: 'continue' with nothing open -> nothing open, the vacation not named, no subscription brief",
          "אין" in reply3 and "קפריסין" not in reply3 and "מנוי" not in reply3)

    # --- a vacation that already has an active subscription ------------------------------------------------
    m4 = member("qa-scanned-change-sub@example.com")
    scanned_trip(m4, "המבורג", "HAM", "2027-05-06", "2027-05-10", subscription="active")
    reply4 = whatsapp_bridge.ariella_turn(m4, "אפשר לדחות את כל הטיסה ביום אחד?")
    check("with an active subscription: the change goes through the tracking, no 'join the subscription'",
          "כבר יש מנוי מעקב יומי פעיל" in reply4 and "להצטרף למנוי" not in reply4)

    # --- the helper itself ---------------------------------------------------------------------------------
    m5 = member("qa-scanned-change-past@example.com")
    scanned_trip(m5, "עבר", "ATH", "2020-01-01", "2020-01-05")
    check("past vacations aren't listed", chat._scanned_upcoming_vacations(m5) == [])

    # The classifier never returns change/other for the old question kind (callers there only know new/keep/unclear).
    with patch.object(chat, "_post_claude", return_value="CHANGE"):
        check("CHANGE is only understood for change_existing - new_vacation gets 'unclear'",
              chat._interpret_pending_choice("k", "m", [], "x", "new_vacation") == "unclear"
              and chat._interpret_pending_choice("k", "m", [], "x", "change_existing") == "change")

with sqlite3.connect(database.DB_PATH) as conn:
    conn.execute("DELETE FROM members WHERE email LIKE 'qa-scanned-change-%'")
    conn.commit()

print()
print("ALL PASS" if not FAILED else f"{len(FAILED)} FAILED: {FAILED}")
sys.exit(1 if FAILED else 0)
