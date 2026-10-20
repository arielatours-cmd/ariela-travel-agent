"""QA for 3 bugs Shaked found in stage-3, run-2 (17.10.2026, main c2563ef,
qa/reports/2026-10-17-stage3-run2.md - relayed by Shaked directly, task
assigned by Shlomo per the business owner's explicit instruction: fix with
general state-based rules, never phrase lists).

Bug 1 (Rome): the customer answered the lodging TYPE question with "מלון
קטן ונעים" (a purely descriptive phrase - no budget/level/star word at
all). The model's own also_mentioned nonetheless invented
lodging_budget_or_level={"level": "בינוני"}, so the separate budget/level
question got skipped entirely and the final summary wrongly stated "רמה
בינונית" for a fact the customer never actually said. Originally fixed:
_guided_field_update_and_confirm took an optional raw_message parameter;
the also_mentioned call site in _handle_guided_extraction_turn passed the
current message, and a level value was only accepted there if it (via
_level_stated_in_message) matched one of the canonical level words/
synonyms (_LODGING_LEVEL_VALUES), a star-rating mention, or an established
no-preference word.

SUPERSEDED 18.10.2026 by the business owner's explicit directive (PR #83):
only the MODEL decides what the customer said - never a word list or
regex, however "general". _level_stated_in_message is gone; the
also_mentioned schema for lodging_budget_or_level now carries its own
"evidence" key, and the check is _value_has_verbatim_evidence against it -
a verbatim quote the model itself must supply, not a canonical-word match
computed in code. The direct-answer call site (answering the budget/level
question itself) is still untouched - raw_message/evidence is only
relevant for also_mentioned, per the task's own scoping.

Bug 2 (Rome, same root principle, different mechanism): the final summary
claimed "אין העדפה לטיסה ישירה" (the exact phrase the system prompt
mandates for a genuinely KNOWN no-preference) while flight.
connection_preference was actually still None - the question was never
asked. Fixed in _ensure_flight_summary_completeness: that exact sentence
is stripped whenever connection_preference is falsy in state.

Bug 3 (Athens): dates (15-19.4) were correct in state, but
_ensure_flight_summary_completeness never checked for them (only budget/
baggage/connection-preference), so a free-text summary that omitted them
was never caught. Fixed: dates and travelers are now part of the same
completeness check, via the newly factored-out _flight_dates_line/
_flight_travelers_line helpers (exact same wording _flight_summary_text
itself already used).

Bug 4 (Paris): once every domain (flights/lodging/car/trip_planning) was
genuinely complete/declined, the existing missing-final-summary retry
(_force_final_summary_now) is not a guarantee - seen live, it re-asked
the route style/pace question and rebuilt an already-approved route
instead of producing the summary. Fixed: a second, deterministic
last-resort layer (_final_summary_fallback_text, mirroring the existing
_premature_approval_fallback_text pattern for the opposite failure) now
replaces the reply whenever it still isn't the real summary/approval
after the retry - state alone (every domain decided) is enough to know a
real summary is owed, regardless of the model's own wording.

Run: python3 tools/qa_stage3_run2_fixes.py
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

FAILED = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


# =====================================================================
# Bug 1 (Rome): also_mentioned must only ever record a level the customer
# actually stated - never infer it from a purely descriptive phrase.
# =====================================================================

# --- unit level: _value_has_verbatim_evidence (replaced _level_stated_
#     in_message entirely per the business owner's 18.10.2026 directive -
#     see the module docstring above) ---
check("_value_has_verbatim_evidence: no evidence at all never backs any "
      "value, whatever the message says",
      not chat._value_has_verbatim_evidence(None, "מלון קטן ונעים")
      and not chat._value_has_verbatim_evidence("", "מלון יוקרתי בבקשה"))
check("_value_has_verbatim_evidence: a quote that genuinely appears in the "
      "message, word-for-word, is accepted",
      chat._value_has_verbatim_evidence("מלון יוקרתי", "מלון יוקרתי בבקשה"))
check("_value_has_verbatim_evidence: a quote that does NOT appear in the "
      "message (the model fabricated it) is rejected - this is the one "
      "thing the function checks, nothing about the quote's wording or "
      "meaning",
      not chat._value_has_verbatim_evidence("מלון יוקרתי", "מלון קטן ונעים"))
check("_value_has_verbatim_evidence: the check never inspects the value "
      "itself, only whether the evidence is a real quote - a quote "
      "justifying 'אין העדפה' via different wording ('לא משנה לי') still "
      "passes, since the model (not this function) decided that meaning",
      chat._value_has_verbatim_evidence("לא משנה לי", "לא משנה לי, מה שתמצאי"))

# --- _guided_field_update_and_confirm: raw_message gating ---
check("direct-answer call site (raw_message=None) still accepts a model-"
      "extracted level unconditionally - unchanged behavior",
      chat._guided_field_update_and_confirm(
          "lodging_budget_or_level", {"level": "בינוני"},
      )[0] == {"lodging": {"details": {"level": "בינוני"}}})
check("also_mentioned call site (Rome repro): a level NOT backed by the "
      "raw message is dropped entirely, not just unconfirmed",
      chat._guided_field_update_and_confirm(
          "lodging_budget_or_level", {"level": "בינוני"},
          raw_message="מלון קטן ונעים",
      ) == ({}, None))
check("also_mentioned call site: a level with real evidence from the raw "
      "message is still accepted (no regression)",
      chat._guided_field_update_and_confirm(
          "lodging_budget_or_level", {"level": "יוקרתי", "evidence": "מלון יוקרתי"},
          raw_message="רוצים מלון יוקרתי, בלי הגבלת תקציב",
      )[0] == {"lodging": {"details": {"level": "יוקרתי"}}})
check("also_mentioned call site: a numeric budget is never subject to "
      "the level guard at all (unaffected by raw_message)",
      chat._guided_field_update_and_confirm(
          "lodging_budget_or_level", {"budget": 150},
          raw_message="מלון קטן ונעים",
      )[0] == {"lodging": {"details": {"budget": 150}}})

# --- full integration: _handle_guided_extraction_turn, exact Rome shape ---
os.environ["GUIDED_EXTRACTION_STEPS"] = "lodging"
GUIDED_STEPS = chat._guided_extraction_steps()
ROME_STATE = {
    "destination": {"places": ["רומא"], "mode": "specific", "status": "known"},
    "active_session": "lodging",
    "requested_services": ["flights", "lodging"],
    "session_status": {"flights": "complete", "lodging": "active", "car": "pending", "trip_planning": "pending"},
    "dates": {"departure": "2026-11-10", "return": "2026-11-15"},
    "travelers": {"adults": 2},
    "guided": {"current_question": "lodging_type", "attempts": 0, "answered": []},
}


def _fake_extract(guided_response):
    def _f(key, model, field, message, history, trip_update):
        return guided_response
    return _f


with patch.object(chat, "_guided_extract_answer", side_effect=_fake_extract({
    "status": "answered", "value": "מלון", "confidence": "high",
    "also_mentioned": {"lodging_budget_or_level": {"level": "בינוני"}},
    "correction": None,
})):
    result_rome = chat._handle_guided_extraction_turn(
        "test-key", "claude-sonnet-5", "מלון קטן ונעים", [], ROME_STATE, dict(ROME_STATE), GUIDED_STEPS,
    )
tu_rome = result_rome["trip_update"]
check("Rome repro end-to-end: lodging.details.level is NOT set from the "
      "invented also_mentioned value",
      (tu_rome.get("lodging") or {}).get("details", {}).get("level") is None)
check("Rome repro end-to-end: lodging_budget_or_level is NOT marked "
      "answered - the budget/level question still gets asked on its own turn",
      "lodging_budget_or_level" not in (tu_rome.get("guided") or {}).get("answered", []))
check("Rome repro end-to-end: the type itself is still correctly saved "
      "(the guard only touches the invented also_mentioned field)",
      (tu_rome.get("lodging") or {}).get("details", {}).get("type") == "מלון")

# --- same shape, but the customer genuinely DID mention a level - must
#     still work (no regression from the guard) ---
with patch.object(chat, "_guided_extract_answer", side_effect=_fake_extract({
    "status": "answered", "value": "מלון", "confidence": "high",
    "also_mentioned": {"lodging_budget_or_level": {"level": "יוקרתי", "evidence": "5 כוכבים"}},
    "correction": None,
})):
    result_rome2 = chat._handle_guided_extraction_turn(
        "test-key", "claude-sonnet-5", "מלון יוקרתי, 5 כוכבים", [], ROME_STATE, dict(ROME_STATE), GUIDED_STEPS,
    )
tu_rome2 = result_rome2["trip_update"]
check("genuine also_mentioned level (real evidence backs it): accepted and "
      "the budget/level question is correctly skipped",
      (tu_rome2.get("lodging") or {}).get("details", {}).get("level") == "יוקרתי"
      and "lodging_budget_or_level" in (tu_rome2.get("guided") or {}).get("answered", []))

os.environ.pop("GUIDED_EXTRACTION_STEPS", None)


# =====================================================================
# Bug 2 (Rome) + Bug 3 (Athens): _ensure_flight_summary_completeness
# =====================================================================

ATHENS_STATE = {
    "destination": {"places": ["אתונה"]},
    "dates": {"departure": "2026-04-15", "return": "2026-04-19"},
    "travelers": {"adults": 2},
    "flight": {},
    "budget_per_person": {},
    "user_gender": "female",
}
athens_reply = chat._ensure_flight_summary_completeness(
    "הסיכום לאתונה: יעד אתונה. אם כל הפרטים נכונים, כתבי מאשרת.", ATHENS_STATE,
)
check("Athens repro: dates known in state (15-19.4) but absent from "
      "Tinkerbell's own summary text get appended",
      "תאריכים: 15.04.2026" in athens_reply and "19.04.2026" in athens_reply)
check("Athens repro: travelers known in state also get appended in the "
      "same pass",
      "מבוגרים" in athens_reply)
check("Athens repro: a summary that already states the dates (any "
      "phrasing containing a dd.mm.yyyy date) is left untouched",
      chat._ensure_flight_summary_completeness(
          "הסיכום: יעד אתונה, 15.4.2026 עד 19.4.2026, 2 מבוגרים. אם כל הפרטים נכונים, כתבי מאשרת.",
          ATHENS_STATE,
      ) == "הסיכום: יעד אתונה, 15.4.2026 עד 19.4.2026, 2 מבוגרים. אם כל הפרטים נכונים, כתבי מאשרת.")

ROME_FLIGHT_STATE = {
    "destination": {"places": ["רומא"]},
    "dates": {"departure": "2026-11-10", "return": "2026-11-15"},
    "travelers": {"adults": 2},
    "flight": {"connection_preference": None},
    "budget_per_person": {},
    "user_gender": "female",
}
rome_reply = chat._ensure_flight_summary_completeness(
    "הסיכום לרומא: יעד רומא, 10.11.2026 עד 15.11.2026, 2 מבוגרים. "
    "אין העדפה לטיסה ישירה. אם כל הפרטים נכונים, כתבי מאשרת.",
    ROME_FLIGHT_STATE,
)
check("Rome repro: a false 'אין העדפה לטיסה ישירה' claim is stripped when "
      "connection_preference is actually unset (question never asked)",
      "אין העדפה לטיסה ישירה" not in rome_reply)
check("Rome repro: the rest of the summary survives the strip untouched",
      "יעד רומא" in rome_reply and "כתבי מאשרת" in rome_reply)
check("regression: a TRUE 'אין העדפה לטיסה ישירה' claim (preference "
      "actually known as such) is kept, not stripped",
      "אין העדפה לטיסה ישירה" in chat._ensure_flight_summary_completeness(
          "הסיכום: יעד רומא. אין העדפה לטיסה ישירה. אם כל הפרטים נכונים, כתבי מאשרת.",
          {**ROME_FLIGHT_STATE, "flight": {"connection_preference": "אין העדפה"}},
      ))
check("regression: a TRUE direct-only claim is never touched by the "
      "connection-preference strip (only the exact no-preference phrase "
      "is ever a candidate for removal)",
      "טיסה ישירה בלבד" in chat._ensure_flight_summary_completeness(
          "הסיכום: יעד רומא. טיסה ישירה בלבד. אם כל הפרטים נכונים, כתבי מאשרת.",
          {**ROME_FLIGHT_STATE, "flight": {"connection_preference": "direct"}},
      ))

# --- alternate phrasing: both bugs 2+3 in the SAME reply at once ---
combined_reply = chat._ensure_flight_summary_completeness(
    "נראה מצוין! אין העדפה לטיסה ישירה מבחינתכם. אם הכול בסדר, כתבי מאשרת.",
    ROME_FLIGHT_STATE,
)
check("combined repro: false connection-preference claim stripped AND "
      "missing dates/travelers appended, in the same pass",
      "אין העדפה לטיסה ישירה" not in combined_reply
      and "תאריכים: 10.11.2026" in combined_reply
      and "מבוגרים" in combined_reply
      and "כתבי מאשרת" in combined_reply)


# =====================================================================
# Bug 4 (Paris): _final_summary_fallback_text - last-resort safety net
# when the missing-final-summary retry itself still fails.
# =====================================================================

PARIS_ALL_DECIDED = {
    "destination": {"places": ["פריז"]},
    "dates": {"departure": "2026-12-20", "return": "2026-12-27"},
    "travelers": {"adults": 2},
    "flight": {"connection_preference": "direct", "baggage": ["checked_bag"], "baggage_detail": {"checked_bag": {"count": 1, "unit": "per_person"}}},
    "budget_per_person": {"status": "unlimited"},
    "user_gender": "female",
    "session_status": {"flights": "complete", "lodging": "complete", "car": "declined", "trip_planning": "complete"},
    "lodging": {"details": {
        "type": "דירה", "rooms": 2, "bathrooms": 2,
        "locations": "אזור שקט ליד המטרו", "level": "אין העדפה",
    }},
    # approved_text sits directly on trip_planning, never nested under
    # trip_planning.details - exactly the real shape _run_chat_turn_engine
    # writes it in (see the comment in _route_summary_line itself), not the
    # wrong nested shape the first version of this test file used (Shaked's
    # PR #81 review: that mismatch is exactly why the real app's route line
    # never appeared at all).
    "trip_planning": {
        "approved_text": "יום 1: מגדל אייפל ושיט בסן. יום 2: לובר ושכונת מארה. המסלול שהצעתי מתאים לכם?",
        "details": {"pace": "רגוע", "style": "תרבות ואוכל מקומי", "route": [{"base": "פריז"}, {"base": "פריז"}]},
    },
}
paris_fallback = chat._final_summary_fallback_text(PARIS_ALL_DECIDED)
check("Paris repro (Shaked's PR #81 review): the fallback never contains "
      "a fixed/canned intro sentence describing state - the business "
      "owner's own rule against hardcoded sentences",
      "כבר סגורים" not in paris_fallback and "אין עוד מה לתכנן" not in paris_fallback)
check("Paris repro: the fallback never re-asks about the route/style/"
      "pace, and never leaks the original proposal's own trailing "
      "question into the summary (Shaked's 2nd review: approved_text "
      "itself ends in a question) - no question mark anywhere",
      "?" not in paris_fallback)
check("Paris repro: the fallback still contains a real flight summary "
      "built from state (destination, dates, connection preference)",
      "פריז" in paris_fallback and "10.12.2026" not in paris_fallback  # sanity: wrong date never appears
      and "20.12.2026" in paris_fallback and "טיסה ישירה בלבד" in paris_fallback)
check("Paris repro (Shaked's PR #81 review, criterion 5): the fallback is "
      "genuinely COMPLETE - the lodging line (apartment, bedrooms, "
      "bathrooms, area, no budget limit) is included too, not just flights",
      "לינה:" in paris_fallback and "דירה" in paris_fallback
      and "2 חדרי שינה" in paris_fallback and "2 חדרי רחצה" in paris_fallback
      and "אזור שקט ליד המטרו" in paris_fallback and "אין הגבלת תקציב" in paris_fallback)
check("Paris repro (Shaked's 2nd review): the route line is found via "
      "the REAL top-level trip_planning.approved_text path (not the "
      "wrong nested .details.approved_text path the first version read), "
      "and is a short state-based line - never the full original "
      "proposal text and never its trailing question",
      "מסלול:" in paris_fallback and "2 ימי מסלול" in paris_fallback
      and "קצב רגוע" in paris_fallback and "תרבות ואוכל מקומי" in paris_fallback
      and "עצירות: פריז" in paris_fallback
      and "מגדל אייפל" not in paris_fallback and "מתאים לכם" not in paris_fallback)
check("regression: _route_summary_line returns None (no route line at "
      "all) when trip_planning.approved_text was never set - a route "
      "that was never actually approved must never be summarized",
      chat._route_summary_line({"trip_planning": {"details": {"pace": "רגוע"}}}) is None)

# --- Shaked's 3rd-round review (same PR): the real s3w2 state has no
# details.route list at all (so day count must come from dates instead)
# and pace is stored as the extractor's own internal English token
# ("relaxed"/"active", never Hebrew) - _route_summary_line printed it
# verbatim, leaking the English word "relaxed" straight at the customer. ---
s3w2_route_state = {
    "trip_planning": {
        "approved_text": "יום 1: ... המסלול שהצעתי מתאים לכם?",
        "details": {"pace": "relaxed", "style": "פעילויות מתאימות לילדים, כמו פארקים ומוזיאונים"},
    },
    "dates": {"departure": "2026-07-01", "return": "2026-07-05"},
}
s3w2_route_line = chat._route_summary_line(s3w2_route_state)
check("Shaked's exact s3w2 repro: the internal English pace token "
      "('relaxed') is translated to Hebrew ('רגוע'), never leaked as-is",
      "relaxed" not in s3w2_route_line and "קצב רגוע" in s3w2_route_line)
check("Shaked's exact s3w2 repro: day count is computed from dates "
      "(5 days, 1.7-5.7) when details.route has no day list at all",
      "5 ימי מסלול" in s3w2_route_line)
check("regression: 'active' (the other internal token) also translates",
      "קצב פעיל" in chat._route_summary_line(
          {"trip_planning": {"approved_text": "x", "details": {"pace": "active"}}}))
check("a pace value the model already wrote in Hebrew directly (not one "
      "of the two known internal tokens) passes through unchanged, never "
      "guessed at or altered",
      "קצב רגוע מאוד" in chat._route_summary_line(
          {"trip_planning": {"approved_text": "x", "details": {"pace": "רגוע מאוד"}}}))
check("Shlomo's follow-up (3rd review round): the Hebrew-translation is a "
      "single GENERAL helper (_to_hebrew_display) applied to every field "
      "this line prints, not special-cased to pace alone - style passes "
      "through unaffected today (no internal-token writer exists for it "
      "yet), proving the generalization adds no new guessing",
      chat._to_hebrew_display("active") == "פעיל"
      and chat._to_hebrew_display("relaxed") == "רגוע"
      and chat._to_hebrew_display("תרבות ואוכל מקומי") == "תרבות ואוכל מקומי"
      and chat._to_hebrew_display(None) == ""
      and "תרבות ואוכל מקומי" in chat._route_summary_line(
          {"trip_planning": {"approved_text": "x", "details": {"style": "תרבות ואוכל מקומי"}}}))
check("single-day trip from dates (no route list) uses the singular "
      "wording, not '1 ימי מסלול'",
      "יום מסלול אחד" in chat._route_summary_line({
          "trip_planning": {"approved_text": "x", "details": {}},
          "dates": {"departure": "2026-07-01", "return": "2026-07-01"},
      }))

check("Paris repro: car is correctly OMITTED - it was declined, not "
      "selected (Shaked: 'רכב רק אם נבחר')",
      "רכב:" not in paris_fallback)
check("Paris repro: the fallback ends in a real approval request "
      "(gendered correctly from state)",
      "כתבי מאשרת" in paris_fallback)

check("gendered correctly for a male customer",
      "כתוב מאשר" in chat._final_summary_fallback_text(
          {**PARIS_ALL_DECIDED, "user_gender": "male"}))
check("gendered neutrally when gender is unknown",
      "מאשר/מאשרת" in chat._final_summary_fallback_text(
          {k: v for k, v in PARIS_ALL_DECIDED.items() if k != "user_gender"}))

# --- a trip where car WAS actually selected (complete, not declined) - the
#     car line must then appear too ---
paris_with_car = dict(PARIS_ALL_DECIDED)
paris_with_car["session_status"] = dict(PARIS_ALL_DECIDED["session_status"], car="complete")
paris_with_car["car"] = {"details": {"vehicle_type": "משפחתי", "transmission": "אוטומטי", "pickup": "שדה התעופה, 20.12", "return": "שדה התעופה, 27.12"}}
paris_with_car_fallback = chat._final_summary_fallback_text(paris_with_car)
check("car genuinely selected and complete: the car line is included too",
      "רכב: משפחתי, אוטומטי" in paris_with_car_fallback
      and "איסוף:" in paris_with_car_fallback and "החזרה:" in paris_with_car_fallback)

# --- no flight data at all to summarize (e.g. a business/ski trip with no
#     flight.* facts) - must still never crash and never re-open anything ---
bare_fallback = chat._final_summary_fallback_text({"session_status": {
    "flights": "declined", "lodging": "complete", "car": "complete", "trip_planning": "complete",
}})
check("no flight facts to summarize: still a safe, non-empty, non-"
      "question fallback with the real approval request",
      bool(bare_fallback) and "?" not in bare_fallback
      and any(p in bare_fallback for p in ("כתבי מאשרת", "כתוב מאשר", "מאשר/מאשרת")))

check("defensive: non-dict input never crashes",
      bool(chat._final_summary_fallback_text(None)))


# =====================================================================
# Bug 5 (found during Shaked's PR #81 re-review, same s3w2 conversation):
# _deterministic_baggage_facts' checked_bag_mentioned regex never matched
# the singular "מזוודה גדולה" (big suitcase) at all - "מזוודות?\s+גדול"
# only makes the plural's own trailing ת optional, which covers "מזוודו
# גדול" (not a real word) or "מזוודות גדול" (plural), never the singular
# spelling ending in ה. "מזוודה גדולה לכל אחד מאיתנו" (the customer's
# exact words) therefore recorded no baggage fact at all. Separately, even
# once checked_bag_mentioned is fixed, the per-person unit ("לכל אחד")
# used to require an explicit digit next to "מזוודה" (bag_count_match) -
# dropping the unit for exactly this phrasing, which states a per-person
# split without a number. Both fixed; verifies real inputs, not an
# artificial fixture, per Shlomo's own stated testing rule.
# =====================================================================

check("Shaked's exact repro: 'מזוודה גדולה לכל אחד מאיתנו' now records "
      "checked_bag AND the per-person unit, not just a bare flag "
      "(plus the stated size itself, fixed 20.10 per Shlomo's priority-5 "
      "finding s12x10 - a size the customer actually said is a real fact too)",
      chat._deterministic_baggage_facts("מזוודה גדולה לכל אחד מאיתנו", traveler_count=2) == {
          "flight": {"baggage": ["checked_bag"], "baggage_detail": {"checked_bag": {"unit": "per_person", "size": "גדולה"}}},
      })
check("regression: the plural phrasing ('שתי מזוודות גדולות לכולנו') "
      "still resolves correctly (unit=total, count=2, size=גדולה)",
      chat._deterministic_baggage_facts("שתי מזוודות גדולות לכולנו", traveler_count=2) == {
          "flight": {"baggage": ["checked_bag"], "baggage_detail": {"checked_bag": {"unit": "total", "count": 2, "size": "גדולה"}}},
      })
check("regression: 'טרולי לכל אחד' alone (no מזוודה word at all) still "
      "never implies a per-person CHECKED bag - carry_on_only only, now "
      "also with its own per-person unit captured (fixed 20.10, carry-on "
      "never tracked count/unit before Shlomo's priority-5 finding)",
      chat._deterministic_baggage_facts("טרולי לכל אחד", traveler_count=2) == {
          "flight": {"baggage": ["carry_on_only"], "baggage_detail": {"carry_on_only": {"unit": "per_person"}}},
      })
check("regression: an explicit count alongside 'לכל אחד' still works "
      "exactly as before (e.g. 'שתי מזוודות לכל אחד')",
      chat._deterministic_baggage_facts("שתי מזוודות לכל אחד", traveler_count=2)
      ["flight"]["baggage_detail"]["checked_bag"] == {"unit": "per_person", "count": 2})
check("alternate phrasing: 'לכל נוסע' (per traveler, not 'לכל אחד') "
      "resolves the same way",
      "checked_bag" in chat._deterministic_baggage_facts(
          "מזוודה גדולה לכל נוסע", traveler_count=2)["flight"]["baggage"])

if FAILED:
    print(f"\nFAILED ({len(FAILED)}): {FAILED}")
    sys.exit(1)
print("\nALL STAGE-3 RUN-2 FIX TESTS PASSED")
