"""QA for dry-run 5h's severe finding (23.10.2026, Shaked's live finding,
business owner's explicit directive relayed by Shlomo): once a destination
is already resolved, an explicit customer correction naming a real,
different destination ("ברגן, בנורווגיה" after Bergamo/BGY was already
saved) did not stick - Ariella's own reply confirmed the correction in
text ("אעדכן את זה"), but destination_airports stayed the old value and
the final summary still showed the wrong city.

Investigated and ruled out: _guard_destination_change_evidence itself
works correctly (verified directly, both with and without destination_
evidence) - the gap is upstream: the general EXTRACTOR_SYSTEM call does
not reliably supply a verified destination_evidence quote for this kind
of correction, even when its own reply text plainly recognizes it.

Fixed per the business owner's explicit directive (model recognition +
catalog verification, never a word list): _reinforce_explicit_destination_
correction, a single dedicated classifier call - same architecture as
_destination_gateway_answer_by_meaning - that runs ONLY when destination_
airports is already resolved AND the raw extractor's own destination_
evidence did not already verify. Wired in right before _guard_destination_
change_evidence, so that guard's own unchanged logic then sees genuine
evidence and lets the change through.

Run: python3 tools/qa_dryrun5h_explicit_destination_correction.py
"""
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")
os.environ.setdefault("SCHEDULER_ENABLED", "false")

from unittest.mock import patch
import ariella_chat_clean as chat

FAILED = []


def check(name, cond):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        FAILED.append(name)


TRIP_STATE_BGY = {"destination_airports": ["BGY"], "destination": {"places": ["ברגמו"]}}
TRIP_UPDATE_BGY = {"destination_airports": ["BGY"], "destination": {"places": ["ברגמו"]}}


def _fake_correction(evidence, candidate):
    def fake(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other", **kw):
        if source == "classifier":
            return json.dumps({"evidence": evidence, "candidate": candidate})
        return "{}"
    return fake


# =====================================================================
# 1. The live repro: a genuine, verbatim, catalog-verified correction to
#    a DIFFERENT real destination is accepted - destination_evidence is
#    set so the next guard call lets the change through.
# =====================================================================
with patch.object(chat, "_post_claude", side_effect=_fake_correction(
        "ברגן, בנורווגיה", {"city_en": "Bergen", "iata_code": "BGO"})):
    update, evidence = chat._reinforce_explicit_destination_correction(
        TRIP_STATE_BGY, dict(TRIP_UPDATE_BGY), None, "לא, בעצם ברגן, בנורווגיה")
check("dry-run 5h FIX: a genuine explicit correction resolves to the new destination",
      update.get("destination_airports") == ["BGO"] and update.get("destination", {}).get("places") == ["ברגן"])
check("dry-run 5h FIX: destination_evidence is set to the verified quote for the next guard call",
      evidence == "ברגן, בנורווגיה")

# =====================================================================
# 2. Cost control: destination_airports not yet resolved - a "correction"
#    isn't meaningful yet, never fires the extra call.
# =====================================================================
calls = []
def _counting_fake(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other", **kw):
    calls.append(1)
    return "{}"
with patch.object(chat, "_post_claude", side_effect=_counting_fake):
    update_unresolved, evidence_unresolved = chat._reinforce_explicit_destination_correction(
        {"destination_airports": []}, {}, None, "ברגן, בנורווגיה")
check("dry-run 5h: destination not yet resolved - no-op, never calls the model",
      update_unresolved == {} and evidence_unresolved is None and len(calls) == 0)

# =====================================================================
# 3. Cost control: the extractor's own destination_evidence already
#    verifies - the common, already-working case is left untouched, no
#    extra model call spent.
# =====================================================================
calls2 = []
def _counting_fake2(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other", **kw):
    calls2.append(1)
    return "{}"
with patch.object(chat, "_post_claude", side_effect=_counting_fake2):
    update_already, evidence_already = chat._reinforce_explicit_destination_correction(
        TRIP_STATE_BGY, dict(TRIP_UPDATE_BGY), "ברגן, בנורווגיה", "לא, בעצם ברגן, בנורווגיה")
check("dry-run 5h: extractor's own evidence already verifies - no extra classifier call, "
      "evidence passed through unchanged",
      len(calls2) == 0 and evidence_already == "ברגן, בנורווגיה")

# =====================================================================
# 4. No correction in the message at all - nothing changes.
# =====================================================================
with patch.object(chat, "_post_claude", side_effect=_fake_correction(None, None)):
    update_none, evidence_none = chat._reinforce_explicit_destination_correction(
        TRIP_STATE_BGY, dict(TRIP_UPDATE_BGY), None, "אני רוצה גם לינה")
check("dry-run 5h regression: no explicit correction in the message - nothing changes",
      update_none == TRIP_UPDATE_BGY and evidence_none is None)

# =====================================================================
# 5. Fabricated/invented evidence (not verbatim in the message) - rejected
#    by the same verbatim-evidence gate used everywhere else.
# =====================================================================
with patch.object(chat, "_post_claude", side_effect=_fake_correction(
        "משהו שלא נאמר בהודעה בכלל", {"city_en": "Bergen", "iata_code": "BGO"})):
    update_fab, evidence_fab = chat._reinforce_explicit_destination_correction(
        TRIP_STATE_BGY, dict(TRIP_UPDATE_BGY), None, "לא, בעצם ברגן, בנורווגיה")
check("dry-run 5h regression: fabricated evidence not actually in the message is rejected",
      update_fab == TRIP_UPDATE_BGY and evidence_fab is None)

# =====================================================================
# 6. The "candidate" is the SAME destination already resolved - not
#    actually a correction, nothing changes.
# =====================================================================
with patch.object(chat, "_post_claude", side_effect=_fake_correction(
        "כן, ברגמו מתאים", {"city_en": "Bergamo", "iata_code": "BGY"})):
    update_same, evidence_same = chat._reinforce_explicit_destination_correction(
        TRIP_STATE_BGY, dict(TRIP_UPDATE_BGY), None, "כן, ברגמו מתאים")
check("dry-run 5h regression: a 'correction' to the SAME already-resolved destination is a no-op",
      update_same == TRIP_UPDATE_BGY and evidence_same is None)

# =====================================================================
# 7. The candidate fails catalog verification (invented code/city) -
#    never trusted on the model's claim alone.
# =====================================================================
with patch.object(chat, "_post_claude", side_effect=_fake_correction(
        "לא, בעצם לאיזשהו מקום אחר", {"city_en": "Nonexistentville", "iata_code": "ZZZ"})):
    update_bad, evidence_bad = chat._reinforce_explicit_destination_correction(
        TRIP_STATE_BGY, dict(TRIP_UPDATE_BGY), None, "לא, בעצם לאיזשהו מקום אחר")
check("dry-run 5h regression: an uncatalogued/invented candidate is rejected",
      update_bad == TRIP_UPDATE_BGY and evidence_bad is None)

# =====================================================================
# 8. End-to-end through the real /api/ariella/chat-clean endpoint - the
#    exact live failure shape (extractor supplies no destination_evidence
#    for the correction, Tinkerbell's reply still confirms it in text).
# =====================================================================
import database
database.init_db()
import app as app_module
from datetime import datetime, timezone
from werkzeug.security import generate_password_hash
import sqlite3

DB = database.DB_PATH
client = app_module.app.test_client()


def _make_member(email):
    with sqlite3.connect(DB) as conn:
        conn.execute("DELETE FROM members WHERE email=?", (email,))
        conn.commit()
        cur = conn.execute(
            "INSERT INTO members (full_name,email,password_hash,created_at,status,whatsapp_opt_in,preferred_airports) "
            "VALUES(?,?,?,?,?,?,?)",
            ("QA Explicit Correction", email, generate_password_hash("Test1234!"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
        )
        return cur.lastrowid


member_id = _make_member("qa-explicit-destination-correction@example.com")
with client.session_transaction() as sess:
    sess["member_id"] = member_id

E2E_STATE = {
    "destination_airports": ["BGY"], "destination": {"places": ["ברגמו"], "mode": "specific", "status": "known"},
    "requested_services": ["flights"], "service_decisions": {"flights": {"wanted": True, "source": "x"}},
}


def _fake_e2e(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other", **kw):
    if source == "state_extractor":
        return json.dumps({
            "restart_request": None, "restart_evidence": None, "dates_evidence": None,
            "destination_evidence": None, "trip_type_evidence": None,
            "relative_date_hint": None, "relative_date_hint_evidence": None,
            "link_request": None, "link_request_evidence": None, "baggage_evidence": None,
            "mentions_medical_reason": False,
            "trip_update": {},
        })
    if source == "classifier":
        return json.dumps({"evidence": "ברגן, בנורווגיה", "candidate": {"city_en": "Bergen", "iata_code": "BGO"}})
    return "אעדכן את זה."


with patch.object(chat, "_post_claude", side_effect=_fake_e2e):
    resp_e2e = client.post("/api/ariella/chat-clean", json={
        "message": "לא, בעצם ברגן, בנורווגיה", "history": [], "trip_state": E2E_STATE,
    })
tu_e2e = (resp_e2e.get_json() or {}).get("trip_update") or {}
check("dry-run 5h e2e (real endpoint): the explicit correction is actually saved to destination_airports",
      tu_e2e.get("destination_airports") == ["BGO"])
check("dry-run 5h e2e (real endpoint): destination.places reflects the catalog's verified spelling",
      tu_e2e.get("destination", {}).get("places") == ["ברגן"])

with sqlite3.connect(DB) as conn:
    conn.execute("DELETE FROM members WHERE email='qa-explicit-destination-correction@example.com'")
    conn.commit()

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL DRYRUN5H-EXPLICIT-DESTINATION-CORRECTION TESTS PASSED")
