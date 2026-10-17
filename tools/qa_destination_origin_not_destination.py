"""QA for the new top-priority blocker Shaked found in round 5 (qa-s95,
2026-10-16, 1c4fc14): "טיסה מ-X ל-Y" (flight FROM X TO Y) set the vacation
destination to X - the ORIGIN - instead of Y. This made Haifa (#33, Air
Haifa routes) effectively unusable in chat: "טיסה מחיפה לרומא" captured
destination.places=['חיפה'] (Haifa itself) instead of ['רומא'], and the
exact same bug hit Tel Aviv too ("טיסה מתל אביב לרומא" -> 'תל אביב'). This
then cascaded: destination_airports=['HFA'], a false "no direct flight"
reply, departure_airport never actually switching to TLV even after the
customer agreed to check from Ben Gurion, and "מאשרת" (approve) replying
that a scan started when none ran. Confirmed pre-existing (also present in
db30b84, per Shaked) - not a regression from this week's PRs.

Root cause: `_deterministic_destination_facts` scanned the message for ANY
known place name appearing anywhere in the text, with zero awareness of
the Hebrew מ.../ל... (from/to) preposition structure - so an outbound
Israeli gateway city named as the ORIGIN (Haifa and Tel Aviv are both
valid destinations in their own right, e.g. for a domestic flight) got
treated as the requested vacation destination.

Fixed by adding `_is_origin_departure_mention`, which recognizes a known
place name directly glued to the Hebrew "from" prefix (מ/מ-) as the
departure city, never the destination, and skipping such occurrences
while still checking every other occurrence/needle for a genuine
destination mention - mirroring the existing `_is_negated_destination_mention`
lookbehind-window approach already used for "don't delete X"/"not X"
phrasing.

These are also the exact 4 cases Shaked added to qa/cases.json
(dest-tisa-me-haifa-le-roma-origin-not-destination,
dest-tisa-me-haifa-le-yavan, dest-tisa-mi-tel-aviv-le-roma,
dest-latus-me-haifa-le-rodos-still-ok) - this file re-asserts them
directly against the function plus a few extra edge cases.

Run: python3 tools/qa_destination_origin_not_destination.py
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


def places_of(history, message):
    result = chat._deterministic_destination_facts(history, message, {})
    return (result.get("destination") or {}).get("places")


# --- Shaked's exact live reproductions (qa-s95) ---
check("'טיסה מחיפה לרומא...' -> Rome, not Haifa (the origin)",
      places_of([], "טיסה מחיפה לרומא, 10 עד 14 בנובמבר, שני מבוגרים") == ["רומא"])
check("'טיסה מחיפה ליוון...' -> Greece, not Haifa",
      places_of([], "טיסה מחיפה ליוון, 5 עד 12 ביוני") == ["יוון"])
check("'טיסה מתל אביב לרומא' -> Rome, not Tel Aviv (same bug, different origin city)",
      places_of([], "טיסה מתל אביב לרומא") == ["רומא"])
check("control case Shaked flagged as already-working stays working: 'לטוס מחיפה לרודוס' -> Rhodes",
      places_of([], "אני רוצה לטוס מחיפה לרודוס") == ["רודוס"])

# --- Extra edge cases: a destination-only mention (no origin city stated
#     at all) must still resolve normally - the origin-prefix check must
#     never suppress a plain destination mention with no "מ" involved ---
check("plain destination mention with no origin city stated still works",
      places_of([], "אני רוצה לטוס לרומא") == ["רומא"])
check("a 'מ' elsewhere in the message unrelated to any place name is harmless",
      places_of([], "מתי אפשר לטוס לרומא?") == ["רומא"])

# --- Hyphenated מ- form ---
check("hyphenated 'מ-תל אביב' origin form is also recognized",
      places_of([], "טיסה מ-תל אביב לרומא") == ["רומא"])

# --- The hfa_routes.py side of the chain is confirmed independently sound
#     (Rhodes is "confirmed"/seasonal there) - Shaked's reported false "no
#     direct flight" for Rhodes was traced to the corrupted conversation
#     state from this same destination-extraction bug, not a separate bug
#     in hfa_routes.py itself. Guard that assumption here too. ---
import hfa_routes
check("hfa_routes.py itself already correctly reports Rhodes as served",
      hfa_routes.hfa_route_check(["רודוס"]) == "served")

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL DESTINATION-ORIGIN-NOT-DESTINATION TESTS PASSED")
