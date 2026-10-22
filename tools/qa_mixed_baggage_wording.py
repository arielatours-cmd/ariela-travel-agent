"""QA for the mixed-per-passenger baggage flow - FINAL business-owner
decision (22.10.2026, 4th and final revision, relayed by Shlomo), fully
superseding every earlier design in this file's history:

Original bug (Shaked, stage-1 run-7 bug B, Phuket, 21.10.2026): a mixed
per-passenger baggage request ("למבוגרים מזוודה... ולילדים טרולי") was
silently resolved to flight.baggage=["checked_bag"] for the whole group,
per the business owner's 20.10 directive - but Tinkerbell was left free to
compose her own acknowledgement and echoed back the very per-passenger
split the resolution existed to override.

PR #121 (first fix, 4f1079a) REJECTED by Shaked (e2848dc, 21.10.2026): it
had Tinkerbell explain the resolution in one sentence - itself a violation
of "בקשה מעורבת: מזוודה, בלי דיון" / "מזוודה: לא מוסיפה משפט".

PR #121 (second version) then had Tinkerbell say nothing about baggage at
all - also now superseded.

FINAL decision (22.10.2026): resolving to checked_bag was itself wrong. A
mixed request is never saved and never silently resolved at all. Ariella
explains, in her own words, that different baggage per passenger can only
be added later, at the payment stage, then asks ONE yes/no question - does
the customer want to choose the same baggage for the whole group right
now? "Yes" moves on to the normal single-group baggage question; "no"
keeps the EXISTING carry_on_only default (never an invented new value).
See _mixed_baggage_payment_time_hint/_mixed_baggage_confirm_retry_hint/
_mixed_baggage_uniform_choice_by_meaning in ariella_chat_clean.py, and
scenario 2c (plus its yes/no/unclear follow-ups) in
tools/qa_guided_extraction_baggage_014a.py for the full guided-flow
coverage. This file keeps direct unit coverage of the hint text itself,
plus the Phuket/correction end-to-end repros that originally caught the
bug.

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


def _fake_classifier_reply(value):
    """Fakes _mixed_baggage_uniform_choice_by_meaning's yes/no/unclear
    model call (source="classifier")."""
    def _fake(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
        if source == "state_extractor":
            return "{}"
        if source == "classifier":
            return value
        return "תשובה לדוגמה."
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
# Direct unit coverage of the hint functions themselves.
# =====================================================================
_hint = chat._mixed_baggage_payment_time_hint()
check("direct: the hint explains baggage can only differ per passenger at "
      "payment time",
      "התשלום" in _hint)
check("direct: the hint forbids saving/mentioning any specific baggage "
      "choice this turn",
      "אל תשמרי" in _hint)
check("direct: the hint asks one yes/no question, no buttons",
      "כן/לא" in _hint and "כפתורים" in _hint and "[" not in _hint)
check("direct: the hint never pre-resolves to checked_bag or any other "
      "specific value (Shaked's rejection of the 20.10/21.10 designs)",
      "checked_bag" not in _hint and "מזוודה בבטן המטוס כרגע" not in _hint)

_retry_hint = chat._mixed_baggage_confirm_retry_hint()
check("direct: the retry hint re-asks the same yes/no question and "
      "explicitly tells Tinkerbell not to repeat the payment-time "
      "explanation again",
      "כן" in _retry_hint and "לא" in _retry_hint and "בלי לחזור" in _retry_hint)


# =====================================================================
# End-to-end Phuket repro: first-time baggage answer, mixed per-passenger
# request. Nothing is saved; the field stays open, flagged pending, and
# the hint explains the payment-time limitation then asks yes/no - never
# a silent resolution to any value.
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
check("Phuket: nothing is saved - the per-passenger description is never "
      "silently resolved to any single value",
      not (tu_phuket.get("flight") or {}).get("baggage"))
check("Phuket: the field stays open and pending for the yes/no reply",
      (tu_phuket.get("guided") or {}).get("current_question") == "baggage"
      and (tu_phuket.get("guided") or {}).get("mixed_baggage_pending") is True)
check("Phuket: the hint explains the payment-time limitation and asks "
      "yes/no",
      "התשלום" in phuket_hint and "כן/לא" in phuket_hint)
check("Phuket: the hint never itself contains the customer's own "
      "per-passenger wording as if it were an instruction to SAY it",
      "למבוגרים מזוודה" not in phuket_hint and "ולילדים טרולי" not in phuket_hint)


# =====================================================================
# Phuket follow-up: customer answers "yes" - moves on to the normal
# single-group baggage question, still nothing saved yet.
# =====================================================================
member_phuket_yes = _make_member("qa-phuket-mixed-baggage-yes@example.com")
with patch.object(chat, "_post_claude", side_effect=_fake_classifier_reply("true")):
    state_phuket_yes = dict(PHUKET_STATE)
    state_phuket_yes["guided"] = {
        "current_question": "baggage", "attempts": 0,
        "answered": ["dates", "travelers"], "mixed_baggage_pending": True,
    }
    r_phuket_yes = _post("כן, בואו נבחר כבודה אחידה", [], state_phuket_yes, member_phuket_yes)
tu_phuket_yes = r_phuket_yes.get("trip_update") or {}
check("Phuket yes-path: pending flag cleared, still nothing saved, normal "
      "3-option question asked next",
      not (tu_phuket_yes.get("guided") or {}).get("mixed_baggage_pending")
      and not (tu_phuket_yes.get("flight") or {}).get("baggage")
      and "תיק יד" in str(tu_phuket_yes.get("_guided_ask_hint") or ""))


# =====================================================================
# Phuket follow-up: customer answers "no" - keeps the EXISTING
# carry_on_only default, never an invented new value.
# =====================================================================
member_phuket_no = _make_member("qa-phuket-mixed-baggage-no@example.com")
with patch.object(chat, "_post_claude", side_effect=_fake_classifier_reply("false")):
    state_phuket_no = dict(PHUKET_STATE)
    state_phuket_no["guided"] = {
        "current_question": "baggage", "attempts": 0,
        "answered": ["dates", "travelers"], "mixed_baggage_pending": True,
    }
    r_phuket_no = _post("לא צריך, תשמרי משהו בסיסי", [], state_phuket_no, member_phuket_no)
tu_phuket_no = r_phuket_no.get("trip_update") or {}
check("Phuket no-path: saves the existing carry_on_only value, never a "
      "new/invented one, and moves on",
      (tu_phuket_no.get("flight") or {}).get("baggage") == ["carry_on_only"]
      and (tu_phuket_no.get("guided") or {}).get("current_question") != "baggage")


# =====================================================================
# Correction path: the model itself judges this answer as CORRECTING an
# earlier-mentioned baggage preference (result.correction set), but it is
# STILL mixed_per_passenger - handled identically to a first answer:
# nothing saved, pending flag set, same payment-time + yes/no hint.
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
check("correction path: the old carry_on_only value is NOT silently "
      "overwritten to checked_bag or anything else - it still stands "
      "until the yes/no question resolves",
      (tu_correction.get("flight") or {}).get("baggage") == ["carry_on_only"])
check("correction path: pending flag set, same payment-time + yes/no hint "
      "as a first answer",
      (tu_correction.get("guided") or {}).get("mixed_baggage_pending") is True
      and "התשלום" in correction_hint and "כן/לא" in correction_hint)


# =====================================================================
# Regression: a plain (non-mixed) uniform request resolving to checked_bag
# must NOT get any mixed-only hint text - _baggage_followup_hint's own
# "nothing to add" behavior for the top tier is unaffected.
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
check("regression: a plain uniform checked_bag request is unaffected - "
      "saved directly, no mixed-only wording leaks into its hint, and no "
      "pending flag is set",
      (tu_plain.get("flight") or {}).get("baggage") == ["checked_bag"]
      and "התשלום" not in plain_hint
      and not (tu_plain.get("guided") or {}).get("mixed_baggage_pending"))

if FAILED:
    print(f"\n{len(FAILED)} CHECK(S) FAILED:")
    for name in FAILED:
        print(f"  - {name}")
    sys.exit(1)
print("\nALL MIXED-BAGGAGE-WORDING TESTS PASSED")
