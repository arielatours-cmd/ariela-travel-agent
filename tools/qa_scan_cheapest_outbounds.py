"""QA: a capped flight search keeps the CHEAPEST outbound flights (live round 13 F,
24.10, Shlomo-approved).

The request asks Google to sort by price (sort_by=2), but search_flights put
best_flights before other_flights and then cut to max_outbounds (3 for a
customer search) - so "best" outbounds could be kept and cheaper ones dropped
before their returns were ever expanded. Now the outbounds are sorted by price
before the cut. The same number of outbounds is expanded: no extra API calls.
Same for search_open_jaw_flights.

Offline (SerpApi stubbed - no paid call). Run: python3 tools/qa_scan_cheapest_outbounds.py
"""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SCHEDULER_ENABLED", "false")
os.environ.setdefault("SERPAPI_API_KEY", "test-key-not-real")

import scanner  # noqa: E402

FAILED = []


def check(name, cond):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        FAILED.append(name)


def leg(price, token=None, hour="08"):
    return {"price": price, "departure_token": token,
            "flights": [{"departure_airport": {"id": "TLV", "time": f"2027-05-06 {hour}:00"},
                         "arrival_airport": {"id": "HAM", "time": f"2027-05-06 {hour}:59"}, "airline": "X"}],
            "total_duration": 300, "booking_token": f"b{price}"}


# Google's answer: two "best" (expensive) outbounds first, then four cheaper ones in other_flights.
OUTBOUND = {"best_flights": [leg(1591, "t1591"), leg(1548, "t1548")],
            "other_flights": [leg(1180, "t1180"), leg(1250, "t1250"), leg(1300, "t1300"), leg(1700, "t1700")]}
calls = []


def fake(params):
    calls.append(dict(params))
    tok = params.get("departure_token")
    if tok:
        price = int(tok[1:])
        return {"other_flights": [dict(leg(price, hour="18"), departure_token=None)]}
    return OUTBOUND


with patch.object(scanner, "_serpapi_request", side_effect=fake), patch.object(scanner, "record_route_availability"):
    result = scanner.search_flights("TLV", "HAM", "2027-05-06", "2027-05-10", max_outbounds=3)
expanded = [c["departure_token"] for c in calls if c.get("departure_token")]
check("the 3 cheapest outbounds are expanded (1180, 1250, 1300), not best_flights' 1591/1548",
      expanded == ["t1180", "t1250", "t1300"])
check("no extra API calls: 1 outbound request + 3 return expansions, as before", len(calls) == 4 and result["api_requests"] == 4)
check("the complete round trips are the cheap ones", sorted(f["price"] for f in result["flights"]) == [1180, 1250, 1300])

calls.clear()
with patch.object(scanner, "_serpapi_request", side_effect=fake), patch.object(scanner, "record_route_availability"):
    scanner.search_flights("TLV", "HAM", "2027-05-06", "2027-05-10", max_outbounds=None)
check("uncapped search (discovery depth) still expands every outbound", len([c for c in calls if c.get("departure_token")]) == 6)

src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scanner.py"), encoding="utf-8").read()
oj = src[src.index("def search_open_jaw_flights"):]
oj = oj[:oj.index("\ndef ")]
check("open-jaw search: the outbound cut is also by price",
      'out_items = sorted(out_items, key=_price_sort_key)' in oj
      and oj.index("sorted(out_items") < oj.index("out_items = out_items[:max(1, int(max_outbounds))]"))
# Shaked (#183 review): a flight with no price must sort LAST, never as 0 at the top.
ordered = sorted([{"price": 1300}, {"price": None}, {}, {"price": "n/a"}, {"price": 0}, {"price": 900}], key=scanner._price_sort_key)
check("no usable price -> last (inf), never first as 0; a real 0 stays a real 0",
      [o.get("price") for o in ordered][:3] == [0, 900, 1300] and all(not isinstance(o.get("price"), (int, float)) for o in ordered[3:]))

print()
print("ALL PASS" if not FAILED else f"{len(FAILED)} FAILED: {FAILED}")
sys.exit(1 if FAILED else 0)
