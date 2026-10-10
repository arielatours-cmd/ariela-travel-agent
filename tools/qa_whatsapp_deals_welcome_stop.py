"""QA for task 003a - WhatsApp deals welcome message + stop button.

Run: python3 tools/qa_whatsapp_deals_welcome_stop.py
"""
import sys
import os
import sqlite3

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

from werkzeug.security import generate_password_hash

import database
import nova_conversation as nc
import whatsapp_deals_messages as wdm
import formatter

database.init_db()
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
            ("QA WhatsApp", email, phone, pw),
        )
        conn.commit()
        return int(cur.lastrowid)


# --- 1. Simulated payment confirm -> opt_in=1, opt_in/payment row, welcome queued (preview) ---
member_id = make_member("qa-whatsapp-deals@example.com", "+972500000001")
changed = wdm.on_whatsapp_deals_paid(member_id)
check("on_whatsapp_deals_paid reports a real state change", changed is True)
with sqlite3.connect(database.DB_PATH) as conn:
    conn.row_factory = sqlite3.Row
    member_row = conn.execute("SELECT whatsapp_opt_in, whatsapp_opt_in_at, whatsapp_welcome_sent_at FROM members WHERE id=?", (member_id,)).fetchone()
    event_row = conn.execute("SELECT event, source FROM whatsapp_opt_events WHERE member_id=? ORDER BY id DESC LIMIT 1", (member_id,)).fetchone()
    queue_row = conn.execute("SELECT kind, status, buttons_json FROM whatsapp_outbound_queue WHERE member_id=? AND kind='welcome' ORDER BY id DESC LIMIT 1", (member_id,)).fetchone()
check("whatsapp_opt_in=1 after simulated payment", member_row["whatsapp_opt_in"] == 1)
check("opt_events row source='payment'", event_row["event"] == "opt_in" and event_row["source"] == "payment")
check("welcome message queued in preview status", queue_row is not None and queue_row["status"] == "preview")
check("welcome message has the stop button payload", "STOP_HOT_DEALS" in (queue_row["buttons_json"] or ""))
check("whatsapp_welcome_sent_at recorded", bool(member_row["whatsapp_welcome_sent_at"]))

# --- 2. Double confirmation of the SAME payment -> no duplicate welcome ---
with sqlite3.connect(database.DB_PATH) as conn:
    before_count = conn.execute("SELECT COUNT(*) FROM whatsapp_outbound_queue WHERE member_id=? AND kind='welcome'", (member_id,)).fetchone()[0]
changed2 = wdm.on_whatsapp_deals_paid(member_id)
with sqlite3.connect(database.DB_PATH) as conn:
    after_count = conn.execute("SELECT COUNT(*) FROM whatsapp_outbound_queue WHERE member_id=? AND kind='welcome'", (member_id,)).fetchone()[0]
check("double payment confirm doesn't flag another opt-in change", changed2 is False)
check("double payment confirm doesn't send a second welcome", after_count == before_count)

# --- Re-join after stop + new payment -> fresh welcome ---
database.set_whatsapp_deals_opt(member_id, False, "whatsapp_button")
changed3 = wdm.on_whatsapp_deals_paid(member_id)
with sqlite3.connect(database.DB_PATH) as conn:
    rejoin_count = conn.execute("SELECT COUNT(*) FROM whatsapp_outbound_queue WHERE member_id=? AND kind='welcome'", (member_id,)).fetchone()[0]
check("re-opt-in after stop + new payment sends a fresh welcome", changed3 is True and rejoin_count == before_count + 1)

# --- 3. build_daily_whatsapp_payload returns the stop button with the right payload ---
fake_deal = {
    "flight": {"price": 999, "stops": 0, "airline": "Test Air", "total_duration_minutes": 180,
               "departure_time": "2027-01-01T10:00:00", "arrival_time": "2027-01-01T13:00:00",
               "baggage": {}},
    "departure_code": "TLV", "arrival_code": "FCO",
    "outbound": {"display_he": "1.1.2027"}, "return": {"display_he": "8.1.2027"},
    "country_flag": "🇮🇹", "booking_url": "https://example.com",
}
payload = formatter.build_daily_whatsapp_payload([fake_deal])
check("daily payload has a body", bool(payload["body"]))
check("daily payload has exactly the stop button", payload["buttons"] == [{"text": "הפסקת הדילים", "payload": "STOP_HOT_DEALS"}])
check("build_daily_message itself is unchanged (still returns just the body text)", formatter.build_daily_message([fake_deal]) == payload["body"])

# --- 4. route_inbound(phone, '', button_payload='STOP_HOT_DEALS') from an active member ---
member_id2 = make_member("qa-whatsapp-stop-active@example.com", "+972500000002")
database.set_whatsapp_deals_opt(member_id2, True, "site")
reply = nc.route_inbound("+972500000002", "", button_payload="STOP_HOT_DEALS")
with sqlite3.connect(database.DB_PATH) as conn:
    conn.row_factory = sqlite3.Row
    after = conn.execute("SELECT whatsapp_opt_in, whatsapp_opt_out_source FROM members WHERE id=?", (member_id2,)).fetchone()
    stop_event = conn.execute("SELECT event, source FROM whatsapp_opt_events WHERE member_id=? ORDER BY id DESC LIMIT 1", (member_id2,)).fetchone()
check("STOP button opts out an active member", after["whatsapp_opt_in"] == 0)
check("opt_out_source='whatsapp_button'", after["whatsapp_opt_out_source"] == "whatsapp_button")
check("opt_events row for the stop", stop_event["event"] == "opt_out" and stop_event["source"] == "whatsapp_button")
check("reply contains the full /deals link", "/deals" in reply)
check("reply does not mention a nonexistent vacation tracking line", "עדכוני החופשה" not in reply)

# --- 5. Second STOP press -> "already stopped" reply, no duplicate opt_out row ---
with sqlite3.connect(database.DB_PATH) as conn:
    before_events = conn.execute("SELECT COUNT(*) FROM whatsapp_opt_events WHERE member_id=?", (member_id2,)).fetchone()[0]
reply2 = nc.route_inbound("+972500000002", "", button_payload="STOP_HOT_DEALS")
with sqlite3.connect(database.DB_PATH) as conn:
    after_events = conn.execute("SELECT COUNT(*) FROM whatsapp_opt_events WHERE member_id=?", (member_id2,)).fetchone()[0]
check("second STOP press replies 'already stopped'", "כבר לא נשלחים" in reply2)
check("second STOP press doesn't add another opt_out row", after_events == before_events)

# --- 6. Unknown phone number -> graceful 'not found' reply, no onboarding ---
reply3 = nc.route_inbound("+972500000099", "", button_payload="STOP_HOT_DEALS")
check("unknown phone gets 'not found' reply", "לא מצאנו" in reply3)

# --- 7. Member with an active tracked vacation gets the extra line ---
member_id3 = make_member("qa-whatsapp-stop-tracked@example.com", "+972500000003")
database.set_whatsapp_deals_opt(member_id3, True, "site")
with sqlite3.connect(database.DB_PATH) as conn:
    conn.execute(
        "INSERT INTO trip_requests (member_id, request_name, status, answers_json, created_at, subscription_status, mobile_notifications) "
        "VALUES (?,?,?,?,datetime('now'),?,?)",
        (member_id3, "QA trip", "active", "{}", "active", 1),
    )
    conn.commit()
reply4 = nc.route_inbound("+972500000003", "", button_payload="STOP_HOT_DEALS")
check("stop reply mentions ongoing vacation tracking when one exists", "עדכוני החופשה" in reply4)

# --- 8. Plain text "עצור" must NOT stop the service (button only, per product owner) ---
member_id4 = make_member("qa-whatsapp-stop-keyword@example.com", "+972500000004")
database.set_whatsapp_deals_opt(member_id4, True, "site")
_ = nc.route_inbound("+972500000004", "עצור", button_payload=None)
with sqlite3.connect(database.DB_PATH) as conn:
    conn.row_factory = sqlite3.Row
    still_on = conn.execute("SELECT whatsapp_opt_in FROM members WHERE id=?", (member_id4,)).fetchone()
check("the word עצור in free text does not stop the service", still_on["whatsapp_opt_in"] == 1)

# --- 9. Site toggle still works and records source='site' ---
member_id5 = make_member("qa-whatsapp-site-toggle@example.com", "+972500000005")
changed5 = database.set_whatsapp_deals_opt(member_id5, True, "site")
with sqlite3.connect(database.DB_PATH) as conn:
    conn.row_factory = sqlite3.Row
    site_event = conn.execute("SELECT source FROM whatsapp_opt_events WHERE member_id=? ORDER BY id DESC LIMIT 1", (member_id5,)).fetchone()
check("site toggle still flips opt_in", changed5 is True)
check("site toggle records source='site'", site_event["source"] == "site")

# --- 10. Migration runs twice on an existing DB without error ---
database.init_db()
database.init_db()
print("PASS: init_db() runs twice without error")

print()
if FAILED:
    print(f"FAILED ({len(FAILED)}): {FAILED}")
    sys.exit(1)
print("ALL CHECKS PASSED")
