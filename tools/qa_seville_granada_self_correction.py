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

# =====================================================================
# Shaked's regression review of this fix in PR #94: the deterministic
# fallback above, correct as a pure function, was still wired in to run
# (and unconditionally override via _merge_trip_state) whenever the PRIOR
# stored state had no destination yet - regardless of what the extractor
# ITSELF returned this very turn. Her two real examples where the model's
# own understanding is the only thing that can get it right at all:
# - "לגרנדה, לא לסביליה" (word order the pure regex/negation heuristic
#   above still gets wrong - stuck on Seville).
# - "טסים לליסבון, ומשם ברכבת לפורטו" - a genuine two-city itinerary, not a
#   correction at all; "latest mention wins" silently drops Lisbon.
# Fixed: the fallback may only act when the extractor's OWN output for
# THIS turn has no destination at all - never to override one it already
# produced. These are full end-to-end tests of that gating (mocked model +
# the real _merge_trip_state/_deterministic_destination_facts call site),
# not just the pure function above.
# =====================================================================
import json
import sqlite3
from datetime import datetime, timezone
from unittest.mock import patch

import database
database.init_db()
import whatsapp_bridge
from werkzeug.security import generate_password_hash

DB = database.DB_PATH


def _make_member(email):
    with sqlite3.connect(DB) as conn:
        conn.execute("DELETE FROM members WHERE email=?", (email,))
        conn.commit()
        cur = conn.execute(
            "INSERT INTO members (full_name,email,password_hash,created_at,status,whatsapp_opt_in,preferred_airports) "
            "VALUES(?,?,?,?,?,?,?)",
            ("QA Seville Granada", email, generate_password_hash("Test1234!"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
        )
        return cur.lastrowid


def _model_destination_response(places):
    def _fake(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
        if source == "state_extractor":
            return json.dumps({
                "trip_update": {"destination": {"places": places, "mode": "specific", "status": "known"}},
                "restart_request": False, "restart_evidence": None,
                "dates_evidence": None, "destination_evidence": None, "trip_type_evidence": None,
            })
        if source == "guided_extract":
            return json.dumps({"status": "other_topic", "field": None, "evidence": None})
        if source == "tinkerbell_reply":
            return "קלטתי, תודה."
        return "{}"
    return _fake


def _first_message_destination(email, message, model_places):
    member = _make_member(email)
    with patch.object(chat, "_post_claude", side_effect=_model_destination_response(model_places)):
        whatsapp_bridge.ariella_turn(member, message)
    state = (database.load_ariella_conversation(member) or {}).get("trip_state") or {}
    return (state.get("destination") or {}).get("places") or []

check("Shaked's regression #1: the model's OWN correct extraction "
      "('גרנדה') for 'לגרנדה, לא לסביליה' is never overridden by the "
      "regex fallback's own (possibly wrong) negation handling",
      _first_message_destination(
          "qa-seville-granada-model-wins@example.com",
          "לגרנדה, לא לסביליה", ["גרנדה"],
      ) == ["גרנדה"])

check("Shaked's regression #2: a genuine two-city itinerary the model "
      "correctly keeps as both cities ('טסים לליסבון, ומשם ברכבת לפורטו') "
      "is never collapsed to one by the 'latest mention wins' fallback, "
      "because the fallback never even runs when the model has an answer",
      _first_message_destination(
          "qa-lisbon-porto-model-wins@example.com",
          "טסים לליסבון, ומשם ברכבת לפורטו", ["ליסבון", "פורטו"],
      ) == ["ליסבון", "פורטו"])

# Regression: the fallback must still act as a genuine safety net when the
# model's own output for this turn has NOTHING for destination at all -
# this is the ORIGINAL purpose of this function and must not be lost.
def _model_no_destination_response(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True, source="other"):
    if source == "state_extractor":
        return json.dumps({
            "trip_update": {}, "restart_request": False, "restart_evidence": None,
            "dates_evidence": None, "destination_evidence": None, "trip_type_evidence": None,
        })
    if source == "guided_extract":
        return json.dumps({"status": "other_topic", "field": None, "evidence": None})
    if source == "tinkerbell_reply":
        return "קלטתי, תודה."
    return "{}"

_gap_member = _make_member("qa-seville-granada-gap-fill@example.com")
with patch.object(chat, "_post_claude", side_effect=_model_no_destination_response):
    whatsapp_bridge.ariella_turn(_gap_member, "בעצם לא סביליה, אני רוצה גרנדה")
_gap_state = (database.load_ariella_conversation(_gap_member) or {}).get("trip_state") or {}
check("regression: when the model's own extraction misses the destination "
      "entirely this turn, the deterministic fallback still fills the gap "
      "exactly as it always did - this fix narrows WHEN it runs, it does "
      "not remove it",
      (_gap_state.get("destination") or {}).get("places") == ["גרנדה"])

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL SEVILLE-GRANADA-SELF-CORRECTION TESTS PASSED")
