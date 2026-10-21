"""QA for Shaked's stage-1 run-7 bug B (relayed by Shlomo, 21.10.2026):

"כבודה בבקשה מעורבת (פוקט): אריאלה ענתה 'למבוגרים מזוודה... ולילדים
טרולי'. זה סותר את ההחלטה: בבקשה מעורבת מזוודה לכולם, בלי דיון ובלי
פירוט לפי נוסע. השמירה כבר תקינה. צריך לתקן רק את הניסוח של התשובה, דרך
ההנחיה למודל או בנייה מה-state."

Root cause confirmed by direct code reading: _guided_field_update_and_
confirm (ariella_chat_clean.py) already resolves a mixed per-passenger
baggage request SILENTLY to flight.baggage=["checked_bag"] for the whole
group, exactly per the business owner's 20.10 directive - the SAVED state
was always correct, as Shaked's own report confirms ("השמירה כבר
תקינה"). But _handle_guided_extraction_turn's own steering hint for how
Tinkerbell should ACKNOWLEDGE this turn came from _baggage_followup_hint,
which returns None for checked_bag (normally nothing needs an upsell
note) - so for the mixed-request path specifically, Tinkerbell was left
with NO steering hint at all for this turn, free to compose her own
wording purely from the conversation history, and echoed back the very
per-passenger split ("למבוגרים... ולילדים...") the silent resolution
exists to override.

Fix: a new _mixed_baggage_acknowledgement_hint() function, wired in
wherever flight.baggage resolves to the mixed case (first answer AND a
later correction), explicitly instructing a neutral one-sentence
acknowledgement with no per-passenger description and no promise of a
future split - letting the next guided question still reach the customer
in the same message, exactly like the existing upsell-note path.

Run: python3 tools/qa_mixed_baggage_wording.py
"""
import os
import sys
import json
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


def _make_member(email):
    with sqlite3.connect(DB) as conn:
        conn.execute("DELETE FROM members WHERE email=?", (email,))
        conn.commit()
        cur = conn.execute(
            "INSERT INTO members (full_name,email,password_hash,created_at,status,whatsapp_opt_in,preferred_airports) "
            "VALUES(?,?,?,?,?,?,?)",
            ("QA Mixed Baggage Wording", email, generate_password_hash("Test1234!"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
        )
        return cur.lastrowid


def _post(message, history, trip_state, member_id):
    with client.session_transaction() as sess:
        sess["member_id"] = member_id
    r = client.post("/api/ariella/chat-clean", json={
        "message": message, "history": history, "trip_state": trip_state,
    })
    return r.get_json()


def _fake_post_claude_factory(guided_response, tinkerbell_reply="תשובה לדוגמה."):
    def _fake(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
        if source == "state_extractor":
            return "{}"
        if source == "guided_extract":
            return json.dumps(guided_response)
        return tinkerbell_reply
    return _fake


PHUKET_STATE = {
    "destination": {"places": ["פוקט"], "mode": "specific", "status": "known"},
    "active_session": "flights",
    "requested_services": ["flights"],
    "session_status": {"flights": "active", "lodging": "declined", "car": "declined", "trip_planning": "declined"},
    "dates": {"departure": "2027-02-10", "return": "2027-02-17"},
    "travelers": {"adults": 2, "children": 2},
}


# =====================================================================
# Direct unit coverage of the new hint function itself.
# =====================================================================
_hint = chat._mixed_baggage_acknowledgement_hint()
check("direct: the hint explicitly forbids describing a per-passenger split",
      "בלי לתאר" in _hint and "חלוקה שונה בין נוסעים" in _hint)
check("direct: the hint explicitly forbids promising a future per-passenger split",
      "להבטיח" in _hint)
check("direct: the hint still tells Tinkerbell to move on to the next topic "
      "in the same message (matches _baggage_followup_hint's own shape)",
      "מיד אחר כך" in _hint and "באותה הודעה" in _hint)
check("regression: no quick-reply buttons in the new hint",
      "[" not in _hint)


# =====================================================================
# End-to-end Phuket repro: first-time baggage answer, mixed per-passenger
# request. The SAVE must stay correct (checked_bag, no size/count), and
# the steering hint Tinkerbell receives must now explicitly forbid the
# live bug's exact wording shape.
# =====================================================================
member_phuket = _make_member("qa-phuket-mixed-baggage@example.com")
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_factory({
    "status": "answered", "no_baggage": False, "mixed_per_passenger": True,
    "items": None, "confidence": "high", "also_mentioned": None, "correction": None,
})):
    state_phuket = dict(PHUKET_STATE)
    state_phuket["guided"] = {"current_question": "baggage", "attempts": 0, "answered": ["dates", "travelers"]}
    r_phuket = _post("למבוגרים מזוודה בבטן המטוס ולילדים רק טרולי", [], state_phuket, member_phuket)
tu_phuket = r_phuket.get("trip_update") or {}
phuket_hint = str(tu_phuket.get("_guided_ask_hint") or "")
check("Phuket: the save stays correct - checked_bag for the whole group, "
      "no size/count synthesized from the per-passenger description",
      (tu_phuket.get("flight") or {}).get("baggage") == ["checked_bag"]
      and not (tu_phuket.get("flight") or {}).get("baggage_detail"))
check("Phuket FIX: Tinkerbell's steering hint now explicitly forbids the "
      "live bug's exact wording shape (a per-passenger breakdown)",
      "בלי לתאר" in phuket_hint and "חלוקה שונה בין נוסעים" in phuket_hint)
check("Phuket: the hint never itself contains the forbidden per-passenger "
      "wording as if it were an instruction to SAY it",
      "למבוגרים מזוודה" not in phuket_hint and "ולילדים טרולי" not in phuket_hint)


# =====================================================================
# Correction path: the model itself judges this answer as CORRECTING an
# earlier-mentioned baggage preference (result.correction set) rather
# than a fresh first answer - current_question is still "baggage" (not
# yet in guided.answered; the model's "correction" judgment is independent
# of that bookkeeping, same as the dates/travelers schemas' own
# correction field). The correction acknowledgement hint must carry the
# same no-breakdown instruction as the first-answer path.
# =====================================================================
member_correction = _make_member("qa-mixed-baggage-correction@example.com")
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_factory({
    "status": "answered", "no_baggage": False, "mixed_per_passenger": True,
    "items": None, "confidence": "high", "also_mentioned": None,
    "correction": {"field": "baggage", "old": "carry_on_only", "new": "mixed"},
})):
    state_correction = dict(PHUKET_STATE, flight={"baggage": ["carry_on_only"]})
    state_correction["guided"] = {"current_question": "baggage", "attempts": 0, "answered": ["dates", "travelers"]}
    r_correction = _post(
        "רגע, בעצם למבוגרים שלנו אנחנו רוצים מזוודה ולילדים מספיק טרולי",
        [], state_correction, member_correction,
    )
tu_correction = r_correction.get("trip_update") or {}
correction_hint = str(tu_correction.get("_guided_ask_hint") or "")
check("correction path: the save still resolves to checked_bag for "
      "everyone, same as a first answer",
      (tu_correction.get("flight") or {}).get("baggage") == ["checked_bag"])
check("correction path FIX: the correction acknowledgement hint also "
      "forbids describing a per-passenger split",
      "בלי לתאר" in correction_hint and "חלוקה שונה בין נוסעים" in correction_hint)


# =====================================================================
# Regression: a plain (non-mixed) uniform request resolving to checked_bag
# must NOT get the new mixed-only hint text - _baggage_followup_hint's
# own "nothing to add" behavior for the top tier is unaffected.
# =====================================================================
member_plain = _make_member("qa-plain-checked-bag@example.com")
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_factory({
    "status": "answered", "no_baggage": False, "mixed_per_passenger": False,
    "items": [{"type": "checked_bag", "count": None, "size": None}],
    "confidence": "high", "also_mentioned": None, "correction": None,
})):
    state_plain = dict(PHUKET_STATE)
    state_plain["guided"] = {"current_question": "baggage", "attempts": 0, "answered": ["dates", "travelers"]}
    r_plain = _post("מזוודה בבטן המטוס לכולנו", [], state_plain, member_plain)
tu_plain = r_plain.get("trip_update") or {}
plain_hint = str(tu_plain.get("_guided_ask_hint") or "")
check("regression: a plain uniform checked_bag request is unaffected - no "
      "mixed-only wording leaks into its hint (checked_bag still needs no "
      "upsell note, and no per-passenger instruction is relevant here)",
      "בלי לתאר" not in plain_hint and "חלוקה שונה בין נוסעים" not in plain_hint)

if FAILED:
    print(f"\n{len(FAILED)} CHECK(S) FAILED:")
    for name in FAILED:
        print(f"  - {name}")
    sys.exit(1)
print("\nALL MIXED-BAGGAGE-WORDING TESTS PASSED")
