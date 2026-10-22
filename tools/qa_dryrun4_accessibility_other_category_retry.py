"""QA for dry-run 4 finding 2 (Shaked/Shlomo, 22.10.2026, qa/reports/
2026-10-22-dryrun4.md): the accessibility open follow-up's detail_category
classifier has a closed list of specific practical buckets (walking_short/
walking_long_distance/stairs/wheelchair/stroller/escort/luggage_help/
boarding_help/hearing/vision) plus "other" as a genuine catch-all - but
"other" alone resolves to the generic label "התאמה מיוחדת אחרת"
(_ACCESSIBILITY_DETAIL_PHRASES_HE), which is useless to actually check with
any supplier. The old code accepted a high-confidence "other" result as
final immediately, same as any specific category, closing accessibility
with nothing concrete ever recorded.

Business owner's approved fix (22.10, relayed by Shlomo): the FIRST time the
open follow-up classifies as "other", ask once more for a concrete,
practical description before accepting it - a SECOND "other" (post-retry)
is accepted as final rather than looping forever.

Offline (the guided extraction is stubbed, same pattern as
tools/qa_dryrun4_mixed_while_accessibility.py). Run:
python3 tools/qa_dryrun4_accessibility_other_category_retry.py
"""
import os
import sys
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


STEPS = {"dates", "travelers", "baggage", "accessibility"}


def awaiting_detail_state():
    """The customer already said yes (needed=True), no detail yet - the
    open follow-up is the live question this turn."""
    g = {"current_question": "accessibility", "attempts": 0, "answered": ["dates", "travelers"]}
    return {"requested_services": ["flights"], "travelers": {"adults": 2},
            "dates": {"departure": "2027-04-20", "return": "2027-04-25"},
            "accessibility": {"announced": ["flights"], "asked": True, "needed": True},
            "flight": {"baggage": []}, "guided": g}


def run(state, message, accessibility_result):
    with patch.object(chat, "_guided_extract_answer", return_value=accessibility_result), \
            patch.object(chat, "_guided_redirect_field", return_value=None), \
            patch.object(chat, "record_diagnostic_event"):
        result = chat._handle_guided_extraction_turn("k", "m", message, [], state, dict(state), STEPS)
    return result or {"trip_update": dict(state), "dynamic_hint": None}


OTHER_RESULT = {
    "status": "answered", "needed": True, "needs": ["other"], "detail_category": "other",
    "confidence": "high", "also_mentioned": None, "correction": None,
}
SPECIFIC_RESULT = {
    "status": "answered", "needed": True, "needs": ["wheelchair"], "detail_category": "wheelchair",
    "confidence": "high", "also_mentioned": None, "correction": None,
}

# --- 1. First "other" classification retries instead of settling ---
state1 = awaiting_detail_state()
r1 = run(state1, "קצת קשה לה בדברים כלליים בטיול", OTHER_RESULT)
tu1 = r1["trip_update"]
check(
    "finding 2 repro: a first 'other' classification does NOT close accessibility",
    "accessibility" not in (tu1.get("guided") or {}).get("answered", []),
)
check(
    "finding 2 repro: current_question stays 'accessibility' for the retry",
    (tu1.get("guided") or {}).get("current_question") == "accessibility",
)
check(
    "finding 2 repro: the retry flag is set so a second 'other' is accepted",
    bool((tu1.get("guided") or {}).get("accessibility_other_retried")),
)
check(
    "finding 2 repro: nothing is merged into accessibility.details yet (still awaiting detail next turn)",
    not (tu1.get("accessibility") or {}).get("details"),
)
check(
    "finding 2 repro: a concrete retry hint is returned, not the generic settle flow",
    "עדיין כללי מדי" in str(r1.get("dynamic_hint") or ""),
)

# --- 2. A second "other" in a row (post-retry) is accepted as final ---
state2 = awaiting_detail_state()
state2["guided"]["accessibility_other_retried"] = True
r2 = run(state2, "סתם, לא יודעת בדיוק", OTHER_RESULT)
tu2 = r2["trip_update"]
check(
    "regression: a second 'other' (post-retry) IS accepted and closes accessibility",
    "accessibility" in (tu2.get("guided") or {}).get("answered", []),
)
check(
    "regression: the generic 'other' label is saved rather than looping forever",
    (tu2.get("accessibility") or {}).get("details") == chat._ACCESSIBILITY_DETAIL_PHRASES_HE["other"],
)

# --- 3. A SPECIFIC category (not "other") is never retried - settles immediately ---
state3 = awaiting_detail_state()
r3 = run(state3, "אמא שלי בכיסא גלגלים", SPECIFIC_RESULT)
tu3 = r3["trip_update"]
check(
    "regression: a specific detail_category (wheelchair) is accepted on the first answer, no retry",
    "accessibility" in (tu3.get("guided") or {}).get("answered", []),
)
check(
    "regression: the specific phrase is saved, not the generic 'other' label",
    (tu3.get("accessibility") or {}).get("details") == chat._ACCESSIBILITY_DETAIL_PHRASES_HE["wheelchair"],
)


# =====================================================================
# Dry-run 5b item 4 (22.10.2026, scenario A, Paphos): "אמא שלי עברה ניתוח
# בברך והיא מתקשה ללכת מרחקים ארוכים" - word-for-word the exact example
# already baked into the classifier's own prompt for detail_category:
# "walking_long_distance" - still ended up saved as needs:["other"] with
# NO details at all. Root cause: the retry above only widened to the
# literal string "other" - but the live result had detail_category
# null/missing (not the string "other") while needs still contained
# "other" - WORSE than the literal "other" case (that one at least maps
# to a real phrase via _ACCESSIBILITY_DETAIL_PHRASES_HE; null maps to
# nothing, so acc["details"] never gets set at all downstream). Fixed to
# widen the retry trigger to "whatever _ACCESSIBILITY_DETAIL_PHRASES_HE
# actually computes is falsy" (covers null/invalid too), not just the
# literal string "other".
# =====================================================================
NULL_CATEGORY_RESULT = {
    "status": "answered", "needed": True, "needs": ["other"], "detail_category": None,
    "confidence": "high", "also_mentioned": None, "correction": None,
}
state4 = awaiting_detail_state()
r4 = run(state4, "אמא שלי עברה ניתוח בברך והיא מתקשה ללכת מרחקים ארוכים", NULL_CATEGORY_RESULT)
tu4 = r4["trip_update"]
check(
    "dr5b fix: a null/missing detail_category (needs=['other'] but no usable "
    "category at all) does NOT close accessibility with nothing recorded - it retries",
    "accessibility" not in (tu4.get("guided") or {}).get("answered", []),
)
check(
    "dr5b fix: current_question stays 'accessibility' for the retry",
    (tu4.get("guided") or {}).get("current_question") == "accessibility",
)
check(
    "dr5b fix: the retry flag is set so a second attempt is accepted",
    bool((tu4.get("guided") or {}).get("accessibility_other_retried")),
)
check(
    "dr5b fix: nothing is merged into accessibility.details yet (still awaiting detail next turn)",
    not (tu4.get("accessibility") or {}).get("details"),
)
check(
    "dr5b fix: a concrete retry hint is returned, not the generic settle flow",
    "עדיין כללי מדי" in str(r4.get("dynamic_hint") or ""),
)

# Regression: a SECOND null-category answer in a row (post-retry) is
# accepted as final rather than looping forever, exactly like the literal
# "other" case - needs=["other"] is saved even with no details phrase.
state5 = awaiting_detail_state()
state5["guided"]["accessibility_other_retried"] = True
r5 = run(state5, "סתם קשה לה קצת", NULL_CATEGORY_RESULT)
tu5 = r5["trip_update"]
check(
    "regression: a second null-category answer (post-retry) IS accepted and closes accessibility",
    "accessibility" in (tu5.get("guided") or {}).get("answered", []),
)
check(
    "regression: needs=['other'] is still saved even though details has nothing to show",
    (tu5.get("accessibility") or {}).get("needs") == ["other"]
    and not (tu5.get("accessibility") or {}).get("details"),
)

# Regression: the exact live example sentence, now correctly classified by
# the model as walking_long_distance (the prompt's own baked-in example) -
# never retried, settles immediately with the real phrase saved.
WALKING_LONG_DISTANCE_RESULT = {
    "status": "answered", "needed": True, "needs": ["other"], "detail_category": "walking_long_distance",
    "confidence": "high", "also_mentioned": None, "correction": None,
}
state6 = awaiting_detail_state()
r6 = run(state6, "אמא שלי עברה ניתוח בברך והיא מתקשה ללכת מרחקים ארוכים", WALKING_LONG_DISTANCE_RESULT)
tu6 = r6["trip_update"]
check(
    "regression: a correctly classified specific category (walking_long_distance) is "
    "accepted on the first answer, no retry",
    "accessibility" in (tu6.get("guided") or {}).get("answered", []),
)
check(
    "regression: the real practical phrase is saved, not the generic 'other' label",
    (tu6.get("accessibility") or {}).get("details") == chat._ACCESSIBILITY_DETAIL_PHRASES_HE["walking_long_distance"],
)


print()
if FAILED:
    print(f"{len(FAILED)} CHECK(S) FAILED:")
    for name in FAILED:
        print(" -", name)
    sys.exit(1)
else:
    print("ALL DRYRUN4-ACCESSIBILITY-OTHER-CATEGORY-RETRY TESTS PASSED")
