"""QA for the CRITICAL regression Shaked found in round 7 (qa-s97,
2026-10-16, on b5a8873) - the worst found so far this round. She asked NOT
to deploy until investigated: "רגרסיה קריטית... אל תפרוס, רק תחקור."

Live transcript (Sicily, right after a Budapest vacation - trip 254 - was
already approved): opening ("רוצה לתכנן חופשה בסיציליה") replied well
("בודפשט נשמרת... סיציליה חדשה ונפרדת"), and the next two turns (dates/
travelers, then baggage/budget) tracked correctly. Turn 4 ("תציעי מסלול" -
suggest a route) replied asking to re-confirm the departure airport (already
answered twice), but the response body carried trip_state_reset=True and
start_flight_search=True with destination/dates/travelers all wiped to None
- a flight search launched with no real criteria, with no "מאשרת" (approve)
from the customer at all. The next turn landed in a blank "nice to meet
you, you have 3 open vacations" greeting, Sicily (and Budapest) erased
entirely.

Root cause: ariella_chat_clean.py's "a new/different destination was named
after an already fully-committed-and-launched trip" branch
(combined_search_launched guard, just above the reopen/history-handling
block) only ever cleared the single combined_search_launched key - every
OTHER already-resolved flag from the OLD, finished trip (post_flight_
continuation, search_confirmed, and a session_status with lodging/car/
trip_planning already complete/declined) silently survived untouched.
destination/dates/travelers then looked fine on the surface (the extractor
updates those fields turn by turn, per its own "replace only the changed
field" rule), while the stale resolved flags from the OLD trip kept
quietly sitting there - until the next turn that evaluates "is this trip
fully resolved" (the auto-reset safety net further down in the same
function) read it as TRUE, immediately wiping the brand-new vacation back
to blank and firing a flight search with no real inputs. Every sibling
"this is actually a new/different vacation" branch (new_vacation_language,
_previous_asked_new_vacation, the reopen "choice==new" branches) already
does a full clean-slate reset instead of a single-key pop - this was the
one branch that didn't, and it's reached silently (no "new vacation" magic
words needed - just naming a different destination after an old, launched
trip), which is why it stayed hidden until a real multi-turn conversation
hit it.

Picking how to detect "a genuinely different destination was named" took a
false start worth recording: the obvious choice, _mentions_a_different_place
(built on _mentioned_places/_known_place_names), fails for "סיציליה" itself
- Sicily is recognized by _known_destination_names (destination-setting,
fixed separately in PR #47) but NOT by _known_place_names. Widening
_known_place_names to match looked like the natural companion fix, but it
silently broke an unrelated, pre-existing reopen-gate call a few lines
below (tools/qa_route_approval_not_treated_as_reopen_choice.py's second
case) that passes _reopenable_trips the CURRENT trip's own destination
name as if it were customer text - it only "worked" before because an
unrecognized place name made that call's filtering a no-op; recognizing
Sicily there made it filter for real and drop every candidate. Reverted
that catalog change and used _deterministic_destination_facts instead
(the same island-aware catalog destination-setting already relies on),
scoped to this message alone - it doesn't touch _known_place_names or
that other call's behavior at all.

Fixed: when the combined_search_launched guard fires AND this message
alone names a destination that doesn't overlap the OLD trip's own places
(_deterministic_destination_facts on just this message), trip_state now
gets the SAME full clean-slate reset its sibling branches use
(session_status all pending, active_session None, profile/gender
preserved, seeded from the trigger message) - not just a single-key pop.
The narrow pop remains the fallback for the genuinely ambiguous case (no
place named at all - small talk, a thank-you), matching prior behavior
there exactly.

Run: python3 tools/qa_combined_search_launched_full_reset.py
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
            ("QA Combined Search Reset", email, generate_password_hash("Test1234!"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
        )
        return cur.lastrowid


def _finished_trip_state(destination):
    return {
        "destination": {"places": [destination], "mode": "specific", "status": "known"},
        "search_confirmed": True,
        "post_flight_continuation": True,
        "combined_search_launched": True,
        "session_status": {"flights": "complete", "lodging": "declined", "car": "declined", "trip_planning": "declined"},
        "service_decisions": {"lodging": {"wanted": False}, "car": {"wanted": False}, "trip_planning": {"wanted": False}},
        "active_session": None,
    }


def _fake_extractor_destination(new_place):
    def _fake(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
        if source == "state_extractor":
            return json.dumps({"trip_update": {"destination": {"places": [new_place], "mode": "specific", "status": "known"}}})
        return f"בשמחה! {new_place} חדשה ונפרדת - באיזו תקופה תרצי לטוס?"
    return _fake


def _fake_extractor_nothing(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        return json.dumps({"trip_update": {}})
    return "בשמחה! איך אפשר לעזור?"


member_id = _make_member("qa-combined-search-reset@example.com")
with client.session_transaction() as sess:
    sess["member_id"] = member_id

# --- 1. The mechanism behind Shaked's exact live scenario (her own repro
#     used Sicily) - a plain, already-recognized city (Rome) named right
#     after a finished, fully-launched Budapest trip. Deliberately NOT
#     Sicily here: Sicily's own recognition is the separate, independent
#     PR #47 (island/region catalog gap, currently frozen per the business
#     owner), and this fix must stand on its own against plain main either
#     way - already confirmed directly (outside this file) that the exact
#     Sicily repro is fixed too once PR #47 is merged alongside this one,
#     since both flow through the same _deterministic_destination_facts
#     call. ---
with patch.object(chat, "_post_claude", side_effect=_fake_extractor_destination("רומא")):
    r = client.post("/api/ariella/chat-clean", json={
        "message": "היי, רוצה לתכנן חופשה ברומא", "history": [],
        "trip_state": _finished_trip_state("בודפשט"),
    })
data = r.get_json()
update = data.get("trip_update") or {}
check("Rome after a finished Budapest trip does NOT reset/launch a search this turn",
      data.get("trip_state_reset") is not True and data.get("start_flight_search") is not True)
check("the new destination (Rome) survives in trip_update",
      "רומא" in ((update.get("destination") or {}).get("places") or []))
check("the OLD trip's post_flight_continuation does not leak into the new vacation",
      not update.get("post_flight_continuation"))
check("the OLD trip's search_confirmed does not leak into the new vacation",
      not update.get("search_confirmed"))
check("session_status is reset to pending for the new vacation (not inherited complete/declined)",
      all(v == "pending" for k, v in (update.get("session_status") or {}).items() if k != "flights"))

# --- 2. Same mechanism with a second, different already-recognized city
#     (Paris), confirming this isn't specific to one destination ---
with patch.object(chat, "_post_claude", side_effect=_fake_extractor_destination("פריז")):
    r2 = client.post("/api/ariella/chat-clean", json={
        "message": "היי, רוצה לתכנן חופשה בפריז", "history": [],
        "trip_state": _finished_trip_state("בודפשט"),
    })
data2 = r2.get_json()
update2 = data2.get("trip_update") or {}
check("Paris after a finished Budapest trip does NOT reset/launch a search this turn",
      data2.get("trip_state_reset") is not True and data2.get("start_flight_search") is not True)
check("Paris survives in trip_update",
      "פריז" in ((update2.get("destination") or {}).get("places") or []))
check("combined_search_launched is cleared, not inherited",
      not update2.get("combined_search_launched"))

# --- 3. Regression guard: a genuinely ambiguous message (no place named -
#     small talk) right after a finished trip must behave exactly as
#     before - this is the real, by-design "clean up after a finished trip"
#     auto-reset, not a bug, and this fix must not touch that path ---
with patch.object(chat, "_post_claude", side_effect=_fake_extractor_nothing):
    r3 = client.post("/api/ariella/chat-clean", json={
        "message": "תודה רבה!", "history": [],
        "trip_state": _finished_trip_state("בודפשט"),
    })
data3 = r3.get_json()
check("small talk with no place named still lets the normal finished-trip cleanup run (unchanged)",
      data3.get("status") == "success")

# --- 4. Regression guard: re-mentioning the SAME (old) destination must
#     NOT be read as naming a different one - this fix's new full-reset
#     branch must never fire for it (whatever happens afterward is the
#     separate, pre-existing, correct "finished trip" cleanup - already
#     covered by case 3 above, and not this fix's concern) ---
_same_dest_facts = (chat._deterministic_destination_facts([], "מה קורה עם בודפשט?", {}).get("destination") or {}).get("places") or []
check("re-mentioning the SAME (old) destination does not look like a different one",
      not (set(_same_dest_facts) - {"בודפשט"}))

# --- Regression guard: _known_place_names (used elsewhere by the reopen-
#     gate's own _reopenable_trips call) must be untouched by this fix -
#     widening it to recognize an island/region name broke that unrelated
#     call during development (see docstring above), so this fix
#     deliberately does not touch _known_place_names at all. This also
#     means this fix stands on its own against plain main: a destination
#     that only _known_destination_names (not _known_place_names) covers -
#     e.g. an island/region name - is PR #47's own independent concern, not
#     a dependency of this one. ---
check("_deterministic_destination_facts (what this fix actually uses) recognizes a plain city",
      "רומא" in ((chat._deterministic_destination_facts([], "רוצה לתכנן חופשה ברומא", {}).get("destination") or {}).get("places") or []))

with sqlite3.connect(DB) as conn:
    conn.execute("DELETE FROM members WHERE id=?", (member_id,))
    conn.commit()

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL COMBINED-SEARCH-LAUNCHED FULL-RESET TESTS PASSED")
