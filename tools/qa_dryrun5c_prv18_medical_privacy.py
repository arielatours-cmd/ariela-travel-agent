"""QA for dry-run 5c item 2 (Shlomo/Shaked, 22.10.2026, qa/reports/
2026-10-22-dryrun5c.md, scenario A, Paphos) - called BLOCKING by Shlomo:

"אמא שלי עברה ניתוח בברך והיא מתקשה ללכת מרחקים ארוכים" (my mother had
knee surgery and has trouble walking long distances) was correctly left
OUT of accessibility.details in state (the extraction layer's own closed-
category rule already worked), yet Tinkerbell's own FINAL SUMMARY still
read "ציינת שלאמא קשה ללכת מרחקים ארוכים בעקבות ניתוח בברך" - the raw
medical detail ("following knee surgery"), quoted straight from the
conversation history she always has access to, not from the sanitized
fact handed to her via _accessibility_hint_text. This is a PRV-18
violation regardless of what's actually stored in state.

Two separate gaps, both fixed here:
1. The leak itself: added a new TINKERBELL_SYSTEM rule forbidding any
   reference to the medical reason (surgery/diagnosis/condition) in any
   reply, plus a structural backstop (_retry_if_medical_detail_leaked) -
   a classifier judges the REPLY alone (never a word list - a diagnosis
   can be phrased endless ways) and forces one retry when it leaked.
   Scoped to accessibility.needed is True only (cost-neutral for the
   overwhelming majority of conversations that never touch it).
2. A SEPARATE completion gap in _guided_field_update_and_confirm: when
   detail_category comes back null/invalid (not literally "other") on a
   SECOND attempt (post the existing "other"-category retry), needs=
   ["other"] got saved with NO details phrase at all - worse than the
   literal "other" case, which already falls back to the generic phrase.
   Fixed to fall back to the same generic phrase whenever needs contains
   "other" but the category itself didn't map to anything.

Run: python3 tools/qa_dryrun5c_prv18_medical_privacy.py
"""
import os
import sys
import json
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")
os.environ.setdefault("SCHEDULER_ENABLED", "false")

import ariella_chat_clean as chat  # noqa: E402

FAILED = []


def check(name, cond):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        FAILED.append(name)


KEY = os.getenv("ANTHROPIC_API_KEY", "test-key-not-real")
MODEL = "claude-sonnet-5"

check("TINKERBELL_SYSTEM documents the PRV-18 medical-privacy rule",
      "PRV-18" in chat.TINKERBELL_SYSTEM and "ניתוח" in chat.TINKERBELL_SYSTEM)

# =====================================================================
# Part 1: the structural backstop itself (_retry_if_medical_detail_leaked).
# =====================================================================
STATE_NEEDED = {"accessibility": {"needed": True, "needs": ["other"]}}
STATE_NOT_NEEDED = {"accessibility": {"needed": False}}
LEAKED_REPLY = "לגבי הנגישות - ציינת שלאמא קשה ללכת מרחקים ארוכים בעקבות ניתוח בברך; אתחשב בזה בבחירת הטיסה."
SAFE_REPLY = "לגבי הנגישות - ציינת שלאמא קשה ללכת מרחקים ארוכים; אתחשב בזה בבחירת הטיסה."


def _fake_classifier_says(leaked):
    def _fake(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
        if source == "classifier":
            return '{"leaked": %s}' % ("true" if leaked else "false")
        return "{}"
    return _fake


with patch.object(chat, "_post_claude", side_effect=_fake_classifier_says(True)) as mock_leak:
    result_leak = chat._retry_if_medical_detail_leaked(KEY, MODEL, [], "אמא שלי עברה ניתוח בברך", STATE_NEEDED, LEAKED_REPLY)
check("scenario A repro: a reply that leaks the medical reason triggers a retry (non-None)",
      result_leak is not None)

with patch.object(chat, "_post_claude", side_effect=_fake_classifier_says(False)) as mock_safe:
    result_safe = chat._retry_if_medical_detail_leaked(KEY, MODEL, [], "אמא שלי עברה ניתוח בברך", STATE_NEEDED, SAFE_REPLY)
check("regression: a safe reply (practical need only, no medical reason) is never retried",
      result_safe is None and mock_safe.call_count == 1)

check("regression: accessibility.needed is not True -> never calls the classifier at all (cost control)",
      chat._retry_if_medical_detail_leaked(KEY, MODEL, [], "כן", STATE_NOT_NEEDED, LEAKED_REPLY) is None)
with patch.object(chat, "_post_claude") as mock_unused:
    chat._retry_if_medical_detail_leaked(KEY, MODEL, [], "כן", STATE_NOT_NEEDED, LEAKED_REPLY)
check("regression: no accessibility need at all -> zero classifier calls",
      not mock_unused.called)

# Dry-run 5c item 5 (cost control): a reply that doesn't even mention
# accessibility/an accommodation at all skips the classifier entirely -
# most turns while accessibility.needed stays True for the rest of the
# conversation (budget, baggage, destination, route planning...).
UNRELATED_REPLY = "נרשם, תקציב של עד 1,100 ש\"ח לאדם. לגבי הטיסה - חשוב לך שתהיה ישירה?"
with patch.object(chat, "_post_claude") as mock_unrelated:
    result_unrelated = chat._retry_if_medical_detail_leaked(KEY, MODEL, [], "עד 1100 שקל", STATE_NEEDED, UNRELATED_REPLY)
check("dr5c item 5: a reply with no mention of accessibility/an accommodation at all "
      "skips the classifier entirely (cheap structural pre-filter)",
      result_unrelated is None and not mock_unrelated.called)

# End-to-end through _call_tinkerbell: first reply leaks, retry is clean.
_calls = {"n": 0}


def _fake_end_to_end(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if source == "tinkerbell_reply":
        _calls["n"] += 1
        if _calls["n"] == 1:
            return LEAKED_REPLY
        return SAFE_REPLY
    if source == "classifier":
        return '{"leaked": true}' if _calls["n"] == 1 else '{"leaked": false}'
    return "{}"


with patch.object(chat, "_post_claude", side_effect=_fake_end_to_end):
    _final = chat._call_tinkerbell(KEY, MODEL, [], "אמא שלי עברה ניתוח בברך", dict(STATE_NEEDED))
check("end-to-end: _call_tinkerbell retries a leaking reply automatically and lands on the safe one",
      "ניתוח" not in _final and "קשה ללכת מרחקים ארוכים" in _final)
check("end-to-end: exactly one retry happened (two tinkerbell_reply calls)",
      _calls["n"] == 2)


# =====================================================================
# Part 2: _guided_field_update_and_confirm's own completion gap - needs=
# ["other"] with a null/invalid detail_category must still get a details
# phrase (the same generic one the literal "other" string already gets).
# =====================================================================
NULL_CATEGORY_RESULT = {
    "status": "answered", "needed": True, "needs": ["other"], "detail_category": None,
    "confidence": "high", "also_mentioned": None, "correction": None,
}
fragment, desc = chat._guided_field_update_and_confirm("accessibility", NULL_CATEGORY_RESULT)
check("dr5c fix: needs=['other'] with a null detail_category still gets the generic details phrase",
      fragment.get("accessibility", {}).get("details") == chat._ACCESSIBILITY_DETAIL_PHRASES_HE["other"])
check("dr5c fix: needs itself is still saved as ['other']",
      fragment.get("accessibility", {}).get("needs") == ["other"])

INVALID_CATEGORY_RESULT = {
    "status": "answered", "needed": True, "needs": ["other"], "detail_category": "some_made_up_category",
    "confidence": "high", "also_mentioned": None, "correction": None,
}
fragment2, _ = chat._guided_field_update_and_confirm("accessibility", INVALID_CATEGORY_RESULT)
check("dr5c fix: needs=['other'] with an invented/invalid detail_category string also falls back to the generic phrase",
      fragment2.get("accessibility", {}).get("details") == chat._ACCESSIBILITY_DETAIL_PHRASES_HE["other"])

# Regression: a genuinely specific, valid category is unaffected - the
# real phrase is used, never the generic fallback.
SPECIFIC_RESULT = {
    "status": "answered", "needed": True, "needs": ["wheelchair"], "detail_category": "wheelchair",
    "confidence": "high", "also_mentioned": None, "correction": None,
}
fragment3, _ = chat._guided_field_update_and_confirm("accessibility", SPECIFIC_RESULT)
check("regression: a specific, valid category still gets its own real phrase, not the generic fallback",
      fragment3.get("accessibility", {}).get("details") == chat._ACCESSIBILITY_DETAIL_PHRASES_HE["wheelchair"])

# Regression: needs is genuinely empty (no "other" either) and category is
# null - details correctly stays absent (nothing to fall back from).
EMPTY_RESULT = {
    "status": "answered", "needed": True, "needs": [], "detail_category": None,
    "confidence": "low", "also_mentioned": None, "correction": None,
}
fragment4, _ = chat._guided_field_update_and_confirm("accessibility", EMPTY_RESULT)
check("regression: no needs at all and no category - details correctly stays absent",
      "details" not in fragment4.get("accessibility", {}))


if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL DRYRUN5C-PRV18-MEDICAL-PRIVACY TESTS PASSED")
