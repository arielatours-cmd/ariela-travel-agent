"""QA for Shaked's live report (2026-10-13, qa-s79, Cyprus): the exact
twin of the lodging.details.budget bug, one field over. car.details.pickup
and car.details.return had no deterministic writer at all - only the LLM's
own JSON extraction ever set them. Three real phrasings tested live:

- "איסוף בפאפוס והחזרה בלרנקה" (both in one sentence)
- "לפי מה שיתברר בהזמנה" (answering a TIME question - never required, see
  _required_state_gaps's own comment - correctly names no location at all)
- "איסוף הרכב בשדה התעופה בפאפוס, החזרה בשדה התעופה בלרנקה" (more verbose)

All three left pickup/return null forever, keeping car "active" with real
missing_required gaps that could never close.

Run: python3 tools/qa_car_pickup_return_locations.py
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


def car_details(msg):
    r = chat._deterministic_car_location_facts(msg, [])
    return (r.get("car") or {}).get("details") or {}


# --- 1-3. The exact three reported phrasings ---
d1 = car_details("איסוף בפאפוס והחזרה בלרנקה")
check("combined pickup+return sentence captures both", d1 == {"pickup": "פאפוס", "return": "לרנקה"})

d2 = car_details("לפי מה שיתברר בהזמנה")
check("a time-question answer (no location at all) correctly captures nothing", d2 == {})

d3 = car_details("איסוף הרכב בשדה התעופה בפאפוס, החזרה בשדה התעופה בלרנקה")
check("verbose 'airport in X' phrasing still captures both cleanly", d3 == {"pickup": "פאפוס", "return": "לרנקה"})

# --- 4. Pickup-only and return-only answers (separate turns) ---
d4 = car_details("רק רוצה לאסוף בלרנקה")
check("pickup-only answer (infinitive 'לאסוף') captures pickup alone", d4 == {"pickup": "לרנקה"})

d5 = car_details("להחזיר בלרנקה")
check("return-only answer captures return alone, no false pickup", d5 == {"return": "לרנקה"})

# --- 5. Two-word Israeli city name (not just single-word Cyprus airports) ---
d6 = car_details("ברצוני לאסוף את הרכב בתל אביב ולהחזיר בחיפה")
check("two-word city name (תל אביב) captured in full, not truncated", d6 == {"pickup": "תל אביב", "return": "חיפה"})

# --- 6. No cue words at all -> nothing captured, no crash ---
d7 = car_details("אותו שדה תעופה בבקשה")
check("no איסוף/להחזיר cue present -> no false capture", d7 == {})

# --- 7. Empty message ---
d8 = car_details("")
check("empty message -> no crash, empty result", d8 == {})

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL CAR PICKUP/RETURN LOCATION TESTS PASSED")
