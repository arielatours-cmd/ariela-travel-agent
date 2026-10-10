"""QA for task 001a - booking-credit detection (CJ) + congrats/how-was-it.

Mocks requests.post for the CJ GraphQL call. Run:
python3 tools/qa_booking_lifecycle_cj.py
"""
import sys
import os
import sqlite3
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")
os.environ["CJ_COMMISSIONS_SYNC_ENABLED"] = "true"
os.environ["CJ_API_TOKEN"] = "qa-test-token"
os.environ["CJ_PUBLISHER_ID"] = "qa-test-cid"

from werkzeug.security import generate_password_hash

import config
import importlib
importlib.reload(config)
import database
database.init_db()
import partner_commissions
importlib.reload(partner_commissions)
import trip_lifecycle_messages as tlm
import nova_conversation as nc

FAILED = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


def make_member(email, phone):
    with sqlite3.connect(database.DB_PATH) as conn:
        conn.execute("DELETE FROM members WHERE email=?", (email,))
        conn.commit()
        pw = generate_password_hash("Test1234!")
        cur = conn.execute(
            "INSERT INTO members (full_name,email,phone,password_hash,created_at,status,whatsapp_opt_in,preferred_airports) "
            "VALUES(?,?,?,?,datetime('now'),'active',0,'[]')",
            ("QA CJ", email, phone, pw),
        )
        conn.commit()
        return int(cur.lastrowid)


def make_trip(member_id, answers=None, departure_date=None, return_date=None):
    a = dict(answers or {})
    if departure_date:
        a["departure_date"] = departure_date
    if return_date:
        a["return_date"] = return_date
    with sqlite3.connect(database.DB_PATH) as conn:
        cur = conn.execute(
            "INSERT INTO trip_requests (member_id, request_name, status, answers_json, created_at) "
            "VALUES (?,?,?,?,datetime('now'))",
            (member_id, "רומא QA", "active", json.dumps(a, ensure_ascii=False)),
        )
        conn.commit()
        return int(cur.lastrowid)


def fake_cj_response(records):
    class R:
        ok = True
        status_code = 200
        def json(self):
            return {"data": {"publisherCommissions": {"count": len(records), "records": records}}}
    return R()


# --- 1. No CJ_API_TOKEN -> disabled, no network call ---
with patch.dict(os.environ, {"CJ_API_TOKEN": "", "CJ_PUBLISHER_ID": "", "CJ_COMMISSIONS_SYNC_ENABLED": "false"}):
    importlib.reload(config)
    importlib.reload(partner_commissions)
    with patch("requests.post") as mock_post:
        result = partner_commissions.sync_cj_commissions()
        check("disabled without credentials", result == {"status": "disabled"})
        check("no network call made when disabled", not mock_post.called)
importlib.reload(config)
importlib.reload(partner_commissions)

# --- 2. Mock CJ response with shopperId='trip{id}' -> trip booked + congrats queued ---
member_id = make_member("qa-cj-booking@example.com", "+972500000301")
trip_id = make_trip(member_id, departure_date=(datetime.now(timezone.utc) + timedelta(days=10)).date().isoformat(),
                     return_date=(datetime.now(timezone.utc) + timedelta(days=17)).date().isoformat())
records = [{
    "commissionId": "qa-comm-1", "sid": f"trip{trip_id}", "actionStatus": "NEW",
    "advertiserName": "Booking.com", "eventDate": "2026-10-01", "postingDate": "2026-10-02",
    "saleAmountPubCurrency": 500.0, "pubCommissionAmountPubCurrency": 25.0, "pubCurrency": "ILS",
}]
with patch("requests.post", return_value=fake_cj_response(records)):
    sync_result = partner_commissions.sync_cj_commissions()
check("sync reports trip confirmed", trip_id in sync_result.get("trips_confirmed", []))
with sqlite3.connect(database.DB_PATH) as conn:
    conn.row_factory = sqlite3.Row
    trip_row = conn.execute("SELECT booked_confirmed_at, booked_source, congrats_queued_at FROM trip_requests WHERE id=?", (trip_id,)).fetchone()
    commission_row = conn.execute("SELECT trip_id FROM partner_commissions WHERE commission_id='qa-comm-1'").fetchone()
    congrats_row = conn.execute("SELECT * FROM whatsapp_outbound_queue WHERE ref_id=? AND kind='booking_congrats'", (trip_id,)).fetchone()
check("trip_id=42-style sid resolved correctly", commission_row["trip_id"] == trip_id)
check("booked_confirmed_at set", bool(trip_row["booked_confirmed_at"]))
check("booked_source='cj_commission'", trip_row["booked_source"] == "cj_commission")
check("congrats message queued", congrats_row is not None)
check("congrats message mentions days until departure", "בעוד" in congrats_row["body"])

# --- 3. Same commission synced twice / two commissions (hotel+car) for same trip -> ONE congrats only ---
with patch("requests.post", return_value=fake_cj_response(records)):
    partner_commissions.sync_cj_commissions()  # same commission again
records2 = [dict(records[0], commissionId="qa-comm-2", advertiserName="RentalCars")]
with patch("requests.post", return_value=fake_cj_response(records2)):
    partner_commissions.sync_cj_commissions()  # second, different commission, same trip
with sqlite3.connect(database.DB_PATH) as conn:
    congrats_count = conn.execute("SELECT COUNT(*) FROM whatsapp_outbound_queue WHERE ref_id=? AND kind='booking_congrats'", (trip_id,)).fetchone()[0]
check("exactly one congrats message despite repeat + second commission", congrats_count == 1)

# --- 4. sid not ours -> stored with trip_id=NULL, no message ---
foreign_records = [{
    "commissionId": "qa-comm-foreign", "sid": "someoneelse-123", "actionStatus": "NEW",
    "advertiserName": "Booking.com", "eventDate": "2026-10-01", "postingDate": "2026-10-02",
    "saleAmountPubCurrency": 100.0, "pubCommissionAmountPubCurrency": 5.0, "pubCurrency": "ILS",
}]
with patch("requests.post", return_value=fake_cj_response(foreign_records)):
    partner_commissions.sync_cj_commissions()
with sqlite3.connect(database.DB_PATH) as conn:
    conn.row_factory = sqlite3.Row
    foreign_row = conn.execute("SELECT trip_id FROM partner_commissions WHERE commission_id='qa-comm-foreign'").fetchone()
check("unrecognized sid stored with trip_id=NULL", foreign_row is not None and foreign_row["trip_id"] is None)

# --- 5. Cancelled commission with no other valid commission -> booking_cancelled_at set, no how-was-it later ---
member_id2 = make_member("qa-cj-cancel@example.com", "+972500000302")
trip_id2 = make_trip(member_id2, departure_date="2026-11-01", return_date="2026-11-08")
cancel_records = [{
    "commissionId": "qa-comm-cancel", "sid": f"trip{trip_id2}", "actionStatus": "cancelled",
    "advertiserName": "Booking.com", "eventDate": "2026-10-01", "postingDate": "2026-10-02",
    "saleAmountPubCurrency": 0, "pubCommissionAmountPubCurrency": 0, "pubCurrency": "ILS",
}]
with patch("requests.post", return_value=fake_cj_response(cancel_records)):
    partner_commissions.sync_cj_commissions()
with sqlite3.connect(database.DB_PATH) as conn:
    conn.row_factory = sqlite3.Row
    cancelled_row = conn.execute("SELECT booking_cancelled_at, booked_confirmed_at FROM trip_requests WHERE id=?", (trip_id2,)).fetchone()
check("cancelled-only commission sets booking_cancelled_at", bool(cancelled_row["booking_cancelled_at"]))
check("cancelled-only commission never sets booked_confirmed_at", not cancelled_row["booked_confirmed_at"])

# --- 6. how_was_it: trip booked, return_date 2 days ago -> queued; 1 day ago -> not yet; 40 days ago -> not at all ---
member_id3 = make_member("qa-howwasit@example.com", "+972500000303")
today = datetime.now(timezone.utc).date()
trip_ready = make_trip(member_id3, return_date=(today - timedelta(days=2)).isoformat())
trip_too_soon = make_trip(member_id3, return_date=(today - timedelta(days=1)).isoformat())
trip_too_late = make_trip(member_id3, return_date=(today - timedelta(days=40)).isoformat())
with sqlite3.connect(database.DB_PATH) as conn:
    for tid in (trip_ready, trip_too_soon, trip_too_late):
        conn.execute("UPDATE trip_requests SET booked_confirmed_at=? WHERE id=?", (database.utc_now_iso(), tid))
    conn.commit()
hw_result = tlm.queue_how_was_it_messages()
check("trip 2 days post-return is queued", trip_ready in hw_result["queued"])
check("trip 1 day post-return is NOT queued yet", trip_too_soon not in hw_result["queued"])
check("trip 40 days post-return is NOT queued (too late)", trip_too_late not in hw_result["queued"])
with sqlite3.connect(database.DB_PATH) as conn:
    conn.row_factory = sqlite3.Row
    hw_queue_row = conn.execute("SELECT * FROM whatsapp_outbound_queue WHERE ref_id=? AND kind='how_was_it'", (trip_ready,)).fetchone()
check("how_was_it message has 3 rating buttons", hw_queue_row is not None and len(json.loads(hw_queue_row["buttons_json"])) == 3)
check("how_was_it buttons use the HOW_WAS_IT:trip:rating payload format", f"HOW_WAS_IT:{trip_ready}:3" in hw_queue_row["buttons_json"])

# --- 7. route_inbound(phone, '', button_payload='HOW_WAS_IT:trip:3') from the trip's own customer ---
database.set_whatsapp_deals_opt(member_id3, True, "site")  # ensures a members row state is sane; not required for linking
with sqlite3.connect(database.DB_PATH) as conn:
    import hashlib
    phone_hash = hashlib.sha256(nc.canonical_phone("+972500000303").encode()).hexdigest()
    conn.execute(
        "INSERT INTO whatsapp_member_links (member_id, wa_phone_hash, verified_at, status, created_at, updated_at) "
        "VALUES (?,?,datetime('now'),'active',datetime('now'),datetime('now'))",
        (member_id3, phone_hash),
    )
    conn.commit()
reply = nc.route_inbound("+972500000303", "", button_payload=f"HOW_WAS_IT:{trip_ready}:3")
check("rating 3 gets the 'מעולה' reply", "איזה כיף לשמוע" in reply)
with sqlite3.connect(database.DB_PATH) as conn:
    conn.row_factory = sqlite3.Row
    feedback_row = conn.execute("SELECT rating, source FROM trip_feedback WHERE trip_id=? AND member_id=?", (trip_ready, member_id3)).fetchone()
check("feedback row saved with rating=3, source=whatsapp_button", feedback_row is not None and feedback_row["rating"] == 3 and feedback_row["source"] == "whatsapp_button")

# --- 8. A free-text reply right after -> saved as the comment ---
reply2 = nc.route_inbound("+972500000303", "המלצת המסעדות הייתה מעולה!", button_payload=None)
check("follow-up comment gets the thank-you reply", "תודה, רשמתי" in reply2)
with sqlite3.connect(database.DB_PATH) as conn:
    conn.row_factory = sqlite3.Row
    commented_row = conn.execute("SELECT comment FROM trip_feedback WHERE trip_id=? AND member_id=?", (trip_ready, member_id3)).fetchone()
check("comment text saved on the feedback row", commented_row["comment"] == "המלצת המסעדות הייתה מעולה!")

# --- 9. HOW_WAS_IT from a DIFFERENT member's trip -> ignored (falls through to normal routing) ---
other_member = make_member("qa-howwasit-other@example.com", "+972500000304")
with sqlite3.connect(database.DB_PATH) as conn:
    other_hash = hashlib.sha256(nc.canonical_phone("+972500000304").encode()).hexdigest()
    conn.execute(
        "INSERT INTO whatsapp_member_links (member_id, wa_phone_hash, verified_at, status, created_at, updated_at) "
        "VALUES (?,?,datetime('now'),'active',datetime('now'),datetime('now'))",
        (other_member, other_hash),
    )
    conn.commit()
reply3 = nc.route_inbound("+972500000304", "", button_payload=f"HOW_WAS_IT:{trip_ready}:3")
check("a rating for someone else's trip is ignored (normal menu reply instead)", "איזה כיף לשמוע" not in reply3)

print()
if FAILED:
    print(f"FAILED ({len(FAILED)}): {FAILED}")
    sys.exit(1)
print("ALL CHECKS PASSED")
