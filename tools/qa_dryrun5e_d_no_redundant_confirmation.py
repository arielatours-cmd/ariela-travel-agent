"""QA for dry-run 5e finding D (Shaked/Shlomo, 23.10.2026, qa/reports/
2026-10-23-dryrun5e.md) - a regression from 5d: Tinkerbell asked a
redundant yes/no confirmation on a fact the customer had JUST stated
explicitly and unambiguously in the same message:
  - "ובעצם אפשר לצאת ב-9.5 ולחזור ב-13.5?" -> got "מתאים לך?" instead of
    being accepted as-is (dates.departure/return were saved correctly -
    the bug is purely in the reply's phrasing).
  - "ונעדיף בעצם מזוודה לכל אחד" -> got "לוודא - בנוסף לטרולי, כל אחד
    ייקח גם מזוודה, נכון?" (flight.baggage was saved correctly as
    checked_bag - again, phrasing only).

TINKERBELL_SYSTEM already had a general rule against re-confirming
already-stated details ("אל תחזרי על פרטים שכבר נאמרו כדי לאשר אותם,
אלא אם יש אי-בהירות אמיתית") - this live regression shows it wasn't
followed when the customer's OWN current message is what supplied the
explicit fact. Fixed with a concrete, explicit extension of that same
rule, naming both live failure shapes (explicit dates, explicit baggage
change) so the model has little room to read the general rule narrowly.

This is a PROMPT-LEVEL mitigation, not a deterministic code fix - this
file only verifies the instruction text is present and reaches the
model's system prompt; only a live dry run can confirm improved
compliance (same standing caveat as every other prompt-only mitigation
in this codebase, e.g. the missing_required-override reinforcement).

Run: python3 tools/qa_dryrun5e_d_no_redundant_confirmation.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")
os.environ.setdefault("SCHEDULER_ENABLED", "false")

import ariella_chat_clean as chat  # noqa: E402

FAILED = []


def check(name, cond):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        FAILED.append(name)


check("the pre-existing standing rule against re-confirming already-stated details is still present",
      "אל תחזרי על פרטים שכבר נאמרו כדי לאשר אותם" in chat.TINKERBELL_SYSTEM)
check("the extension explicitly covers the case where THIS turn's own message supplied the "
      "explicit fact (not just an earlier turn)",
      "ההודעה הנוכחית של הלקוח עצמה היא שמסרה את הפרט" in chat.TINKERBELL_SYSTEM)
check("the explicit-dates live failure shape is named concretely",
      "9.5" in chat.TINKERBELL_SYSTEM and "13.5" in chat.TINKERBELL_SYSTEM)
check("the explicit-baggage-change live failure shape is named concretely",
      "מזוודה לכל אחד" in chat.TINKERBELL_SYSTEM)
check("the rule still carves out a real exception for genuine ambiguity - never an absolute ban "
      "on ever asking a clarifying question",
      "משתמע לשתי פרשנויות אפשריות" in chat.TINKERBELL_SYSTEM)


if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL DRYRUN5E-D-NO-REDUNDANT-CONFIRMATION TESTS PASSED (prompt-level mitigation - "
      "needs live dry-run confirmation, same as other prompt-only fixes in this file)")
