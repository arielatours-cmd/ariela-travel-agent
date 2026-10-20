"""QA for Shlomo's relay (20.10.2026, live finding on main@30e07e1, prior to
PR #91): r90a5, Seville/Granada - a same-message destination self-correction
("לא סביליה, גרנדה" / "בעצם לא סביליה, אני רוצה גרנדה") was not recognized
on the FIRST message at all; Ariella kept treating Seville as the
destination. Root cause: _deterministic_destination_facts scanned
_known_destination_names() in its pre-sorted tier order and returned on the
FIRST needle match found anywhere in the text - so whichever of the two
known places happened to sort first in the catalog dict won, never
necessarily the one the customer said LAST (the actual correction).

Fixed: _deterministic_destination_facts now does two separate, sequential
decisions instead of one position-only rule (collapsing them into one
regressed the pre-existing tier rule itself - caught via the full QA sweep,
see the three regression checks below):
1. Tier first - a specific place (city/resort/island-region) always beats a
   bare country name, exactly as _known_destination_names() has always
   documented.
2. Within the winning tier, the LATEST-position candidate wins (the later
   mention is the correction) - a NEW rule, only ever applied among
   same-tier candidates.
Substring-containment is resolved before either rule: a shorter known name
that is a literal substring of a longer match found in the same text
(סין/China inside קפריסין/Cyprus, מיורקה/Mallorca inside פלמה דה מיורקה/
Palma de Mallorca) is dropped first, or it would win the position tie-break
by sheer coincidence.

Run: python3 tools/qa_seville_granada_self_correction.py
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


def _places(history, message):
    facts = chat._deterministic_destination_facts(history, message, {})
    return (facts.get("destination") or {}).get("places") or []


# =====================================================================
# r90a5: same-message self-correction, first message, no prior history.
# =====================================================================
check("r90a5: 'לא סביליה, גרנדה' on the first message recognizes Granada (the later mention), not Seville",
      _places([], "חופשה לא לסביליה, אני רוצה לגרנדה") == ["גרנדה"])

check("r90a5 (Shaked's exact wording): 'בעצם לא סביליה, אני רוצה גרנדה' recognizes Granada",
      _places([], "בעצם לא סביליה, אני רוצה גרנדה") == ["גרנדה"])

check("regression: a plain single-destination message (no correction) still resolves normally",
      _places([], "חופשה לגרנדה בספרד") == ["גרנדה"])

check("regression: the SAME pair in the other order ('גרנדה... בעצם סביליה') now correctly flips to Seville",
      _places([], "גרנדה... לא, בעצם סביליה") == ["סביליה"])

# =====================================================================
# Regression #1: tier priority (specific place beats bare country name),
# the pre-existing rule this fix must not break even though a bare country
# name can appear LATER in the sentence than the specific place.
# =====================================================================
check("regression (qa-s91 round2 C2 precedent): a specific resort beats a bare country name "
      "mentioned later in the same sentence",
      _places([], "חופשת סקי בזאלבאך שבאוסטריה") not in ([], ["אוסטריה"]))

# =====================================================================
# Regression #2: substring containment (Cyprus/China, Mallorca/Palma de
# Mallorca) must not let the shorter needle win the position tie-break.
# =====================================================================
check("regression: 'קפריסין' (Cyprus) is recognized whole, never collapsed to the contained "
      "substring 'סין' (China)",
      _places([], "חופשה לקפריסין") == ["קפריסין"])

check("regression: 'פלמה דה מיורקה' is recognized whole, never collapsed to the contained "
      "substring 'מיורקה'",
      _places([], "טיסה לפלמה דה מיורקה") == ["פלמה דה מיורקה"])

# =====================================================================
# Regression #3: history-only scan still works (no message-level correction,
# destination named in an earlier customer turn).
# =====================================================================
_history = [
    {"role": "user", "content": "אני רוצה לטוס לגרנדה בספטמבר"},
    {"role": "assistant", "content": "קלטתי - גרנדה. כמה נוסעים?"},
]
check("regression: a destination named in an earlier customer turn (not the current message) "
      "is still recovered from history",
      _places(_history, "שנינו מבוגרים") == ["גרנדה"])

# Already-resolved destination in state is never reopened by this safety net.
_facts_with_state = chat._deterministic_destination_facts(
    [], "בעצם לא סביליה, אני רוצה גרנדה", {"destination": {"places": ["רומא"]}}
)
check("regression: once destination.places is already set in state, this safety net never runs at all",
      _facts_with_state == {})

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL SEVILLE-GRANADA-SELF-CORRECTION TESTS PASSED")
