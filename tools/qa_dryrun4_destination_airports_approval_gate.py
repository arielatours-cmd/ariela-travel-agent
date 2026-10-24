"""QA for dry-run 4 finding 3 (Shaked/Shlomo, 22.10.2026, qa/reports/
2026-10-22-dryrun4.md, scenario E - Rovinj/Pula):

"אני ושתי חברות לרוביני" -> "פולה מתאים לנו" -> Tinkerbell correctly named
a real, catalogued airport (PUY, Pula) in her own free-text reply - but
destination_airports (the structured, searchable field) was NEVER actually
written. Nothing ever flagged this as a gap, because _required_state_gaps's
destination_airports check (ariella_chat_clean.py) only ever fired for a
BROAD destination_mode (country/region/area/broad) or a ski trip - a
SPECIFIC named place (destination.places non-empty, mode None/"specific")
whose catalog resolution simply found no match fell through entirely.
Flights reached session_status "complete" with destination_airports still
empty, every other domain got declined, and the final approval summary
went out ("כתבי מאשרת") naming PUY only in Tinkerbell's own narrative text
- never in a saved field. Business owner's rule (relayed by Shlomo): never
ask for approval when there is no field actually saved to search on.

Fixed: the destination_airports gap now fires whenever a real place HAS
been named (destination.places non-empty, ANY mode) but the airport
genuinely never resolved - not only for the broad-geography case. This
stops flights from ever closing in the first place while the only
accessible verified source from the stated city is a confirmed answer with
no saved field, so the whole later "approval with nothing to search on"
scenario in this report (flights wrongly 'complete', ready_for_summary
only blocked by the SEPARATE _destination_gateway_unresolved check, the
model free-composing its own summary and approval request regardless)
never arises.

Run: python3 tools/qa_dryrun4_destination_airports_approval_gate.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

from ariella_chat_clean import _required_state_gaps, _session_gaps, _flight_gap_question, _advance_sessions

FAILED = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


def _flight_gaps(state):
    gaps = _required_state_gaps(state)
    return [g for g in gaps if g == "destination_airports"]


BASE = {
    "trip_type": "standard",
    "dates": {"departure": "2027-07-02", "return": "2027-07-06", "needs_confirmation": False},
    "travelers": {"adults": 3, "children": 0, "child_ages": []},
    "flight": {"baggage": ["carry_on_only"]},
    "departure_airport": "TLV",
    "requested_services": ["flights"],
    "service_decisions": {"flights": {"wanted": True, "source": "destination_trip_intent"}},
}

# =====================================================================
# 1. The live repro itself: a specific, uncatalogued town (mode None),
#    destination_airports still empty -> now a real gap (was silently
#    invisible before this fix).
# =====================================================================
state_rovinj = dict(BASE, destination={"places": ["רוביני"], "mode": None, "status": "known"}, destination_airports=[])
check("mode=None (no mode classified at all), destination_airports empty -> "
      "destination_airports IS a gap (the live Rovinj/Pula bug)",
      "destination_airports" in _flight_gaps(state_rovinj))
check("_session_gaps('flights') includes it too, so flights cannot close",
      "destination_airports" in _session_gaps(state_rovinj, "flights"))
check("the gap question is a safe, generic ask - never a fabricated city/code",
      _flight_gap_question(_session_gaps(state_rovinj, "flights"), state_rovinj) == "באיזה שדה תרצי לנחות בהלוך?")

# =====================================================================
# 2. Same uncatalogued place, mode explicitly "specific"/"city" - same fix
#    must cover these labels too, not just mode=None.
# =====================================================================
for mode in ("specific", "city"):
    state = dict(BASE, destination={"places": ["רוביני"], "mode": mode, "status": "known"}, destination_airports=[])
    check(f"mode='{mode}', destination_airports empty -> still a gap",
          "destination_airports" in _flight_gaps(state))

# =====================================================================
# 3. Regression: the ORIGINAL broad-geography case (the comment this fix
#    extends) must still fire exactly as before.
# =====================================================================
for mode in ("country", "region", "area", "broad"):
    state = dict(BASE, destination={"places": ["יוון"], "mode": mode, "status": "known"}, destination_airports=[])
    check(f"regression: broad mode='{mode}', destination_airports empty -> still a gap",
          "destination_airports" in _flight_gaps(state))

# =====================================================================
# 4. Regression: a ski trip with destination_airports still empty -> still
#    a gap, regardless of destination.mode (is_ski_trip still honored).
# =====================================================================
state_ski = dict(
    BASE, trip_type="ski",
    destination={"places": ["אוסטריה"], "mode": "country", "status": "known"},
    destination_airports=[],
)
check("regression: ski trip, destination_airports empty -> still a gap",
      "destination_airports" in _flight_gaps(state_ski))

# =====================================================================
# 5. Regression: once destination_airports IS populated, never a gap -
#    for every mode, including the newly-covered specific/None ones.
# =====================================================================
for mode in (None, "specific", "city", "country", "region"):
    state = dict(BASE, destination={"places": ["פריז"], "mode": mode, "status": "known"}, destination_airports=["CDG"])
    check(f"regression: mode={mode!r} with destination_airports already set -> never a gap",
          "destination_airports" not in _flight_gaps(state))

# =====================================================================
# 6. Regression: nothing named at all yet - the separate, broader
#    "destination" gap covers this; destination_airports itself must not
#    ALSO fire redundantly (destination.places is empty, guarded by "if
#    (destination.get('places') or []) and not destination_airports").
# =====================================================================
state_unnamed = dict(BASE, destination={"places": [], "mode": None, "status": "unknown"}, destination_airports=[])
gaps_unnamed = _required_state_gaps(state_unnamed)
check("regression: no destination named at all -> the general 'destination' "
      "gap fires", "destination" in gaps_unnamed)
check("regression: no destination named at all -> 'destination_airports' "
      "itself does not ALSO fire (nothing to resolve yet)",
      "destination_airports" not in gaps_unnamed)

# =====================================================================
# 7. End-to-end: _advance_sessions must never mark flights 'complete'
#    while this gap is open - the exact mechanism that let the live bug's
#    flights session close prematurely.
# =====================================================================
state_live = dict(
    BASE,
    destination={"places": ["רוביני"], "mode": None, "status": "known"},
    destination_airports=[],
    active_session="flights",
    session_status={"flights": "active"},
)
advanced = _advance_sessions(dict(state_live))
check("end-to-end: flights session_status stays 'active' (never silently "
      "'complete') while destination_airports is unresolved for a named place",
      advanced.get("session_status", {}).get("flights") == "active")
check("end-to-end: ready_for_summary stays False (nothing to approve with "
      "no saved field to search on)",
      advanced.get("ready_for_summary") is False)
check("end-to-end: missing_required actually surfaces destination_airports "
      "as the thing still open",
      "destination_airports" in (advanced.get("missing_required") or []))

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL DRYRUN4-DESTINATION-AIRPORTS-APPROVAL-GATE TESTS PASSED")
