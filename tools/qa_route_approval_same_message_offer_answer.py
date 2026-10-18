"""QA for round-8 item #2 (Shaked, 2026-10-16, qa/reports/2026-10-16-round8-conversation.md,
A5, London, "all services"): details stated in the SAME message that
approves a just-proposed route were swallowed.

Live transcript: Ariella proposed a day-by-day route ending in "מתאים לך
ככה, או שתרצי לשנות משהו?". The customer answered "כן, מלון 4 כוכבים
במרכז" - approving the route AND stating a lodging preference in one
message (reasonable, since she'd already asked for every service up
front). Ariella replied "מצוין, המסלול מאושר. תרצי שאמשיך גם עם לינה?" -
the exact same "do you want lodging too?" offer, as if nothing had been
said about lodging at all. The star rating and area were gone for good.

Root cause: chat_clean()'s planning_accept branch, once it determines
lodging is the next undecided domain, unconditionally asked the generic
yes/no offer and stashed post_flight_offer=["lodging"] for the NEXT turn
to answer - never checking whether the CURRENT approval message already
answered that very offer itself.

Fixed: before falling back to the generic offer, the same message is run
through the existing _post_flight_offer_answer classifier (the same one
that handles a plain "כן"/"לא" on the FOLLOWING turn) against the
about-to-be-asked domain. A decisive true/false result settles the domain
immediately (mirroring the existing "already active" branch) instead of
re-asking a question the customer already answered.

Updated per Shaked's stage-2 run-2 finding (0/5, 2f9b859, qa/reports/
2026-10-17-stage2-run2.md): the extra classifier call was originally
gated on "the message has 3+ alnum characters left after stripping known
acceptance words" (_approval_message_has_extra_content). That gate was
too loose - "מושלם, מתאים לנו" strips down to "לנו" (3 chars), which says
nothing about lodging/car, yet was enough to invoke the classifier, which
then had to guess a decision with nothing to go on. Its answer came back
tagged source="post_flight_offer" - a recognized explicit-decision tag -
so the separate revert guard (which only reverts an untagged decision)
left the hallucinated result in place. Now the classifier is only invoked
when the message actually names the domain being decided (the same
_service_name_words regex the revert guard uses). A bare acceptance word,
or one with unrelated filler ("מושלם, מתאים לנו"), is left exactly as
before: the generic yes/no offer is asked and post_flight_offer is set
for the next turn to answer.

Run: python3 tools/qa_route_approval_same_message_offer_answer.py
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


def _fake_post_claude(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        return "{}"
    if source == "classifier":
        # A correctly-behaving post_flight_offer classifier on the combined
        # reply: an unambiguous yes to lodging, extra detail notwithstanding.
        return '{"lodging": true}'
    return "תשובה לדוגמה."


def _fake_post_claude_decline(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        return "{}"
    if source == "classifier":
        return '{"lodging": false}'
    return "תשובה לדוגמה."


def _make_member(email):
    with sqlite3.connect(DB) as conn:
        conn.execute("DELETE FROM members WHERE email=?", (email,))
        conn.commit()
        cur = conn.execute(
            "INSERT INTO members (full_name,email,password_hash,created_at,status,whatsapp_opt_in,preferred_airports) "
            "VALUES(?,?,?,?,?,?,?)",
            ("QA Route Offer Answer", email, generate_password_hash("Test1234!"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
        )
        return cur.lastrowid


ROUTE_TEXT = (
    "יום 1, 1.6.2027 (שלישי)\nנחיתה בלונדון.\n\n"
    "יום 2, 2.6.2027 (רביעי)\nסיור בעיר.\n\n"
    "מתאים לך ככה, או שתרצי לשנות משהו?"
)
HISTORY = [
    {"role": "user", "content": "אני רוצה מסלול ללונדון, כל השירותים"},
    {"role": "assistant", "content": "ספרי לי קצת על המסלול שאתם מדמיינים?"},
    {"role": "user", "content": "מתאים"},
    {"role": "assistant", "content": ROUTE_TEXT},
]
STATE_BEFORE_APPROVAL = {
    "destination": {"places": ["לונדון"], "mode": "specific", "status": "known"},
    "active_session": "trip_planning",
    "requested_services": ["trip_planning", "lodging", "car", "flights"],
    "session_status": {"flights": "complete", "lodging": "pending", "car": "pending", "trip_planning": "active"},
}

# --- Shaked's exact live repro: "כן + details" must not be swallowed ---
member_id = _make_member("qa-route-offer-answer@example.com")
with client.session_transaction() as sess:
    sess["member_id"] = member_id

with patch.object(chat, "_post_claude", side_effect=_fake_post_claude):
    r = client.post("/api/ariella/chat-clean", json={
        "message": "כן, מלון 4 כוכבים במרכז", "history": HISTORY, "trip_state": dict(STATE_BEFORE_APPROVAL),
    })
data = r.get_json()
tu = data.get("trip_update") or {}
check("the route is still approved",
      (tu.get("trip_planning") or {}).get("approved") is True)
check("the reply no longer re-asks the generic lodging offer",
      "תרצי שאמשיך גם עם" not in str(data.get("reply") or ""))
check("lodging became active instead of staying pending",
      (tu.get("session_status") or {}).get("lodging") == "active")
check("lodging was added to requested_services",
      "lodging" in (tu.get("requested_services") or []))
check("active_session moved to lodging",
      tu.get("active_session") == "lodging")
check("no stale post_flight_offer left dangling",
      not tu.get("post_flight_offer"))

# --- Regression: a bare "מתאים" (nothing extra) must still ask the normal
#     yes/no offer and set post_flight_offer for the next turn, exactly as
#     before - no behavior change for the common case ---
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude):
    r2 = client.post("/api/ariella/chat-clean", json={
        "message": "מתאים", "history": HISTORY, "trip_state": dict(STATE_BEFORE_APPROVAL),
    })
data2 = r2.get_json()
tu2 = data2.get("trip_update") or {}
check("regression: a bare 'מתאים' still asks the generic lodging offer",
      "תרצי שאמשיך גם עם" in str(data2.get("reply") or ""))
check("regression: a bare 'מתאים' still leaves lodging pending (nothing to settle)",
      (tu2.get("session_status") or {}).get("lodging") == "pending")
check("regression: a bare 'מתאים' still sets post_flight_offer for the next turn",
      tu2.get("post_flight_offer") == ["lodging"])

# --- Shaked's stage-2 run-2 regression repro: a route-approval message
#     with filler words but NO mention of lodging/car at all ("מושלם, מתאים
#     לנו") must NOT invoke the classifier, even though stripping the known
#     acceptance words leaves "לנו" (3 chars) behind - the old gate treated
#     that as "extra content" worth checking. The classifier mock below is
#     rigged to answer "lodging: true" if called at all, so if this test
#     passes with lodging left pending, the classifier was correctly never
#     invoked. ("נראה טוב" is omitted here - it isn't in _is_itinerary_
#     acceptance's hardcoded positives and falls through to the
#     meaning-based classifier, which this harness's generic mock doesn't
#     answer in the right format; unrelated to the fix under test.) ---
for _bare_phrase in ("מושלם, מתאים לנו", "סבבה, אהבנו"):
    with patch.object(chat, "_post_claude", side_effect=_fake_post_claude):
        r_bare = client.post("/api/ariella/chat-clean", json={
            "message": _bare_phrase, "history": HISTORY, "trip_state": dict(STATE_BEFORE_APPROVAL),
        })
    data_bare = r_bare.get_json()
    tu_bare = data_bare.get("trip_update") or {}
    check(f"regression (stage2 run2): {_bare_phrase!r} does not invoke the classifier - lodging stays pending",
          (tu_bare.get("session_status") or {}).get("lodging") == "pending")
    check(f"regression (stage2 run2): {_bare_phrase!r} still asks the generic lodging offer",
          "תרצי שאמשיך גם עם" in str(data_bare.get("reply") or ""))
    check(f"regression (stage2 run2): {_bare_phrase!r} still sets post_flight_offer for the next turn",
          tu_bare.get("post_flight_offer") == ["lodging"])

# --- A same-message decline must also be honored, not just an acceptance ---
with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_decline):
    r3 = client.post("/api/ariella/chat-clean", json={
        "message": "כן, רק טיסות ומסלול, שום דבר אחר", "history": HISTORY, "trip_state": dict(STATE_BEFORE_APPROVAL),
    })
data3 = r3.get_json()
tu3 = data3.get("trip_update") or {}
check("a same-message decline marks lodging declined instead of re-asking",
      (tu3.get("session_status") or {}).get("lodging") == "declined")
check("a same-message decline removes lodging from requested_services",
      "lodging" not in (tu3.get("requested_services") or []))

with sqlite3.connect(DB) as conn:
    conn.execute("DELETE FROM members WHERE id=?", (member_id,))
    conn.commit()

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL ROUTE-APPROVAL-SAME-MESSAGE-OFFER-ANSWER TESTS PASSED")
