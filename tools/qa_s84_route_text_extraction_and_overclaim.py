"""QA for Shaked's live report (2026-10-13, qa-s84, Cyprus, commit 7dd83c5):

1. 🔴 Lodging locations were STILL stuck in a loop even after the qa-s83
   fix, because the root cause was worse than suspected: the model never
   fills trip_planning.details.route as structured JSON at all (not even
   with the wrong key names) - only approved=true and approved_text (free
   text) got saved. Fixed by deterministically extracting the lodging
   bases straight out of approved_text at the moment of approval
   (_extract_route_bases_from_approved_text, anchored on Tinkerbell's own
   "לינה ב-X"/"לינה באזור X" wording), and backfilling
   trip_planning.details.route with them so the existing _route_base_names
   machinery keeps working unchanged.

2. 🟠 A lodging type answer ("מלון") got written into lodging.details.level
   as a literal, meaningless string, because the budget_or_level composite
   splitter accepted any unmatched text as a "level" value. Fixed: route a
   recognized lodging TYPE word to the real type field instead, and drop
   (never guess) a value that matches neither a number, a canonical level
   word, nor a type word.

3. 🟠 "זה בדיוק מסתדר - יש טיסה ישירה... בתאריכים האלה" / "יש לכם טיסה
   ישירה... לתאריכים האלה" - a false promise that a specific flight on the
   customer's specific dates was already confirmed, before any real scan
   ran. Root cause: the direct_route_hint_text injected into Tinkerbell's
   prompt literally said "ליעד ולתאריכים האלה קיימת טיסה ישירה מאומתת...
   מותר לציין זאת כעובדה" - but _direct_route_available only confirms a
   nonstop ROUTE/schedule exists, never seat availability on a specific
   date. Reworded so the hint can never be read as license to claim
   confirmed date-specific availability before a scan runs.

Run: python3 tools/qa_s84_route_text_extraction_and_overclaim.py
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


# --- 1a. The exact qa-s84 shape: route stayed completely unset, only free
#         text with "לינה ב-X"/"לינה באזור X" lines is available ---
approved_text = (
    "מצוין! הנה המסלול: לרנקה (לילה אחד), לימסול (שני לילות) ופאפוס (שני לילות). "
    "לינה באזור לרנקה ללילה הראשון, לינה בלימסול לשני הלילות הבאים, ולינה בפאפוס לשני הלילות האחרונים. "
    "מתאים לך המסלול הזה?"
)
bases = chat._extract_route_bases_from_approved_text(approved_text)
check("route bases extracted deterministically from 'לינה ב-'/'לינה באזור' wording",
      bases == ["לרנקה", "לימסול", "פאפוס"])

# --- 1b. No such wording at all -> empty, never guesses ---
check("text with no 'לינה ב-' wording at all yields nothing (never guesses)",
      chat._extract_route_bases_from_approved_text("מסלול יפה, תיהנו מהטיול!") == [])

# --- 1c. Full integration: once this text is saved as approved_text with no
#         structured route, _route_base_names/_resolve_lodging_locations_
#         from_route must still work exactly as if the model had filled the
#         JSON - reproducing the fix in the exact spot it's wired into
#         chat_clean() (the plan["approved_text"]=... block) ---
plan = {"interested": True, "approved": True}
plan_details = dict(plan.get("details") or {})
if not plan_details.get("route"):
    route_bases = chat._extract_route_bases_from_approved_text(approved_text)
    if route_bases:
        plan_details["route"] = [{"base": b} for b in route_bases]
        plan["details"] = plan_details
state_after_approval = {"trip_planning": plan, "lodging": {"details": {"locations": None}}}
resolved = chat._resolve_lodging_locations_from_route(state_after_approval)
check("lodging.details.locations fills correctly end-to-end from approved_text alone",
      resolved["lodging"]["details"]["locations"] == "לרנקה, לימסול, פאפוס")

# --- 2a. A lodging TYPE word answering the budget_or_level gap routes to
#         the real 'type' field, never a literal nonsense 'level' ---
import json
from unittest.mock import patch
type_state = {
    "active_session": "lodging",
    "requested_services": ["flights", "lodging"],
    "service_decisions": {"lodging": {"wanted": True}},
    "destination": {"places": ["קפריסין"]},
    "dates": {"departure": "2026-12-06", "return": "2026-12-11"},
    "travelers": {"adults": 2},
    "lodging": {"details": {"type": None, "rooms": 1, "locations": "פאפוס", "budget": None, "level": None}},
}
type_history = [{"role": "assistant", "content": "מה התקציב ללילה, או איזו רמת נוחות אתם מחפשים?"}]
def fake_type_answer(key, model, s, d, h, m, mt, include_history=True, source="other"):
    return json.dumps({"resolved": {"lodging.details.budget_or_level": "מלון"}, "clarify": None})
with patch.object(chat, "_post_claude", side_effect=fake_type_answer):
    resolved_type, _ = chat._understand_open_gap_answer("test-key", "claude-sonnet-5", "מלון", type_history, type_state)
check("'מלון' answering budget_or_level routes to the real 'type' field, never a literal level",
      resolved_type == {"lodging": {"details": {"type": "מלון"}}})

# --- 2b. A value matching neither number, level word, nor type word is
#         dropped entirely rather than written as garbage into 'level' ---
def fake_garbage_answer(key, model, s, d, h, m, mt, include_history=True, source="other"):
    return json.dumps({"resolved": {"lodging.details.budget_or_level": "אולי נראה"}, "clarify": None})
with patch.object(chat, "_post_claude", side_effect=fake_garbage_answer):
    resolved_garbage, _ = chat._understand_open_gap_answer("test-key", "claude-sonnet-5", "אולי נראה", type_history, type_state)
check("an unrecognized value for budget_or_level is dropped, never written as a literal level",
      resolved_garbage == {})

# --- 2c. Regression guard: a real level word and a real budget number still
#         resolve exactly as before ---
def fake_level_answer(key, model, s, d, h, m, mt, include_history=True, source="other"):
    return json.dumps({"resolved": {"lodging.details.budget_or_level": "יוקרתי בבקשה"}, "clarify": None})
with patch.object(chat, "_post_claude", side_effect=fake_level_answer):
    resolved_level, _ = chat._understand_open_gap_answer("test-key", "claude-sonnet-5", "יוקרתי בבקשה", type_history, type_state)
check("a real level word still resolves to 'level' exactly as before",
      resolved_level == {"lodging": {"details": {"level": "יוקרתי"}}})

# --- 3. The direct-route hint text can no longer be read as license to
#        claim a specific date's flight is already confirmed ---
hint_state = {"destination": {"places": ["קפריסין"]}, "destination_airports": ["LCA", "PFO"],
              "dates": {"departure": "2026-12-06"}, "departure_airport": "TLV"}
check("_direct_route_available is true for the now-seeded Cyprus routes (precondition for this test)",
      chat._direct_route_available(hint_state) is True)
hint_text = chat._direct_route_hint_text(hint_state)
check("the hint no longer says 'ליעד ולתאריכים האלה' (destination AND these dates) together",
      "ולתאריכים האלה" not in hint_text)
check("the hint explicitly forbids claiming confirmed availability before a real scan",
      "אסור לטעון" in hint_text and "נבדק רק בסריקה" in hint_text)

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL QA-S84 FIXES PASSED")
