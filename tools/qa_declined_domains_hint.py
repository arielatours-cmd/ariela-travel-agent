"""QA for a bug Carmit found live on the production site (2026-10-14):
after declining lodging, car AND trip_planning across several separate
chat turns, Ariella's "you can always come back and ask for help with
this too" acknowledgment (per the system prompt's own rule right after a
decline) only named lodging and car - trip_planning, declined earlier in
the same conversation, silently dropped out of the free-text recap.

Root cause: this acknowledgment is pure free text, built from the model's
own in-context memory of the conversation - reliable for the domain just
declined this turn, not for something declined several turns back. Added
_declined_domains_hint, the same deterministic-hint pattern already used
for the weekday table and total-nights count in this file: a precomputed,
authoritative list of every currently-declined domain from session_status,
injected into every Tinkerbell call.

Run: python3 tools/qa_declined_domains_hint.py
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


# --- 1. The exact live shape: all three optional domains declined across
#        separate turns -> all three named, in the fixed display order ---
state_all_declined = {"session_status": {"flights": "active", "lodging": "declined", "car": "declined", "trip_planning": "declined"}}
hint = chat._declined_domains_hint(state_all_declined)
check("all three declined domains are named", all(w in hint for w in ("לינה", "השכרת רכב", "מסלול ואטרקציות")))
check("the instruction to include the full list is present", "כל הרשימה הזו במדויק" in hint)

# --- 2. Only some domains declined -> only those are named, not the ones
#        still pending/active ---
state_partial = {"session_status": {"flights": "active", "lodging": "declined", "car": "declined", "trip_planning": "pending"}}
hint_partial = chat._declined_domains_hint(state_partial)
check("only genuinely declined domains are named",
      "לינה" in hint_partial and "השכרת רכב" in hint_partial and "מסלול" not in hint_partial)

# --- 3. Nothing declined yet -> empty string, no hint injected at all ---
check("no declined domains -> empty hint", chat._declined_domains_hint({"session_status": {"flights": "active"}}) == "")

# --- 4. A completed (not declined) domain is never listed as declined ---
state_completed = {"session_status": {"flights": "active", "lodging": "complete", "car": "declined", "trip_planning": "declined"}}
hint_completed = chat._declined_domains_hint(state_completed)
check("a completed domain is never listed alongside declined ones",
      "לינה" not in hint_completed and "השכרת רכב" in hint_completed and "מסלול ואטרקציות" in hint_completed)

# --- 5. Defensive: non-dict/missing state never crashes ---
check("non-dict state never crashes", chat._declined_domains_hint(None) == "")
check("missing session_status never crashes", chat._declined_domains_hint({}) == "")

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL DECLINED-DOMAINS-HINT TESTS PASSED")
