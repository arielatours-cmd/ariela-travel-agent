"""QA for task 016a Stage 3: the /api/ariella/route-status/<job_id> polling
endpoint (route_build_status in ariella_chat_clean.py), mirroring
/trip/<id>/flight-status's own {status, stages:{...}} shape per Ofek's
spec, but keyed by route_jobs.member_id instead of a trip_id (no trip_id
exists yet at this point - the route hasn't been approved/saved).

Run: python3 tools/qa_016a_route_status_endpoint.py
"""
import os
import sys
import sqlite3
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import database
database.init_db()

import ariella_chat_clean as chat  # noqa: F401 - ensures the blueprint's routes are registered
import app as app_module
from werkzeug.security import generate_password_hash

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
            ("QA 016a Route Status", email, generate_password_hash("Test1234!"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
        )
        return cur.lastrowid


member_a = _make_member("qa-016a-route-status-a@example.com")
member_b = _make_member("qa-016a-route-status-b@example.com")

# --- 1. Not logged in at all ---
anon_client = app_module.app.test_client()
resp = anon_client.get("/api/ariella/route-status/1")
check("not logged in -> 401", resp.status_code == 401)

with client.session_transaction() as sess:
    sess["member_id"] = member_a

# --- 2. A job id that doesn't exist at all ---
resp = client.get("/api/ariella/route-status/999999")
check("nonexistent job id -> 404 missing", resp.status_code == 404 and resp.get_json().get("status") == "missing")

# --- 3. A job belonging to a DIFFERENT member is never exposed ---
other_job_id = database.create_route_job(member_b, "website", "תציעי מסלול", [], {})
resp = client.get(f"/api/ariella/route-status/{other_job_id}")
check("a job belonging to another member -> 404 missing (never leaked)", resp.status_code == 404 and resp.get_json().get("status") == "missing")

# --- 4. Still building, well within the 150s budget ---
building_job_id = database.create_route_job(member_a, "website", "תציעי מסלול", [], {})
resp = client.get(f"/api/ariella/route-status/{building_job_id}")
data = resp.get_json()
check("still building -> status=building", data.get("status") == "building")
check("still building -> stages.plan=searching", (data.get("stages") or {}).get("plan") == "searching")
check("still building -> all_done=False", data.get("all_done") is False)
check("still building -> no reply/error leaked yet", "reply" not in data and "error" not in data)

# --- 5. Ready ---
ready_job_id = database.create_route_job(member_a, "website", "תציעי מסלול", [], {})
database.update_route_job(ready_job_id, status="ready", result_reply="יום 1: נחיתה. יום 2: סיור.", result_trip_update={"flight": {"origin": "TLV"}})
resp = client.get(f"/api/ariella/route-status/{ready_job_id}")
data = resp.get_json()
check("ready -> status=ready", data.get("status") == "ready")
check("ready -> stages.plan=complete", (data.get("stages") or {}).get("plan") == "complete")
check("ready -> all_done=True", data.get("all_done") is True)
check("ready -> carries the real reply text", "יום 1" in (data.get("reply") or ""))
check("ready -> carries the real trip_update", (data.get("trip_update") or {}).get("flight", {}).get("origin") == "TLV")

# --- 6. Failed outright ---
failed_job_id = database.create_route_job(member_a, "website", "תציעי מסלול", [], {})
database.update_route_job(failed_job_id, status="failed", error="simulated engine crash")
resp = client.get(f"/api/ariella/route-status/{failed_job_id}")
data = resp.get_json()
check("failed -> status=failed", data.get("status") == "failed")
check("failed -> stages.plan=failed", (data.get("stages") or {}).get("plan") == "failed")
check("failed -> all_done=True", data.get("all_done") is True)
check("failed -> error message present", data.get("error") == "simulated engine crash")

# --- 7. Still 'building' in the DB, but past the 150s absolute timeout ---
# Simulates a job whose background thread died/hung without ever updating
# the row - the client must never be left polling forever.
stale_job_id = database.create_route_job(member_a, "website", "תציעי מסלול", [], {})
stale_started_at = (datetime.now(timezone.utc) - timedelta(seconds=200)).isoformat()
with sqlite3.connect(DB) as conn:
    conn.execute("UPDATE route_jobs SET started_at=? WHERE id=?", (stale_started_at, stale_job_id))
    conn.commit()
resp = client.get(f"/api/ariella/route-status/{stale_job_id}")
data = resp.get_json()
check("stale 'building' row past 150s -> reported as failed, not stuck forever", (data.get("stages") or {}).get("plan") == "failed")
check("stale 'building' row past 150s -> all_done=True", data.get("all_done") is True)
check("stale 'building' row past 150s -> status itself still reads the raw DB value", data.get("status") == "building")

print()
if FAILED:
    print(f"FAILED ({len(FAILED)}): {FAILED}")
    sys.exit(1)
print("ALL 016A-ROUTE-STATUS-ENDPOINT TESTS PASSED")
