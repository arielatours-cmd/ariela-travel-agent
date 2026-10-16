"""QA for A2 (Shaked, qa-s97, round 7, focused conversation-flow pass,
2026-10-16): the generic restart-confirmation gate ("למחוק את כל הפרטים
ולהתחיל חופשה חדשה מאפס?") lost dates and travelers stated in the SAME
message that triggered it, even though destination and trip_type already
survived there (fixed earlier for C2, round 2).

Live transcript: "זו חופשה חדשה לגמרי?" -> "חופשה חדשה לגמרי לאיטליה, 10
עד 17 באפריל, שלושה מבוגרים" -> "למחוק את כל הפרטים?" -> "כן" -> only
Italy survived; both the dates (10-17 April) and the traveler count
(three adults), stated in that exact same breath, were silently dropped
and asked again a turn later as if the customer had never said them.

Root cause: the reset-confirmation ("yes") branch in ariella_chat_clean.py
only ever hand-picked two fields from the original triggering message -
_deterministic_destination_facts and _deterministic_trip_type_facts -
instead of using the already-existing _seed_fresh_trip_from_trigger_
message helper, which runs the FULL deterministic cascade (destination,
trip_type, dates, duration, travelers, departure_airport, budget) built
specifically to avoid losing facts stated in a reset's own triggering
message (this exact class of bug, first found round 4 for B2/B3/C2).
This one spot had drifted from that shared helper and silently regressed
to losing everything except the two fields it hand-picked.

Fixed: swapped the two hand-picked extractions for a single call to
_seed_fresh_trip_from_trigger_message(original_change).

Run: python3 tools/qa_reset_confirmation_preserves_dates_and_travelers.py
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
            ("QA Reset Confirm Dates", email, generate_password_hash("Test1234!"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
        )
        return cur.lastrowid


member_id = _make_member("qa-reset-confirm-dates@example.com")
with client.session_transaction() as sess:
    sess["member_id"] = member_id

pending_state = {
    "reset_pending": True,
    "reset_change_request": "חופשה חדשה לגמרי לאיטליה, 10 עד 17 באפריל, שלושה מבוגרים",
}

with patch.object(chat, "_post_claude", side_effect=_fake_post_claude):
    r = client.post("/api/ariella/chat-clean", json={
        "message": "כן", "history": [{"role": "assistant", "content": "למחוק את כל הפרטים ולהתחיל חופשה חדשה מאפס?"}],
        "trip_state": dict(pending_state),
    })
data = r.get_json()
update = data.get("trip_update") or {}

check("destination (Italy) survives the reset confirmation",
      "איטליה" in ((update.get("destination") or {}).get("places") or []))
check("dates (10-17 April) survive the reset confirmation",
      (update.get("dates") or {}).get("departure") == "2027-04-10" and (update.get("dates") or {}).get("return") == "2027-04-17")
check("travelers (three adults) survive the reset confirmation",
      (update.get("travelers") or {}).get("adults") == 3)
check("the reply never re-asks for a travel period the customer already gave",
      "באיזו תקופה" not in str(data.get("reply") or "") or bool((update.get("dates") or {}).get("departure")))

# --- Regression guard: a ski-specific scenario (C2, round 2) with
#     destination + trip_type only (no dates/travelers stated) must still
#     work exactly as before ---
pending_ski_state = {
    "reset_pending": True,
    "reset_change_request": "אני רוצה לפתוח חופשה חדשה ונפרדת: חופשת סקי בזאלבאך שבאוסטריה, עם טיסה ולינה",
}
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude):
    r2 = client.post("/api/ariella/chat-clean", json={
        "message": "כן", "history": [{"role": "assistant", "content": "למחוק את כל הפרטים ולהתחיל חופשה חדשה מאפס?"}],
        "trip_state": dict(pending_ski_state),
    })
data2 = r2.get_json()
update2 = data2.get("trip_update") or {}
check("regression guard: the specific resort (זלבאך) still survives",
      "זלבאך" in ((update2.get("destination") or {}).get("places") or []))
check("regression guard: trip_type (ski) still survives",
      update2.get("trip_type") == "ski")

with sqlite3.connect(DB) as conn:
    conn.execute("DELETE FROM members WHERE id=?", (member_id,))
    conn.commit()

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL RESET-CONFIRMATION-PRESERVES-DATES-AND-TRAVELERS TESTS PASSED")
