"""QA for Shaked's stage-2, run-4 live finding (17.10.2026, qa/reports/
2026-10-17-stage2-run4.md, main a3b1240): 3/5 scenarios passed (up from
1/5 in run-3 - #66 and #67 both confirmed fixed across all 5 scenarios:
the route-approval-to-lodging transition and the flights-to-trip_planning
offer question both now resolve correctly).

Bug 1 (Budapest): a comma-less bundled question. "מעולה! כדי לתכנן את
המסלול - תוכלו לספר לי מה אתם אוהבים לעשות בחופשה ואם חשוב לכם קצב
רגוע?" bundles the style and pace gap-questions into one sentence using
" ואם " (no comma at all before the seam) - both of
_BUNDLED_AND_QUESTION_RE's existing alternatives require a comma before
the "ו". Fixed: a third alternative, "\\sו(?:אם|האם|גם)\\s", catches the
same fused "ו" + question-word/pronoun seam even with plain whitespace
instead of a comma in front of it. Covered in
tools/qa_stage1_run3_levad_xory_gender.py (where the rest of
_BUNDLED_AND_QUESTION_RE's test coverage already lives).

Bug 2 (Paris, this file): the final flight summary can drop a fact that
was already collected in state. The customer explicitly said "אין
הגבלה" (no limit) and flight.budget_per_person.status became
"unlimited", but the "כתבי מאשרת" summary reply had no budget line at
all - earlier turns in the SAME run correctly produced "תקציב: ללא
הגבלה" for the identical fact, so this is an inconsistent free-text
omission, not a missing capability. Tinkerbell's own final summary is
free text and nothing previously verified it actually mentioned every
fact state already holds.

Fixed: _flight_connection_line/_flight_baggage_line/_flight_budget_line
(factored out of _flight_summary_text itself, so the exact same wording
is shared) are checked against marker words already present in any reply
that contains the reserved מאשר/מאשרת approval phrase
(_ensure_flight_summary_completeness, wired into _call_tinkerbell's own
reply pipeline right after _enforce_one_option_question). Whichever
fixed line is missing is inserted immediately before the approval-request
sentence; a fact already mentioned, however it was phrased, is never
touched.

Run: python3 tools/qa_stage2_run4_summary_completeness.py
"""
import os
import sys
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


# === Unit-level: _flight_budget_line / _flight_baggage_line / _flight_connection_line ===

check("_flight_budget_line reports the explicit-unlimited case",
      chat._flight_budget_line({"status": "unlimited"}) == "תקציב: ללא הגבלה")
check("_flight_budget_line reports a known numeric amount",
      chat._flight_budget_line({"amount": 1500, "currency": "₪"}) == "תקציב לאדם: 1500 ₪")
check("_flight_budget_line returns None when nothing is known yet",
      chat._flight_budget_line({}) is None and chat._flight_budget_line(None) is None)
check("_flight_baggage_line matches _flight_summary_text's own wording (carry_on_only)",
      chat._flight_baggage_line({"baggage": ["carry_on_only"]}) == "כבודה: טרולי בלבד")
check("_flight_connection_line reports a direct-only preference",
      chat._flight_connection_line({"connection_preference": "direct"}) == "טיסה ישירה בלבד")
check("_flight_connection_line returns None when unknown",
      chat._flight_connection_line({}) is None)


# === Bug 2: _ensure_flight_summary_completeness ===

STATE_UNLIMITED_BUDGET = {
    "budget_per_person": {"status": "unlimited", "amount": None, "currency": None},
    "user_gender": "female",
}

check("Shaked's exact stage-2 run-4 repro (Paris, a3b1240): a final "
      "summary reply that omits the budget line gets it inserted right "
      "before the approval-request sentence, with the exact wording "
      "_flight_summary_text itself would use",
      chat._ensure_flight_summary_completeness(
          "הנה הסיכום לפריז: יעד פריז, 3 לילות. אם כל הפרטים נכונים, כתבי מאשרת.",
          STATE_UNLIMITED_BUDGET,
      ) == "הנה הסיכום לפריז: יעד פריז, 3 לילות.\nתקציב: ללא הגבלה\n "
           "אם כל הפרטים נכונים, כתבי מאשרת.")

check("a reply that already mentions the budget (any phrasing containing "
      "'תקציב') is left completely untouched - no duplicate line",
      chat._ensure_flight_summary_completeness(
          "הסיכום: יעד פריז. תקציב: ללא הגבלה. אם כל הפרטים נכונים, כתבי מאשרת.",
          STATE_UNLIMITED_BUDGET,
      ) == "הסיכום: יעד פריז. תקציב: ללא הגבלה. אם כל הפרטים נכונים, כתבי מאשרת.")

check("a reply with no approval-request phrase at all is never touched - "
      "this is not yet the final-summary moment",
      chat._ensure_flight_summary_completeness(
          "מה התקציב שלכם?", STATE_UNLIMITED_BUDGET,
      ) == "מה התקציב שלכם?")

STATE_ALL_THREE_FACTS = {
    "flight": {"baggage": ["carry_on_only"], "connection_preference": "direct"},
    "budget_per_person": {"status": "unlimited"},
    "user_gender": "female",
}
_all_three_fixed = chat._ensure_flight_summary_completeness(
    "הנה הסיכום: יעד פריז, 3 לילות, שני מבוגרים. אם כל הפרטים נכונים, כתבי מאשרת.",
    STATE_ALL_THREE_FACTS,
)
check("all three named facts (budget, baggage, connection preference) are "
      "completed together when all three are missing from the reply",
      "תקציב: ללא הגבלה" in _all_three_fixed
      and "כבודה: טרולי בלבד" in _all_three_fixed
      and "טיסה ישירה בלבד" in _all_three_fixed)
check("the original statement content and the approval-request sentence "
      "both survive, untouched, around the inserted lines",
      _all_three_fixed.startswith("הנה הסיכום: יעד פריז, 3 לילות, שני מבוגרים.")
      and _all_three_fixed.rstrip().endswith("אם כל הפרטים נכונים, כתבי מאשרת."))

check("a reply already mentioning connection preference via 'קונקשן' "
      "(not 'ישיר') is also recognized as already covered - no duplicate",
      "כבודה" not in chat._ensure_flight_summary_completeness(
          "יעד פריז. ישירה או עם קונקשן. אם כל הפרטים נכונים, כתבי מאשרת.",
          {"flight": {"connection_preference": "flexible"}, "user_gender": "female"},
      ))

check("a known numeric budget amount (not unlimited) is completed the "
      "same way when missing",
      "תקציב לאדם: 1500 ₪" in chat._ensure_flight_summary_completeness(
          "יעד פריז. אם כל הפרטים נכונים, כתבי מאשרת.",
          {"budget_per_person": {"amount": 1500, "currency": "₪"}, "user_gender": "female"},
      ))


# === Shaked's stage-2 run-5 finding (London, 4/5, ba101e4): a budget
#     line that IS present but names the WRONG currency ===

check("_flight_budget_line renders a Hebrew-friendly currency name, "
      "never the bare 3-letter code",
      chat._flight_budget_line({"amount": 250, "currency": "GBP"}) == "תקציב לאדם: 250 פאונד"
      and chat._flight_budget_line({"amount": 500, "currency": "EUR"}) == "תקציב לאדם: 500 יורו"
      and chat._flight_budget_line({"amount": 300, "currency": "USD"}) == "תקציב לאדם: 300 דולר")
check("_flight_budget_line stays backward compatible with an already-"
      "symbol currency value (e.g. '₪' itself, not a 3-letter code)",
      chat._flight_budget_line({"amount": 1500, "currency": "₪"}) == "תקציב לאדם: 1500 ₪")

check("Shaked's exact stage-2 run-5 repro (London, ba101e4): the "
      "customer said 'עד 250 פאונד' (GBP), but the summary wrote the "
      "ILS symbol ('תקציב: עד 250 ₪ לאדם') - the wrong-currency line is "
      "replaced with the correct one, in the same place it already was",
      chat._ensure_flight_summary_completeness(
          "הסיכום: יעד לונדון. תקציב: עד 250 ₪ לאדם. אם כל הפרטים נכונים, כתבי מאשרת.",
          {"budget_per_person": {"amount": 250, "currency": "GBP"}, "user_gender": "female"},
      ) == "הסיכום: יעד לונדון. תקציב לאדם: 250 פאונד. אם כל הפרטים נכונים, כתבי מאשרת.")
check("the same currency-mismatch fix applies to EUR too",
      chat._ensure_flight_summary_completeness(
          "הסיכום: יעד פריז. תקציב: עד 500 ₪ לאדם. אם כל הפרטים נכונים, כתבי מאשרת.",
          {"budget_per_person": {"amount": 500, "currency": "EUR"}, "user_gender": "female"},
      ) == "הסיכום: יעד פריז. תקציב לאדם: 500 יורו. אם כל הפרטים נכונים, כתבי מאשרת.")
check("a budget line that ALREADY names the correct currency is left "
      "completely untouched - no false positive on the real fix",
      chat._ensure_flight_summary_completeness(
          "הסיכום: יעד לונדון. תקציב לאדם: 250 פאונד. אם כל הפרטים נכונים, כתבי מאשרת.",
          {"budget_per_person": {"amount": 250, "currency": "GBP"}, "user_gender": "female"},
      ) == "הסיכום: יעד לונדון. תקציב לאדם: 250 פאונד. אם כל הפרטים נכונים, כתבי מאשרת.")
check("a correct ILS budget line (using the ₪ symbol) is never flagged "
      "as a mismatch against itself",
      chat._ensure_flight_summary_completeness(
          "הסיכום: יעד תל אביב. תקציב לאדם: 1500 ₪. אם כל הפרטים נכונים, כתבי מאשרת.",
          {"budget_per_person": {"amount": 1500, "currency": "ILS"}, "user_gender": "female"},
      ) == "הסיכום: יעד תל אביב. תקציב לאדם: 1500 ₪. אם כל הפרטים נכונים, כתבי מאשרת.")
check("a correct GBP budget line using 'ליש\"ט' (the other recognized "
      "GBP marker, not 'פאונד') is also recognized as already correct",
      "ליש" in chat._ensure_flight_summary_completeness(
          'הסיכום: תקציב לאדם: 250 ליש"ט. אם כל הפרטים נכונים, כתבי מאשרת.',
          {"budget_per_person": {"amount": 250, "currency": "GBP"}, "user_gender": "female"},
      ))


# === End-to-end via _call_tinkerbell: the fix actually applies to a real
#     model reply, not just the unit-level function ===

def _fake_post_claude_missing_budget(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        return "{}"
    return "הנה הסיכום לפריז: יעד פריז, 3 לילות, שני מבוגרים. אם כל הפרטים נכונים, כתבי מאשרת."


with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_missing_budget):
    e2e_reply = chat._call_tinkerbell(
        "test-key", "test-model", [], "אין הגבלה על התקציב",
        {"budget_per_person": {"status": "unlimited"}, "user_gender": "female"},
    )
check("end-to-end via _call_tinkerbell: Shaked's exact stage-2 run-4 "
      "repro (Paris) - a model reply that omits the budget line - comes "
      "back with 'תקציב: ללא הגבלה' through the real reply pipeline, not "
      "just the unit-level function",
      "תקציב: ללא הגבלה" in e2e_reply)


def _fake_post_claude_wrong_currency(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        return "{}"
    return "הסיכום: יעד לונדון. תקציב: עד 250 ₪ לאדם. אם כל הפרטים נכונים, כתבי מאשרת."


with patch.object(chat, "_post_claude", side_effect=_fake_post_claude_wrong_currency):
    e2e_currency_reply = chat._call_tinkerbell(
        "test-key", "test-model", [], "עד 250 פאונד",
        {"budget_per_person": {"amount": 250, "currency": "GBP"}, "user_gender": "female"},
    )
check("end-to-end via _call_tinkerbell: Shaked's exact stage-2 run-5 "
      "repro (London) - a model reply that names the wrong currency - "
      "comes back with the correct 'תקציב לאדם: 250 פאונד' through the "
      "real reply pipeline, not just the unit-level function",
      "תקציב לאדם: 250 פאונד" in e2e_currency_reply and "₪" not in e2e_currency_reply)


if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL STAGE2-RUN4-SUMMARY-COMPLETENESS TESTS PASSED")
