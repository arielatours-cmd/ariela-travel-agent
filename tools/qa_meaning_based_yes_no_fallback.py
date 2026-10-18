"""QA for Carmit's explicit, general instruction (2026-10-15): "יש לקוחות
שעונים... כל אחד מתבטא בצורה אחרת... אתה חייב לשנות את התנאים לפי המשמעות
של התשובה ולא לפי המילים המדויקות" - every customer phrases a yes/no
differently, so binary confirmation gates must classify by MEANING, never
by matching exact words, or the conversation keeps looping on replies the
fast path doesn't recognize.

Added _interpret_yes_no: a Claude-based classifier (reusing the exact
pattern already established by _interpret_pending_choice) that any binary
gate can fall back to once its fast regex/keyword check is genuinely
inconclusive. Wired into the reset-vacation gate and the destination-
change gate - both now resolve a reply the fast path can't parse
("בטוח, קדימה" - sure, go ahead) by meaning instead of re-asking the same
question.

Run: python3 tools/qa_meaning_based_yes_no_fallback.py
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


# --- 1. _interpret_yes_no itself: classifies YES/NO/UNCLEAR from the
#        model's raw response ---
def _fake_classifier_yes(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    return "YES - the customer clearly agreed"


def _fake_classifier_no(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    return "NO"


def _fake_classifier_unclear(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    return "UNCLEAR"


with patch.object(chat, "_post_claude", side_effect=_fake_classifier_yes):
    check("_interpret_yes_no returns 'yes' when the model classifies YES",
          chat._interpret_yes_no("test-key", "test-model", [], "בטוח, קדימה", "question?") == "yes")
with patch.object(chat, "_post_claude", side_effect=_fake_classifier_no):
    check("_interpret_yes_no returns 'no' when the model classifies NO",
          chat._interpret_yes_no("test-key", "test-model", [], "עדיף שלא", "question?") == "no")
with patch.object(chat, "_post_claude", side_effect=_fake_classifier_unclear):
    check("_interpret_yes_no returns 'unclear' when the model can't tell",
          chat._interpret_yes_no("test-key", "test-model", [], "אולי", "question?") == "unclear")
check("_interpret_yes_no never crashes and returns 'unclear' with no API key",
      chat._interpret_yes_no("", "test-model", [], "כן", "question?") == "unclear")


# --- 2. End to end: the reset gate resolves a reply its fast regex can't
#        parse ("בטוח, קדימה") via the meaning-based fallback, not a re-ask ---
def _make_member(email):
    with sqlite3.connect(DB) as conn:
        conn.execute("DELETE FROM members WHERE email=?", (email,))
        conn.commit()
        cur = conn.execute(
            "INSERT INTO members (full_name,email,password_hash,created_at,status,whatsapp_opt_in,preferred_airports) "
            "VALUES(?,?,?,?,?,?,?)",
            ("QA Meaning Fallback", email, generate_password_hash("Test1234!"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
        )
        return cur.lastrowid


member_id = _make_member("qa-meaning-fallback@example.com")
with client.session_transaction() as sess:
    sess["member_id"] = member_id


def _fake_post_claude_dispatch(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if source == "classifier":
        return "YES"
    if source == "state_extractor":
        return "{}"
    return "תשובה לדוגמה."


pending_state = {
    "reset_pending": True,
    "reset_change_request": "חופשה חדשה לקפריסין",
    "reset_scope": "vacation",
}
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_dispatch):
    r = client.post("/api/ariella/chat-clean", json={
        "message": "בטוח, קדימה", "history": [], "trip_state": dict(pending_state),
    })
data = r.get_json()
check("a reply the fast regex can't parse is resolved via meaning (no re-ask)",
      "רק כדי לוודא" not in str(data.get("reply") or ""))
check("the reset gate actually proceeded (reset_pending cleared)",
      not bool((data.get("trip_update") or {}).get("reset_pending")))

with sqlite3.connect(DB) as conn:
    conn.execute("DELETE FROM members WHERE id=?", (member_id,))
    conn.commit()

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL MEANING-BASED-YES-NO-FALLBACK TESTS PASSED")
