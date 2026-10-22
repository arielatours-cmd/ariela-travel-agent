"""QA for run-10 findings (a) and (b) (Shaked/Shlomo, 22.10.2026, qa/reports/
2026-10-22-stage1-live-run10.md) - part of the central guided-dispatch bug,
continuing PR #137's fix of the EXTRACTION side:

guided.current_question named a field (e.g. accessibility) and set its own
hint in trip_update["_guided_ask_hint"], correctly fed into Tinkerbell's
prompt - but system_dynamic/continuity ALSO unconditionally carries every
other open gap's own hint in the SAME prompt (direct-flight preference,
gender, dates truth, etc., all concatenated regardless of whether a guided
field is live). With nothing telling Tinkerbell which one to actually ask
about, she asked the WRONG one in three of five run-10 conversations
(Genoa, Karlovy Vary, Torun) - the accessibility question was never
actually asked at all. In Karlovy Vary this also produced a dangling
fragment ("this is completely optional... was this started but abandoned
mid-composition for the direct-flight question instead") - part (b), the
same root cause rather than a separate raw-text leak.

Fix: an explicit priority instruction, placed directly beside the guided
hint's own text (never by suppressing the other hints, which still carry
genuinely-needed factual grounding even on a turn where their topic isn't
being asked about) - states plainly that the guided question is the one
and only thing to ask about this turn, overriding every other open topic
mentioned elsewhere in the same prompt.

Run: python3 tools/qa_run10_hint_priority.py
"""
import os
import sys
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


ROME_STATE_BASE = {
    "destination": {"places": ["רומא"], "mode": "specific", "status": "known"},
    "active_session": "flights",
    "requested_services": ["flights"],
    "session_status": {"flights": "active", "lodging": "declined", "car": "declined", "trip_planning": "declined"},
    "dates": {"departure": "2026-11-10", "return": "2026-11-15"},
    "travelers": {"adults": 2},
}

_captured_system_dynamic = []


def _capturing_post_claude(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if source == "tinkerbell_reply":
        _captured_system_dynamic.append(system_dynamic)
    return "תשובה לדוגמה."


_ACCESSIBILITY_HINT = chat._accessibility_ask_hint(False, 0)

# =====================================================================
# 1. A guided field (accessibility) is live (trip_update["_guided_ask_
#    hint"] already set by dispatch) AND a competing open-gap hint
#    (direct-flight preference, destination known, no connection_
#    preference set yet) both land in the same _call_tinkerbell prompt.
# =====================================================================
_captured_system_dynamic.clear()
state_with_guided_hint = dict(ROME_STATE_BASE, _guided_ask_hint=_ACCESSIBILITY_HINT)
with patch.object(chat, "_post_claude", side_effect=_capturing_post_claude):
    chat._call_tinkerbell("test-key", "claude-sonnet-5", [], "שלום", state=state_with_guided_hint)

check("the competing direct-flight hint is indeed present this turn (the "
      "scenario the fix targets is real, not already a no-op)",
      len(_captured_system_dynamic) >= 1 and "ישירה" in _captured_system_dynamic[0])
check("the priority instruction is present, stating the guided question is "
      "the only thing to ask this turn",
      len(_captured_system_dynamic) >= 1
      and "היא הדבר היחיד שצריך לברר מול הלקוח בהודעה הזו" in _captured_system_dynamic[0])
check("the priority instruction explicitly overrides other open topics "
      "(e.g. direct-flight preference, budget)",
      len(_captured_system_dynamic) >= 1
      and "גוברת על כל נושא פתוח אחר" in _captured_system_dynamic[0])
check("the actual guided hint text (accessibility yes/no) is still carried "
      "through, now inside the priority sentence",
      len(_captured_system_dynamic) >= 1 and _ACCESSIBILITY_HINT in _captured_system_dynamic[0])
# =====================================================================
# 2. No guided field live at all -> no priority sentence added (no
#    unnecessary noise on an ordinary turn), and the competing hint is
#    unaffected (nothing suppressed).
# =====================================================================
_captured_system_dynamic.clear()
with patch.object(chat, "_post_claude", side_effect=_capturing_post_claude):
    chat._call_tinkerbell("test-key", "claude-sonnet-5", [], "שלום", state=dict(ROME_STATE_BASE))
check("no guided field live: the priority sentence is absent",
      len(_captured_system_dynamic) >= 1
      and "היא הדבר היחיד שצריך לברר מול הלקוח בהודעה הזו" not in _captured_system_dynamic[0])
check("no guided field live: the direct-flight hint itself is unaffected "
      "(still present on its own, nothing suppressed)",
      len(_captured_system_dynamic) >= 1 and "ישירה" in _captured_system_dynamic[0])

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL RUN-10 HINT-PRIORITY TESTS PASSED")
