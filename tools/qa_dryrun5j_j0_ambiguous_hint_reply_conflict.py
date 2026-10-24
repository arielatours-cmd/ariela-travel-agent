"""QA for Shaked/Shlomo's 5j finding J0 (23.10.2026, qa/reports/2026-10-23-
dryrun5j.md, relayed by Shlomo): diagnostic.json for turn 0 of the live
Bergen/Bergamo run showed a genuinely live _destination_ambiguous_hint in
state (set by _resolve_destination_by_meaning), yet the actual reply asked
the fully generic "באיזה שדה תרצה לנחות בהלוך?" instead of naming both real
candidates ("ברגן שבנורווגיה או ברגמו שבאיטליה?").

Root cause (confirmed by tracing _call_tinkerbell's actual system_dynamic
prompt text): _destination_catalog_hint's own "unknown place" background
FACT - deliberately never gated by _turn_question_arbiter, since a fact
must survive regardless of which question wins this turn - ends with its
OWN "ask this as your one question" imperative ("אם יש יותר משדה קרוב אחד,
זו שאלה שהלקוח בוחר בה: שאלי אותה כשאלה היחידה בהודעה"), appearing in the
SAME prompt right after the arbiter's own, more specific "the following
question is the ONLY thing to ask" instruction (_destination_ambiguous_
hint, naming the real candidates) - two competing "this is your one
question" instructions for the exact same underlying situation (the raw,
still-ambiguous spelling has no catalog entry of its own, which is
precisely WHY it's ambiguous in the first place).

Fixed: _destination_catalog_hint now skips its own generic "ask this as
your one question" sentence whenever state already carries a live
_destination_ambiguous_hint - the arbiter's own, more specific instruction
already owns that job. Every other part of the background fact (the
don't-invent-an-airport verification warning) is unchanged and still
always present. The genuinely-unresolved case with no live arbiter hint at
all (Rovinj/Pula - dry-run 3, Shaked) is unaffected - that generic sentence
is still the ONLY mechanism telling Tinkerbell to ask about nearby
options there, so it still fires exactly as before.

Run: python3 tools/qa_dryrun5j_j0_ambiguous_hint_reply_conflict.py
"""
import os
import sys

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


def _traced_system_dynamic(state, message):
    captured = {}

    def _fake(key, model, system_static, system_dynamic, history, msg, max_tokens, include_history=True, source="other", **kw):
        captured["system_dynamic"] = system_dynamic
        return "דמה"

    with patch.object(chat, "_post_claude", side_effect=_fake):
        chat._call_tinkerbell("test-key-not-real", "claude-sonnet-5", [], message, state=state)
    return captured.get("system_dynamic") or ""


GENERIC_COMPETING_SENTENCE = "זו שאלה שהלקוח בוחר בה"

# =====================================================================
# J0 FIX: a genuinely live _destination_ambiguous_hint (Bergen/Bergamo)
# must be the ONLY "ask this as your one question" instruction Tinkerbell
# sees - the generic background-fact sentence must not also compete for
# that same framing.
# =====================================================================
BERGEN_BERGAMO_STATE = {
    "destination": {"places": ["ברגם"], "mode": "specific", "status": "known"},
    "destination_airports": [],
    "_destination_ambiguous_hint": chat._destination_ambiguous_hint_from_candidates(
        [("city", "BGO"), ("city", "BGY")]),
}
sd_ambiguous = _traced_system_dynamic(BERGEN_BERGAMO_STATE, "אני רוצה לטוס לברגם")
check("J0 FIX: the generic 'ask this as your one question' background-fact "
      "sentence is suppressed when a specific _destination_ambiguous_hint is live",
      GENERIC_COMPETING_SENTENCE not in sd_ambiguous)
check("J0 FIX: the arbiter's own specific instruction (naming both real "
      "candidates) is still present",
      "ברגן (נורווגיה) או ברגמו (איטליה)" in sd_ambiguous)
check("J0 FIX: the arbiter's priority framing ('the following question is "
      "the only thing to ask') is still present",
      "השאלה/הנחיה הבאה היא הדבר היחיד שצריך לברר" in sd_ambiguous)
check("J0 FIX: the don't-invent-an-airport verification warning is still "
      "present (only the competing imperative sentence was removed)",
      "אסור לך להמציא או" in sd_ambiguous)

# =====================================================================
# Regression: the genuinely-unresolved case with NO live arbiter hint at
# all (dry-run 3, Shaked, Rovinj/Pula) must be completely unaffected - the
# generic sentence is the only mechanism asking about nearby options there.
# =====================================================================
ROVINJ_STATE = {
    "destination": {"places": ["רוביניה"], "mode": "specific", "status": "known"},
    "destination_airports": [],
}
sd_rovinj = _traced_system_dynamic(ROVINJ_STATE, "אני רוצה לטוס לרוביניה")
check("regression (Rovinj/Pula, dry-run 3): with no live _destination_ambiguous_hint "
      "at all, the generic 'ask about nearby options' sentence still fires normally",
      GENERIC_COMPETING_SENTENCE in sd_rovinj)

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL DRYRUN5J-J0-AMBIGUOUS-HINT-REPLY-CONFLICT TESTS PASSED")
