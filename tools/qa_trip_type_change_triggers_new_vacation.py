"""QA for C1 (Shaked, qa-s91, round 2, 2026-10-15, trip 228) - flagged as a
SEVERE cross-vacation data leak. Right after approving a Zurich BUSINESS
trip, the customer wrote "אני רוצה חופשת סקי, טיסה לז'נבה" (I want a SKI
vacation, flight to Geneva). Live symptoms:
  1. The reply claimed "all details point to a ski vacation in Zurich"
     (Zurich is the OLD business destination) while also setting
     start_flight_search=true in the same turn as a clarifying question.
  2. After "new and separate", Geneva was forgotten entirely.
  3. After "I said Geneva", Ariella compared "Ben Gurion vs Zurich (ZRH) -
     already fixed".
  4. After two explicit corrections ("not Zurich! Geneva", "GVA"), Ariella
     said "I'm correcting" but trip_update still had
     destination_airports=['ZRH'], trip_type="business", and the summary
     read "business trip to Geneva" (mixing the new city with the old trip
     type).

Root cause: the only "this is a genuinely new vacation after a committed
trip" detector (new_vacation_language) was an exact-phrase list that never
included trip-type phrasing ("חופשת סקי", "נסיעת עסקים" etc.) - so stating
a DIFFERENT trip type than the one already committed never triggered the
hard reset, and the plain "טיסה ל..." in the same message got swallowed by
the earlier, destination-blind "flights is always allowed" session switch
instead, re-activating flights on the OLD (Zurich/business) trip.

Fixed by also triggering new_vacation_language whenever the message states
a trip_type (via the already-existing, richer _deterministic_trip_type_facts)
that differs from the trip_type already committed on the active trip -
reusing the exact same hard-reset path (clears destination/airports/
trip_type, reseeds only what this message actually says) already used for
the literal "חופשה חדשה" phrases.

Run: python3 tools/qa_trip_type_change_triggers_new_vacation.py
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


# --- 1. Unit: new_vacation_language's underlying trip-type signal ---
check("_deterministic_trip_type_facts recognizes 'חופשת סקי' as ski",
      chat._deterministic_trip_type_facts("אני רוצה חופשת סקי, טיסה לז'נבה").get("trip_type") == "ski")

# --- 2. End to end: a committed Zurich BUSINESS trip + "חופשת סקי...ז'נבה"
#        must hard-reset, never stay stuck on Zurich/business ---
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
            ("QA Trip Type Change", email, generate_password_hash("Test1234!"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
        )
        return cur.lastrowid


member_id = _make_member("qa-trip-type-change@example.com")
with client.session_transaction() as sess:
    sess["member_id"] = member_id

zurich_business_state = {
    "trip_type": "business",
    "destination": {"places": ["ציריך"], "mode": "specific", "status": "known"},
    "destination_airports": ["ZRH"],
    "active_session": None,
    "search_confirmed": True,
    "post_flight_continuation": True,
    "requested_services": ["flights", "lodging"],
    "session_status": {"flights": "complete", "lodging": "complete", "car": "declined", "trip_planning": "declined"},
    "service_decisions": {
        "flights": {"wanted": True, "source": "explicit_request"},
        "lodging": {"wanted": True, "source": "explicit_request"},
        "car": {"wanted": False, "source": "business_trip_default"},
        "trip_planning": {"wanted": False, "source": "business_trip_default"},
    },
}

with patch.object(chat, "_post_claude", side_effect=_fake_post_claude):
    r = client.post("/api/ariella/chat-clean", json={
        "message": "אני רוצה חופשת סקי, טיסה לז'נבה",
        "history": [{"role": "assistant", "content": "מעולה, נסיעת העסקים לציריך אושרה ויצאה לסריקה."}],
        "trip_state": dict(zurich_business_state),
    })
data = r.get_json()
trip_update = data.get("trip_update") or {}
reply = str(data.get("reply") or "")

check("the old Zurich business trip_type never survives into the new request",
      trip_update.get("trip_type") != "business")
check("the old ZRH airport never survives into the new request",
      "ZRH" not in (trip_update.get("destination_airports") or []))
check("Geneva is captured as the new destination",
      "ז'נבה" in ((trip_update.get("destination") or {}).get("places") or []))
# destination_airports resolution for the new place happens later in the
# normal pipeline (the model's own extraction, or a later deterministic
# pass) - this immediate reset turn only ever seeds destination.places,
# exactly like the pre-existing literal "חופשה חדשה" reset path already did.
check("the reply never claims the request points to Zurich",
      "ציריך" not in reply)
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
print("\nALL TRIP-TYPE-CHANGE-TRIGGERS-NEW-VACATION TESTS PASSED")
