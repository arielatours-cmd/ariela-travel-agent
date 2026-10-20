"""QA for Shaked's stage-2, run-1 live finding (17.10.2026, qa/reports/
2026-10-17-stage2-run1.md on the shaked branch, main 5b46648): 1/5 scenarios
passed.

Bug 1 (4/5): the transition from route approval to the lodging offer.
Right after planning_accept (route approval) runs, lodging's session_status
sometimes already read "active" or "declined" instead of the genuinely
still-undecided "pending" it was before the turn started - even though
the route-approval message itself ("מושלם, מתאים לנו", "סבבה, אהבנו",
"מתאים לנו", "נראה טוב") never names lodging/car at all. Only "מעולה,
מתאים" (London) left it correctly untouched. Shaked's own hypothesis:
something earlier in the turn (the main structured extraction call, or a
by-meaning classifier) already changes lodging within the SAME turn.

Fixed in the planning_accept block: for lodging/car, if its session_status
changed this turn relative to trip_state (the state as of the START of
this turn, before any of this turn's extraction ran) AND its
service_decisions entry carries no recognized "source" tag, the change is
reverted - session_status, service_decisions and requested_services are
all restored to their pre-turn values. The source tag, not whether the
message happens to name the service, is the reliable signal: every
DETERMINISTIC function in this file that legitimately decides lodging/car
(an explicit "רק טיסות" via _deterministic_only_flights_facts, a
same-message answer via _post_flight_offer_answer, an explicit named
decline/accept, etc.) tags its decision with its own recognizable source
string; only the raw model extraction ever leaves service_decisions
untagged. An earlier version of this fix checked for a literal lodging/
car noun in the message instead, and broke "כן, רק טיסות ומסלול, שום דבר
אחר" - _deterministic_only_flights_facts' own legitimate decline of
lodging/car never names either noun either, since it fires on the
EXCLUSIVITY phrase "רק טיסות", not a lodging/car word. A message that
genuinely answers lodging/car in the same breath as the approval (e.g.
"כן, מלון 4 כוכבים") is untouched here too, since that legitimate case
is tagged "post_flight_offer" by the same_message_answer logic further
below (see tools/qa_route_approval_same_message_offer_answer.py).

Secondary result (same bug 1 report): once lodging was active, "עזבי" or
"כבר יש לנו איפה לישון" didn't close it - the state stayed active and the
same two detail questions (type -> rooms -> type...) looped forever. Ariella
never actually said anything about declining lodging, even though she
typed something like "בלי לינה" - the state simply never recorded it.
Neither _deterministic_named_decline_facts (requires an exact service
noun - "לישון" isn't one of them) nor _deterministic_service_decline_facts
(requires an exact short phrase AND Ariella's own prior message to name
the service) covered this. Fixed with a new, tightly-scoped
_deterministic_active_service_decline_facts: only fires when lodging/car
is genuinely the active session right now (per trip_state, before this
turn), where a decline naturally never needs to name the service by noun.

Bug 2 (Budapest): baggage.
(a) "טרולי לכל אחד ומזוודה אחת משותפת" -> summary read "טרולי בלבד
ומזוודה גדולה לכל נוסע" - besides the dropped-value bug fixed separately
(see tools/qa_baggage_and_itinerary_acceptance_by_meaning.py's own
coverage of _deterministic_baggage_facts combining multiple matches), the
checked-bag label itself always assumed one suitcase PER PASSENGER
(_BAGGAGE_HE's own qa-s83 fix), which is simply wrong when the customer
explicitly said ONE suitcase shared by the whole party. Fixed: a new
flight.baggage_shared boolean (set by _deterministic_baggage_facts when it
matches "משותפת") makes both _BAGGAGE_HE/_baggage_summary and
_state_context's own baggage_labels say "מזוודה אחת משותפת לכל הנוסעים"
instead of the per-passenger phrasing.
(b) a leak: Ariella wrote "רק נדייק - בשדה הפנימי זה מתועד כ'טרולי
בלבד'..." straight to the customer - internal representation language
("שדה"/"מתועד כ-") that must never reach customer-facing text. Root
cause: TINKERBELL_SYSTEM's OWN baggage-question rule used exactly this
"בשדה הפנימי" phrasing as an instruction to the model, which then echoed
it back almost verbatim. Fixed in two parts: the system prompt is
reworded to describe the same behavior without ever using "field"/
"state"/"session"-shaped language, and the existing "never show the
customer system words" rule is extended to explicitly ban Hebrew internal
terms too, now backed by a new deterministic safety net,
_strip_internal_terminology_leak, that removes just the offending
sentence if one slips through anyway (same defense-in-depth philosophy
as every other prompt-plus-backstop pair in this file).

Addition (Eran's 502 diagnosis, relayed by Shlomo): the per-turn timeout
ceiling from PR #55/#56 didn't actually bound a turn's real wall-clock
time, for two compounding reasons - (1) the shared Anthropic client was
created with no max_retries, so the SDK's OWN hidden internal retrying
(separate from and invisible to _post_claude's own deliberate, narrower
retry loop) could silently multiply a single call's real duration by up
to 3x; (2) once the turn's budget was already exhausted, _post_claude
still floored the next call's timeout at 8s instead of skipping it
entirely, so a turn making several sequential calls kept adding
guaranteed extra seconds past its own ceiling. Fixed: max_retries=0 on
client construction, and _claude_call_timeout() now returns 0 (not the
old 8s floor) once genuinely out of budget - _post_claude fails fast on
that without ever reaching the SDK. See tools/qa_per_turn_timeout_cap_and_
duration_logging.py for the dedicated coverage of both.

Shaked's same-day review of PR #65 found 2 blocking regressions in the
fixes above:

1. "מושלם. לינה כבר יש לנו" (perfect, we already have lodging) in the
   SAME message as a route approval is a genuine, CORRECT decision the
   raw extraction got right - the customer explicitly named lodging and
   said it's arranged - yet it carries no recognized source tag either,
   so the source-tag-only revert guard wrongly reverted it back to
   pending, re-asking a question already answered. Fixed: the revert now
   requires BOTH conditions - the message doesn't name the service by
   noun AND the decision carries no recognized source tag. "רק טיסות" is
   still protected by its own tag regardless of the noun check, and "לינה
   כבר יש לנו" is now protected by the noun check regardless of the
   (absent) tag - the two checks are a conjunction, not alternatives.

2. The final summary still read "טרולי בלבד, מזוודה אחת משותפת לכל
   הנוסעים" for "טרולי לכל אחד ומזוודה אחת משותפת" - self-contradictory,
   since "carry_on_only" literally means "ONLY a carry-on, no checked
   bag" (the system prompt's own definition), directly contradicting the
   checked_bag label sitting right next to it. Fixed: when checked_bag is
   ALSO in the list, carry_on_only's label drops the "בלבד" (only)
   framing - "טרולי לכל נוסע" instead - in both baggage-label sites.

Also fixed, though explicitly marked non-blocking by Shaked (it's in the
same new function from this same PR): "כבר יש לנו איפה לישון בלילה
הראשון, צריך לשאר הלילות" (we already have it for night 1, still need
the rest) was read as a full lodging decline. A continuing-need word
("צריך"/"עדיין") anywhere else in the message now means this is a
PARTIAL arrangement, not a full decline.

Run: python3 tools/qa_stage2_run1_lodging_transition.py
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
import json

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
            ("QA Stage2 Lodging Transition", email, generate_password_hash("Test1234!"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
        )
        return cur.lastrowid


ROUTE_TEXT = (
    "יום 1, 1.6.2027 (שלישי)\nנחיתה ברומא.\n\n"
    "יום 2, 2.6.2027 (רביעי)\nסיור בעיר.\n\n"
    "מתאים לך ככה, או שתרצי לשנות משהו?"
)
HISTORY = [
    {"role": "user", "content": "אני רוצה מסלול לרומא"},
    {"role": "assistant", "content": "ספרי לי קצת על המסלול שאתם מדמיינים?"},
    {"role": "user", "content": "מתאים"},
    {"role": "assistant", "content": ROUTE_TEXT},
]
STATE_BEFORE_APPROVAL = {
    "destination": {"places": ["רומא"], "mode": "specific", "status": "known"},
    "active_session": "trip_planning",
    "requested_services": ["trip_planning", "flights"],
    "session_status": {"flights": "complete", "lodging": "pending", "car": "pending", "trip_planning": "active"},
}


def _spurious_extractor(service_decisions, session_status):
    def _fake_post_claude(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
        if source == "state_extractor":
            return json.dumps({"trip_update": {
                "service_decisions": service_decisions,
                "session_status": session_status,
            }})
        return "תשובה לדוגמה."
    return _fake_post_claude


# --- Shaked's exact repro: a bare route-approval message, with the
#     extractor spuriously declining lodging on this same turn (mirrors
#     the Rome scenario she reported: lodging=declined, post_flight_offer
#     never even recorded) ---
member_id = _make_member("qa-stage2-lodging@example.com")
with client.session_transaction() as sess:
    sess["member_id"] = member_id

with patch.object(chat, "_post_claude", side_effect=_spurious_extractor(
    {"lodging": {"wanted": False, "source": "hallucinated"}}, {"lodging": "declined"},
)):
    r1 = client.post("/api/ariella/chat-clean", json={
        "message": "מושלם, מתאים לנו", "history": HISTORY, "trip_state": dict(STATE_BEFORE_APPROVAL),
    })
data1 = r1.get_json()
tu1 = data1.get("trip_update") or {}
check("Shaked's Rome repro: a spurious same-turn lodging=declined (message "
      "never names lodging at all) is reverted back to pending",
      (tu1.get("session_status") or {}).get("lodging") == "pending")
check("lodging is still in requested_services after the revert (never "
      "really declined)",
      "lodging" not in (tu1.get("service_decisions") or {})
      or (tu1.get("service_decisions") or {}).get("lodging", {}).get("wanted") is not False)
check("the real yes/no lodging offer is asked instead of silently "
      "skipping past it",
      "תרצי שאמשיך גם עם לינה" in str(data1.get("reply") or ""))
check("post_flight_offer correctly records lodging as what was just offered",
      tu1.get("post_flight_offer") == ["lodging"])

# --- Same repro, but the extractor spuriously ACTIVATES lodging instead
#     (mirrors the Paris/Athens/Budapest scenarios: lodging=active,
#     post_flight_offer=[], jumping straight to a detail question) ---
with patch.object(chat, "_post_claude", side_effect=_spurious_extractor(
    {"lodging": {"wanted": True, "source": "hallucinated"}}, {"lodging": "active"},
)):
    r2 = client.post("/api/ariella/chat-clean", json={
        "message": "סבבה, אהבנו", "history": HISTORY, "trip_state": dict(STATE_BEFORE_APPROVAL),
    })
data2 = r2.get_json()
tu2 = data2.get("trip_update") or {}
check("Shaked's Paris/Athens/Budapest repro: a spurious same-turn "
      "lodging=active (message never names lodging) is reverted back to "
      "pending, not left to skip straight into a detail question",
      (tu2.get("session_status") or {}).get("lodging") == "pending")
check("the real yes/no lodging offer is asked, not a detail question "
      "('איזה סוג לינה' never appears)",
      "תרצי שאמשיך גם עם לינה" in str(data2.get("reply") or "")
      and "איזה סוג לינה" not in str(data2.get("reply") or ""))

# --- Regression: the legitimate same-message-answer mechanism (tagged
#     "post_flight_offer" - a RECOGNIZED source) must still work exactly as
#     qa_route_approval_same_message_offer_answer.py already covers - the
#     revert guard must never fire on a change carrying a recognized
#     source tag, regardless of whether the message names the service ---
def _fake_post_claude_same_message(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        return "{}"
    if source == "classifier":
        return '{"lodging": true}'
    return "תשובה לדוגמה."


with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_same_message):
    r3 = client.post("/api/ariella/chat-clean", json={
        "message": "כן, מלון 4 כוכבים במרכז", "history": HISTORY, "trip_state": dict(STATE_BEFORE_APPROVAL),
    })
data3 = r3.get_json()
tu3 = data3.get("trip_update") or {}
check("regression: the dedicated same-message-answer mechanism (source="
      "'post_flight_offer', a recognized tag) still activates lodging "
      "correctly - the revert guard never touches a tagged decision",
      (tu3.get("session_status") or {}).get("lodging") == "active")

with sqlite3.connect(DB) as conn:
    conn.execute("DELETE FROM members WHERE id=?", (member_id,))
    conn.commit()


# === Secondary result: closing an ACTIVE lodging/car session on an
#     implicit decline that names no service noun at all ===

check("_deterministic_active_service_decline_facts: 'עזבי' while lodging "
      "is active declines it",
      chat._deterministic_active_service_decline_facts(
          {"active_session": "lodging"}, "עזבי",
      ) == {
          "service_decisions": {"lodging": {"wanted": False, "source": "explicit_active_decline"}},
          "session_status": {"lodging": "declined"},
      })
check("'כבר יש לנו איפה לישון' while lodging is active declines it too - "
      "neither _deterministic_named_decline_facts nor _deterministic_"
      "service_decline_facts recognize 'לישון' as a lodging noun at all",
      chat._deterministic_active_service_decline_facts(
          {"active_session": "lodging"}, "כבר יש לנו איפה לישון",
      ).get("session_status") == {"lodging": "declined"})
check("the same phrase does nothing when lodging/car is NOT the active "
      "session - never fires outside the one context it's scoped to",
      chat._deterministic_active_service_decline_facts(
          {"active_session": "flights"}, "עזבי",
      ) == {})
check("'עזבי' while CAR is active declines car, not lodging",
      chat._deterministic_active_service_decline_facts(
          {"active_session": "car"}, "עזבי",
      ) == {
          "service_decisions": {"car": {"wanted": False, "source": "explicit_active_decline"}},
          "session_status": {"car": "declined"},
      })
check("confirms the gap existed before this fix: _deterministic_named_"
      "decline_facts alone does not recognize either phrase",
      chat._deterministic_named_decline_facts("עזבי") == {}
      and chat._deterministic_named_decline_facts("כבר יש לנו איפה לישון") == {})


# === Bug 2a: "מזוודה אחת משותפת" (one SHARED suitcase) must never be
#     summarized as if every passenger had their own. Migrated 2026-10-17
#     (Shaked's review of #78/the 014a baggage field) from a bare
#     baggage_shared boolean to flight.baggage_detail.checked_bag =
#     {count, unit} - a boolean lost the actual COUNT and the real UNIT
#     ("לכל זוג" vs "לכולנו" vs an unclear split) a customer stated. ===

check("Shaked's exact Budapest repro: 'טרולי לכל אחד ומזוודה אחת משותפת' "
      "sets BOTH values (not just carry_on_only, the dropped-value half of "
      "this already fixed separately) AND the shared detail, with count=1 "
      "correctly recovered from 'מזוודה אחת' - plus the trolley's own "
      "per-person split itself (fixed 20.10, Shlomo's priority-5 finding: "
      "carry_on never tracked count/unit before, unlike checked_bag)",
      chat._deterministic_baggage_facts("טרולי לכל אחד ומזוודה אחת משותפת") == {
          "flight": {
              "baggage": ["carry_on_only", "checked_bag"],
              "baggage_detail": {
                  "checked_bag": {"unit": "total", "count": 1},
                  "carry_on_only": {"unit": "per_person"},
              },
          },
      })
check("an ordinary (non-shared) checked-bag phrase does NOT set a "
      "baggage_detail - the per-passenger phrasing remains the default",
      not chat._deterministic_baggage_facts("יש לנו מזוודה בבטן המטוס").get("flight", {}).get("baggage_detail"))
check("_baggage_summary (car-session context) says 'משותפת', never the "
      "per-passenger phrasing, when baggage_detail.checked_bag.unit is total",
      "משותפת" in chat._baggage_summary({"flight": {"baggage": ["checked_bag"], "baggage_detail": {"checked_bag": {"unit": "total"}}}})
      and "לכל נוסע" not in chat._baggage_summary({"flight": {"baggage": ["checked_bag"], "baggage_detail": {"checked_bag": {"unit": "total"}}}}))
check("_baggage_summary still uses the per-passenger phrasing (qa-s83's "
      "own fix) when there is no baggage_detail - no regression",
      "לכל נוסע" in chat._baggage_summary({"flight": {"baggage": ["checked_bag"]}}))


# === Bug 2a-follow-up (Shaked, 2026-10-17, 014a stage-1 run-1, Budapest Z5,
#     then reviewed again the same day): a shared bag stated WITHOUT the
#     literal word "משותפת" still never got flagged - "מזוודה אחת לכולנו"
#     has none of the old explicit patterns. Her SECOND review (of the
#     first fix, #78) found that a bare shared/not-shared flag still lost
#     the actual COUNT and the real UNIT ("לכל זוג" vs "לכולנו" collapsed
#     to the same label) - see qa_guided_extraction_baggage_014a.py for the
#     full set of her exact phrases against both the guided field (primary
#     path) and this regex (fail-safe only). These few stay here as the
#     general boundary checks (count-vs-party heuristic when no unit word
#     is present at all). ===
check("Shaked's exact Budapest Z5 repro: 'מזוודה אחת לכולנו' with 3 "
      "travelers (couple + a 3-year-old) is flagged total via the unit "
      "word itself ('לכולנו'), with count=1 preserved - plus the "
      "trolley's own per-person split (same 20.10 fix as above)",
      chat._deterministic_baggage_facts("טרולי לכל אחד ועוד מזוודה אחת לכולנו", 3) == {
          "flight": {
              "baggage": ["carry_on_only", "checked_bag"],
              "baggage_detail": {
                  "checked_bag": {"unit": "total", "count": 1},
                  "carry_on_only": {"unit": "per_person"},
              },
          },
      })
check("'מזוודה אחת לכל זוג' for a solo traveler (count=1) does NOT infer "
      "'total' from the count-vs-party fallback - sharing needs more than "
      "one traveler in the first place (the explicit 'לכל זוג' unit word "
      "still applies on its own, regardless of party size)",
      chat._deterministic_baggage_facts("מזוודה אחת לכל זוג", 1).get("flight", {}).get("baggage_detail", {}).get("checked_bag", {}).get("unit") == "per_couple")
check("an exact one-bag-per-person count ('ארבע מזוודות' for 4 travelers, "
      "no unit word) is NOT inferred as total - 4 is not smaller than 4",
      chat._deterministic_baggage_facts("ארבע מזוודות", 4).get("flight", {}).get("baggage_detail", {}).get("checked_bag", {}).get("unit") is None)
check("with no traveler_count given at all (back-compat, existing call "
      "sites with only the message positional arg), the count-vs-party "
      "fallback never fires, but an explicit unit word still does",
      chat._deterministic_baggage_facts("מזוודה אחת לכולנו").get("flight", {}).get("baggage_detail", {}).get("checked_bag", {}).get("unit") == "total")
check("a genuinely multi-bag statement bigger than the party ('שתי "
      "מזוודות' for a solo traveler, no unit word) is never inferred as total",
      chat._deterministic_baggage_facts("שתי מזוודות", 1).get("flight", {}).get("baggage_detail", {}).get("checked_bag", {}).get("unit") is None)


# === Bug 2b: internal terminology ("בשדה הפנימי", "מתועד כ-") must never
#     reach a customer-facing reply ===

check("Shaked's exact Budapest leak repro is stripped, keeping the rest "
      "of the reply intact",
      chat._strip_internal_terminology_leak(
          "מעולה, הבנתי. רק נדייק - בשדה הפנימי זה מתועד כ'טרולי בלבד', "
          "זה מדויק? איזה תאריך נוח לכם לטוס?"
      ) == "מעולה, הבנתי. איזה תאריך נוח לכם לטוס?")
check("a reply with no internal-terminology leak at all is returned "
      "completely unchanged",
      chat._strip_internal_terminology_leak("מעולה, הבנתי. איזה תאריך נוח לכם לטוס?")
      == "מעולה, הבנתי. איזה תאריך נוח לכם לטוס?")
check("if the ENTIRE reply is nothing but the leaked sentence, the "
      "original reply is returned unchanged rather than emitting an "
      "empty string",
      chat._strip_internal_terminology_leak("זה מתועד כ'טרולי בלבד' בשדה הפנימי.")
      == "זה מתועד כ'טרולי בלבד' בשדה הפנימי.")
check("also catches 'ה-state'/'ה-session' leaking into a reply",
      chat._strip_internal_terminology_leak("מעולה. ה-state מעודכן. יש עוד משהו?")
      == "מעולה. יש עוד משהו?")

# === Shaked's stage-2 run-2 finding (Budapest, 0/5, 2f9b859): a SECOND,
#     narrower internal-terminology leak - the system prompt's own
#     suggested acknowledgment example ("לינה: נקלט") echoed verbatim ===
check("Shaked's exact stage-2 run-2 leak repro ('לינה: נקלט שנסגור את "
      "הפרטים.') is stripped, keeping the real summary that follows",
      chat._strip_internal_terminology_leak(
          "לינה: נקלט שנסגור את הפרטים. עכשיו הסיכום לטיסות: טיסה ישירה "
          "מתל אביב."
      ) == "עכשיו הסיכום לטיסות: טיסה ישירה מתל אביב.")
check("the same leak pattern is also caught for car/flights/trip_planning",
      chat._strip_internal_terminology_leak("רכב: נקלט. עוד משהו?")
      == "עוד משהו?")
check("a LEGITIMATE summary line using the same 'domain: content' colon "
      "format is never touched - only the bare 'נקלט'/'נקלטה' acknowledgment "
      "is scoped, not real summary content after the colon",
      chat._strip_internal_terminology_leak("לינה: מלון 4 כוכבים במרכז בודפשט.")
      == "לינה: מלון 4 כוכבים במרכז בודפשט.")


# === Shaked's PR #65 review (same day): 2 blocking regressions in the
#     bug-1 fix above ===

# -- Regression 1: a same-message lodging decline during route approval
#    ("מושלם. לינה כבר יש לנו") was wrongly reverted back to pending by
#    the source-tag check alone, re-asking a question already answered.
#    The revert now requires BOTH the message not naming the service AND
#    no recognized source tag. --

member_id2 = _make_member("qa-stage2-review-fix@example.com")
with client.session_transaction() as sess:
    sess["member_id"] = member_id2


def _fake_post_claude_untagged_lodging_decline(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        # Mirrors the raw model extraction correctly reading an explicit,
        # same-message decline - no "source" tag, since only the
        # deterministic helper functions ever add one.
        return json.dumps({"trip_update": {
            "service_decisions": {"lodging": {"wanted": False}},
            "session_status": {"lodging": "declined"},
        }})
    return "תשובה לדוגמה."


with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_untagged_lodging_decline):
    r_review1 = client.post("/api/ariella/chat-clean", json={
        "message": "מושלם. לינה כבר יש לנו", "history": HISTORY, "trip_state": dict(STATE_BEFORE_APPROVAL),
    })
data_review1 = r_review1.get_json()
check("Shaked's exact regression repro: an untagged but CORRECT same-"
      "message lodging decline (the message names 'לינה' explicitly) "
      "survives the revert guard - lodging stays declined",
      (data_review1.get("trip_update") or {}).get("session_status", {}).get("lodging") == "declined")
check("the reply correctly moves on to the car offer, not a repeated "
      "lodging question",
      "תרצי שאמשיך גם עם השכרת רכב" in str(data_review1.get("reply") or "")
      and "תרצי שאמשיך גם עם לינה" not in str(data_review1.get("reply") or ""))

with sqlite3.connect(DB) as conn:
    conn.execute("DELETE FROM members WHERE id=?", (member_id2,))
    conn.commit()

# -- Regression 2: "carry_on_only" ("טרולי בלבד") literally means "ONLY a
#    carry-on, no checked bag" - contradicts sitting next to checked_bag's
#    own label in the same sentence. Dropped the "בלבד" framing in exactly
#    that combination. --

_COMBINED_STATE = {"flight": {"baggage": ["carry_on_only", "checked_bag"], "baggage_detail": {"checked_bag": {"unit": "total"}}}}
check("Shaked's exact self-contradiction repro (_flight_summary_text): "
      "carry_on_only reads 'לכל נוסע', never 'בלבד', once checked_bag is "
      "also in the list",
      "טרולי לכל נוסע" in chat._flight_summary_text(_COMBINED_STATE)
      and "טרולי בלבד" not in chat._flight_summary_text(_COMBINED_STATE))
check("the same fix applies to _baggage_summary (car-session context)",
      "טרולי לכל נוסע" in chat._baggage_summary(_COMBINED_STATE)
      and "טרולי בלבד" not in chat._baggage_summary(_COMBINED_STATE))
check("regression: carry_on_only ALONE (no checked_bag) still reads "
      "'בלבד' - the fix only applies to the combined case",
      "טרולי בלבד" in chat._flight_summary_text({"flight": {"baggage": ["carry_on_only"]}}))

# -- Non-blocking item fixed anyway (same new function): a PARTIAL lodging
#    arrangement ("כבר יש לנו איפה לישון בלילה הראשון, צריך לשאר הלילות")
#    must not be read as a full decline --

check("a partial 'already have it for night 1, still need the rest' "
      "message is NOT read as a full lodging decline",
      chat._deterministic_active_service_decline_facts(
          {"active_session": "lodging"},
          "כבר יש לנו איפה לישון בלילה הראשון, צריך לשאר הלילות",
      ) == {})
check("the plain 'already have lodging' phrase (no continuing-need word) "
      "still declines it as before - no regression",
      chat._deterministic_active_service_decline_facts(
          {"active_session": "lodging"}, "כבר יש לנו איפה לישון",
      ).get("session_status") == {"lodging": "declined"})

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL STAGE2-RUN1-LODGING-TRANSITION TESTS PASSED")
