"""QA for Shaked's stage-3 run-5 report (qa/reports/2026-10-18-stage3-run5.md,
main @9588047, 1/5 passed), sent directly 18.10.2026, then prioritized by
Shlomo the same day with the exact mechanism to use for item 1. Covers the
items fixed this round:

item 1 (s3z4, Palermo, MOST SEVERE per Shlomo) - a plain "כן" answering an
unrelated trip_planning yes/no question was followed by destination_
airports silently replaced with an entirely unrelated list (SZG/PRG/CAI/
SSH - no overlap with Palermo/Italy at all). Per Shlomo's explicit
directive: destination (places) and destination_airports that are already
set are never replaced without a genuine customer quote that changes them -
the same evidence mechanism as dates_evidence. Added:
- destination_evidence, a new top-level JSON sibling of trip_update
  (alongside restart_evidence/dates_evidence), and _guard_destination_
  change_evidence - a code-level lock mirroring the sticky-dates fix:
  once destination.places and/or destination_airports is already set, the
  extractor's own claimed change is accepted only with a verbatim quote
  behind it; otherwise both fields revert to their prior values. Also
  records a "destination_change" diagnostic (structured values only -
  airport codes, place names - never the customer's own free-text
  message) so a live failure of this same mechanism is visible.
- Also in the same report: "עד 350 אירו לאדם" saved with currency=ILS.
  Root cause (verifiable offline, a real code bug, not a live-model
  mystery): every currency-detection regex in the codebase matched only
  the more standard Hebrew spelling "יורו" for euro, never the equally
  common alternate spelling "אירו" Shaked's own repro actually used - it
  fell through to the silent ILS default every time. Fixed in both
  _CURRENCY_MARKERS and _deterministic_budget_facts's own regex. Also
  hardened _budget_answer_by_meaning (the semantic classifier path) to
  derive currency from the customer's own message text FIRST (the real
  quote) before ever trusting the classifier's "currency" guess or
  falling back to ILS - per Shlomo's "currency saved only per quote"
  directive.

item 2 (rsn3) - a real mid-conversation date correction ("רגע, בעצם מה-11
עד ה-16 בפברואר") still didn't persist live even though PR #87's dates_
evidence mechanism was fully implemented and unit-tested against a mocked
model. Per Shlomo's own lead: dates_evidence (and now destination_
evidence) were the LAST JSON keys after the full trip_update object (many
nested fields) with only a 700-token budget - a live truncation risk this
offline suite can't see. Fixed: moved all four evidence siblings (restart_
request/restart_evidence/dates_evidence/destination_evidence) to the FRONT
of the JSON schema, before trip_update, and raised the token budget 700->
900. Also added:
- A new diagnostic event "dates_change" (present/verified), recorded at
  the exact point the sticky-dates block decides whether to trust the
  extractor's own claimed range.
- A new TINKERBELL_SYSTEM rule (Shaked's second ask, confirmed by Shlomo):
  Ariella/Tinkerbell must never confirm a change ("עדכנתי", "שיניתי ל...")
  unless the new value genuinely exists in the state she received this
  turn - the explicit mirror of the already-existing "never claim already
  recorded" rule, for the "claims an unsaved change succeeded" case.

Other stage-3 run-5 findings (items 3/4: rsn1/rsn2 restart-gate miss +
seed-from-trigger-message bug, s3z3 "מלא" pace misclassification, s3z2/
s3z5 premature travelers-confirmation, duplicate region question, duplicate
car summary sentence) are NOT addressed in this file - a separate, later
round per the volume of this run's report.

Run: python3 tools/qa_stage3_run5_diagnostics.py
"""
import os
import sys
import json
import sqlite3
from datetime import datetime, timezone
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import database
database.init_db()

import ariella_chat_clean as chat
import whatsapp_bridge
import ai_usage
from werkzeug.security import generate_password_hash

DB = database.DB_PATH
FAILED = []


def _make_member(email):
    with sqlite3.connect(DB) as conn:
        conn.execute("DELETE FROM members WHERE email=?", (email,))
        conn.commit()
        cur = conn.execute(
            "INSERT INTO members (full_name,email,password_hash,created_at,status,whatsapp_opt_in,preferred_airports) "
            "VALUES(?,?,?,?,?,?,?)",
            ("QA Stage3 Run5", email, generate_password_hash("Test1234!"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
        )
        return cur.lastrowid


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


# =====================================================================
# item 1a: destination/destination_airports evidence-gated lock (Palermo).
# =====================================================================
check("destination_change registered as a valid diagnostic event source",
      "destination_change" in ai_usage.DIAGNOSTIC_EVENT_SOURCES)
check("EXTRACTOR_SYSTEM documents destination_evidence as a top-level sibling of trip_update",
      '"destination_evidence"' in chat.EXTRACTOR_SYSTEM)
check("the four evidence siblings are schema-ordered before trip_update (truncation-safe)",
      chat.EXTRACTOR_SYSTEM.index('"destination_evidence"') < chat.EXTRACTOR_SYSTEM.index('"trip_update"'))

# Direct unit test of the guard function itself.
_palermo_state = {
    "destination": {"places": ["פלרמו"], "mode": "specific", "status": "known"},
    "destination_airports": ["PMO"],
}
_hallucinated = {
    "destination": {"places": ["פלרמו"], "mode": "specific", "status": "known"},
    "destination_airports": ["SZG", "PRG", "CAI", "SSH"],
}
_locked = chat._guard_destination_change_evidence(_palermo_state, dict(_hallucinated), None, "כן")
check("item 1a: an ungrounded destination_airports replacement (no evidence quote) is reverted to the prior value",
      _locked.get("destination_airports") == ["PMO"])

_genuine_change = {
    "destination": {"places": ["רומא"], "mode": "specific", "status": "known"},
    "destination_airports": ["FCO"],
}
_accepted = chat._guard_destination_change_evidence(
    _palermo_state, dict(_genuine_change), "בעצם רומא", "רגע, בעצם רומא, לא פלרמו"
)
check("item 1a: a genuinely quoted destination change is accepted, not reverted",
      _accepted.get("destination_airports") == ["FCO"]
      and _accepted.get("destination", {}).get("places") == ["רומא"])

_no_prior_state = {"destination": {"places": []}, "destination_airports": []}
_first_time = chat._guard_destination_change_evidence(_no_prior_state, dict(_genuine_change), None, "רומא")
check("regression: the FIRST time destination/airports are set (nothing to protect yet) is never blocked",
      _first_time.get("destination_airports") == ["FCO"])

# End-to-end through the real pipeline.
m_airports = _make_member("qa-stage3run5-airports@example.com")
airports_state = {
    "destination": {"places": ["פלרמו"], "mode": "specific", "status": "known"},
    "destination_airports": ["PMO"],
    "travelers": {"adults": 2},
    "dates": {"departure": "2027-06-10", "return": "2027-06-17", "needs_confirmation": False},
    "requested_services": ["flights"],
    "session_status": {"flights": "active", "lodging": "pending", "car": "pending", "trip_planning": "pending"},
    "active_session": "flights",
}
database.save_ariella_conversation(m_airports, [
    {"role": "user", "content": "פלרמו, זוג, 10-17 ביוני 2027"},
    {"role": "assistant", "content": "קלטתי - פלרמו. לתכנן גם מסלול ואטרקציות?"},
], dict(airports_state))


def _fake_post_claude_airports(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        return json.dumps({
            "trip_update": {"destination_airports": ["SZG", "PRG", "CAI", "SSH"]},
            "restart_request": False, "restart_evidence": None, "dates_evidence": None,
            "destination_evidence": None,
        })
    if source == "guided_extract":
        return json.dumps({"status": "other_topic", "field": None, "evidence": None})
    if source == "tinkerbell_reply":
        return "תשובה לדוגמה."
    return "{}"


with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_airports):
    whatsapp_bridge.ariella_turn(m_airports, "כן")
_state_after = (database.load_ariella_conversation(m_airports) or {}).get("trip_state") or {}
check("item 1a end-to-end: an ungrounded extractor claim never actually overwrites destination_airports live",
      _state_after.get("destination_airports") == ["PMO"])
_airport_rows = [
    r for r in ai_usage.diagnostic_rows("destination_change", include_test=True)
    if r.get("member_id") == m_airports
]
check("a destination_change diagnostic row was written for the blocked attempt",
      bool(_airport_rows) and json.loads(_airport_rows[0]["details"]).get("verified") is False)
check("no diagnostic row anywhere contains the customer's own message text",
      all("כן" != (r.get("details") or "") for r in _airport_rows))

# Regression: an ordinary turn where destination_airports is untouched must
# never write a spurious diagnostic row.
m_airports_quiet = _make_member("qa-stage3run5-airports-quiet@example.com")
database.save_ariella_conversation(m_airports_quiet, [
    {"role": "user", "content": "פלרמו, זוג, 10-17 ביוני 2027"},
    {"role": "assistant", "content": "קלטתי - פלרמו. איזו כבודה תצטרכו?"},
], dict(airports_state))


def _fake_post_claude_quiet(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        return json.dumps({"trip_update": {}, "restart_request": False, "restart_evidence": None, "dates_evidence": None, "destination_evidence": None})
    if source == "guided_extract":
        return json.dumps({"status": "answered", "no_baggage": True, "items": [], "confidence": "high", "also_mentioned": {}})
    if source == "tinkerbell_reply":
        return "תשובה לדוגמה."
    return "{}"


with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_quiet):
    whatsapp_bridge.ariella_turn(m_airports_quiet, "בלי כבודה")
_quiet_rows = [
    r for r in ai_usage.diagnostic_rows("destination_change", include_test=True)
    if r.get("member_id") == m_airports_quiet
]
check("regression: a turn that never touches destination/destination_airports writes no destination_change row",
      not _quiet_rows)

# Shaked's stage-1/2 regression (20.10, s12x6, live main@9588047, AFTER this
# same evidence mechanism was already merged in PR #87): "לליסבון... לא,
# סליחה, לפורטו" - Ariella said "שיניתי" (changed it) but places stayed
# ['ליסבון'] and airports stayed ['LIS']. A genuinely quoted correction like
# this one must be ACCEPTED, not just an ungrounded claim blocked - the two
# live symptoms (never persisting vs. never being overridden) are opposite
# failure modes of the same mechanism, and both must be covered.
m_lisbon_porto = _make_member("qa-stage3run5-lisbon-porto@example.com")
lisbon_state = {
    "destination": {"places": ["ליסבון"], "mode": "specific", "status": "known"},
    "destination_airports": ["LIS"],
    "travelers": {"adults": 2},
    "dates": {"departure": "2027-04-10", "return": "2027-04-14", "needs_confirmation": False},
    "requested_services": ["flights"],
    "session_status": {"flights": "active", "lodging": "pending", "car": "pending", "trip_planning": "pending"},
    "active_session": "flights",
}
database.save_ariella_conversation(m_lisbon_porto, [
    {"role": "user", "content": "ללישבון, זוג, 10-14 באפריל 2027"},
    {"role": "assistant", "content": "קלטתי - ליסבון. איזו כבודה תצטרכו?"},
], dict(lisbon_state))


def _fake_post_claude_lisbon_porto(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        return json.dumps({
            "trip_update": {"destination": {"places": ["פורטו"], "mode": "specific", "status": "known"}, "destination_airports": ["OPO"]},
            "restart_request": False, "restart_evidence": None, "dates_evidence": None,
            "destination_evidence": "לא, סליחה, לפורטו",
        })
    if source == "guided_extract":
        return json.dumps({"status": "other_topic", "field": None, "evidence": None})
    if source == "tinkerbell_reply":
        return "שיניתי לפורטו."
    return "{}"


with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_lisbon_porto):
    whatsapp_bridge.ariella_turn(m_lisbon_porto, "לליסבון... לא, סליחה, לפורטו")
_lisbon_porto_state = (database.load_ariella_conversation(m_lisbon_porto) or {}).get("trip_state") or {}
check("regression (Shaked's live s12x6): a genuinely quoted destination correction "
      "('לא, סליחה, לפורטו') IS accepted - the destination actually changes to Porto",
      _lisbon_porto_state.get("destination", {}).get("places") == ["פורטו"]
      and _lisbon_porto_state.get("destination_airports") == ["OPO"])


# =====================================================================
# item 1b: currency "אירו" spelling bug (same Palermo report).
# =====================================================================
check("item 1b: _CURRENCY_MARKERS recognizes the alternate euro spelling 'אירו', not just 'יורו'",
      __import__("re").search(chat._CURRENCY_MARKERS["EUR"], "350 אירו") is not None)
_budget_facts = chat._deterministic_budget_facts("עד 350 אירו לאדם")
check("item 1b: _deterministic_budget_facts now saves 'אירו' as EUR, not the silent ILS default",
      _budget_facts.get("budget_per_person", {}).get("currency") == "EUR"
      and _budget_facts.get("budget_per_person", {}).get("amount") == 350)
# Regression: the original spelling and other currencies still work.
check("regression: the standard 'יורו' spelling still resolves to EUR",
      chat._deterministic_budget_facts("עד 300 יורו לאדם").get("budget_per_person", {}).get("currency") == "EUR")
check("regression: dollar amounts still resolve to USD",
      chat._deterministic_budget_facts("תקציב 400 דולר").get("budget_per_person", {}).get("currency") == "USD")
check("regression: a bare shekel amount with no currency word still defaults to ILS (the one case a "
      "silent default is actually correct)",
      chat._deterministic_budget_facts("תקציב 1000 לאדם").get("budget_per_person", {}).get("currency") == "ILS")


# =====================================================================
# item 2: dates_change diagnostic event + Tinkerbell confirm-grounding rule.
# =====================================================================
check("dates_change registered as a valid diagnostic event source",
      "dates_change" in ai_usage.DIAGNOSTIC_EVENT_SOURCES)
check("new TINKERBELL_SYSTEM rule: never confirm a change unless the new value "
      "genuinely exists in the state received this turn",
      "מאותה סיבה בדיוק, גם כשהלקוח מבקש לתקן" in chat.TINKERBELL_SYSTEM
      and "אסור לך לומר או לרמוז שהשינוי כבר בוצע" in chat.TINKERBELL_SYSTEM)

ai_usage.set_ai_usage_context(member_id=None, is_test=True)
ai_usage.record_diagnostic_event("dates_change", {"present": True, "verified": False})
_rows = ai_usage.diagnostic_rows("dates_change", include_test=True)
check("dates_change: a row was written and comes back via diagnostic_rows",
      bool(_rows) and json.loads(_rows[0]["details"]) == {"present": True, "verified": False})
ai_usage.clear_ai_usage_context()

m_datechange = _make_member("qa-stage3run5-dateschange@example.com")
datechange_state = {
    "destination": {"places": ["רומא"], "mode": "specific", "status": "known"},
    "destination_airports": ["FCO"],
    "travelers": {"adults": 2},
    "dates": {"departure": "2027-02-10", "return": "2027-02-14", "needs_confirmation": False},
    "requested_services": ["flights"],
    "session_status": {"flights": "active", "lodging": "pending", "car": "pending", "trip_planning": "pending"},
    "active_session": "flights",
    "guided": {"current_question": "travelers", "attempts": 0, "answered": ["dates"]},
}
database.save_ariella_conversation(m_datechange, [
    {"role": "user", "content": "רומא, 10-14 בפברואר 2027"},
    {"role": "assistant", "content": "קלטתי - רומא, 10-14 בפברואר. כמה נוסעים?"},
], dict(datechange_state))


def _fake_post_claude_present_not_verified(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        return json.dumps({
            "trip_update": {"dates": {"departure": "2027-02-11", "return": "2027-02-16"}},
            "restart_request": False, "restart_evidence": None,
            "dates_evidence": "ציטוט שלא קיים בהודעה בכלל", "destination_evidence": None,
        })
    if source == "guided_extract":
        return json.dumps({"status": "other_topic", "field": None, "evidence": None})
    if source == "tinkerbell_reply":
        return "תשובה לדוגמה."
    return "{}"


with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_present_not_verified):
    whatsapp_bridge.ariella_turn(m_datechange, "רגע, בעצם מה-11 עד ה-16 בפברואר")
_change_rows = [
    r for r in ai_usage.diagnostic_rows("dates_change", include_test=True)
    if r.get("member_id") == m_datechange
]
check("end-to-end: a real turn where the extractor claims a differing date range "
      "without a verifying quote writes present=true, verified=false",
      bool(_change_rows) and json.loads(_change_rows[0]["details"]) == {"present": True, "verified": False})
check("regression: the sticky-dates lock still holds the prior range when the "
      "claimed change isn't verified",
      (database.load_ariella_conversation(m_datechange) or {}).get("trip_state", {}).get("dates", {}).get("departure") == "2027-02-10")

m_datechange_none = _make_member("qa-stage3run5-dateschange-none@example.com")
database.save_ariella_conversation(m_datechange_none, [
    {"role": "user", "content": "רומא, 10-14 בפברואר 2027"},
    {"role": "assistant", "content": "קלטתי - רומא, 10-14 בפברואר. כמה נוסעים?"},
], dict(datechange_state))


def _fake_post_claude_no_change(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        return json.dumps({"trip_update": {}, "restart_request": False, "restart_evidence": None, "dates_evidence": None, "destination_evidence": None})
    if source == "guided_extract":
        return json.dumps({"status": "answered", "adults": 2, "children": 0, "confidence": "high", "also_mentioned": {}})
    if source == "tinkerbell_reply":
        return "תשובה לדוגמה."
    return "{}"


with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_no_change):
    whatsapp_bridge.ariella_turn(m_datechange_none, "שנינו מבוגרים")
_none_rows = [
    r for r in ai_usage.diagnostic_rows("dates_change", include_test=True)
    if r.get("member_id") == m_datechange_none
]
check("regression: an ordinary turn with no claimed date change records present=false, "
      "verified=null (distinguishes 'never attempted' from 'attempted but unverified')",
      bool(_none_rows) and json.loads(_none_rows[0]["details"]) == {"present": False, "verified": None})

_secret_message_dates = "רגע, בעצם מה-11 עד ה-16 בפברואר - זה סודי"
m_datechange_secret = _make_member("qa-stage3run5-dateschange-secret@example.com")
database.save_ariella_conversation(m_datechange_secret, [
    {"role": "user", "content": "רומא, 10-14 בפברואר 2027"},
    {"role": "assistant", "content": "קלטתי - רומא, 10-14 בפברואר. כמה נוסעים?"},
], dict(datechange_state))
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_present_not_verified):
    whatsapp_bridge.ariella_turn(m_datechange_secret, _secret_message_dates)
_all_dates_change_rows = ai_usage.diagnostic_rows("dates_change", include_test=True)
check("no diagnostic row anywhere contains the customer's own message text",
      all(_secret_message_dates not in (r.get("details") or "") for r in _all_dates_change_rows))

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL STAGE3-RUN5-DIAGNOSTICS TESTS PASSED")
