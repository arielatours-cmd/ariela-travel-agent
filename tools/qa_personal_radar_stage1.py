"""QA for task 002a - personal radar, stage 1 (no sending).

Run: python3 tools/qa_personal_radar_stage1.py
"""
import sys
import os
import sqlite3
import json
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

from werkzeug.security import generate_password_hash

import database
import radar_alerts

database.init_db()
FAILED = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


def make_member(email):
    with sqlite3.connect(database.DB_PATH) as conn:
        conn.execute("DELETE FROM members WHERE email=?", (email,))
        conn.commit()
        pw = generate_password_hash("Test1234!")
        cur = conn.execute(
            "INSERT INTO members (full_name,email,phone,password_hash,created_at,status,whatsapp_opt_in,preferred_airports) "
            "VALUES(?,?,?,?,datetime('now'),'active',0,'[]')",
            ("QA Radar", email, "+972500000111", pw),
        )
        conn.commit()
        return int(cur.lastrowid)


def make_trip(member_id, offer_ids, mobile_notifications=1, subscription_status="active", subscription_plan="scan"):
    answers = {"_matched_offer_ids": offer_ids}
    with sqlite3.connect(database.DB_PATH) as conn:
        cur = conn.execute(
            "INSERT INTO trip_requests (member_id, request_name, status, answers_json, created_at, "
            "subscription_status, subscription_plan, mobile_notifications) VALUES (?,?,?,?,datetime('now'),?,?,?)",
            (member_id, "QA Radar Trip", "active", json.dumps(answers), subscription_status, subscription_plan, mobile_notifications),
        )
        conn.commit()
        return int(cur.lastrowid)


def make_offer(price_ils, route="TLV-FCO", outbound="2027-05-01", ret="2027-05-08", observed_days_ago=0, baggage_included=True):
    observed_at = (datetime.now(timezone.utc) - timedelta(days=observed_days_ago)).isoformat()
    payload = {
        "flight": {"price": price_ils, "baggage": {"checked_bag_23kg": {"included": baggage_included}}},
        "destination_name": "רומא",
    }
    with sqlite3.connect(database.DB_PATH) as conn:
        cur = conn.execute(
            "INSERT INTO scan_runs (started_at, status, searches_planned) VALUES (datetime('now'), 'done', 1)"
        )
        scan_run_id = cur.lastrowid
        cur = conn.execute(
            """INSERT INTO offers (scan_run_id, observed_at, route, departure_code, arrival_code, outbound_date,
               return_date, price_ils, score, score_label, payload_json)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (scan_run_id, observed_at, route, "TLV", "FCO", outbound, ret, price_ils, 90, "great",
             json.dumps(payload, ensure_ascii=False)),
        )
        conn.commit()
        return int(cur.lastrowid)


def reset_trip_alerts(trip_id):
    with sqlite3.connect(database.DB_PATH) as conn:
        conn.execute("DELETE FROM trip_alerts_log WHERE trip_id=?", (trip_id,))
        conn.execute("UPDATE trip_requests SET alert_baseline_price_ils=NULL, alert_last_price_ils=NULL, alert_last_at=NULL WHERE id=?", (trip_id,))
        conn.commit()


member_id = make_member("qa-radar@example.com")

# --- 1. First run on a tracked trip -> saves baseline, no alert ---
offer1 = make_offer(1000)
trip_id = make_trip(member_id, [offer1])
result1 = radar_alerts.evaluate_trip_alert(trip_id)
check("first run saves baseline, no alert", result1 is None)
with sqlite3.connect(database.DB_PATH) as conn:
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT alert_baseline_price_ils FROM trip_requests WHERE id=?", (trip_id,)).fetchone()
check("baseline price saved", row["alert_baseline_price_ils"] == 1000)

# --- 2. 8% + 120 ILS drop -> price_drop alert, log row, queue row (preview) ---
with sqlite3.connect(database.DB_PATH) as conn:
    conn.execute("UPDATE offers SET price_ils=? WHERE id=?", (880, offer1))  # -12%, -120
    conn.commit()
result2 = radar_alerts.evaluate_trip_alert(trip_id)
check("8%/120 ILS drop triggers price_drop alert", result2 is not None and result2["reason"] == "price_drop")
with sqlite3.connect(database.DB_PATH) as conn:
    conn.row_factory = sqlite3.Row
    log_row = conn.execute("SELECT * FROM trip_alerts_log WHERE trip_id=? ORDER BY id DESC LIMIT 1", (trip_id,)).fetchone()
    queue_row = conn.execute("SELECT * FROM whatsapp_outbound_queue WHERE ref_id=? AND kind='radar' ORDER BY id DESC LIMIT 1", (trip_id,)).fetchone()
check("log row written with reason/price/previous_price", log_row is not None and log_row["reason"] == "price_drop" and log_row["price_ils"] == 880 and log_row["previous_price_ils"] == 1000)
check("log row status is preview", log_row["status"] == "preview")
check("message includes new price and previous price", "880" in log_row["message_text"] and "1000" in log_row["message_text"])
check("queue row written (mobile_notifications=1)", queue_row is not None and queue_row["status"] == "preview")

# --- 3. Small drop (3% or 40 ILS only) -> no alert. Uses its own fresh
# route/dates (not offer1's) with a genuinely lower historical price already
# on record, so "lowest seen in 30 days" legitimately does NOT fire either -
# isolating this check to the price_drop threshold alone, the way it would
# actually play out against a real multi-observation price history. ---
small_drop_route = "TLV-BCN"
make_offer(900, route=small_drop_route, outbound="2027-06-01", ret="2027-06-08", observed_days_ago=15)
offer3 = make_offer(970, route=small_drop_route, outbound="2027-06-01", ret="2027-06-08", observed_days_ago=0)  # -3%, -30
trip_id3 = make_trip(member_id, [offer3])
with sqlite3.connect(database.DB_PATH) as conn:
    conn.execute(
        "UPDATE trip_requests SET alert_baseline_price_ils=1000, alert_last_price_ils=1000 WHERE id=?",
        (trip_id3,),
    )
    conn.commit()
result3 = radar_alerts.evaluate_trip_alert(trip_id3)
check("3%/30 ILS drop alone does not trigger an alert", result3 is None)

# --- 4. Same-day second drop -> no second alert; "next day" -> allowed again ---
reset_trip_alerts(trip_id)
with sqlite3.connect(database.DB_PATH) as conn:
    conn.execute("UPDATE offers SET price_ils=? WHERE id=?", (1000, offer1))
    conn.commit()
radar_alerts.evaluate_trip_alert(trip_id)
with sqlite3.connect(database.DB_PATH) as conn:
    conn.execute("UPDATE offers SET price_ils=? WHERE id=?", (850, offer1))
    conn.commit()
first_today = radar_alerts.evaluate_trip_alert(trip_id)
with sqlite3.connect(database.DB_PATH) as conn:
    conn.execute("UPDATE offers SET price_ils=? WHERE id=?", (700, offer1))
    conn.commit()
second_today = radar_alerts.evaluate_trip_alert(trip_id)
check("first alert today fires", first_today is not None)
check("second alert same day is suppressed", second_today is None)
# Simulate "yesterday" by backdating alert_last_at.
yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
with sqlite3.connect(database.DB_PATH) as conn:
    conn.execute("UPDATE trip_requests SET alert_last_at=? WHERE id=?", (yesterday, trip_id))
    conn.commit()
next_day = radar_alerts.evaluate_trip_alert(trip_id)
check("a further drop the next day is allowed", next_day is not None)

# --- 5. Price not lower than comparison but "lowest in 30 days" -> still no alert (must be lower than comparison too) ---
reset_trip_alerts(trip_id)
with sqlite3.connect(database.DB_PATH) as conn:
    conn.execute("UPDATE offers SET price_ils=? WHERE id=?", (1000, offer1))
    conn.commit()
radar_alerts.evaluate_trip_alert(trip_id)  # baseline 1000
with sqlite3.connect(database.DB_PATH) as conn:
    conn.execute("UPDATE offers SET price_ils=? WHERE id=?", (1000, offer1))  # same price as comparison
    conn.commit()
result5 = radar_alerts.evaluate_trip_alert(trip_id)
check("price equal to comparison (even if it's the 30-day low) does not alert", result5 is None)

# --- 6. mobile_notifications=0 -> log row written, but no queue row ---
offer6 = make_offer(1000)
trip_id6 = make_trip(member_id, [offer6], mobile_notifications=0)
radar_alerts.evaluate_trip_alert(trip_id6)  # baseline
with sqlite3.connect(database.DB_PATH) as conn:
    conn.execute("UPDATE offers SET price_ils=? WHERE id=?", (850, offer6))
    conn.commit()
result6 = radar_alerts.evaluate_trip_alert(trip_id6)
check("alert still evaluated with mobile_notifications=0", result6 is not None)
with sqlite3.connect(database.DB_PATH) as conn:
    log6 = conn.execute("SELECT COUNT(*) FROM trip_alerts_log WHERE trip_id=?", (trip_id6,)).fetchone()[0]
    queue6 = conn.execute("SELECT COUNT(*) FROM whatsapp_outbound_queue WHERE ref_id=? AND kind='radar'", (trip_id6,)).fetchone()[0]
check("log row written even with mobile_notifications=0", log6 == 1)
check("NO queue row when mobile_notifications=0", queue6 == 0)

# --- 7. Trip without an active paid subscription is never evaluated ---
offer7 = make_offer(1000)
trip_id7 = make_trip(member_id, [offer7], subscription_status="none", subscription_plan=None)
result7 = radar_alerts.evaluate_trip_alert(trip_id7)
check("trip without active subscription is skipped entirely", result7 is None)
with sqlite3.connect(database.DB_PATH) as conn:
    baseline7 = conn.execute("SELECT alert_baseline_price_ils FROM trip_requests WHERE id=?", (trip_id7,)).fetchone()[0]
check("no baseline saved for an untracked trip", baseline7 is None)

# --- 8. "כולל מזוודה" only appears when baggage is actually included ---
reset_trip_alerts(trip_id)
offer8 = make_offer(1000, baggage_included=False)
trip_id8 = make_trip(member_id, [offer8])
radar_alerts.evaluate_trip_alert(trip_id8)
with sqlite3.connect(database.DB_PATH) as conn:
    conn.execute("UPDATE offers SET price_ils=? WHERE id=?", (850, offer8))
    conn.commit()
result8 = radar_alerts.evaluate_trip_alert(trip_id8)
check("no baggage mention when not included", "כולל מזוודה" not in result8["message_text"])

# --- 9. No call to Meta/WhatsApp anywhere in this module ---
with open("radar_alerts.py", encoding="utf-8") as f:
    src = f.read()
check("radar_alerts.py never imports whatsapp.py / calls Meta", "import whatsapp" not in src and "graph.facebook.com" not in src)

# --- 10. Account page batched query works and doesn't crash with no alerts ---
from database import latest_trip_alerts
alerts_map = latest_trip_alerts([trip_id6, trip_id7, 999999])
check("latest_trip_alerts returns alerts for trips that have one", trip_id6 in alerts_map)
check("latest_trip_alerts omits trips with no alert", trip_id7 not in alerts_map and 999999 not in alerts_map)

# --- 11. Migration runs twice without error ---
database.init_db()
database.init_db()
print("PASS: init_db() runs twice without error")

print()
if FAILED:
    print(f"FAILED ({len(FAILED)}): {FAILED}")
    sys.exit(1)
print("ALL CHECKS PASSED")
