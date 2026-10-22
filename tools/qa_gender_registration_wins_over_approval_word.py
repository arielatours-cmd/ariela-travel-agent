"""QA for the business owner's directive (20.10.2026, relayed by Shlomo),
reacting to a bug this session itself found while investigating a different
request ("talk to the customer per their registration, never per the
grammar of what they type"):

_user_gender_from_approval literally reads the customer's final-approval
word ("מאשר"/"מאשרת") and, until this fix, unconditionally overwrote
user_gender with whatever gender that WORD implies - even for a member with
a real, registered gender in members.gender (set at signup, shown read-only
in account details). A female-registered customer who types the masculine
"מאשר" (autocomplete, habit, a typo) got addressed in masculine form for
that turn, and the wrong value was then carried forward into the NEXT
vacation's fresh state too (session_status/base_trip_state copy whatever
user_gender ends up in merged, uncritically).

Fixed: the literal-word override at the search-confirmed branch now only
ever runs when the member has NO registered gender in members.gender at
all. Once a registered gender exists, it was already written into
user_gender earlier in the SAME turn's pipeline (from _member_profile - see
"trip_update['profile'] = _member_profile(...)" / "if trip_update['profile']
.get('gender'): trip_update['user_gender'] = ...", a few lines above this
turn's _merge_trip_state call) and this literal-word check must never touch
it again.

Driven through the real /api/ariella/chat-clean endpoint (same pattern as
tools/qa_combined_search_launched_full_reset.py) rather than through
whatsapp_bridge.ariella_turn - the latter actually launches the real flight
search once approval fires, which resets the conversation's own trip_state
to a fresh follow-up vacation before this test could inspect it. The JSON
response's own trip_update is the authoritative place to check what THIS
turn's merge actually produced, with no real search side effects needed.

Run: python3 tools/qa_gender_registration_wins_over_approval_word.py
"""
import os
import sys
import sqlite3
from datetime import datetime, timezone
from unittest.mock import patch
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import database
database.init_db()

import ariella_chat_clean as chat
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


def _make_member(email, gender):
    with sqlite3.connect(DB) as conn:
        conn.execute("DELETE FROM members WHERE email=?", (email,))
        conn.commit()
        cur = conn.execute(
            "INSERT INTO members (full_name,email,password_hash,created_at,status,whatsapp_opt_in,preferred_airports,gender) "
            "VALUES(?,?,?,?,?,?,?,?)",
            ("QA Gender Registration", email, generate_password_hash("Test1234!"),
             datetime.now(timezone.utc).isoformat(), "active", 0, "[]", gender),
        )
        return cur.lastrowid


# A "nothing left to decide" flights-only trip: every flights gap closed,
# lodging/car/trip_planning explicitly declined, so the server-side pipeline
# reaches the real search-confirmed/ready_for_summary approval branch this
# fix touches, with no shortcuts.
def _ready_state():
    return {
        "trip_type": "standard",
        "destination": {"places": ["רומא"], "mode": "specific", "status": "known"},
        "destination_airports": ["FCO"],
        "departure_airport": "TLV",
        "travelers": {"adults": 2, "children": 0},
        "dates": {"departure": "2027-03-05", "return": "2027-03-10", "needs_confirmation": False},
        "budget_per_person": {"status": "unlimited"},
        "flight": {
            "connection_preference": "any", "cabin": "economy",
            "baggage": ["checked_bag"],
            "baggage_detail": {"checked_bag": {"count": 2, "size": "גדולה"}},
        },
        "requested_services": ["flights"],
        "service_decisions": {
            "flights": {"wanted": True},
            "lodging": {"wanted": False}, "car": {"wanted": False}, "trip_planning": {"wanted": False},
        },
        "session_status": {"flights": "active", "lodging": "declined", "car": "declined", "trip_planning": "declined"},
        "active_session": "flights",
    }


assert chat._session_gaps(_ready_state(), "flights") == [], "test setup: the flights gaps list must genuinely be empty"


def _approve(email, gender, message):
    member = _make_member(email, gender)
    with client.session_transaction() as sess:
        sess["member_id"] = member
    def _quiet_post_claude(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
        if source == "state_extractor":
            return json.dumps({
                "trip_update": {}, "restart_request": False, "restart_evidence": None,
                "dates_evidence": None, "destination_evidence": None, "trip_type_evidence": None,
            })
        if source == "guided_extract":
            return json.dumps({"status": "other_topic", "field": None, "evidence": None})
        if source == "tinkerbell_reply":
            return "החופשה מאושרת, תודה!"
        return "{}"

    with patch.object(chat, "_post_claude", side_effect=_quiet_post_claude):
        r = client.post("/api/ariella/chat-clean", json={
            "message": message,
            "history": [{"role": "assistant", "content": "קלטתי את כל הפרטים - אם הכל נכון, כתבי/כתוב מאשרת/מאשר."}],
            "trip_state": _ready_state(),
        })
    data = r.get_json()
    return (data.get("trip_update") or {}), data


# =====================================================================
# The exact bug: a FEMALE-registered customer types the masculine "מאשר"
# (habit, autocomplete, typo) - the registered value must win this turn.
# =====================================================================
_update, _data = _approve("qa-gender-female-types-masculine@example.com", "female", "מאשר")
check("approval actually fired this turn (sanity check on the test setup itself)",
      _update.get("search_confirmed") is True)
check("a female-registered customer who types the masculine approval word "
      "'מאשר' stays addressed as female this turn - the registration wins "
      "over the literal word she typed",
      _update.get("user_gender") == "female")

# =====================================================================
# Regression, other direction: a MALE-registered customer typing the
# feminine "מאשרת" must likewise stay male.
# =====================================================================
_update_m, _ = _approve("qa-gender-male-types-feminine@example.com", "male", "מאשרת")
check("regression: a male-registered customer who types the feminine "
      "approval word 'מאשרת' stays addressed as male - same guarantee, "
      "other direction",
      _update_m.get("user_gender") == "male")

# =====================================================================
# Regression: a customer with NO registered gender at all (gender column
# empty/null) still gets today's existing literal-word behavior - this fix
# only narrows WHEN the override applies, it does not remove the mechanism
# for members who were never asked to register a gender.
# =====================================================================
_update_none, _ = _approve("qa-gender-unregistered@example.com", None, "מאשרת")
check("regression: a member with no registered gender at all still gets "
      "the literal-word fallback (today's existing behavior, unchanged)",
      _update_none.get("user_gender") == "female")

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL GENDER-REGISTRATION-WINS-OVER-APPROVAL-WORD TESTS PASSED")
