"""QA for Shaked's live report (2026-10-13, qa-s83, Cyprus, commit 997d8f8):
five findings from the same full fresh-account run, per the business
owner's standing instruction to keep iterating with Shaked until one clean
run passes start to finish.

1. lodging.details.locations never got filled from an approved route's own
   bases, and "כמו שכתבת, לפי המסלול" (as you wrote, per the route) wasn't
   understood as a reference to those bases - the same question kept
   getting re-asked verbatim. Root cause: the extractor had no fixed schema
   for trip_planning.details.route, so _resolve_lodging_locations_from_route
   (and _resolve_destination_airports_from_route) silently found nothing to
   extract whenever the model used a shape other than base/city/region
   dicts. Fixed with: (a) a pinned-down route schema in EXTRACTOR_SYSTEM,
   (b) a shared _route_base_names() helper with broader key fallbacks and
   plain-string day support, (c) the route's own bases handed to
   _understand_open_gap_answer as reference context for lodging.details.
   locations, so a "per the route" answer resolves to real area names.

2. The direct-flight question (business owner checklist 7a) never got
   asked for Cyprus - confirmed via direct DB query this is the same
   sparse direct_routes catalog gap already documented in
   qa/reports/2026-10-10.md (only 2 seeded rows, no Cyprus), not a code
   bug. Added TLV-LCA/TLV-PFO seed rows (database.py), sourced as
   general knowledge rather than a web-verified pass.

3. A duplicated "route approved" announcement with an internal-reasoning
   phrase ("כדי לחסוך בסריקות" - to save on scans) leaking straight to the
   customer. Root cause found exactly: chat_clean() prepends "מצוין,
   המסלול מאושר..." and then appends _flight_gap_question's own
   gateway_narrow text, which used to start with its own "המסלול אושר!"
   and end with the scan-cost phrase. Fixed by dropping both from the
   shared question text.

4. A dangling "**" markdown artifact between a rhetorical question and
   Tinkerbell answering it for itself - a thinking-out-loud leak, and
   itself a second violation of the existing "no markdown"/"never think
   out loud in the reply" rules. Added _strip_stray_markdown_markers as a
   deterministic safety net alongside the existing
   _strip_leaked_internal_paragraph.

5. (lower severity) car.return extracted as the literal, meaningless
   string "שדה שנטוס" (the airport we fly to) instead of being left for
   the meaning-based layer to resolve against the real known airports.
   Root cause: _CAR_LOCATION_RE's airport-prefix group only strips the
   longer "שדה התעופה ב-" phrasing, so a bare "שדה" followed by a relative
   clause leaked through as the captured value. Fixed by rejecting any
   capture whose first word is the bare "שדה". Also: the final summary's
   baggage line read as a generic singular "מזוודה גדולה" with no
   per-passenger qualifier - _BAGGAGE_HE now always says "...לכל נוסע".

Run: python3 tools/qa_s83_route_locations_and_leaks.py
"""
import json
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import ariella_chat_clean as chat

FAILED = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


# --- 1a. _route_base_names tolerates alternate day-object keys, not just
#         base/city/region ---
state_location_key = {
    "trip_planning": {"details": {"route": [
        {"day": 1, "location": "לרנקה"},
        {"day": 2, "area": "פאפוס"},
        {"day": 3, "place": "פאפוס"},
    ]}}
}
check("_route_base_names tolerates 'location'/'area'/'place' keys",
      chat._route_base_names(state_location_key) == ["לרנקה", "פאפוס"])

# --- 1b. plain-string route days are supported too ---
state_string_days = {"trip_planning": {"details": {"route": ["לרנקה", "פאפוס", "פאפוס"]}}}
check("_route_base_names tolerates plain-string route days",
      chat._route_base_names(state_string_days) == ["לרנקה", "פאפוס"])

# --- 1c. _resolve_lodging_locations_from_route now fills from a route that
#         uses the non-base-key shape that previously silently failed ---
lodging_from_route_state = {
    "trip_planning": {"details": {"route": [
        {"day": 1, "area": "לרנקה"}, {"day": 2, "area": "פאפוס"}, {"day": 3, "area": "פאפוס"},
    ]}},
    "lodging": {"details": {"locations": None}},
}
resolved_state = chat._resolve_lodging_locations_from_route(lodging_from_route_state)
check("lodging.details.locations now fills from a route using 'area' keys",
      resolved_state["lodging"]["details"]["locations"] == "לרנקה, פאפוס")

# --- 1d. _understand_open_gap_answer hands the route's own bases over as
#         reference context for the lodging.details.locations gap, so "per
#         the route" resolves to real area names instead of being stuck ---
gap_state = {
    "active_session": "lodging",
    "requested_services": ["flights", "lodging"],
    "service_decisions": {"lodging": {"wanted": True}},
    "destination": {"places": ["קפריסין"]},
    "dates": {"departure": "2026-12-06", "return": "2026-12-11"},
    "travelers": {"adults": 2},
    "lodging": {"details": {"type": "מלון", "rooms": 1, "locations": None, "budget": 500}},
    "trip_planning": {"details": {"route": [
        {"day": 1, "base": "לרנקה"}, {"day": 2, "base": "פאפוס"}, {"day": 3, "base": "פאפוס"},
    ]}},
}
gap_history = [{"role": "assistant", "content": "באיזה אזור תרצו שהלינה תהיה?"}]
captured_prompt = {}
def fake_post_claude_capture(key, model, system_static, system_dynamic, history_arg, msg, max_tokens, include_history=True, source="other"):
    captured_prompt["text"] = system_static
    return json.dumps({"resolved": {"lodging.details.locations": "לרנקה, פאפוס"}, "clarify": None})
with patch.object(chat, "_post_claude", side_effect=fake_post_claude_capture):
    resolved, clarify = chat._understand_open_gap_answer("test-key", "claude-sonnet-5", "כמו שכתבתי, לפי המסלול", gap_history, gap_state)
check("route bases are handed to the model as reference context for lodging.details.locations",
      "לרנקה" in captured_prompt.get("text", "") and "פאפוס" in captured_prompt.get("text", ""))
check("'לפי המסלול' resolves lodging.details.locations via the route reference",
      resolved == {"lodging": {"details": {"locations": "לרנקה, פאפוס"}}} and clarify is None)

# --- 2. The direct-flight catalog gap: TLV-LCA/TLV-PFO are now seeded ---
import sqlite3
import config
conn = sqlite3.connect(config.DB_PATH)
rows = conn.execute(
    "SELECT destination_code FROM direct_routes WHERE origin_code='TLV' AND destination_code IN ('LCA','PFO') AND status='active'"
).fetchall()
conn.close()
check("TLV-LCA and TLV-PFO are now seeded in direct_routes",
      {r[0] for r in rows} == {"LCA", "PFO"})

# --- 3. The gateway_narrow question text no longer duplicates "route
#        approved" or leaks the internal scan-cost reasoning ---
gateway_question = chat._flight_gap_question(["flight.gateway_narrow"], {"destination_airports": ["LCA", "PFO"]})
check("gateway_narrow question no longer says 'המסלול אושר!' (avoids duplicating the caller's own route-approval line)",
      "המסלול אושר" not in gateway_question)
check("gateway_narrow question no longer leaks 'כדי לחסוך בסריקות' internal reasoning to the customer",
      "לחסוך בסריקות" not in gateway_question)
check("gateway_narrow question still names the actual candidate airports",
      "LCA" in gateway_question or "לרנקה" in gateway_question or "פאפוס" in gateway_question or "PFO" in gateway_question)

# --- 4. _strip_stray_markdown_markers drops a bare "**" paragraph and any
#        other stray asterisks, exactly the qa-s83 shape ---
leaked = (
    "...או שזה כבר מובן מאליו לפי האזורים שבמסלול?\n\n**\n\nזה כבר ברור מהמסלול - "
    "לרנקה ללילה אחד, פאפוס לשני לילות."
)
cleaned = chat._strip_stray_markdown_markers(leaked)
check("a bare '**' paragraph is dropped entirely", "**" not in cleaned and "\n\n\n" not in cleaned)
check("the real surrounding text survives the cleanup",
      "האזורים שבמסלול" in cleaned and "לרנקה ללילה אחד" in cleaned)
check("ordinary text with no asterisks at all passes through unchanged",
      chat._strip_stray_markdown_markers("טקסט רגיל לגמרי.") == "טקסט רגיל לגמרי.")

# --- 5a. car.return no longer captures the bare relative "שדה שנטוס" ---
no_loc = chat._deterministic_car_location_facts("איסוף בפאפוס, והחזרה בשדה שנטוס אליו", [])
check("'שדה שנטוס' is never captured as a literal car.return value",
      (no_loc.get("car", {}).get("details", {}) or {}).get("return") is None)
check("the pickup half of the same message still resolves normally",
      no_loc.get("car", {}).get("details", {}).get("pickup") == "פאפוס")

# --- 5a (regression guard). A real place name is still captured normally -
#       this fix must not start rejecting legitimate locations ---
real_loc = chat._deterministic_car_location_facts("איסוף בפאפוס והחזרה בלרנקה", [])
check("a real place name (לרנקה) for car.return still works after the fix",
      real_loc.get("car", {}).get("details", {}).get("return") == "לרנקה")

# --- 5b. Checked baggage always reads as an explicit per-passenger fact ---
check("_BAGGAGE_HE's checked_bag label is always per-passenger, never a bare generic singular",
      "לכל נוסע" in chat._BAGGAGE_HE["checked_bag"] and "לכל נוסע" in chat._BAGGAGE_HE["checked"])

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL QA-S83 FIXES PASSED")
