"""QA for Shaked's bug 8 (2026-10-12 live QA): there was previously no way
to delete an account - not for the customer, not in admin - despite privacy
law requiring one. Covers both POST /account/delete (customer self-service,
requires the member's own current password) and GET /admin/delete-member
(ops/support, read-only unless ?confirm=1), and that deletion actually
removes rows from every member-linked table, not just the members row.

Run: python3 tools/qa_account_delete.py
"""
import os
import sqlite3
import sys
from datetime import datetime, timezone
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import database
database.init_db()

import app as app_module
from werkzeug.security import generate_password_hash

DB = database.DB_PATH
client = app_module.app.test_client()


def _make_member(email, password):
    with sqlite3.connect(DB) as conn:
        conn.execute("DELETE FROM members WHERE email=?", (email,))
        conn.commit()
        pw_hash = generate_password_hash(password)
        cur = conn.execute(
            "INSERT INTO members (full_name,email,password_hash,created_at,status,whatsapp_opt_in,preferred_airports) "
            "VALUES(?,?,?,?,?,?,?)",
            ("QA בדיקה", email, pw_hash, datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
        )
        member_id = cur.lastrowid
        conn.execute(
            "INSERT INTO trip_requests (member_id, request_name, created_at, status, answers_json) VALUES(?,?,?,?,?)",
            (member_id, "test", datetime.now(timezone.utc).isoformat(), "active", "{}"),
        )
        conn.execute(
            "INSERT INTO site_events (event_type, member_id, created_at) VALUES(?,?,?)",
            ("test_event", member_id, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
        return member_id


# --- 1. Customer self-service: wrong password -> account NOT deleted ---
member_id = _make_member("qa-account-delete-1@example.com", "DeleteMe123!")
with client.session_transaction() as sess:
    sess["member_id"] = member_id
r = client.post("/account/delete", data={"password": "wrong-password"})
assert r.status_code == 302, r.status_code
with sqlite3.connect(DB) as conn:
    assert conn.execute("SELECT 1 FROM members WHERE id=?", (member_id,)).fetchone()
print("PASS: wrong password does not delete the account")

# --- 2. Customer self-service: correct password -> member + all linked rows deleted ---
r2 = client.post("/account/delete", data={"password": "DeleteMe123!"})
assert r2.status_code == 302, r2.status_code
with sqlite3.connect(DB) as conn:
    assert not conn.execute("SELECT 1 FROM members WHERE id=?", (member_id,)).fetchone()
    assert not conn.execute("SELECT 1 FROM trip_requests WHERE member_id=?", (member_id,)).fetchone()
    assert not conn.execute("SELECT 1 FROM site_events WHERE member_id=?", (member_id,)).fetchone()
with client.session_transaction() as sess:
    assert "member_id" not in sess
print("PASS: correct password deletes member + every linked table's rows, and logs out")

# --- 3. Admin: no admin token -> 401 ---
member_id2 = _make_member("qa-account-delete-2@example.com", "AdminDel123!")
with patch.object(app_module, "ADMIN_TOKEN", "real-admin-secret"):
    r3 = client.get("/admin/delete-member", query_string={"email": "qa-account-delete-2@example.com"})
assert r3.status_code == 401, r3.status_code
print("PASS: admin route without admin token -> 401")

# --- 4. Admin: read-only without confirm=1 ---
r4 = client.get("/admin/delete-member", query_string={"email": "qa-account-delete-2@example.com"})
data4 = r4.get_json()
assert data4["would_delete"] is True and data4["applied"] is False, data4
with sqlite3.connect(DB) as conn:
    assert conn.execute("SELECT 1 FROM members WHERE id=?", (member_id2,)).fetchone()
print("PASS: admin route without confirm=1 is read-only")

# --- 5. Admin: confirm=1 actually deletes, found by email ---
r5 = client.get("/admin/delete-member", query_string={"email": "qa-account-delete-2@example.com", "confirm": "1"})
data5 = r5.get_json()
assert data5["applied"] is True, data5
with sqlite3.connect(DB) as conn:
    assert not conn.execute("SELECT 1 FROM members WHERE id=?", (member_id2,)).fetchone()
print("PASS: admin route with confirm=1 deletes the member found by email")

# --- 6. Admin: nonexistent account -> 404 ---
r6 = client.get("/admin/delete-member", query_string={"email": "nonexistent-qa@example.com"})
assert r6.status_code == 404, r6.status_code
print("PASS: admin route on a nonexistent account -> 404")

print("\nALL ACCOUNT DELETE TESTS PASSED")
