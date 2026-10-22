"""QA for run-10's central finding (Shaked/Shlomo, 22.10.2026, qa/reports/
2026-10-22-stage1-live-run10.md, branch shaked 0ccca50) - 0/5 live
conversations passed:

guided.current_question named which field was being extracted (e.g.
"accessibility"), but Tinkerbell's own last message sometimes asked about a
completely different open gap instead (e.g. direct-flight preference,
competing for the single question-per-message slot). _guided_extract_answer
had no explicit grounding telling it what Ariella's last message ACTUALLY
asked - its own prompt instead ASSERTED "Ariella asked the yes/no
accessibility question" as a given fact, so the model anchored on that
framing rather than checking it against the real conversation. A bare
"לא חובה" (really answering "is a direct flight important to you?") got
force-fit as needed=False for accessibility in three of the five run-10
conversations (Genoa, Karlovy Vary, Torun) - the accessibility question was
never actually asked at all, yet a value was saved as if it had been.

Fix (per the business owner's exact wording, relayed by Shlomo: "guided must
not interpret an answer as answering a field unless the question actually
asked matched it - determine this by comparing to the gap actually asked,
or a marker of what Ariella actually asked. No word list."):

_last_question_clause (already established, PR #116, deterministic sentence-
boundary text extraction - not a word list, not a model call) now extracts
the real last assistant question for EVERY guided field (dates, travelers,
baggage, all 5 lodging sub-fields, both accessibility sub-questions), and
each field's prompt is grounded with it explicitly, instructing the MODEL
to compare it against the field being extracted and return status=
"other_topic" when the customer's reply actually answers that OTHER real
question - exactly the dual-call-mismatch pattern already established for
the connection-preference gap (_connection_preference_pending_hint, PR
#116), generalized to every guided field.

Separately (Zaragoza, same run-10 report): merely stating a baby's age while
answering "travelers" ("התינוקת שלנו בת שנה") got misread as a volunteered
accessibility NEED (needed=True, needs=[infant]) with no actual need
described at all - infants.count already captures the baby as a traveler on
its own. Tightened the also_mentioned.accessibility volunteer-capture
instruction (dates/travelers fields) to require a genuinely described need,
never fired by the baby's mere presence/age alone.

Run: python3 tools/qa_run10_guided_question_mismatch.py
"""
import os
import sys
import json
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


MISMATCHED_HISTORY = [
    {"role": "user", "content": "אנחנו שתי משפחות, 4 מבוגרים ו-2 ילדים."},
    {"role": "assistant", "content": "קלטתי, 4 מבוגרים ו-2 ילדים. חשוב לכם שתהיה טיסה ישירה?"},
]
MATCHED_ACCESSIBILITY_HISTORY = [
    {"role": "user", "content": "אנחנו שתי משפחות, 4 מבוגרים ו-2 ילדים."},
    {"role": "assistant", "content": "קלטתי. האם מישהו מהנוסעים צריך התאמה (נגישות) לאורך הטיול?"},
]


def _capture_prompt(expected_source):
    captured = {}

    def _fake(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
        if source == expected_source:
            captured["prompt"] = system_static
        return json.dumps({"status": "unclear"})
    return _fake, captured


# =====================================================================
# 1. Grounding present: every field's prompt quotes Ariella's REAL last
#    question verbatim, not just the field's own canonical description.
# =====================================================================
state = {"flight": {"baggage": []}, "travelers": {"adults": 4, "children": 2}, "dates": {}}

for field in ("dates", "travelers", "baggage"):
    fake, captured = _capture_prompt("guided_extract")
    with patch.object(chat, "_post_claude", side_effect=fake):
        chat._guided_extract_answer("k", "m", field, "לא חובה", MISMATCHED_HISTORY, state)
    check(f"field={field}: prompt quotes the real last question (direct-flight), word for word",
          "חשוב לכם שתהיה טיסה ישירה?" in captured.get("prompt", ""))
    check(f"field={field}: prompt instructs other_topic when the reply answers that other real question",
          "status=\"other_topic\"" in captured.get("prompt", "") and 'חשוב' in captured.get("prompt", ""))

for field in ("lodging_type", "lodging_rooms", "lodging_bathrooms", "lodging_locations", "lodging_budget_or_level"):
    fake, captured = _capture_prompt("guided_extract")
    with patch.object(chat, "_post_claude", side_effect=fake):
        chat._guided_extract_answer("k", "m", field, "לא חובה", MISMATCHED_HISTORY, {"lodging": {}})
    check(f"lodging field={field}: prompt also quotes the real last question",
          "חשוב לכם שתהיה טיסה ישירה?" in captured.get("prompt", ""))

# Accessibility, both sub-questions (yes/no gate, and the open follow-up
# once "awaiting_detail" is live).
fake, captured = _capture_prompt("guided_extract")
with patch.object(chat, "_post_claude", side_effect=fake):
    chat._guided_extract_answer("k", "m", "accessibility", "לא חובה", MISMATCHED_HISTORY, {})
check("accessibility (yes/no gate): prompt quotes the real last question",
      "חשוב לכם שתהיה טיסה ישירה?" in captured.get("prompt", ""))

fake, captured = _capture_prompt("guided_extract")
with patch.object(chat, "_post_claude", side_effect=fake):
    chat._guided_extract_answer("k", "m", "accessibility", "לא חובה",
                                 MISMATCHED_HISTORY, {"accessibility": {"needed": True}})
check("accessibility (open follow-up, awaiting_detail): prompt quotes the real last question too",
      "חשוב לכם שתהיה טיסה ישירה?" in captured.get("prompt", ""))

# =====================================================================
# 2. When the real last question genuinely DOES match the field, the same
#    grounding text is present but harmless (still describes the correct
#    question - never a false "other_topic" push for a matching case).
# =====================================================================
fake, captured = _capture_prompt("guided_extract")
with patch.object(chat, "_post_claude", side_effect=fake):
    chat._guided_extract_answer("k", "m", "accessibility", "לא", MATCHED_ACCESSIBILITY_HISTORY, {})
check("accessibility, matching case: the real last question IS the accessibility question itself",
      "האם מישהו מהנוסעים צריך התאמה" in captured.get("prompt", ""))

# =====================================================================
# 3. No prior assistant message at all (very first turn) -> no grounding
#    note, no crash, prompt still well-formed.
# =====================================================================
fake, captured = _capture_prompt("guided_extract")
with patch.object(chat, "_post_claude", side_effect=fake):
    result = chat._guided_extract_answer("k", "m", "dates", "בסוף אוגוסט", [], state)
check("no history at all: never crashes, still returns a parsed result",
      result is not None and result.get("status") == "unclear")

# =====================================================================
# 4. Zaragoza fix: also_mentioned.accessibility volunteer-capture now
#    requires a genuinely described need, never fired by a baby's mere
#    presence/age alone (infants.count already covers that fact on its own).
# =====================================================================
state_asking_accessibility = {"flight": {"baggage": []}, "travelers": {}, "dates": {},
                               "guided": {}}
fake, captured = _capture_prompt("guided_extract")
with patch.object(chat, "_post_claude", side_effect=fake), \
     patch.object(chat, "_guided_field_known_with_confidence", return_value=False):
    chat._guided_extract_answer("k", "m", "travelers", "התינוקת שלנו בת שנה",
                                 [], state_asking_accessibility, guided_steps={"accessibility"})
check("travelers prompt (accessibility volunteer rule active): explicitly excludes mere age/presence alone",
      "עצם קיומו של תינוק" in captured.get("prompt", "")
      and "בלי שום תיאור של צורך בעזרה" in captured.get("prompt", ""))

fake, captured = _capture_prompt("guided_extract")
with patch.object(chat, "_post_claude", side_effect=fake), \
     patch.object(chat, "_guided_field_known_with_confidence", return_value=False):
    chat._guided_extract_answer("k", "m", "dates", "בסוף אוגוסט", [], state_asking_accessibility, guided_steps={"accessibility"})
check("dates prompt (accessibility volunteer rule active): same tightened wording",
      "עצם קיומו של תינוק" in captured.get("prompt", ""))

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL RUN-10 GUIDED-QUESTION-MISMATCH TESTS PASSED")
