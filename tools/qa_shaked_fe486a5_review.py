"""QA for Shaked's review of PR #54 (commit fe486a5, 2026-10-16) - two
blocking findings and one non-blocking note.

**Blocking #1**: _deterministic_connection_preference_facts/_car_vehicle_
facts/_lodging_facts resolved a bare "כן"/"לא" by checking whether a topic
word (e.g. "ישיר") appeared ANYWHERE in Ariella's previous message, not
specifically in the question actually asked. Under the one-question-per-
message principle, a message can combine a STATEMENT with an unrelated
question ("אין כרגע אפשרות מאומתת לטיסה ישירה ישראל-בודפשט... תרצי שאעזור
גם עם בניית מסלול?") - one question, fully compliant, but the earlier
statement's "ישיר" wrongly hijacked a "לא" meant for the route question,
overwriting the customer's real direct-flight preference. Same live finding
for car transmission ("רכב קטן אוטומטי נרשם. תרצי שאחפש גם לינה?" + "לא")
and lodging level ("מלון... יוקרתי... נרשם. תרצי גם רכב שכור?" + "כן"/"לא").

Fixed: every gate now matches only within the actual last question clause
(_last_question_clause - the text after the last sentence break before the
final "?"), never the whole prior message.

**Blocking #2**: seven fixed fallback question texts (_departure_question/
_flight_gap_question, plus the weekday-conflict helper) still used the
dictated "X or Y?" shape. All rewritten to a single open question or a
single-option yes/no, matching the same policy already applied to
_GAP_QUESTION_TEXT in fe486a5 - no extra model call added.

**Non-blocking**: the new_trip_pending gate's question ("זה שינוי יעד
בחופשה הנוכחית ל-X?") had no deterministic fast path for a bare "כן"/"לא" -
added one, consistent with every other single-option gate in this PR.

Run: python3 tools/qa_shaked_fe486a5_review.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import ariella_chat_clean as chat

FAILED = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


# =========================================================================
# Blocking #1: yes/no must bind to the actual question asked
# =========================================================================

BUDAPEST = "אין כרגע אפשרות מאומתת לטיסה ישירה ישראל-בודפשט... תרצי שאעזור גם עם בניית מסלול?"
check("Budapest: 'לא' to the route question must NOT touch connection_preference",
      chat._deterministic_connection_preference_facts("לא", [{"role": "assistant", "content": BUDAPEST}]) == {})
check("Budapest: 'כן' to the route question must NOT touch connection_preference",
      chat._deterministic_connection_preference_facts("כן", [{"role": "assistant", "content": BUDAPEST}]) == {})

CAR_THEN_LODGING = "רכב קטן אוטומטי נרשם. תרצי שאחפש גם לינה?"
check("car-then-lodging: 'לא' to the lodging question must NOT touch transmission",
      chat._deterministic_car_vehicle_facts("לא", [{"role": "assistant", "content": CAR_THEN_LODGING}]) == {})

LODGING_THEN_CAR = "מלון 4 כוכבים יוקרתי במרכז - נרשם. תרצי גם רכב שכור?"
check("lodging-then-car: 'כן' to the car question must NOT touch lodging level",
      chat._deterministic_lodging_facts("כן", [{"role": "assistant", "content": LODGING_THEN_CAR}]) == {})
check("lodging-then-car: 'לא' to the car question must NOT touch lodging level",
      chat._deterministic_lodging_facts("לא", [{"role": "assistant", "content": LODGING_THEN_CAR}]) == {})

# Regressions: the genuine single-option questions (no preceding unrelated
# statement) must still resolve correctly.
check("regression: genuine connection-preference question still works",
      chat._deterministic_connection_preference_facts("כן", [{"role": "assistant", "content": "חשוב לכם טיסה ישירה?"}])
      == {"flight": {"connection_preference": "direct"}})
check("regression: genuine transmission question still works",
      chat._deterministic_car_vehicle_facts("כן", [{"role": "assistant", "content": "חשוב לכם רכב אוטומטי?"}])
      == {"car": {"details": {"transmission": "אוטומטי"}}})
check("regression: genuine lodging-level question still works",
      chat._deterministic_lodging_facts("כן", [{"role": "assistant", "content": "חשוב לכם מלון יוקרתי?"}])
      == {"lodging": {"details": {"level": "יוקרתי"}}})

# _last_question_clause itself, directly
check("_last_question_clause isolates the question after the last sentence break",
      chat._last_question_clause(BUDAPEST) == "תרצי שאעזור גם עם בניית מסלול?")
check("_last_question_clause with no preceding sentence break returns the whole text",
      chat._last_question_clause("חשוב לכם טיסה ישירה?") == "חשוב לכם טיסה ישירה?")
check("_last_question_clause with no question mark at all returns the whole text",
      chat._last_question_clause("אין שאלה כאן") == "אין שאלה כאן")

# =========================================================================
# Blocking #2: seven fallback texts must no longer dictate "X or Y?"
# =========================================================================

def has_dictated_or(text):
    return " או " in text


check("_departure_question (single known airport) no longer offers 'X, or another'",
      not has_dictated_or(chat._departure_question({"departure_options": ["TLV"]})))
check("flight.gateway_narrow fallback is one open question, info given separately",
      not has_dictated_or(chat._flight_gap_question(["flight.gateway_narrow"], {"destination_airports": ["LCA", "PFO"]}).split(".")[1]))
check("budget_per_person fallback is a plain open question",
      chat._flight_gap_question(["budget_per_person"], {}) == "מה התקציב שלכם לאדם לטיסה?")
check("trip_type fallback is a plain open question (no dictated categories)",
      chat._flight_gap_question(["trip_type"], {}) == "איזה סוג נסיעה זו?")
check("flight.connection_preference fallback is a single-option yes/no",
      chat._flight_gap_question(["flight.connection_preference"], {}) == "חשוב לכם שהטיסה תהיה ישירה?")
check("flight.baggage fallback is a plain open question",
      chat._flight_gap_question(["flight.baggage"], {}) == "איזו כבודה תרצו לקחת?")

# The rewritten connection-preference fallback must still be recognized by
# its own deterministic gate (same phrasing style the gate expects).
check("the new connection-preference fallback text is itself gate-compatible",
      chat._deterministic_connection_preference_facts(
          "כן", [{"role": "assistant", "content": chat._flight_gap_question(["flight.connection_preference"], {})}]
      ) == {"flight": {"connection_preference": "direct"}})

# =========================================================================
# Non-blocking: new_trip_pending bare yes/no fast path
# =========================================================================
import database
database.init_db()
import app as app_module
from datetime import datetime, timezone
from werkzeug.security import generate_password_hash
import sqlite3
from unittest.mock import patch

DB = database.DB_PATH
client = app_module.app.test_client()


def _fake_post_claude(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        return "{}"
    return "לא אמור להגיע לכאן"


def _make_member(email):
    with sqlite3.connect(DB) as conn:
        conn.execute("DELETE FROM members WHERE email=?", (email,))
        conn.commit()
        cur = conn.execute(
            "INSERT INTO members (full_name,email,password_hash,created_at,status,whatsapp_opt_in,preferred_airports) "
            "VALUES(?,?,?,?,?,?,?)",
            ("QA Shaked Review", email, generate_password_hash("Test1234!"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
        )
        return cur.lastrowid


member_id = _make_member("qa-shaked-review@example.com")
with client.session_transaction() as sess:
    sess["member_id"] = member_id

STATE_PENDING = {
    "new_trip_pending": "פראג",
    "destination": {"places": ["רומא"], "mode": "specific", "status": "known"},
}
HISTORY_PENDING = [
    {"role": "assistant", "content": "רק כדי לוודא - פראג: זה שינוי יעד בחופשה הנוכחית לרומא?"},
]

with patch.object(chat, "_post_claude", side_effect=_fake_post_claude):
    r_keep = client.post("/api/ariella/chat-clean", json={
        "message": "כן", "history": HISTORY_PENDING, "trip_state": dict(STATE_PENDING),
    })
tu_keep = (r_keep.get_json() or {}).get("trip_update") or {}
check("bare 'כן' to the destination-change question is resolved WITHOUT a model call (keep)",
      tu_keep.get("destination_change_pending") == "פראג")

with patch.object(chat, "_post_claude", side_effect=_fake_post_claude):
    r_new = client.post("/api/ariella/chat-clean", json={
        "message": "לא", "history": HISTORY_PENDING, "trip_state": dict(STATE_PENDING),
    })
tu_new = (r_new.get_json() or {}).get("trip_update") or {}
check("bare 'לא' to the destination-change question is resolved WITHOUT a model call (new trip)",
      (tu_new.get("destination") or {}).get("places") == ["פראג"] and not tu_new.get("new_trip_pending"))

with sqlite3.connect(DB) as conn:
    conn.execute("DELETE FROM members WHERE id=?", (member_id,))
    conn.commit()

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL SHAKED-FE486A5-REVIEW TESTS PASSED")
