"""QA for Shlomo's relay of Shaked's stage-1 run-3 live finding
(Thessaloniki, 9d1d8f9) - the THIRD time this bug class surfaced:

"אפשר להקדים ביום אחד?" got the reply "נצא ב-27.11", but trip state
stayed at 28.11 unchanged (the extractor most likely never returned
shift_days for this message, and Tinkerbell invented a plausible-sounding
date change of her own). Same conversation: a 10-day-duration request got
"21-28 בנובמבר, נכון?" offered back - a 7-day span matching neither the
requested length nor any of the real computed candidate_ranges.

Per the business owner's explicit structural direction, this is now a
two-layer defense, neither layer a word/phrase list:

(a) _dates_truth_hint hands Tinkerbell the one genuine source of truth
    for THIS turn, explicitly and human-readably - the real confirmed
    departure/return, or (while still pending) the exact candidate
    options already computed - with an outright prohibition on stating
    anything else.

(b) _retry_if_dates_invented is a structural (date FORMAT, not words)
    safety net for when (a) alone still isn't followed: it extracts
    every date-shaped token from the reply and compares it against the
    valid set (confirmed dates, or every candidate's own start/end). If
    a reply names a date matching neither, Tinkerbell is called again
    EXACTLY ONCE with a corrective hint describing the mismatch - never
    a silent rewrite of the first reply, and never more than one retry.

Run: python3 tools/qa_never_invent_dates.py
"""
import os
import sys
from datetime import date
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import ariella_chat_clean as chat

FAILED = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


# =====================================================================
# Direct unit tests of _dates_truth_hint.
# =====================================================================
confirmed_hint = chat._dates_truth_hint({"dates": {"departure": "2026-11-28", "return": "2026-12-05"}})
check("confirmed dates produce an explicit, labeled 'saved dates' hint",
      "28.11.2026" in confirmed_hint and "05.12.2026" in confirmed_hint and "לעולם אל תציעי" in confirmed_hint)

pending_hint = chat._dates_truth_hint({"dates": {
    "needs_confirmation": True,
    "candidate_ranges": ["יום שישי 21.11.2026–יום שישי 28.11.2026", "יום שישי 28.11.2026–יום שישי 05.12.2026"],
}})
check("pending candidates produce an explicit, labeled 'pending options only' hint",
      "21.11.2026" in pending_hint and "28.11.2026" in pending_hint and "05.12.2026" in pending_hint)

check("neither confirmed dates nor pending candidates -> no hint at all",
      chat._dates_truth_hint({"dates": {}}) == "" and chat._dates_truth_hint({}) == "")

check("pending with no candidate_ranges at all (shouldn't normally happen) -> no hint, never raises",
      chat._dates_truth_hint({"dates": {"needs_confirmation": True}}) == "")

# =====================================================================
# Direct unit tests of the extraction/comparison helpers.
# =====================================================================
check("_mentioned_date_day_months extracts every date-shaped token, "
      "ignoring year",
      chat._mentioned_date_day_months("נצא ב-27.11 ונחזור ב-04.12.2026") == [(27, 11), (4, 12)])
check("_mentioned_date_day_months returns [] for text with no date-shaped tokens",
      chat._mentioned_date_day_months("מה התקציב שלכם?") == [])
check("_valid_trip_date_day_months collects both confirmed dates",
      chat._valid_trip_date_day_months({"departure": "2026-11-28", "return": "2026-12-05"}) == {(28, 11), (5, 12)})
check("_valid_trip_date_day_months collects every candidate's start/end dates",
      chat._valid_trip_date_day_months({
          "needs_confirmation": True,
          "candidate_ranges": ["יום שישי 21.11.2026–יום שישי 28.11.2026"],
      }) == {(21, 11), (28, 11)})

# =====================================================================
# End-to-end: Shaked's EXACT live shape - a shift request gets a reply
# naming a date that doesn't match the confirmed dates. Exactly one
# corrective retry fires, and the second reply is used as-is.
# =====================================================================
_CONFIRMED_STATE = {"dates": {"departure": "2026-11-28", "return": "2026-12-05"}}


def _make_mock(replies):
    calls = []

    def _mock(key, model, system_static, system_dynamic, history, message_, max_tokens, include_history=True, source="other"):
        calls.append(source)
        if source == "tinkerbell_reply":
            idx = min(len([c for c in calls if c == "tinkerbell_reply"]) - 1, len(replies) - 1)
            return replies[idx]
        return "{}"

    return calls, _mock


calls, mock_invented = _make_mock([
    "בטח, נצא ב-27.11 במקום.",
    "קלטתי - אפשר לוודא: 27.11 מתאים לך, או שנשאר ב-28.11?",
])
with patch.object(chat, "_post_claude", side_effect=mock_invented):
    reply = chat._call_tinkerbell("k", "m", [], "אפשר להקדים ביום אחד?", dict(_CONFIRMED_STATE))
check("Shaked's exact live shape: a first reply naming an unconfirmed "
      "date (27.11, state stayed at 28.11) triggers EXACTLY ONE "
      "corrective retry",
      calls.count("tinkerbell_reply") == 2)
check("the retried reply (asking to confirm instead of asserting) is "
      "what's actually returned",
      reply == "קלטתי - אפשר לוודא: 27.11 מתאים לך, או שנשאר ב-28.11?")

# =====================================================================
# Regression: a reply that correctly only mentions the real confirmed
# dates never triggers a retry at all - a single model call.
# =====================================================================
calls_ok, mock_ok = _make_mock(["קלטתי, יציאה 28.11.2026 וחזרה 05.12.2026 - מעולה."])
with patch.object(chat, "_post_claude", side_effect=mock_ok):
    reply_ok = chat._call_tinkerbell("k", "m", [], "מעולה", dict(_CONFIRMED_STATE))
check("a reply correctly restating only the real confirmed dates never "
      "triggers a retry (single model call)",
      calls_ok.count("tinkerbell_reply") == 1
      and reply_ok == "קלטתי, יציאה 28.11.2026 וחזרה 05.12.2026 - מעולה.")

# =====================================================================
# Regression: even if the SECOND (retried) reply still names an invented
# date, there is never a third call - the retried reply is accepted
# as-is, capping the mechanism at exactly one retry.
# =====================================================================
calls_still, mock_still = _make_mock(["נצא ב-27.11.", "בכל זאת 27.11, זה התאריך הנכון."])
with patch.object(chat, "_post_claude", side_effect=mock_still):
    reply_still = chat._call_tinkerbell("k", "m", [], "אפשר להקדים?", dict(_CONFIRMED_STATE))
check("even when the retried reply STILL invents a date, there is never "
      "a third call - capped at exactly one retry",
      calls_still.count("tinkerbell_reply") == 2
      and reply_still == "בכל זאת 27.11, זה התאריך הנכון.")

# =====================================================================
# Regression: a reply mentioning a date that matches one of the PENDING
# candidates (not yet confirmed) is correctly accepted, no retry -
# candidates are also part of the valid set, not just confirmed dates.
# =====================================================================
_PENDING_STATE = {"dates": {
    "needs_confirmation": True,
    "candidate_ranges": ["יום שישי 21.11.2026–יום שישי 28.11.2026"],
}}
calls_cand, mock_cand = _make_mock(["האם 21.11 עד 28.11 מתאים לך?"])
with patch.object(chat, "_post_claude", side_effect=mock_cand):
    reply_cand = chat._call_tinkerbell("k", "m", [], "כן", dict(_PENDING_STATE))
check("a reply naming dates that match a real PENDING candidate (not yet "
      "confirmed) is accepted without a retry",
      calls_cand.count("tinkerbell_reply") == 1)

# =====================================================================
# Regression: with no dates known/pending at all in state, the mechanism
# never fires (nothing to validate against) - matches the hint's own
# empty-string behavior.
# =====================================================================
calls_none, mock_none = _make_mock(["לאן תרצו לטוס?"])
with patch.object(chat, "_post_claude", side_effect=mock_none):
    reply_none = chat._call_tinkerbell("k", "m", [], "שלום", {"dates": {}})
check("with no dates known/pending at all, the mechanism never fires",
      calls_none.count("tinkerbell_reply") == 1)

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL NEVER-INVENT-DATES TESTS PASSED")
