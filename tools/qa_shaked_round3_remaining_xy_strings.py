"""QA for Shaked's third-round review of PR #54 (a776880): an AST-based
scan of every short string literal containing "?" together with " או "/
" או ש"/"כן או לא" turned up several fixed texts this PR had missed.

Fixed (all now a single open question or a single-option yes/no, with the
escape-hatch/explanatory text that doesn't itself ask a second question
kept as a separate statement, never appended to the question mark):
- _reopen_first_question_text (lodging/car/trip_planning; a function since
  20.10.2026's gender-address fix needs it to pick a form, not a static
  dict) - each used to ask 2-3 things at once with "X, Y או Z" framing; now
  asks only the first thing actually needed, same as _GAP_QUESTION_TEXT's
  own phrasing.
- _pick_reopen_option's single-trip question used to spell out
  "(כן = לחופשה הזו, לא = חופשה חדשה)" - _pick_reopen_option itself
  already resolves a bare כן/לא deterministically regardless of wording,
  so the parenthetical was pure unneeded "(yes=X, no=Y)" framing.
- The 2-trip variant's "...או שזו חופשה חדשה?" second question is now a
  separate non-question statement.
- destination_change_pending's confirmation text had a redundant literal
  "כן או לא?" suffix on an already-single yes/no question.
- _GAP_QUESTION_TEXT["trip_planning.approved"] still had an "או שתרצו
  לשנות משהו?" escape clause appended to the yes/no question.
- The generic post-flight continuation offer ("עוד דבר אחד לפני
  שסוגרים...") had an "או שזה הכל להפעם?" second question appended.

Run: python3 tools/qa_shaked_round3_remaining_xy_strings.py
"""
import ast
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import ariella_chat_clean as chat

FAILED = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


check("_reopen_first_question_text(lodging) is a single open question",
      chat._reopen_first_question_text("lodging", None) == "איזה סוג לינה מתאים לכם?")
check("_reopen_first_question_text(car) is a single open question",
      chat._reopen_first_question_text("car", None) == "איזה סוג רכב מתאים לכם?")
check("_reopen_first_question_text(trip_planning) is a single open question",
      chat._reopen_first_question_text("trip_planning", None) == "ספרי לי מה אתם אוהבים לעשות בחופשה.")
check("_GAP_QUESTION_TEXT[trip_planning.approved] has no escape-clause second question",
      chat._GAP_QUESTION_TEXT["trip_planning.approved"] == "המסלול שהצעתי מתאים לכם?")

# --- AST-based sweep: no short string should contain "?" together with
#     " או "/" או ש"/"כן או לא" (Shaked's own method), save for two
#     explicitly accepted exceptions: the TINKERBELL_SYSTEM prompt's own
#     instruction giving the banned shape as an example to avoid, and the
#     3+-concurrent-vacations case's second sentence, which is a statement
#     (no "?" of its own) explaining how to answer, not a second question.
with open(chat.__file__, encoding="utf-8") as f:
    source = f.read()
tree = ast.parse(source)


def offending(s):
    if not isinstance(s, str) or len(s) >= 300 or "?" not in s:
        return False
    return " או " in s or " או ש" in s or "כן או לא" in s


hits = []
for node in ast.walk(tree):
    if isinstance(node, ast.Constant) and isinstance(node.value, str) and offending(node.value):
        hits.append((node.lineno, node.value))
    elif isinstance(node, ast.JoinedStr):
        parts = [str(v.value) if isinstance(v, ast.Constant) else "{...}" for v in node.values]
        joined = "".join(parts)
        if offending(joined):
            hits.append((node.lineno, joined))

ALLOWED_SUBSTRINGS = (
    'לא "X, Y או Z?"',  # TINKERBELL_SYSTEM's own instruction, not a live question
    "אפשר לציין יעד או תאריך, או להגיד שזו חופשה חדשה",  # a statement, not a question - Shaked's own "borderline, your call"
)
unexpected = [(ln, s) for ln, s in hits if not any(a in s for a in ALLOWED_SUBSTRINGS)]
check(f"no unexpected 'X or Y?' strings remain (found: {[ln for ln, _ in unexpected]})",
      not unexpected)

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL SHAKED-ROUND3-REMAINING-XY-STRINGS TESTS PASSED")
