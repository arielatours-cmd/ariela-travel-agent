"""QA for a bug Carmit flagged directly (2026-10-15), after noticing it as
a contributing cause in Shaked's round-14 loop findings (A5, C1): the
reset-vacation confirmation gate matched the customer's answer against a
tiny exact-string set - {"כן","כן.","כן!","בטח","בהחלט"} for yes,
{"לא","לא.","לא!","לא תודה"} for no. An unambiguous "yes" with the
customer's own natural elaboration right after it - "כן, להתחיל חופשה
חדשה", "כן, מתאים" - matched NEITHER set, so it fell through to a
redundant, robotic "just to confirm, yes or no?" re-ask of the exact same
question, part of the route-approval loop both A5 and C1 got stuck in.

Carmit's own broader point: prefer understanding real phrasing over
hard-coded example words, matching the philosophy already used elsewhere
in this codebase (meaning-based fallbacks like
_itinerary_acceptance_by_meaning) rather than growing ever-longer exact-
match word lists. Fixed with a word-boundary-aware leading-word match
(_RESET_GATE_YES_RE / _RESET_GATE_NO_RE) instead of exact-string equality -
still a simple, fast, deterministic check appropriate for a binary gate,
but robust to any natural elaboration after the leading כן/לא.

Run: python3 tools/qa_reset_gate_natural_yes_no.py
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


# --- 1. Unit-level: the regexes directly, covering both the original exact
#        set members and the natural-elaboration phrasing that broke ---
check("'כן' matches yes", bool(chat._RESET_GATE_YES_RE.match("כן")))
check("'כן.' matches yes", bool(chat._RESET_GATE_YES_RE.match("כן.")))
check("'כן, להתחיל חופשה חדשה' (the exact live failure) matches yes",
      bool(chat._RESET_GATE_YES_RE.match("כן, להתחיל חופשה חדשה")))
check("'כן, מתאים' (the exact live failure) matches yes",
      bool(chat._RESET_GATE_YES_RE.match("כן, מתאים")))
check("'לא תודה' matches no", bool(chat._RESET_GATE_NO_RE.match("לא תודה")))
check("'לא, תשאירי את זה' matches no", bool(chat._RESET_GATE_NO_RE.match("לא, תשאירי את זה")))
check("an unrelated word starting with different letters matches neither",
      not chat._RESET_GATE_YES_RE.match("אולי") and not chat._RESET_GATE_NO_RE.match("אולי"))

# --- 2. End to end via the real Flask route: the reset gate must not
#        re-ask itself when the customer says "כן, <elaboration>" ---
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
            ("QA Reset Gate", email, generate_password_hash("Test1234!"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
        )
        return cur.lastrowid


member_id = _make_member("qa-reset-gate@example.com")
with client.session_transaction() as sess:
    sess["member_id"] = member_id

pending_state = {
    "reset_pending": True,
    "reset_change_request": "חופשה חדשה. אל תמחקי את ניו יורק",
    "reset_scope": "vacation",
}
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude):
    r = client.post("/api/ariella/chat-clean", json={
        "message": "כן, להתחיל חופשה חדשה", "history": [], "trip_state": dict(pending_state),
    })
data = r.get_json()
check("the reset gate does not re-ask the redundant 'just to confirm' question",
      "רק כדי לוודא" not in str(data.get("reply") or ""))
check("the reset gate actually proceeds (reset_pending cleared in the response)",
      not bool((data.get("trip_update") or {}).get("reset_pending")))

with sqlite3.connect(DB) as conn:
    conn.execute("DELETE FROM members WHERE id=?", (member_id,))
    conn.commit()

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL RESET-GATE-NATURAL-YES-NO TESTS PASSED")
