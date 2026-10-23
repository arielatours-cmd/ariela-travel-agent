"""QA for dry-run 5e finding C (Shaked/Shlomo, 23.10.2026, qa/reports/
2026-10-23-dryrun5e.md, Hallstatt/Salzburg, SHA 76936af):

28b250a (dryrun5d item 4) correctly advanced guided.current_question from
"dates" to "accessibility" the SAME turn dates resolved via the
deterministic candidate-choice path - that part worked exactly as
intended. But Tinkerbell's actual reply still asked "מתי בדיוק תרצו
לצאת" (a prompt-compliance gap, the same class as scenario B's baggage-
skip) - never accessibility at all. The next turn, the customer's plain
"כן" (genuinely answering the dates re-ask she actually saw) got
extracted as a real accessibility answer (needed=true, needs=["other"]):
current_question said accessibility, so the extraction call ran against
that name with no concept of what Tinkerbell actually asked.

Shlomo's explicit fix: before trusting a genuine "answered" extraction
for accessibility, verify - via the SAME classifier _guard_accessibility_
question_skipped already uses - that Tinkerbell's own immediately-
preceding reply actually asked about accessibility. If it demonstrably
asked about something else instead, downgrade to "unclear" (the existing
branch) rather than saving a misattributed answer.

Offline (the guided extraction model call and the classifier are both
stubbed). Run:
python3 tools/qa_dryrun5e_c_accessibility_misattribution.py
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


STEPS = {"dates", "travelers", "accessibility", "baggage"}
MISATTRIBUTED_ANSWER = {"status": "answered", "confidence": "high", "needed": True,
                         "needs": ["other"], "detail_category": "other", "also_mentioned": {}, "correction": None}
GENUINE_ACCESSIBILITY_NO = {"status": "answered", "confidence": "high", "needed": False,
                             "needs": [], "detail_category": None, "also_mentioned": {}, "correction": None}

STALE_DATES_REPLY = "מתי בדיוק תרצו לצאת ולחזור?"
GENUINE_ACCESSIBILITY_ASK = "יש מישהו מהנוסעים שצריך התאמות נגישות כלשהן בחופשה הזו?"


def c_state():
    return {
        "requested_services": ["flights"],
        "travelers": {"adults": 2},
        "dates": {"departure": "2026-11-21", "return": "2026-11-25", "needs_confirmation": False, "candidate_ranges": []},
        "accessibility": {},
        "flight": {"baggage": ["carry_on_only"], "connection_preference": "אין העדפה"},
        "guided": {"current_question": "accessibility", "attempts": 0, "answered": ["dates", "travelers", "baggage"]},
    }


def run(state, message, extract_result, last_assistant_reply, classifier_says_asked):
    history = [
        {"role": "user", "content": "אפשר לצאת ב-21.11 ולחזור ב-25.11?"},
        {"role": "assistant", "content": last_assistant_reply},
    ]

    def fake_extract(key, model, field, msg, history_, s, guided_steps=None):
        return extract_result

    def fake_classifier(key, model, system_static, system_dynamic, history_, message_, max_tokens, include_history=True, source="other"):
        if source == "classifier":
            return json.dumps({"asked": classifier_says_asked})
        return "{}"

    with patch.object(chat, "_guided_extract_answer", side_effect=fake_extract), \
            patch.object(chat, "_post_claude", side_effect=fake_classifier), \
            patch.object(chat, "record_diagnostic_event"):
        return chat._handle_guided_extraction_turn("k", "m", message, history, state, dict(state), STEPS)


# =====================================================================
# Part 1 (the exact C repro): current_question="accessibility", the
# extraction call wrongly classifies "כן" as answering accessibility,
# but Tinkerbell's actual last reply asked about dates. FIX: downgraded
# to "unclear" - nothing saved, attempts bumped, accessibility re-asked.
# =====================================================================
r1 = run(c_state(), "כן", MISATTRIBUTED_ANSWER, STALE_DATES_REPLY, classifier_says_asked=False)
check("C repro FIX: misattributed 'כן' is NOT saved as an accessibility answer "
      "(needed/needs never written)",
      "needed" not in (r1["trip_update"].get("accessibility") or {}))
check("C repro FIX: guided.current_question stays on accessibility (re-ask, not advanced)",
      r1["trip_update"]["guided"].get("current_question") == "accessibility")
check("C repro FIX: attempts bumped (treated exactly like a genuinely unclear answer)",
      r1["trip_update"]["guided"].get("attempts") == 1)
check("C repro FIX: the dynamic_hint re-asks accessibility, not dates",
      "נגישות" in (r1.get("dynamic_hint") or "") or "התאמ" in (r1.get("dynamic_hint") or ""))


# =====================================================================
# Part 2: regression guard - when Tinkerbell's last reply DID genuinely
# ask about accessibility, a real "answered" extraction is trusted and
# saved exactly as before (the fix must never second-guess a correct
# extraction).
# =====================================================================
r2 = run(c_state(), "לא", GENUINE_ACCESSIBILITY_NO, GENUINE_ACCESSIBILITY_ASK, classifier_says_asked=True)
check("regression: a genuine accessibility answer (Tinkerbell really asked it) is saved normally",
      r2["trip_update"].get("accessibility", {}).get("needed") is False)
check("regression: 'accessibility' is recorded in guided.answered once genuinely settled",
      "accessibility" in r2["trip_update"]["guided"].get("answered", []))


# =====================================================================
# Part 3: regression guard - the fix only intervenes on status=="answered".
# An honestly "unclear" extraction result is untouched (no classifier
# call needed - it already hits the exact same recovery path).
# =====================================================================
UNCLEAR_RESULT = {"status": "unclear", "confidence": "low", "also_mentioned": {}, "correction": None}
with patch.object(chat, "_post_claude") as mock_classifier_unused:
    r3 = run(c_state(), "אולי", UNCLEAR_RESULT, STALE_DATES_REPLY, classifier_says_asked=False)
check("regression: an honestly 'unclear' extraction never calls the classifier at all",
      not mock_classifier_unused.called)
check("regression: 'unclear' still bumps attempts and re-asks, exactly as before this fix",
      r3["trip_update"]["guided"].get("attempts") == 1
      and r3["trip_update"]["guided"].get("current_question") == "accessibility")


# =====================================================================
# Part 4: regression guard - no assistant turn in history at all (e.g.
# very first guided turn) never crashes, and a genuine "answered" result
# is trusted (nothing to contradict it with).
# =====================================================================
r4 = run(c_state(), "לא", GENUINE_ACCESSIBILITY_NO, "", classifier_says_asked=True)
with patch.object(chat, "_guided_extract_answer", return_value=GENUINE_ACCESSIBILITY_NO), \
        patch.object(chat, "_post_claude") as mock_classifier_unused2, \
        patch.object(chat, "record_diagnostic_event"):
    r4b = chat._handle_guided_extraction_turn("k", "m", "לא", [], c_state(), dict(c_state()), STEPS)
check("regression: empty history (no prior assistant turn) never crashes, extraction still trusted",
      r4b["trip_update"].get("accessibility", {}).get("needed") is False
      and not mock_classifier_unused2.called)


if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL DRYRUN5E-C-ACCESSIBILITY-MISATTRIBUTION TESTS PASSED")
