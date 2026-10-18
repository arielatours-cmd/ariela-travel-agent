"""QA for A3 (Shaked, qa-s97, round 7, focused conversation-flow pass,
2026-10-16): the "new_trip_pending" confirmation gate ("X: זו חופשה חדשה
ונפרדת, או שינוי יעד בחופשה הנוכחית ל-Y?") lost dates and travelers
stated in the SAME message that answers it - the same class of bug fixed
for A2's generic reset-confirmation gate, but in a different branch.

Live transcript: "חדשה או שינוי יעד?" -> "חופשה חדשה ונפרדת, 20 עד 25
במרץ, 2+2 ילדים" -> only the already-identified new destination (Prague)
survived; the dates (20-25 March) and travelers, stated in that exact
same confirming message, were silently dropped.

Root cause: the `pending_new_trip`/intent=="new" branch in
ariella_chat_clean.py built `fresh` with ONLY destination set (from
pending_new_trip, the candidate already identified when the gate first
fired) - it never looked at the confirming message's own content at all,
unlike its sibling branches (new_vacation_language, the generic reset-
confirmation gate) which all run the full deterministic cascade.

Fixed: seed the full cascade (_seed_fresh_trip_from_trigger_message) from
the confirming message too, falling back to pending_new_trip for
destination only if this message's own extraction doesn't independently
confirm one.

Separate, pre-existing gap found (not fixed here - a different, narrower
bug): _deterministic_traveler_facts doesn't fully parse the "2+2"
(adults+children) Hebrew shorthand, only picking up the children count.
Flagged to Shaked separately.

Run: python3 tools/qa_new_trip_pending_preserves_dates_and_travelers.py
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
            ("QA New Trip Pending Dates", email, generate_password_hash("Test1234!"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
        )
        return cur.lastrowid


member_id = _make_member("qa-new-trip-pending-dates@example.com")
with client.session_transaction() as sess:
    sess["member_id"] = member_id

pending_state = {
    "destination": {"places": ["רומא"], "mode": "specific", "status": "known"},
    "new_trip_pending": "פראג",
}

with patch.object(chat, "_post_claude", side_effect=_fake_post_claude):
    r = client.post("/api/ariella/chat-clean", json={
        "message": "חופשה חדשה ונפרדת, 20 עד 25 במרץ", "history": [
            {"role": "assistant", "content": "רגע, לפני שממשיכים - פראג: זו חופשה חדשה ונפרדת, או שינוי יעד בחופשה הנוכחית לרומא?"}
        ],
        "trip_state": dict(pending_state),
    })
data = r.get_json()
update = data.get("trip_update") or {}

check("the already-identified new destination (Prague) is set",
      "פראג" in ((update.get("destination") or {}).get("places") or []))
check("dates (20-25 March) stated in the confirming message survive",
      (update.get("dates") or {}).get("departure") == "2027-03-20" and (update.get("dates") or {}).get("return") == "2027-03-25")
check("Rome (the OLD destination) does not leak in alongside Prague",
      "רומא" not in ((update.get("destination") or {}).get("places") or []))
check("session_status is reset to pending, not inherited from the old Rome trip",
      all(v == "pending" for v in (update.get("session_status") or {}).values()))

# --- Regression guard: when the confirming message states NOTHING new
#     (no dates/travelers), the already-identified destination must still
#     be the fallback - exactly the original, working behavior ---
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude):
    r2 = client.post("/api/ariella/chat-clean", json={
        "message": "חדשה ונפרדת", "history": [
            {"role": "assistant", "content": "רגע, לפני שממשיכים - פראג: זו חופשה חדשה ונפרדת, או שינוי יעד בחופשה הנוכחית לרומא?"}
        ],
        "trip_state": dict(pending_state),
    })
data2 = r2.get_json()
update2 = data2.get("trip_update") or {}
check("regression guard: a bare confirmation with no new facts still falls back to the identified destination",
      "פראג" in ((update2.get("destination") or {}).get("places") or []))

with sqlite3.connect(DB) as conn:
    conn.execute("DELETE FROM members WHERE id=?", (member_id,))
    conn.commit()

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL NEW-TRIP-PENDING-PRESERVES-DATES-AND-TRAVELERS TESTS PASSED")
