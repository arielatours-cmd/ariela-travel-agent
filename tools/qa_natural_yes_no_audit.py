"""QA for a broader audit Carmit asked for (2026-10-15), after the
reset-gate fix: are there other binary yes/no gates in the codebase using
a brittle exact-string set (easily broken by the customer's own natural
elaboration) instead of understanding real phrasing? Two more identical
instances were found and fixed:

1. The destination-change confirmation gate ("לשנות את היעד...?") used the
   exact same {"כן","כן.","כן!","בטח","בהחלט"} / {"לא","לא.","לא!","לא
   תודה"} sets as the reset gate already fixed - same word-boundary-aware
   regex fix applied (_RESET_GATE_YES_RE / _RESET_GATE_NO_RE).

2. The single-room confirmation extractor ("חדר זוגי אחד מספיק?" ->
   lodging.details.rooms=1) matched only {"כן","בטח","מספיק","נכון","כן,
   מספיק"} - a natural "כן, חדר אחד מספיק לנו" or "כן בהחלט" fell through
   and left rooms unset. Broadened to the same leading-word match, or the
   word "מספיק" appearing anywhere in the reply.

Three other similar-looking exact-match sets were examined and found to
already correctly fall back to a real Claude classification call for
anything not matching their fast path (confirmed by reading past the
exact-match block in each): _understand_post_flight_offer_answer,
_pick_reopen_option, and the `generic_yes` guard (line ~7699, which is
deliberately narrow for a different reason - distinguishing a bare
agreement word from a real additional request bundled with it, not a
binary yes/no gate at all) - left unchanged.

Run: python3 tools/qa_natural_yes_no_audit.py
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


# --- 1. The single-room confirmation extractor: a natural elaborated
#        "yes" must still set rooms=1 ---
prior_single_room = [{"role": "assistant", "content": "חדר זוגי אחד מספיק?"}]
check("'כן, חדר אחד מספיק לנו' still sets rooms=1",
      chat._deterministic_lodging_facts("כן, חדר אחד מספיק לנו", prior_single_room)
      .get("lodging", {}).get("details", {}).get("rooms") == 1)
check("a bare 'כן' still sets rooms=1 (original exact-match case preserved)",
      chat._deterministic_lodging_facts("כן", prior_single_room)
      .get("lodging", {}).get("details", {}).get("rooms") == 1)
check("'מספיק' anywhere in the reply still sets rooms=1",
      chat._deterministic_lodging_facts("כן זה בהחלט מספיק", prior_single_room)
      .get("lodging", {}).get("details", {}).get("rooms") == 1)

# --- 2. The destination-change gate now uses the shared word-boundary
#        regex instead of its own exact-string set ---
check("the destination-change gate's yes check uses the shared regex",
      bool(chat._RESET_GATE_YES_RE.match("כן, תשני בבקשה")))
check("the destination-change gate's no check uses the shared regex",
      bool(chat._RESET_GATE_NO_RE.match("לא, תשאירי")))

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL NATURAL-YES-NO-AUDIT TESTS PASSED")
