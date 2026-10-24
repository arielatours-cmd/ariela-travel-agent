"""QA for Shaked/Shlomo's 5j finding J6 (23.10.2026, qa/reports/2026-10-23-
dryrun5j.md): after "בעצם נעדיף פראג במקום וינה" (actually let's go with
Prague instead of Vienna), Ariella asked "should I delete the route/
lodging/car details that depend on the destination and rebuild them?"
even though the trip had none of those yet - a question about destroying
and rebuilding something that was never built. Per the business owner's
instruction (relayed by Shlomo): only ask this when something
destination-dependent genuinely exists; if there isn't, save and continue
silently.

Fixed: _destination_dependent_details_exist (ariella_chat_clean.py) checks
whether trip_planning.details.route/a real lodging or car detail already
exists; when none do, the destination-change gate applies the change
immediately via the shared _apply_destination_change helper instead of
asking. The genuine case (something real to lose) is unaffected - same
question, same mechanism as before.

UPDATED (23.10.2026, Shaked's static review of 0dc89e77, SHA she rejected):
the first version of this fix also counted destination_airports/return_
departure_airports as "dependent details" - but the REAL live J6 scenario
(qa/reports/2026-10-23-review-0dc89e7.md) has EXACTLY destination_airports
=['VIE'] with nothing else, since the OLD destination (Vienna) obviously
already has its own derived gateway code the moment it was settled at
all - that is not independent destination-dependent PROGRESS, just the
destination fact itself, which _apply_destination_change already clears
and replaces unconditionally either way. Counting it wrongly kept the
original bug alive for the exact case this fix exists for. The fixture
below now matches that real scenario precisely instead of an artificially
"nothing at all" state the live bug never actually looked like.

UPDATED AGAIN (23.10.2026, Shaked's static review of 892d10ad, SHA she
also rejected): _apply_destination_change clears destination_airports,
and this fast path never goes through a model call to re-resolve it -
_flight_gap_question then asked "which airport would you like to land
at?" even for Prague, a destination with exactly one real catalog
airport. Fixed by running the SAME deterministic catalog resolvers the
main pipeline always runs (_resolve_destination_airports_from_route,
_resolve_ski_destination_airports) on `changed` before computing the
next question - safe here specifically because the destination name
already passed a deterministic exact/near-exact catalog match earlier
in this same turn (known_destinations), unlike a raw, possibly-ambiguous
customer typo elsewhere in the file.

Run: python3 tools/qa_dryrun5j_j6_destination_change_no_dependent_details.py
"""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")
os.environ.setdefault("SCHEDULER_ENABLED", "false")

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
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        FAILED.append(name)


def _fake_post_claude(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other", **kw):
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
            ("QA J6 Destination Change", email, generate_password_hash("Test1234!"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
        )
        return cur.lastrowid


member_id = _make_member("qa-j6-destination-change@example.com")
with client.session_transaction() as sess:
    sess["member_id"] = member_id

REBUILD_QUESTION_SNIPPET = "למחוק את הפרטים שתלויים ביעד"

# =====================================================================
# J6 FIX: the ACTUAL real-world scenario (Shaked's own review, SHA
# 0dc89e77) - destination_airports already set (['VIE'], the settled
# Vienna trip's own gateway) but no route/lodging/car details at all ->
# change applies silently, no question. destination_airports alone must
# NEVER count as "dependent details" here - see _destination_dependent_
# details_exist's own docstring.
# =====================================================================
EMPTY_VIENNA_STATE = {
    "destination": {"places": ["וינה"], "mode": "specific", "status": "known"},
    "destination_airports": ["VIE"],
    "requested_services": ["flights"],
    "dates": {"departure": "2026-12-01", "return": "2026-12-05"},
    "travelers": {"adults": 2, "children": 0, "child_ages": []},
    "departure_airport": "TLV",
    "lodging": {"interested": "unknown", "details": {}},
    "car": {"interested": "unknown", "details": {}},
    "trip_planning": {"interested": "unknown", "details": {}},
}

with patch.object(chat, "_post_claude", side_effect=_fake_post_claude):
    r = client.post("/api/ariella/chat-clean", json={
        "message": "בעצם נעדיף פראג במקום וינה",
        "history": [],
        "trip_state": dict(EMPTY_VIENNA_STATE),
    })
data = r.get_json()
reply = str(data.get("reply") or "")
update = data.get("trip_update") or {}

check("J6 FIX: no dependent details -> the rebuild question is NOT asked",
      REBUILD_QUESTION_SNIPPET not in reply)
check("J6 FIX (Shaked's review of 0dc89e77): the reply has genuine forward "
      "motion - never a dead-end 'let's continue from here' with no actual "
      "next question", "נמשיך מכאן." not in reply and len(reply.strip()) > 0)
check("J6 FIX: the destination is updated to Prague immediately, with no "
      "pending confirmation gate left open",
      "פראג" in ((update.get("destination") or {}).get("places") or [])
      and not update.get("destination_change_pending"))
check("J6 FIX (Shaked's SECOND review, of 892d10ad): the new destination's "
      "own catalog airport is re-resolved deterministically (PRG for Prague) "
      "instead of leaving destination_airports empty",
      update.get("destination_airports") == ["PRG"])
check("J6 FIX (Shaked's SECOND review): since Prague has exactly one real "
      "catalog airport, the needless 'which airport would you like to land "
      "at?' question is never asked - the gateway is already resolved",
      "באיזה שדה" not in reply)

# =====================================================================
# Regression: a REAL destination-dependent detail already exists (route) -
# the rebuild question must still be asked exactly as before.
# =====================================================================
VIENNA_WITH_ROUTE_STATE = {
    "destination": {"places": ["וינה"], "mode": "specific", "status": "known"},
    "destination_airports": ["VIE"],
    "trip_planning": {"interested": "yes", "details": {"route": [{"day": 1, "base": "וינה"}]}},
    "lodging": {"interested": "unknown", "details": {}},
    "car": {"interested": "unknown", "details": {}},
}

with patch.object(chat, "_post_claude", side_effect=_fake_post_claude):
    r2 = client.post("/api/ariella/chat-clean", json={
        "message": "בעצם נעדיף פראג במקום וינה",
        "history": [],
        "trip_state": dict(VIENNA_WITH_ROUTE_STATE),
    })
data2 = r2.get_json()
reply2 = str(data2.get("reply") or "")
update2 = data2.get("trip_update") or {}

check("regression: a real route already exists -> the rebuild question is "
      "still asked, unchanged", REBUILD_QUESTION_SNIPPET in reply2)
check("regression: destination is NOT changed yet - still pending the "
      "customer's yes/no", update2.get("destination_change_pending") == "פראג")

with sqlite3.connect(DB) as conn:
    conn.execute("DELETE FROM members WHERE id=?", (member_id,))
    conn.commit()

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL DRYRUN5J-J6-DESTINATION-CHANGE-NO-DEPENDENT-DETAILS TESTS PASSED")
