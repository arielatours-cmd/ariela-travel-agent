"""QA for a gap found while auditing the one-option-per-question principle
(2026-10-16): three deterministic answer-writers
(_deterministic_connection_preference_facts, _deterministic_car_vehicle_
facts' transmission, _deterministic_lodging_facts' level) were relaxed
earlier the same day so their GATE (which prior-assistant text counts as
"this exact question was just asked") no longer requires both of the old
two words together. But each writer's own MESSAGE-side matching still
required the customer to repeat a specific word ("ישיר"/"אוטומטי"/"ידני"/a
tier name) - and the whole point of the new single-option yes/no phrasing
("חשוב לכם טיסה ישירה?", "חשוב לכם רכב אוטומטי?", "חשוב לכם מלון יוקרתי?")
is that a real customer very plausibly just answers "כן"/"לא" and nothing
else. A bare "כן"/"לא" silently returned {} from all three writers -
exactly the one-word-answer-gets-lost failure mode these deterministic
writers exist to prevent in the first place (see their own docstrings).

Fixed: each writer now also resolves a bare yes/no word (checked only
after the specific-word checks, and only when prior_assistant named
exactly ONE option - never for an old-style "X או Y?" dual phrasing, which
stays genuinely ambiguous and is correctly left to the extractor). "כן"
means the one asked-about option; "לא" means no real preference - never an
assertion of the opposite option.

Run: python3 tools/qa_bare_yes_no_single_option_gates.py
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


def connpref(msg, prior):
    return chat._deterministic_connection_preference_facts(msg, [{"role": "assistant", "content": prior}])


def carvehicle(msg, prior):
    return chat._deterministic_car_vehicle_facts(msg, [{"role": "assistant", "content": prior}])


def lodging(msg, prior):
    return chat._deterministic_lodging_facts(msg, [{"role": "assistant", "content": prior}])


# --- connection preference ---
check("bare 'כן' to 'חשוב לכם טיסה ישירה?' -> direct",
      connpref("כן", "חשוב לכם טיסה ישירה?") == {"flight": {"connection_preference": "direct"}})
check("bare 'לא' -> no preference (NOT a request for a connection)",
      connpref("לא", "חשוב לכם טיסה ישירה?") == {"flight": {"connection_preference": "אין העדפה"}})
check("another bare affirmative ('בטח') also resolves to direct",
      connpref("בטח", "חשוב לכם טיסה ישירה?") == {"flight": {"connection_preference": "direct"}})
check("explicit 'ישירה' in the answer still works as before (regression)",
      connpref("כן, ישירה בבקשה", "חשוב לכם טיסה ישירה?") == {"flight": {"connection_preference": "direct"}})
check("unrelated prior question -> gate stays shut, no false positive",
      connpref("כן", "כמה מזוודות?") == {})

# --- car transmission ---
check("single-option automatic phrasing, bare 'כן' -> אוטומטי",
      carvehicle("כן", "חשוב לכם רכב אוטומטי?") == {"car": {"details": {"transmission": "אוטומטי"}}})
check("single-option automatic phrasing, bare 'לא' -> לא משנה (not an assertion of ידני)",
      carvehicle("לא", "חשוב לכם רכב אוטומטי?") == {"car": {"details": {"transmission": "לא משנה"}}})
check("single-option manual phrasing, bare 'כן' -> ידני",
      carvehicle("כן", "חשוב לכם רכב ידני?") == {"car": {"details": {"transmission": "ידני"}}})
check("single-option manual phrasing, bare 'לא' -> לא משנה",
      carvehicle("לא", "חשוב לכם רכב ידני?") == {"car": {"details": {"transmission": "לא משנה"}}})
check("regression: old-style dual phrasing 'אוטומטי או ידני?' + bare 'כן' stays ambiguous -> {}",
      carvehicle("כן", "אוטומטי או ידני?") == {})
check("regression: explicit word still works ('ידני' answer to automatic question)",
      carvehicle("לא, ידני", "חשוב לכם רכב אוטומטי?") == {"car": {"details": {"transmission": "ידני"}}})

# --- lodging level ---
check("single-tier phrasing, bare 'כן' -> that tier",
      lodging("כן", "חשוב לכם מלון יוקרתי?") == {"lodging": {"details": {"level": "יוקרתי"}}})
check("single-tier phrasing, bare 'לא' -> no preference",
      lodging("לא", "חשוב לכם מלון יוקרתי?") == {"lodging": {"details": {"level": "אין העדפה"}}})
check("open 'איזו רמת נוחות' question + bare 'כן' does NOT answer it -> {} (genuinely ambiguous)",
      lodging("כן", "איזו רמת נוחות אתם מחפשים?") == {})
check("open 'איזו רמת נוחות' question answered with an actual tier word still works (regression)",
      lodging("יוקרתי", "איזו רמת נוחות אתם מחפשים?") == {"lodging": {"details": {"level": "יוקרתי"}}})

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL BARE-YES/NO SINGLE-OPTION GATE TESTS PASSED")
