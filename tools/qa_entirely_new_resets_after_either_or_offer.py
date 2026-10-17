"""QA for A5 (Shaked, qa-s92, round 3, 2026-10-15): right after a committed
Budapest vacation, the customer wrote "היי, רוצה לתכנן חופשה בסיציליה".
Ariella herself asked the open either/or question "להמשיך עם בודפשט או
תכנון חדש לגמרי?" - and the customer answered "תכנון חדש לגמרי לסיציליה"
(entirely new planning for Sicily), an unambiguous answer to Ariella's own
question. No reset fired: trip_update kept destination_airports=['BUD'],
Budapest's lodging (hotel, budget=4, "ליד הדנובה"), car=declined, and
initially even the Budapest traveler count.

Shaked's own diagnosis, echoing the business owner's standing instruction
to classify by meaning rather than word lists: _NEW_AND_SEPARATE_RE
requires "חדש" AND "נפרד" together, and the fixed phrase list only has the
one specific "חיפוש חדש לגמרי" - neither matches "תכנון חדש לגמרי" at all,
even though it answers Ariella's own just-asked question.

Fixed with _ENTIRELY_NEW_RE: "חדש" and "לגמרי" (entirely) found near each
other, in either order - not tied to whichever noun happens to follow
("תכנון", "חיפוש", "מסלול"...), the same "collect the standalone
compound phrase regardless of what's around it" pattern already used by
_NEW_AND_SEPARATE_RE for "new and separate".

Run: python3 tools/qa_entirely_new_resets_after_either_or_offer.py
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
check("'תכנון חדש לגמרי לסיציליה' is recognized as an entirely-new declaration",
      bool(chat._ENTIRELY_NEW_RE.search("תכנון חדש לגמרי לסיציליה")))
check("a message merely mentioning a 'new room' is never a false positive",
      not chat._ENTIRELY_NEW_RE.search("אני רוצה חדר חדש בבקשה"))

# --- 2. End to end: a committed Budapest trip + "תכנון חדש לגמרי לסיציליה"
#        must hard-reset, dropping the old destination/lodging/car entirely ---
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
            ("QA Entirely New", email, generate_password_hash("Test1234!"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
        )
        return cur.lastrowid


member_id = _make_member("qa-entirely-new@example.com")
with client.session_transaction() as sess:
    sess["member_id"] = member_id

budapest_state = {
    "trip_type": "standard",
    "destination": {"places": ["בודפשט"], "mode": "specific", "status": "known"},
    "destination_airports": ["BUD"],
    "active_session": None,
    "search_confirmed": True,
    "post_flight_continuation": True,
    "requested_services": ["flights", "lodging"],
    "session_status": {"flights": "complete", "lodging": "complete", "car": "declined", "trip_planning": "declined"},
    "lodging": {"interested": "yes", "details": {"type": "hotel", "budget_or_level": 4, "locations": ["ליד הדנובה"]}},
    "service_decisions": {
        "flights": {"wanted": True, "source": "explicit_request"},
        "lodging": {"wanted": True, "source": "explicit_request"},
        "car": {"wanted": False, "source": "explicit_decline"},
    },
    "travelers": {"adults": 2, "children": 0, "child_ages": []},
}

with patch.object(chat, "_post_claude", side_effect=_fake_post_claude):
    r = client.post("/api/ariella/chat-clean", json={
        # "סיציליה" (Sicily) itself - the real live destination Shaked saw -
        # isn't in the general destination catalog at all (a separate,
        # pre-existing, lower-priority gap unrelated to this fix; see
        # "זלבאך"/ski-resort-style catalog gaps elsewhere). Using a
        # catalog-known destination here isolates exactly what this fix
        # covers: that the reset fires and the OLD trip's facts are
        # dropped, regardless of whether the NEW destination name itself
        # is independently recognized.
        "message": "תכנון חדש לגמרי ליוון",
        "history": [{"role": "assistant", "content": "להמשיך עם בודפשט או תכנון חדש לגמרי?"}],
        "trip_state": dict(budapest_state),
    })
data = r.get_json()
trip_update = data.get("trip_update") or {}
reply = str(data.get("reply") or "")

check("the old Budapest airport code never survives into the new request",
      "BUD" not in (trip_update.get("destination_airports") or []))
check("the old Budapest destination never survives",
      "בודפשט" not in ((trip_update.get("destination") or {}).get("places") or []))
check("Greece is captured as the new destination",
      "יוון" in ((trip_update.get("destination") or {}).get("places") or []))
check("the old Budapest lodging details never survive (fresh lodging state)",
      (trip_update.get("lodging") or {}).get("details") in (None, {}) or not (trip_update.get("lodging") or {}).get("details", {}).get("locations"))
check("car's old explicit decline never survives as leftover state",
      (trip_update.get("service_decisions") or {}).get("car", {}).get("source") != "explicit_decline")
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
print("\nALL ENTIRELY-NEW-RESETS-AFTER-EITHER-OR-OFFER TESTS PASSED")
