"""QA for dry-run 2 finding #5 (Shaked/Shlomo, 22.10.2026, qa/reports/
2026-10-22-dryrun2.md, Rovinj/Pula): a destination with no catalog entry
of its own (no commercial airport) needs the customer to pick a nearby
gateway airport - across all 10 turns of the live transcript,
destination_airports stayed None the entire conversation while the
nearby options (Pula/Zagreb) were only ever mentioned as plain
background info, competing unreliably against whatever else happened to
be open that turn (baggage, trip planning, accessibility) - and the final
summary still silently printed "נחיתה: פולה (PUY), קרואטיה", a specific
choice the customer never actually made or confirmed.

Shaked's own diagnosis/proposal (relayed by Shlomo): make this a gate on
state, mirroring the accessibility gate #143 already established, instead
of relying on a background hint alone.

Fix, mirroring #143's own pattern exactly:
- _destination_gateway_unresolved_places/_unresolved/_question_hint (new):
  state-only classification - a destination place with no catalog city OR
  country match, while destination_airports is still empty.
- _advance_sessions's ready_for_summary now also requires this resolved,
  alongside the existing _guided_incomplete_fields check.
- _turn_question_arbiter: a new candidate, checked just above the
  standing guided question (nothing else about the trip can be properly
  summarized without a landing airport).
- _force_guided_field_retry: extended to also retry on this condition
  when nothing else (guided) is open - used by both the premature-מאשרת
  and closing_claim safety nets.

Run: python3 tools/qa_dryrun2_destination_gateway_gate.py
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
            ("QA dryrun2 gateway gate", email, generate_password_hash("Test1234!"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
        )
        return cur.lastrowid


def _post(message, history, trip_state, member_id):
    with client.session_transaction() as sess:
        sess["member_id"] = member_id
    r = client.post("/api/ariella/chat-clean", json={
        "message": message, "history": history, "trip_state": trip_state,
    })
    return r.get_json()


# =====================================================================
# 1. Direct unit coverage.
# =====================================================================
check("Rovinj (no catalog entry, flights requested, no destination_airports yet): unresolved",
      chat._destination_gateway_unresolved({
          "destination": {"places": ["רוביני"]}, "requested_services": ["flights"],
      }))
check("once destination_airports is set (customer chose/confirmed PUY), no longer unresolved",
      not chat._destination_gateway_unresolved({
          "destination": {"places": ["רוביני"]}, "requested_services": ["flights"], "destination_airports": ["PUY"],
      }))
check("a catalog city (Valencia, post-020a or plain casefold match) is never flagged unresolved",
      not chat._destination_gateway_unresolved({
          "destination": {"places": ["ולנסיה"]}, "requested_services": ["flights"],
      }))
check("a bare country name is never flagged unresolved (no gateway question for a whole country)",
      not chat._destination_gateway_unresolved({
          "destination": {"places": ["קרואטיה"]}, "requested_services": ["flights"],
      }))
check("flights not actually requested: never flagged (nothing to resolve a gateway for)",
      not chat._destination_gateway_unresolved({
          "destination": {"places": ["רוביני"]}, "requested_services": ["lodging"],
      }))
check("no destination known at all: never flagged",
      not chat._destination_gateway_unresolved({"requested_services": ["flights"]}))

# =====================================================================
# 2. _advance_sessions: ready_for_summary must stay False while the
# gateway is unresolved, even with every domain complete/declined and
# accessibility (the OTHER cross-cutting gate) already answered.
# =====================================================================
_statuses_all_decided = {"flights": "complete", "lodging": "declined", "car": "declined", "trip_planning": "declined"}
_adv_gateway_unresolved = chat._advance_sessions({
    "session_status": dict(_statuses_all_decided),
    "destination": {"places": ["רוביני"]},
    "requested_services": ["flights"],
    "guided": {"answered": ["dates", "travelers", "baggage", "accessibility"]},
    "accessibility": {"needed": False},
    "dates": {"departure": "2027-07-02", "return": "2027-07-06"},
    "travelers": {"adults": 3},
})
check("_advance_sessions FIX: ready_for_summary stays False while the "
      "destination gateway is unresolved, even though every domain and "
      "accessibility are otherwise done",
      _adv_gateway_unresolved.get("ready_for_summary") is False)

_adv_gateway_resolved = chat._advance_sessions(dict(
    {k: v for k, v in _adv_gateway_unresolved.items() if k not in ("ready_for_summary", "missing_required", "next_session", "active_session")},
    destination_airports=["PUY"],
))
check("_advance_sessions: ready_for_summary correctly becomes True once "
      "destination_airports is also genuinely set",
      _adv_gateway_resolved.get("ready_for_summary") is True)

# =====================================================================
# 3. Arbiter priority: the gateway question wins over the plain standing
# guided question, but loses to a higher-priority direct continuation
# (shift/mixed-baggage/clarify).
# =====================================================================
check("arbiter: destination-gateway question wins over the plain standing guided question",
      chat._turn_question_arbiter({
          "destination": {"places": ["רוביני"]}, "requested_services": ["flights"],
          "_guided_ask_hint": "שאלת תקציב רגילה",
          "guided": {"mixed_baggage_pending": False},
      })[1] == "destination_gateway")
check("arbiter: a genuinely live shift candidate still wins over the destination-gateway question",
      chat._turn_question_arbiter({
          "destination": {"places": ["רוביני"]}, "requested_services": ["flights"],
          "_shift_candidate_hint": "שאלת הזזה",
      })[1] == "shift_candidate")

# =====================================================================
# 4. End-to-end HTTP: case E (Rovinj) - every domain complete/declined,
# gateway still unresolved, Tinkerbell's own reply falsely claims the
# handoff ("מעבירה אותך"). closing_claim's forced retry must ask the
# real gateway question, never let the false claim or a silent pick
# (e.g. "נחיתה: פולה" with no customer confirmation) through.
# =====================================================================
def _fake_rovinj_turn(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        return json.dumps({
            "trip_update": {}, "restart_request": False, "restart_evidence": None,
            "dates_evidence": None, "destination_evidence": None, "trip_type_evidence": None,
            "link_request": False, "link_request_evidence": None,
        })
    if source == "guided_extract":
        return json.dumps({"status": "other_topic", "field": None, "evidence": None})
    if source == "classifier":
        return "false"
    if source == "tinkerbell_reply":
        if "שדה התעופה הקרוב ביותר" in str(system_dynamic or ""):
            return "לפני שנסגור הכל - איזה שדה תעופה הכי נוח לכן, פולה או זאגרב?"
        return "בסדר גמור. מעבירה אותך לתוצאות הטיסה - ותמיד אפשר לחזור לכאן."
    return "{}"


member_e = _make_member("qa-dryrun2-rovinj@example.com")
with patch.object(chat, "_post_claude", side_effect=_fake_rovinj_turn):
    state_e = {
        "destination": {"places": ["רוביני"], "mode": "specific", "status": "known"},
        "active_session": None,
        "requested_services": ["flights"],
        "session_status": {"flights": "complete", "lodging": "declined", "car": "declined", "trip_planning": "declined"},
        "dates": {"departure": "2027-07-02", "return": "2027-07-06"},
        "travelers": {"adults": 3},
        "flight": {"baggage": ["carry_on_only"]},
        "trip_type": "leisure",
        "departure_airport": "TLV",
        "budget_per_person": 1100,
        "accessibility": {"needed": False},
        "guided": {"current_question": None, "answered": ["dates", "travelers", "baggage", "accessibility"], "mixed_baggage_pending": False},
        "next_session": None,
    }
    r_e = _post("לא", [{"role": "assistant", "content": "רוצים גם רכב?"}], state_e, member_e)
tu_e = r_e.get("trip_update") or {}
reply_e = str(r_e.get("reply") or "")
check("dry-run 2 case E (Rovinj) FIX: the false 'מעבירה אותך' claim never "
      "reaches the customer while the gateway is still genuinely unresolved",
      "מעבירה אותך" not in reply_e)
check("dry-run 2 case E (Rovinj) FIX: the forced retry actually asked "
      "about the real gateway choice",
      "פולה" in reply_e or "זאגרב" in reply_e)
check("dry-run 2 case E (Rovinj) FIX: destination_airports was never "
      "silently filled in without the customer's own confirmed choice",
      not tu_e.get("destination_airports"))
check("ready_for_summary correctly stayed False",
      tu_e.get("ready_for_summary") is False)

with sqlite3.connect(DB) as conn:
    conn.execute("DELETE FROM members WHERE email LIKE 'qa-dryrun2-%@example.com'")
    conn.commit()

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL DRY-RUN-2 DESTINATION-GATEWAY-GATE TESTS PASSED")
