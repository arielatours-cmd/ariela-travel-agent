"""QA for a round-4 bug Shaked found (B2/B3/C2, Croatia, 2026-10-16): every
"start a new and separate vacation" reset (explicit "חופשה חדשה"/"טיול
אחר" language, the _NEW_AND_SEPARATE_RE/_ENTIRELY_NEW_RE phrasing, the
pending-reopen "new" choice, and the "is this a new plan or the current
one?" confirm-"new" branch) only ever seeded the fresh blank trip_state
with the DESTINATION extracted from the triggering message - every other
fact stated in that same breath (trip type, dates, duration, travelers,
departure airport, budget) was silently thrown away, so Ariella asked for
it again a moment later as if it had never been said.

Concretely (qa-round4, C3): "עוד חופשת סקי, חדשה ונפרדת" (another ski
vacation, new and separate) reset trip_type to None even though the
customer stated "סקי" in the very same message, and Ariella re-asked
"regular/business/ski?" right after.

Fixed by routing every one of these reset branches through
`_seed_fresh_trip_from_trigger_message`, which runs the same deterministic
extraction cascade (destination/trip_type/dates/duration/travelers/
departure_airport/budget) the normal per-turn flow already runs - scoped
to only the single triggering message, never the older/stale history.

Run: python3 tools/qa_round4_new_and_separate_keeps_same_message_facts.py
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
            ("QA Round4 New Separate", email, generate_password_hash("Test1234!"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
        )
        return cur.lastrowid


member_id = _make_member("qa-round4-new-separate@example.com")
with client.session_transaction() as sess:
    sess["member_id"] = member_id

# --- C3-style: "עוד חופשת סקי, חדשה ונפרדת" after a committed (different
#     trip_type) vacation must keep BOTH the new destination AND the
#     stated trip_type (ski) in the fresh state, not just the destination ---
committed_state = {
    "destination": {"places": ["זלצבורג"], "mode": "specific", "status": "known"},
    "trip_type": "standard",
    "search_confirmed": True,
    "session_status": {"flights": "complete", "lodging": "complete", "car": "declined", "trip_planning": "declined"},
}
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude):
    r = client.post("/api/ariella/chat-clean", json={
        "message": "עוד חופשת סקי, חדשה ונפרדת לבנסקו", "history": [], "trip_state": dict(committed_state),
    })
data = r.get_json()
update = data.get("trip_update") or {}
check("trip_state_reset actually happened", bool(data.get("trip_state_reset")))
check("new destination (בנסקו) carried into the fresh state",
      "בנסקו" in ((update.get("destination") or {}).get("places") or []))
check("trip type stated in the SAME message (ski) is kept, not dropped",
      update.get("trip_type") == "ski")

# --- B2/B3-style: dates + travelers stated in the same "new and separate"
#     message must also survive, not just the destination ---
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude):
    r2 = client.post("/api/ariella/chat-clean", json={
        "message": "רוצה חופשה חדשה ונפרדת לקרואטיה, זוג, 10/6/2027 עד 17/6/2027",
        "history": [], "trip_state": dict(committed_state),
    })
data2 = r2.get_json()
update2 = data2.get("trip_update") or {}
check("Croatia destination carried into the fresh state",
      "קרואטיה" in ((update2.get("destination") or {}).get("places") or []))
check("travelers (זוג -> 2 adults) stated in the same message are kept",
      (update2.get("travelers") or {}).get("adults") == 2)
check("exact dates stated in the same message are kept",
      (update2.get("dates") or {}).get("departure") == "2027-06-10"
      and (update2.get("dates") or {}).get("return") == "2027-06-17")

with sqlite3.connect(DB) as conn:
    conn.execute("DELETE FROM members WHERE id=?", (member_id,))
    conn.commit()

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL ROUND4-NEW-AND-SEPARATE-KEEPS-SAME-MESSAGE-FACTS TESTS PASSED")
