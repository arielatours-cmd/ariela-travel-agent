"""QA for C2 (Shaked, qa-s91, round 2, 2026-10-15) - the generic restart
gate (_reset_intent, triggered by phrases like "חופשה חדשה") lost facts the
SAME triggering message already stated, even though the sibling
new_vacation_language path (used when an OLD trip is already committed)
already preserves them. Live transcript:

  "אני רוצה לפתוח חופשה חדשה ונפרדת: חופשת סקי בזאלבאך שבאוסטריה, עם טיסה
  ולינה" -> "למחוק את כל הפרטים ולהתחיל חופשה חדשה מאפס?" -> "כן" ->
  "מתחילים חופשה חדשה לאוסטריה... זה נסיעת עסקים, חופשה רגילה או סקי?"

Two compounding bugs, both in the same reset-confirmation branch:
1. It never re-extracted trip_type from the original triggering message
   (reset_change_request) the way it already did for destination - so
   "חופשת סקי" had to be repeated right after already being stated.
2. The destination extractor itself picked "אוסטריה" (the country) over
   "זאלבאך" (the specific resort) because a pure string-length sort
   checked the longer "אוסטריה" needle first when both appeared in the
   same sentence - and once destination.places is set it is never
   re-extracted, so the specific resort was permanently lost for the rest
   of the conversation (feeding wrong lodging-search defaults downstream).
   A related, narrower gap: the catalog's resort_he for Saalbach is
   "זלבאך", but the customer's natural spelling "זאלבאך" matched neither
   it nor the catalog's English name at all.

Fixed: (a) _known_destination_names() now sorts city/resort-level entries
before country-level ones, so a specific place always wins when both
appear together; (b) added the "זאלבאך"->"זלבאך" spelling alias; (c) the
reset-confirmation branch now also merges _deterministic_trip_type_facts
from the original triggering message, mirroring what it already did for
destination.

Run: python3 tools/qa_reset_gate_preserves_trip_type_and_specific_resort.py
"""
import os
import sys
import json
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


MESSAGE = "אני רוצה לפתוח חופשה חדשה ונפרדת: חופשת סקי בזאלבאך שבאוסטריה, עם טיסה ולינה"

# --- 1. Unit: destination extraction prefers the specific resort over the
#        country when both are named in the same sentence ---
check("the specific resort (זלבאך) is extracted, not just the country",
      chat._deterministic_destination_facts([], MESSAGE, {}).get("destination", {}).get("places") == ["זלבאך"])
check("trip_type (ski) is extracted from the same message",
      chat._deterministic_trip_type_facts(MESSAGE).get("trip_type") == "ski")

# --- 2. End to end: the reset-confirmation flow preserves both ---
# Per Shlomo's follow-up (18.10, task/resume-live-reset-and-one-question):
# the reset-confirmation gate no longer has a phrase-list short-circuit at
# all. A further PR #85 review (Shaked, 18.10) then moved the restart
# signal itself out of a dedicated classifier call and into the SAME
# state_extractor call that already runs every turn (restart_request/
# restart_evidence, siblings of trip_update in EXTRACTOR_SYSTEM's JSON -
# see _parse_restart_signal), to avoid doubling the model calls per turn.
# This fake must answer that call like the real model would for MESSAGE's
# explicit "חופשה חדשה ונפרדת" ("new and separate vacation") wording.
def _fake_post_claude(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        text = str(message or "").split("תשובת הלקוח:", 1)[-1].strip()
        for phrase in ("טיול חדש", "חופשה חדשה", "טיול אחר", "חדש ונפרד"):
            if phrase in text:
                return json.dumps({"trip_update": {}, "restart_request": True, "restart_evidence": phrase})
        return "{}"
    return "תשובה לדוגמה."


def _make_member(email):
    with sqlite3.connect(DB) as conn:
        conn.execute("DELETE FROM members WHERE email=?", (email,))
        conn.commit()
        cur = conn.execute(
            "INSERT INTO members (full_name,email,password_hash,created_at,status,whatsapp_opt_in,preferred_airports) "
            "VALUES(?,?,?,?,?,?,?)",
            ("QA Reset Trip Type", email, generate_password_hash("Test1234!"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
        )
        return cur.lastrowid


member_id = _make_member("qa-reset-trip-type@example.com")
with client.session_transaction() as sess:
    sess["member_id"] = member_id

with patch.object(chat, "_post_claude", side_effect=_fake_post_claude):
    r1 = client.post("/api/ariella/chat-clean", json={
        "message": MESSAGE, "history": [], "trip_state": {},
    })
data1 = r1.get_json()
trip_update1 = data1.get("trip_update") or {}
check("the reset gate fires (asks to confirm before clearing anything)",
      bool(trip_update1.get("reset_pending")))

with patch.object(chat, "_post_claude", side_effect=_fake_post_claude):
    r2 = client.post("/api/ariella/chat-clean", json={
        "message": "כן", "history": [{"role": "assistant", "content": data1.get("reply") or ""}],
        "trip_state": trip_update1,
    })
data2 = r2.get_json()
trip_update2 = data2.get("trip_update") or {}
reply2 = str(data2.get("reply") or "")

check("trip_type (ski) survives the reset confirmation, never re-asked",
      trip_update2.get("trip_type") == "ski")
check("the specific resort survives the reset confirmation",
      "זלבאך" in ((trip_update2.get("destination") or {}).get("places") or []))
check("the reply never asks 'regular vacation, business trip, or ski?' again",
      not any(p in reply2 for p in ("חופשה רגילה, נסיעת עסקים", "נסיעת עסקים, חופשה רגילה", "רגילה או חופשת סקי")))

with sqlite3.connect(DB) as conn:
    conn.execute("DELETE FROM members WHERE id=?", (member_id,))
    conn.commit()

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL RESET-GATE-PRESERVES-TRIP-TYPE-AND-SPECIFIC-RESORT TESTS PASSED")
