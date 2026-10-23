"""QA for a bug Shaked found while LIVE-VERIFYING PR #48 (qa-s97, on
90f39b5, 2026-10-16): right after approving a London flight (trip 257),
"היי, רוצה לתכנן חופשה בסיציליה" returned BOTH trip_state_reset=True AND
start_flight_search=True in the same response, with destination=None - a
real flight search launched with absolutely no criteria (no destination,
no dates), and no "מאשרת" from the customer at all.

Root cause: at the time this was written, Sicily wasn't recognized as a
destination on main yet, so this reproduced with ANY unrecognized/
ambiguous message, Sicily included. PR #47 has since merged Sicily (and
other islands/regions) into the recognized catalog - the original message
now takes the OTHER branch of this same guard (a genuinely-recognized new
destination), not the ambiguous one this file tests, so the message below
was changed to one that still names no destination at all ("לתכנן חופשה"
with nothing further), keeping this file testing the ambiguous/
unrecognized branch it was written for regardless of the catalog's
contents. When the combined_search_launched guard's
_deterministic_destination_facts check (PR #48) can't find a genuinely
different destination in the message, it falls to the "ambiguous" branch,
which used to pop ONLY combined_search_launched - leaving search_confirmed
still True from the OLD, already-launched trip.
The very next computation in this same function, start_flight_search =
bool(trip_update.get('search_confirmed')) and all-domains-resolved and
not combined_search_launched, then read True immediately: search_confirmed
was still true, the old trip's domains were still all resolved, and
combined_search_launched had just been popped - three stale conditions
lining up into a phantom launch, firing in the exact same response as the
(separate, legitimate) trip_fully_resolved auto-cleanup that also fires
for a finished trip's very next ambiguous message.

Fixed: the ambiguous branch now also clears search_confirmed (not just
combined_search_launched). post_flight_continuation is deliberately left
alone - it's what lets the already-tested trip_fully_resolved auto-cleanup
further below still recognize this as a finished trip and wipe it to a
proper clean slate instead of leaving it in limbo.

Run: python3 tools/qa_combined_search_launched_ambiguous_no_phantom_search.py
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


def _make_member(email):
    with sqlite3.connect(DB) as conn:
        conn.execute("DELETE FROM members WHERE email=?", (email,))
        conn.commit()
        cur = conn.execute(
            "INSERT INTO members (full_name,email,password_hash,created_at,status,whatsapp_opt_in,preferred_airports) "
            "VALUES(?,?,?,?,?,?,?)",
            ("QA No Phantom Search", email, generate_password_hash("Test1234!"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
        )
        return cur.lastrowid


def _finished_trip_state(destination):
    return {
        "destination": {"places": [destination], "mode": "specific", "status": "known"},
        "search_confirmed": True,
        "post_flight_continuation": True,
        "combined_search_launched": True,
        "session_status": {"flights": "complete", "lodging": "declined", "car": "declined", "trip_planning": "declined"},
    }


def _fake_extractor_nothing(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        return json.dumps({"trip_update": {}})
    return "נעים להכיר! בחירה נהדרת..."


member_id = _make_member("qa-no-phantom-search@example.com")
with client.session_transaction() as sess:
    sess["member_id"] = member_id

# --- 1. Shaked's exact live scenario: an unrecognized/ambiguous new
#     destination right after a finished, fully-launched London trip must
#     never launch a phantom flight search with no real criteria ---
with patch.object(chat, "_post_claude", side_effect=_fake_extractor_nothing):
    r = client.post("/api/ariella/chat-clean", json={
        "message": "היי, רוצה לתכנן חופשה", "history": [],
        "trip_state": _finished_trip_state("לונדון"),
    })
data = r.get_json()
check("no phantom flight search launches with no real destination/dates",
      data.get("start_flight_search") is not True)
check("the old, finished trip still gets properly cleaned up (the separate, legitimate auto-cleanup)",
      data.get("trip_state_reset") is True)

# --- 2. Regression guard: a message that genuinely continues the SAME
#     trip (mentions its own destination again, no different place) must
#     be recognized as such - _same_trip_again's own building block must
#     stay True, so this fix's branches never even run for it. (The full
#     HTTP round trip isn't checked here: a truly finished trip's very
#     next message - continuing or not - still correctly triggers the
#     separate, legitimate trip_fully_resolved auto-cleanup regardless,
#     same as case 1 above; that's by design, not this fix's concern.) ---
check("re-mentioning the same destination is never read as naming a different one",
      not chat._mentions_a_different_place("מה קורה עם לונדון?", ["לונדון"]))

with sqlite3.connect(DB) as conn:
    conn.execute("DELETE FROM members WHERE id=?", (member_id,))
    conn.commit()

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL COMBINED-SEARCH-LAUNCHED AMBIGUOUS NO-PHANTOM-SEARCH TESTS PASSED")
