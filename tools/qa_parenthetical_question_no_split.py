"""QA for Shaked's live finding (20.10, stage-1/2 regression,
qa/reports/2026-10-20-stage1-2-regression.md, P7's companion finding - the
cut lodging message quoted by the business owner: "שקט יותר?), וגם אם יש
לכם תקציב מסוים בראש ללינה. באיזה אזור תרצו שהלינה תהיה?").

Root cause, confirmed directly: a lodging question illustrated with a
parenthetical example containing its own embedded "?" ("...מיקום הלינה
(קרוב למרכז? או שקט יותר?), וגם אם יש לכם תקציב...") got a sentence
boundary wrongly placed at the FIRST "?" inside the still-open
parenthetical in _split_sentences, purely because it happened to be
followed by whitespace. That split the one real sentence in two and left
a dangling, unmatched ")" stranded at the start of the second half.
_enforce_one_option_question then legitimately saw what looked like two
separate top-level question sentences (the embedded "?" and the reply's
real final "?") and dropped both of them, leaving exactly the cut-off
fragment the business owner saw live.

Fixed: _split_sentences now only treats "."/"!"/"?" as a real sentence
boundary once every "(" opened since the last real split has already been
closed by a ")" - a bare "\\n" is still always a boundary regardless,
exactly as before. Shaked's own proposed rule ("לא לפצל משפטים בתוך
סוגריים, ולא להשאיר שארית שמתחילה באמצע משפט") is exactly what this
tests.

Run: python3 tools/qa_parenthetical_question_no_split.py
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


# =====================================================================
# Direct unit test of _split_sentences on the reconstructed live repro.
# =====================================================================
_repro = (
    "רוצים לבדוק אם יש לכם העדפה למיקום הלינה (קרוב למרכז? או שקט יותר?), "
    "וגם אם יש לכם תקציב מסוים בראש ללינה. באיזה אזור תרצו שהלינה תהיה?"
)
_spans = chat._split_sentences(_repro)
check("item 4a: the embedded '?' inside the still-open parenthetical is NOT "
      "treated as a sentence boundary",
      len(_spans) == 2)
check("item 4a: the first real sentence (terminator '.') contains the WHOLE "
      "parenthetical intact, open paren through its own close",
      _spans[0][1] == "." and "(קרוב למרכז? או שקט יותר?)" in _spans[0][0])
check("item 4a: the second sentence is the genuine final question, never a "
      "dangling fragment starting with a stray ')'",
      _spans[1][1] == "?" and not _spans[1][0].lstrip().startswith(")"))

# =====================================================================
# End-to-end through _enforce_one_option_question: the reply must survive
# completely untouched - no sentence dropped, no dangling ")".
# =====================================================================
_state = {"active_session": None, "session_status": {
    "flights": "complete", "lodging": "active", "car": "pending", "trip_planning": "pending",
}}
_result = chat._enforce_one_option_question(_repro, _state)
check("item 4b end-to-end: the reply is returned completely unchanged - "
      "the parenthetical example and the real final question both survive",
      _result == _repro)
check("item 4b end-to-end: no dangling unmatched ')' anywhere in the output",
      _result.count("(") == _result.count(")"))

# =====================================================================
# Regressions: genuine multi-question violations (no parens involved) are
# still caught exactly as before - this fix must never mask a real bundle.
# =====================================================================
_genuine_bundle = "חשוב לכם שהטיסה תהיה ישירה? איזו כבודה תרצו לקחת?"
_bundle_spans = chat._split_sentences(_genuine_bundle)
check("regression: two genuinely separate question sentences (no parens at "
      "all) still split into two spans",
      len(_bundle_spans) == 2 and all(t == "?" for _, t in _bundle_spans))

_date_text = "הטיסה ב-15.4.2027 יוצאת בבוקר. מתי תרצו לחזור?"
_date_spans = chat._split_sentences(_date_text)
check("regression: a date like 15.4.2027 is still never split on its own "
      "internal periods",
      len(_date_spans) == 2 and "15.4.2027" in _date_spans[0][0])

_closed_paren_example = (
    "מה הסגנון שהכי מדבר אלייך בטיול הזה (תרבות ומוזיאונים, שופינג, אווירה לוקאלית)?"
)
check("regression: a parenthetical example list with NO internal '?' (the "
      "ordinary, already-allowed case) still produces exactly one question span",
      len(chat._split_sentences(_closed_paren_example)) == 1)

_unbalanced_but_no_question_inside = "המלון (רק 3 כוכבים) מתאים לכם? ומה לגבי התקציב?"
_unb_spans = chat._split_sentences(_unbalanced_but_no_question_inside)
check("regression: a closed parenthetical with no '?' inside it never "
      "affects splitting of the real questions around it",
      len(_unb_spans) == 2 and _unb_spans[0][0].rstrip().endswith("מתאים לכם?"))

# =====================================================================
# Shlomo's follow-up finding on this same fix (PR #90 review, 20.10): an
# "(" that is NEVER closed anywhere later in the text (e.g. a stray
# emoticon like ":(") used to suppress EVERY later "."/"!"/"?" boundary
# for the rest of the message, since the imbalance it created never
# resolved - the one-question-per-message rule then went unenforced for
# everything that followed. Fixed: at each candidate boundary, check
# whether a real ")" still exists somewhere LATER in the text to actually
# close the debt - only then is the boundary still suppressed. If no such
# close exists anywhere ahead, the "(" will never close, so it no longer
# blocks, immediately (not after an arbitrary distance - a stray unclosed
# "(" can sit right next to the very next real boundary).
# =====================================================================
_never_closed_paren = "בסדר גמור :( אז נדבר על זה מאוחר יותר. מתי תרצו לטוס?"
_never_closed_spans = chat._split_sentences(_never_closed_paren)
check("Shlomo's finding: a never-closed '(' (a stray emoticon) does NOT "
      "suppress the real sentence boundaries that follow it later in the "
      "message, even though the next boundary sits just a few words after "
      "it",
      len(_never_closed_spans) == 2
      and _never_closed_spans[0][1] == "."
      and _never_closed_spans[1][1] == "?")

_eventually_closed_far_away = (
    "מיקום הלינה (קרוב למרכז, רחוק מהים, חשוב לנו שיהיה נוח ונעים ולא יקר "
    "מדי?) איך זה נשמע לכם?"
)
_far_spans = chat._split_sentences(_eventually_closed_far_away)
check("regression: an embedded '?' inside an open '(' that DOES close "
      "later, even many words later, still never becomes its own boundary "
      "- only a genuinely never-closing '(' stops blocking",
      len(_far_spans) == 1 and _far_spans[0][1] == "?"
      and "איך זה נשמע" in _far_spans[0][0])

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL PARENTHETICAL-QUESTION-NO-SPLIT TESTS PASSED")
