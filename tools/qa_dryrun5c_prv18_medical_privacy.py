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

Three gaps, all fixed here:
1. The leak itself: added a new TINKERBELL_SYSTEM rule forbidding any
   reference to the medical reason (surgery/diagnosis/condition) in any
   reply, plus a structural backstop (_retry_if_medical_detail_leaked) -
   a classifier judges the REPLY alone (never a word list - a diagnosis
   can be phrased endless ways) and forces one retry when it leaked.
2. A SEPARATE completion gap in _guided_field_update_and_confirm: when
   detail_category comes back null/invalid (not literally "other") on a
   SECOND attempt (post the existing "other"-category retry), needs=
   ["other"] got saved with NO details phrase at all - worse than the
   literal "other" case, which already falls back to the generic phrase.
   Fixed to fall back to the same generic phrase whenever needs contains
   "other" but the category itself didn't map to anything.
3. Shaked's static review of the first cut (6b1efab, 22.10.2026): the
   original gate (accessibility.needed is True, plus a reply-text keyword
   scan for "נגישות"/"התאמה") had two real holes - needed stayed None
   after a low-confidence/failed/other_topic extraction even when a
   medical reason WAS named in that same message (never checked at all),
   and a reply naming the reason without either trigger word (e.g. "בגלל
   הניתוח בברך של אמא נבקש מושב קרוב למעבר" - a seat-choice reply, never
   says "נגישות"/"התאמה") or using the plain plural ("התאמות" is not a
   substring of "התאמה") slipped through the pre-filter undetected.
   Replaced with a STICKY state flag (accessibility._medical_detail_
   mentioned) set by the SAME accessibility classifier call (cost-
   neutral) the moment the customer's own message names a medical reason,
   independent of how needed itself resolves - and the reply-text keyword
   pre-filter is gone entirely (the classifier call is now unconditional
   once the sticky flag is set, same as its sibling guards
   _guard_baggage_type_self_picked/_guard_accessibility_question_skipped).

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
# Part 1: the structural backstop itself (_retry_if_medical_detail_leaked),
# gated on the STICKY accessibility._medical_detail_mentioned flag - never
# on accessibility.needed, never on a reply-text keyword scan.
# =====================================================================
STATE_MENTIONED = {"accessibility": {"needed": True, "needs": ["other"], "_medical_detail_mentioned": True}}
STATE_NOT_MENTIONED = {"accessibility": {"needed": True, "needs": ["other"]}}
STATE_NO_ACCESSIBILITY = {"accessibility": {"needed": False}}
LEAKED_REPLY = "ציינת שלאמא קשה ללכת מרחקים ארוכים בעקבות ניתוח בברך; אתחשב בזה בבחירת הטיסה."
SAFE_REPLY = "ציינת שלאמא קשה ללכת מרחקים ארוכים; אתחשב בזה בבחירת הטיסה."
# Shaked's two repro phrasings the OLD keyword gate missed entirely - no
# "נגישות"/"התאמה" substring in either (a seat-choice reply that still
# names the medical reason; a plural "התאמות" that never matches the
# singular "התאמה" substring the old gate scanned for).
LEAKED_NO_TRIGGER_WORD = "בגלל הניתוח בברך של אמא נבקש מושב קרוב למעבר."
LEAKED_PLURAL_ONLY = "נדרשות התאמות מיוחדות בגלל הניתוח שאמא עברה."


def _fake_classifier_says(leaked):
    def _fake(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
        if source == "classifier":
            return '{"leaked": %s}' % ("true" if leaked else "false")
        return "{}"
    return _fake


with patch.object(chat, "_post_claude", side_effect=_fake_classifier_says(True)) as mock_leak:
    result_leak = chat._retry_if_medical_detail_leaked(KEY, MODEL, [], "אמא שלי עברה ניתוח בברך", STATE_MENTIONED, LEAKED_REPLY)
check("scenario A repro: a reply that leaks the medical reason triggers a retry (non-None)",
      result_leak is not None)

with patch.object(chat, "_post_claude", side_effect=_fake_classifier_says(False)) as mock_safe:
    result_safe = chat._retry_if_medical_detail_leaked(KEY, MODEL, [], "אמא שלי עברה ניתוח בברך", STATE_MENTIONED, SAFE_REPLY)
check("regression: a safe reply (practical need only, no medical reason) is never retried",
      result_safe is None and mock_safe.call_count == 1)

check("regression: accessibility._medical_detail_mentioned is not True -> never calls the classifier at all (cost control)",
      chat._retry_if_medical_detail_leaked(KEY, MODEL, [], "כן", STATE_NOT_MENTIONED, LEAKED_REPLY) is None)
with patch.object(chat, "_post_claude") as mock_unused:
    chat._retry_if_medical_detail_leaked(KEY, MODEL, [], "כן", STATE_NOT_MENTIONED, LEAKED_REPLY)
check("regression: accessibility.needed=True alone (no medical mention ever flagged) -> zero classifier calls",
      not mock_unused.called)
with patch.object(chat, "_post_claude") as mock_unused2:
    chat._retry_if_medical_detail_leaked(KEY, MODEL, [], "כן", STATE_NO_ACCESSIBILITY, LEAKED_REPLY)
check("regression: no accessibility need at all -> zero classifier calls",
      not mock_unused2.called)

# Shaked's fix: the classifier now runs on EVERY reply once the sticky
# flag is set, regardless of reply content - no reply-text pre-filter
# left to skip a reply that happens not to mention the topic by name.
with patch.object(chat, "_post_claude", side_effect=_fake_classifier_says(False)) as mock_any_reply:
    chat._retry_if_medical_detail_leaked(KEY, MODEL, [], "עד 1100 שקל", STATE_MENTIONED,
                                          "נרשם, תקציב של עד 1,100 ש\"ח לאדם. לגבי הטיסה - חשוב לך שתהיה ישירה?")
check("Shaked's fix: the classifier call is unconditional once the sticky flag is set - "
      "no reply-text keyword pre-filter left to skip an unrelated-looking reply",
      mock_any_reply.called)

# Shaked's two repro phrasings the OLD keyword gate missed - both now
# correctly reach (and are caught by) the classifier.
with patch.object(chat, "_post_claude", side_effect=_fake_classifier_says(True)) as mock_no_trigger:
    result_no_trigger = chat._retry_if_medical_detail_leaked(KEY, MODEL, [], "אמא שלי עברה ניתוח בברך", STATE_MENTIONED, LEAKED_NO_TRIGGER_WORD)
check("Shaked's fix: a leak with neither 'נגישות' nor 'התאמה' anywhere in the reply "
      "(old keyword gate would have skipped it) still reaches the classifier and is caught",
      mock_no_trigger.called and result_no_trigger is not None)

with patch.object(chat, "_post_claude", side_effect=_fake_classifier_says(True)) as mock_plural:
    result_plural = chat._retry_if_medical_detail_leaked(KEY, MODEL, [], "אמא שלי עברה ניתוח בברך", STATE_MENTIONED, LEAKED_PLURAL_ONLY)
check("Shaked's fix: a leak using only the plural 'התאמות' (not a substring of the old "
      "gate's singular 'התאמה') still reaches the classifier and is caught",
      mock_plural.called and result_plural is not None)

# Shaked's note: needed=None after a failed/low-confidence/other_topic
# extraction was never checked at all under the old gate - the sticky
# flag fixes this directly, since it's independent of needed.
STATE_MENTIONED_NEEDED_NONE = {"accessibility": {"needed": None, "_medical_detail_mentioned": True}}
with patch.object(chat, "_post_claude", side_effect=_fake_classifier_says(True)) as mock_needed_none:
    result_needed_none = chat._retry_if_medical_detail_leaked(KEY, MODEL, [], "אמא שלי עברה ניתוח בברך", STATE_MENTIONED_NEEDED_NONE, LEAKED_REPLY)
check("Shaked's fix: accessibility.needed=None (extraction never resolved it) no longer "
      "blocks the backstop - the sticky medical-mention flag is the only gate that matters",
      mock_needed_none.called and result_needed_none is not None)

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
    _final = chat._call_tinkerbell(KEY, MODEL, [], "אמא שלי עברה ניתוח בברך", dict(STATE_MENTIONED))
check("end-to-end: _call_tinkerbell retries a leaking reply automatically and lands on the safe one",
      "ניתוח" not in _final and "קשה ללכת מרחקים ארוכים" in _final)
check("end-to-end: exactly one retry happened (two tinkerbell_reply calls)",
      _calls["n"] == 2)


# =====================================================================
# Part 2: _guided_field_update_and_confirm sets the sticky flag from the
# classifier's own mentions_medical_reason field - independent of needed,
# and never cleared by a later turn that doesn't mention one.
# =====================================================================
MENTIONS_WITH_NEEDED_TRUE = {
    "status": "answered", "needed": True, "needs": ["walking_long_distance"],
    "detail_category": "walking_long_distance", "confidence": "high",
    "mentions_medical_reason": True, "also_mentioned": None, "correction": None,
}
fragment_mentioned, _ = chat._guided_field_update_and_confirm("accessibility", MENTIONS_WITH_NEEDED_TRUE)
check("dr5c fix: mentions_medical_reason=True with needed=True sets the sticky flag",
      fragment_mentioned.get("accessibility", {}).get("_medical_detail_mentioned") is True)

MENTIONS_WITH_NEEDED_NONE = {
    "status": "unclear", "needed": None, "needs": [], "detail_category": None,
    "confidence": "low", "mentions_medical_reason": True, "also_mentioned": None, "correction": None,
}
fragment_needed_none, _ = chat._guided_field_update_and_confirm("accessibility", MENTIONS_WITH_NEEDED_NONE)
check("Shaked's fix: mentions_medical_reason=True with needed=None (extraction didn't "
      "resolve it) STILL sets the sticky flag - previously this whole case returned an "
      "empty fragment and the mention was silently lost",
      fragment_needed_none.get("accessibility", {}).get("_medical_detail_mentioned") is True)

NO_MENTION_RESULT = {
    "status": "answered", "needed": True, "needs": ["wheelchair"], "detail_category": "wheelchair",
    "confidence": "high", "mentions_medical_reason": False, "also_mentioned": None, "correction": None,
}
fragment_no_mention, _ = chat._guided_field_update_and_confirm("accessibility", NO_MENTION_RESULT)
check("regression: mentions_medical_reason=False never sets the flag at all",
      "_medical_detail_mentioned" not in fragment_no_mention.get("accessibility", {}))

NO_MENTION_NEEDED_NONE = {
    "status": "other_topic", "needed": None, "needs": [], "detail_category": None,
    "confidence": "low", "mentions_medical_reason": False, "also_mentioned": None, "correction": None,
}
check("regression: needed=None with no medical mention either -> still the original empty fragment",
      chat._guided_field_update_and_confirm("accessibility", NO_MENTION_NEEDED_NONE) == ({}, None))


# =====================================================================
# Part 3: _guided_field_update_and_confirm's own completion gap - needs=
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
