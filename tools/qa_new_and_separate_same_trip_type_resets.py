"""QA for C3 (Shaked, qa-s91, round 2, 2026-10-15) - a direct follow-up to
the C1 fix (trip-type-mismatch triggers a new-vacation reset). Shaked's own
note after reviewing that fix: "תיקון C1 לא יכסה את C3. שם 'עוד חופשת סקי,
חדשה ונפרדת' הגיעה אחרי סקי בזאלבאך, כלומר אותו סוג נסיעה" - right after a
committed SKI trip to Saalbach, "עוד חופשת סקי, חדשה ונפרדת" (another ski
vacation, new and separate) is the SAME trip_type (ski), so the C1 check
never fires. The exact-phrase new_vacation_language list ("חופשה חדשה",
"טיול חדש", ...) didn't match either, because "חדשה" here never sits
directly next to "חופשה"/"טיול" (the word order/punctuation is different:
"חדשה ונפרדת" at the end of the sentence, not "חופשה חדשה" as one unit).
Live symptoms once the reset failed to fire: Saalbach facts leaked into the
"new" conversation ("זאלבאך כבר דיברנו"), lodging stayed marked complete
with null fields, and start_flight_search=true appeared in the very first
reply after approval.

Fixed with _NEW_AND_SEPARATE_RE (module level): "new" and "separate" found
near each other, in either order, with an optional ו-conjunction prefix on
either word - regardless of exact phrasing or adjacency to "חופשה"/"טיול".

Run: python3 tools/qa_new_and_separate_same_trip_type_resets.py
"""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import database
database.init_db()

import ariella_chat_clean as chat
import app as app_module
from datetime import datetime, timezone
from werkzeug.security import generate_password_hash
import sqlite3

DB = database.DB_PATH
client = app_module.app.test_client()

FAILED = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


# --- 1. Unit: the regex itself ---
check("'עוד חופשת סקי, חדשה ונפרדת' is recognized as a new-and-separate declaration",
      bool(chat._NEW_AND_SEPARATE_RE.search("עוד חופשת סקי, חדשה ונפרדת")))
check("a message merely mentioning a 'new room' is never a false positive",
      not chat._NEW_AND_SEPARATE_RE.search("אני רוצה חדר חדש בבקשה"))

# --- 2. End to end: a committed SKI trip (Saalbach) + 'עוד חופשת סקי, חדשה
#        ונפרדת' (same trip_type!) must still hard-reset ---
def _fake_post_claude(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        return "{}"
    return "תשובה לדוגמה."


def _make_member(email):
    with sqlite3.connect(DB) as conn:
        conn.execute("DELETE FROM members WHERE email=?", (email,))
        conn.commit()
        cur = conn.execute(
            "INSERT INTO members (full_name,email,password_hash,created_at,status,whatsapp_opt_in,preferred_airports) "
            "VALUES(?,?,?,?,?,?,?)",
            ("QA New Separate Same Type", email, generate_password_hash("Test1234!"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
        )
        return cur.lastrowid


member_id = _make_member("qa-new-separate-same-type@example.com")
with client.session_transaction() as sess:
    sess["member_id"] = member_id

saalbach_ski_state = {
    "trip_type": "ski",
    "destination": {"places": ["זאלבאך"], "mode": "specific", "status": "known"},
    "destination_airports": ["SZG"],
    "active_session": None,
    "search_confirmed": True,
    "post_flight_continuation": True,
    "requested_services": ["flights", "lodging"],
    "session_status": {"flights": "complete", "lodging": "complete", "car": "declined", "trip_planning": "declined"},
    "service_decisions": {
        "flights": {"wanted": True, "source": "explicit_request"},
        "lodging": {"wanted": True, "source": "explicit_request"},
    },
}

with patch.object(chat, "_post_claude", side_effect=_fake_post_claude):
    r = client.post("/api/ariella/chat-clean", json={
        "message": "עוד חופשת סקי, חדשה ונפרדת",
        "history": [{"role": "assistant", "content": "מעולה, חופשת הסקי לזאלבאך אושרה ויצאה לסריקה."}],
        "trip_state": dict(saalbach_ski_state),
    })
data = r.get_json()
trip_update = data.get("trip_update") or {}
reply = str(data.get("reply") or "")

check("the old Saalbach destination never survives into the new request",
      "זאלבאך" not in ((trip_update.get("destination") or {}).get("places") or []))
check("the old SZG airport never survives into the new request",
      "SZG" not in (trip_update.get("destination_airports") or []))
check("lodging is never left marked complete from the old trip",
      (trip_update.get("session_status") or {}).get("lodging") != "complete")
check("the reply never references Saalbach",
      "זאלבאך" not in reply)
check("this turn never launches a flight search by itself (a reset always asks first)",
      not data.get("start_flight_search"))
check("the reset is flagged to the client (trip_state_reset)",
      bool(data.get("trip_state_reset")))

with sqlite3.connect(DB) as conn:
    conn.execute("DELETE FROM members WHERE id=?", (member_id,))
    conn.commit()

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL NEW-AND-SEPARATE-SAME-TRIP-TYPE-RESETS TESTS PASSED")
