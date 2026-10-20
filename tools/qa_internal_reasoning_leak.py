"""QA for Shlomo's priority-2 finding (20.10, stage-1/2 regression,
qa/reports/2026-10-20-stage1-2-regression.md, s12x2, Amsterdam): the
model's own internal reasoning, in ENGLISH ("Wait, this is already known -
let me check. Actually the state shows baggage..."), leaked into the
customer-facing reply as its own leading paragraph, immediately followed
by the real Hebrew reply as a second paragraph.

_strip_leaked_internal_paragraph already stripped a similar leak (a stray
Hebrew technical/meta sentence like "פורמט תאריך לא ידוע") via a short
Hebrew meta-marker word list - that check never matches English text at
all. Extended with a script-ratio check instead of more keywords: a
leading paragraph that is substantially Latin-script, immediately followed
by a genuinely Hebrew second paragraph, is dropped regardless of which
specific English words appear - the same category of check _strip_mixed_
script_garble/_strip_mixed_hebrew_latin_token already use for narrower,
single-token glitches, just applied to a whole leading paragraph. A
minimum letter-count floor on both sides keeps a short, ordinary foreign
place/airport name sitting as its own opening line from ever being
mistaken for this.

Also reinforced TINKERBELL_SYSTEM with an explicit rule: never write out
the internal reasoning/thinking process in the reply itself, in any
language - the general principle this specific leak is one instance of.

Run: python3 tools/qa_internal_reasoning_leak.py
"""
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


check("TINKERBELL_SYSTEM has a new rule forbidding writing out internal "
      "reasoning/thinking in the reply, in any language",
      "לעולם אל תכתבי בתשובה עצמה את תהליך המחשבה הפנימי שלך" in chat.TINKERBELL_SYSTEM)

# =====================================================================
# The exact live repro shape (Amsterdam, s12x2).
# =====================================================================
_leak = (
    "Wait, this is already known - let me check. Actually the state shows "
    "baggage is already set to carry on only, so I should not ask about it again.\n\n"
    "מעולה, אז בואו נדבר על התקציב לטיסה - יש לכם תקרה מסוימת בראש?"
)
check("item 2: an English internal-reasoning leading paragraph is stripped, "
      "leaving only the real Hebrew reply",
      chat._strip_leaked_internal_paragraph(_leak)
      == "מעולה, אז בואו נדבר על התקציב לטיסה - יש לכם תקרה מסוימת בראש?")

_leak_different_wording = (
    "Hold on, let me reconsider this - the customer already told me the dates "
    "earlier in the conversation, so I don't need to ask again here.\n\n"
    "קלטתי - התאריכים כבר נקבעו. איזו כבודה תצטרכו?"
)
check("item 2: a differently-worded English leak (not matching any specific "
      "phrase) is still caught by the script-ratio check, not a phrase list",
      chat._strip_leaked_internal_paragraph(_leak_different_wording)
      == "קלטתי - התאריכים כבר נקבעו. איזו כבודה תצטרכו?")

# =====================================================================
# Regressions: every pre-existing behavior of this function is untouched.
# =====================================================================
check("regression: the original Hebrew meta-marker leak (unrelated to this "
      "fix) is still stripped",
      chat._strip_leaked_internal_paragraph(
          "פורמט תאריך לא ידוע. אנא נסה תבנית אחרת.\n\nמעולה, מתי תרצו לטוס?"
      ) == "מעולה, מתי תרצו לטוס?")
check("regression: a short English airport-code opening line survives "
      "(below the letter-count floor, legitimate house style)",
      chat._strip_leaked_internal_paragraph(
          "FCO\n\nמעולה, הטיסה שלכם נוחתת ברומא פיומיצ'ינו."
      ) == "FCO\n\nמעולה, הטיסה שלכם נוחתת ברומא פיומיצ'ינו.")
check("regression: an ordinary single-paragraph Hebrew reply (no blank-line "
      "break at all) is never touched",
      chat._strip_leaked_internal_paragraph("קלטתי - פלרמו. איזו כבודה תצטרכו?")
      == "קלטתי - פלרמו. איזו כבודה תצטרכו?")
check("regression: a genuine two-paragraph Hebrew reply (both sides Hebrew) "
      "is never touched",
      chat._strip_leaked_internal_paragraph(
          "קלטתי - פלרמו, 10-17 ביוני.\n\nאיזו כבודה תצטרכו?"
      ) == "קלטתי - פלרמו, 10-17 ביוני.\n\nאיזו כבודה תצטרכו?")
check("regression: a short English lead under the floor even without a "
      "Hebrew second half present (no false trigger on tiny fragments)",
      chat._strip_leaked_internal_paragraph("OK\n\nFCO") == "OK\n\nFCO")
check("regression: a reply with no paragraph break at all (single block) is "
      "returned completely unchanged even if it happens to contain English",
      chat._strip_leaked_internal_paragraph("Wait let me check the state carefully here first")
      == "Wait let me check the state carefully here first")

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL INTERNAL-REASONING-LEAK TESTS PASSED")
