"""QA for round-13 live finding A (24.10.2026, Paphos, qa/reports/2026-10-
24-live13.md on branch `shaked`, main a8b6425): on "yes" to the
accessibility question, no follow-up question was asked, the reply
claimed "אדאג להתאמה שציינת" (I'll arrange the accommodation you
mentioned) when nothing was specified, and the saved state was a generic
"other" placeholder with the practical need from the NEXT message never
captured.

The business owner's directive (relayed by Shlomo, two follow-up
messages, 24.10.2026): "אם אריאלה שואלת האם יש צורך בנגישות והלקוח עונה
שכן - היא צריכה להתייחס לזה כאל כסא גלגלים לכל דבר ולהתאים את עצמה. לא
משנה מה הסיבה" (treat it like a wheelchair case for everything, whatever
the reason) and "אין צורך לפרט" (no need to detail). The summary must
explicitly state "נגישות: נדרשת התאמה מלאה (כיסא גלגלים)", never "אדאג
להתאמה שציינת". Scope is conversation-level only (ariella_chat_clean.py) -
lodging/car/route-level accessibility changes stay in Ofek's plan 023a,
after testing (the business owner's separate 24.10 message).

Fixed in two parts:
(a) _guided_field_update_and_confirm's accessibility branch: a bare "yes"
    with nothing volunteered in the same message (needs/detail_category
    both empty) now resolves immediately to needs=["wheelchair"],
    details=_ACCESSIBILITY_FULL_NEED_DETAILS_HE - never left empty. Since
    _guided_field_known_with_confidence("accessibility", ...) already
    requires needs/details to be non-empty, this makes the field count
    as answered on THIS turn through the EXISTING guided-dispatch control
    flow, with no special-case rewiring - _accessibility_awaiting_detail
    (and the whole open-follow-up turn it used to trigger) becomes
    structurally unreachable rather than needing to be ripped out.
(b) With no follow-up turn left to ground Tinkerbell's own
    acknowledgment, she had nothing to go on and improvised the
    presumptuous "אדאג להתאמה שציינת" live. A one-turn marker,
    _accessibility_just_resolved (same lifetime pattern as the existing
    _mixed_baggage_just_resolved: set in _handle_guided_extraction_turn,
    popped at the top of the next turn's guided dispatch), makes
    _accessibility_hint_text fire on THIS exact turn with wording
    specific to a fresh resolution - explicitly forbidding a claim that
    the customer specified anything, and forbidding a follow-up "why".

Covers only the pieces not already exercised by
tools/qa_guided_extraction_accessibility_014b.py's rewritten scenario 4
(the bare-yes default itself) and the existing PRV-18/other-category
suites (volunteered medical detail handling, unaffected by this change).

Run: python3 tools/qa_dryrun_live13_a_accessibility_full_immediately.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")
os.environ.setdefault("SCHEDULER_ENABLED", "false")

import ariella_chat_clean as chat

FAILED = []


def check(name, cond):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        FAILED.append(name)


# =====================================================================
# (a) the data-layer default itself, via _guided_field_update_and_confirm
# directly (unit-level, complementing the 014b file's full HTTP scenario).
# =====================================================================
BARE_YES_RESULT = {"needed": True, "needs": [], "detail_category": None, "mentions_medical_reason": False}
fragment, desc = chat._guided_field_update_and_confirm("accessibility", BARE_YES_RESULT)
acc = fragment.get("accessibility") or {}
check("(a) a bare yes resolves to needs=['wheelchair'] immediately",
      acc.get("needs") == ["wheelchair"])
check("(a) details is the fixed full-accommodation phrase, never a guess",
      acc.get("details") == chat._ACCESSIBILITY_FULL_NEED_DETAILS_HE)
check("(a) the confirm description reflects the resolved need, not empty",
      desc == chat._ACCESSIBILITY_FULL_NEED_DETAILS_HE)

# A specific detail volunteered unprompted in the SAME message still wins -
# the default only applies when truly nothing at all was given.
VOLUNTEERED_RESULT = {"needed": True, "needs": ["reduced_mobility"], "detail_category": "walking_long_distance",
                       "mentions_medical_reason": False}
fragment2, _ = chat._guided_field_update_and_confirm("accessibility", VOLUNTEERED_RESULT)
acc2 = fragment2.get("accessibility") or {}
check("(a) regression: a specific need volunteered in the same message is "
      "still saved as-is, never overridden by the full-accommodation default",
      acc2.get("needs") == ["reduced_mobility"] and acc2.get("details") == "קושי בהליכה למרחקים ארוכים")

# =====================================================================
# (b) _accessibility_hint_text's new wording for the exact resolution turn.
# =====================================================================
JUST_RESOLVED_STATE = {
    "guided": {"steps": ["accessibility"]},
    "accessibility": {"needed": True, "needs": ["wheelchair"], "details": chat._ACCESSIBILITY_FULL_NEED_DETAILS_HE},
    "_accessibility_just_resolved": True,
}
hint = chat._accessibility_hint_text(JUST_RESOLVED_STATE)
check("(b) the just-resolved hint fires with the full-accommodation text",
      chat._ACCESSIBILITY_FULL_NEED_DETAILS_HE in hint)
check("(b) the hint explicitly forbids claiming the customer specified "
      "anything (the exact live bug: 'אדאג להתאמה שציינת')",
      "אל תטעני" in hint and "ציין" in hint)
check("(b) the hint explicitly forbids a follow-up question about the "
      "reason/detail",
      "שאלת המשך" in hint)

# One-turn lifetime: without the marker, even with the identical
# accessibility state, the generic (session-start/summary-gated) hint
# logic applies instead - never the just-resolved wording forever.
STALE_STATE = dict(JUST_RESOLVED_STATE)
STALE_STATE.pop("_accessibility_just_resolved")
stale_hint = chat._accessibility_hint_text(STALE_STATE)
check("(b) regression: without the marker (a later turn), the just-"
      "resolved wording is never shown - ordinary session-start/summary "
      "gating applies instead",
      "אל תטעני" not in stale_hint)

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL DRYRUN-LIVE13-A-ACCESSIBILITY-FULL-IMMEDIATELY TESTS PASSED")
