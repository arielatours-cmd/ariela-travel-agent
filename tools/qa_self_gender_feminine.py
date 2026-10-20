"""QA for Shaked's direct live-run finding (stage-1 run-2, reported directly
to this session, not yet relayed through Shlomo): Ariella referred to
HERSELF in masculine form - "אני ממשיך עם הטיול" instead of "אני ממשיכה".

Ariella's own persona is established as female throughout TINKERBELL_SYSTEM
itself ("את מלוות החופשה של אריאלה"...), but free-text generation can still
drift to a default masculine Hebrew verb form. Unlike the customer's own
gender (which genuinely varies and must be read from state via _g() at
each construction site - see PR #102), Ariella's gender is a FIXED,
non-customer-dependent fact - so a deterministic post-processing
correction is safe and appropriate here, same defense-in-depth philosophy
already used for _strip_internal_terminology_leak and friends.

_ensure_self_gender_feminine scans only for "אני <verb>" (Ariella speaking
about herself - the only first-person voice in this chat) against a known
vocabulary of common masculine present-tense forms, replacing each with
its feminine counterpart. Wired into _reply(), the single exit point for
every successful turn, so it applies regardless of which code path
produced the reply (fixed string or model-generated free text alike).

Run: python3 tools/qa_self_gender_feminine.py
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


# =====================================================================
# Direct unit tests of _ensure_self_gender_feminine.
# =====================================================================
check("Shaked's exact live finding: 'אני ממשיך עם הטיול' is corrected to "
      "'אני ממשיכה עם הטיול'",
      chat._ensure_self_gender_feminine("אני ממשיך עם הטיול") == "אני ממשיכה עם הטיול")

check("an already-feminine self-reference is left completely untouched",
      chat._ensure_self_gender_feminine("אני ממשיכה עם הטיול") == "אני ממשיכה עם הטיול")

check("a masculine verb NOT preceded by 'אני' is left untouched (not a "
      "self-reference at all)",
      chat._ensure_self_gender_feminine("הבעל ממשיך לבד") == "הבעל ממשיך לבד")

check("multiple self-references in the same reply are all corrected",
      chat._ensure_self_gender_feminine("אני בודק את הטיסות ואני מעדכן אותך בקרוב")
      == "אני בודקת את הטיסות ואני מעדכנת אותך בקרוב")

check("a verb not in the known vocabulary is left untouched (fail-safe "
      "net, not an exhaustive grammar engine)",
      chat._ensure_self_gender_feminine("אני מתלבטת") == "אני מתלבטת")

check("None/empty reply never raises",
      chat._ensure_self_gender_feminine(None) is None
      and chat._ensure_self_gender_feminine("") == "")

check("a reply with no first-person self-reference at all is untouched",
      chat._ensure_self_gender_feminine("מתי תרצו לטוס?") == "מתי תרצו לטוס?")

check("the fix does not touch an unrelated masculine word elsewhere in "
      "the same sentence as 'אני' (word-boundary scoped to the word "
      "immediately after 'אני')",
      chat._ensure_self_gender_feminine("אני רואה שהטיול מתחיל בקרוב")
      == "אני רואה שהטיול מתחיל בקרוב")


# =====================================================================
# End-to-end: a mocked Tinkerbell reply with the exact live masculine
# self-reference reaches the customer already corrected, via the real
# endpoint (through _reply(), the single exit point for every turn).
# =====================================================================
def _make_member(email):
    with sqlite3.connect(DB) as conn:
        conn.execute("DELETE FROM members WHERE email=?", (email,))
        conn.commit()
        cur = conn.execute(
            "INSERT INTO members (full_name,email,password_hash,created_at,status,whatsapp_opt_in,preferred_airports,gender) "
            "VALUES(?,?,?,?,?,?,?,?)",
            ("QA Self Gender Feminine", email, generate_password_hash("Test1234!"),
             datetime.now(timezone.utc).isoformat(), "active", 0, "[]", "male"),
        )
        return cur.lastrowid


member = _make_member("qa-self-gender-feminine@example.com")
with client.session_transaction() as sess:
    sess["member_id"] = member

base_state = {
    "trip_type": "standard",
    "destination": {"places": ["רומא"], "mode": "specific", "status": "known"},
    "destination_airports": ["FCO"],
    "departure_airport": "TLV",
    "travelers": {"adults": 2, "children": 0},
    "dates": {"departure": "2026-11-10", "return": "2026-11-17", "needs_confirmation": False},
    "requested_services": ["flights"],
    "service_decisions": {"flights": {"wanted": True}},
    "session_status": {"flights": "active", "lodging": "declined", "car": "declined", "trip_planning": "declined"},
    "active_session": "flights",
}


def _post_claude_masculine_self_reference(key, model, system_static, system_dynamic, history, message_, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        return json.dumps({
            "trip_update": {}, "restart_request": False, "restart_evidence": None,
            "dates_evidence": None, "destination_evidence": None, "trip_type_evidence": None,
            "relative_date_hint": None, "relative_date_hint_evidence": None,
            "link_request": False, "link_request_evidence": None,
        })
    if source == "guided_extract":
        return json.dumps({"status": "other_topic", "field": None, "evidence": None})
    if source == "tinkerbell_reply":
        # Even though the customer here is male (the deliberately-chosen
        # gender in base_state), Ariella's OWN self-reference must still
        # be feminine - that is never about the customer's gender at all.
        return "בטח, אני ממשיך עם הטיול - מה עוד תרצה לדעת?"
    return "{}"


with patch.object(chat, "_post_claude", side_effect=_post_claude_masculine_self_reference):
    r = client.post("/api/ariella/chat-clean", json={
        "message": "מעולה",
        "history": [{"role": "assistant", "content": "יש לי עוד שאלה - מתאים?"}],
        "trip_state": base_state,
    })
data = r.get_json() or {}
reply = str(data.get("reply") or "")
check("end-to-end: a model reply with a masculine self-reference reaches "
      "the customer already corrected to feminine - the customer's OWN "
      "male gender is irrelevant to Ariella's own self-reference",
      "ממשיכה" in reply and "ממשיך " not in reply)

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL SELF-GENDER-FEMININE TESTS PASSED")
