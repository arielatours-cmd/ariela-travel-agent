"""QA for Bezalel's task 4, reworked per the business owner (22.10; PR #134
was rejected for filtering the model's finished reply by regex - never
allowed). After a switch to a checked suitcase (e.g. right after the
summary) the reply must not add "אפשר להוסיף גם תיק קטן... באתר חברת
התעופה". Now done BEFORE the reply is written:

  - _baggage_followup_hint(["checked_bag"]) returns an explicit "don't add
    any sentence about extra baggage" instruction (was None)
  - outside the guided dispatcher (it doesn't run once every domain is
    decided, i.e. after the summary) the same instruction is set as a
    one-turn hint (_baggage_note_hint) on the turn baggage switches to
    checked_bag, and reaches Tinkerbell's system_dynamic; cleared otherwise
  - no after-the-fact text filter exists any more

Offline (Claude stubbed). Run: python3 tools/qa_checked_bag_no_upsell_after_switch.py
"""
import json
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TMP = tempfile.mkdtemp(prefix="ariella-qa-upsell-")
os.environ.update({"DB_PATH": os.path.join(_TMP, "qa.db"), "SCHEDULER_ENABLED": "false", "SCANNER_ENABLED": "false",
                   "ANTHROPIC_API_KEY": "test-key-not-real"})

FAILED = []


def check(name, cond):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        FAILED.append(name)


import ariella_chat_clean as chat  # noqa: E402
import app as app_module  # noqa: E402
import database  # noqa: E402

NO_UPSELL = "אל תוסיפי שום משפט על הוספת כבודה נוספת"

# --- The hint itself ----------------------------------------------------------------------------
hint = chat._baggage_followup_hint(["checked_bag"]) or ""
check("checked_bag -> an explicit no-upsell instruction (not None any more)", NO_UPSELL in hint)
check("...it never itself suggests adding baggage", "שאפשר תמיד להוסיף" not in hint)
check("carry-on still gets the 'can add a suitcase' note (unchanged)",
      "שאפשר תמיד להוסיף מזוודה" in (chat._baggage_followup_hint(["carry_on_only"]) or ""))
check("hand bag still gets the 'can add a trolley or suitcase' note (unchanged)",
      "טרולי או מזוודה" in (chat._baggage_followup_hint(["personal_item"]) or ""))
plain = "מעולה, מזוודה לכל נוסע. מה התקציב?"
check("the code backup still adds nothing for a checked bag",
      chat._ensure_baggage_followup_note_present(plain, {"flight": {"baggage": ["checked_bag"]}}, {}) == plain)

# --- The hint reaches the model's context ---------------------------------------------------------
captured = {}


def capture(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    captured[source] = system_dynamic
    return "בסדר."


with patch.object(chat, "_post_claude", side_effect=capture):
    chat._call_tinkerbell("k", "m", [], "כן", {"_baggage_note_hint": hint, "flight": {"baggage": ["checked_bag"]}})
check("_baggage_note_hint is woven into Tinkerbell's system_dynamic", NO_UPSELL in (captured.get("tinkerbell_reply") or ""))

# --- End to end: post-summary switch trolley -> suitcase ---------------------------------------------
client = app_module.app.test_client()
with sqlite3.connect(database.DB_PATH) as conn:
    member_id = conn.execute(
        "INSERT INTO members (full_name,email,password_hash,created_at,status,whatsapp_opt_in,preferred_airports) "
        "VALUES('QA','qa-upsell@example.com','x',?,'active',0,'[]')", (datetime.now(timezone.utc).isoformat(),)).lastrowid
with client.session_transaction() as sess:
    sess["member_id"] = member_id

POST_SUMMARY = {
    "destination": {"places": ["קורפו"], "mode": "specific", "status": "known"},
    "requested_services": ["flights"], "active_session": None, "ready_for_summary": True,
    "session_status": {"flights": "complete", "lodging": "declined", "car": "declined", "trip_planning": "declined"},
    "dates": {"departure": "2026-09-21", "return": "2026-09-28"},
    "travelers": {"adults": 2}, "flight": {"baggage": ["carry_on_only"], "connection_preference": "direct"},
    "budget_per_person": {"amount": 1500, "currency": "ILS"},
}


def turn(state, extracted):
    seen = {}

    def fake(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
        seen.setdefault(source, system_dynamic)
        if source == "state_extractor":
            return json.dumps({"restart_request": False, "trip_update": extracted}, ensure_ascii=False)
        return "עדכנתי."

    with patch.object(chat, "_post_claude", side_effect=fake):
        r = client.post("/api/ariella/chat-clean", json={"message": "רגע, נעבור למזוודה לכל אחד", "history": [], "trip_state": state})
    return (r.get_json() or {}), seen


data, seen = turn(POST_SUMMARY, {"flight": {"baggage": ["checked_bag"]}})
tu = data.get("trip_update") or {}
check("e2e: baggage switched to checked_bag in state", "checked_bag" in ((tu.get("flight") or {}).get("baggage") or []))
check("e2e: the reply was written WITH the no-upsell instruction in its context",
      NO_UPSELL in (seen.get("tinkerbell_reply") or ""))

data2, seen2 = turn(dict(tu), {})
check("e2e: next turn (baggage unchanged) -> the one-turn hint is gone",
      NO_UPSELL not in (seen2.get("tinkerbell_reply") or "") and "_baggage_note_hint" not in (data2.get("trip_update") or {}))

# --- The rejected text filter is gone ----------------------------------------------------------------
src = open(os.path.join(os.path.dirname(__file__), "..", "ariella_chat_clean.py"), encoding="utf-8").read()
check("_strip_upsell_note_for_checked_bag and _BAGGAGE_UPSELL_SENTENCE_RE are removed",
      "_strip_upsell_note_for_checked_bag" not in src and "_BAGGAGE_UPSELL_SENTENCE_RE" not in src)

print()
print("ALL PASS" if not FAILED else f"{len(FAILED)} FAILED: {FAILED}")
sys.exit(1 if FAILED else 0)
