"""QA: VIP Cars location ids for every airport Ofek verified (the business
owner, 23.10 - Shaked's booking-links audit: trip 246, Zurich, went to VIP
Cars' home page with no dates and no place, because only LIS was mapped).

static/vipcars_locations.json now holds the 132 airports from ofek 8dc085c
(product/data/vipcars_locations_draft.json, "airports" only - the
"unverified" list is not used). LIS stays the business owner's own search
(120/1788/777). An airport still unmapped keeps the partner's home page:
VIP Cars' search needs its own location ids, and no URL that takes dates
without a place is known - never a guessed one.

Offline. Run: python3 tools/qa_vipcars_locations_ofek.py
"""
import json
import os
import sys
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")
os.environ.setdefault("SCHEDULER_ENABLED", "false")

import public_site  # noqa: E402

FAILED = []


def check(name, cond):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        FAILED.append(name)


locs = json.load(open(os.path.join(ROOT, "static", "vipcars_locations.json"), encoding="utf-8"))["locations"]
check("132 verified airports, every one with integer country/city/location ids",
      len(locs) == 132 and all(all(isinstance(v.get(k), int) for k in ("country", "city", "location")) for v in locs.values()))
check("LIS is still the business owner's own search (120/1788/777)",
      (locs["LIS"]["country"], locs["LIS"]["city"], locs["LIS"]["location"]) == (120, 1788, 777))
check("ZRH (Shaked's trip 246) is mapped", public_site._vipcars_location("ZRH") == {**locs["ZRH"]})

VIP = ("https://www.vipcars.com/search/?language=en&pickup_country={pickup_country}&pickup_city={pickup_city}"
       "&pickup_location={pickup_location}&dropoff_country={dropoff_country}&dropoff_city={dropoff_city}"
       "&dropoff_location={dropoff_location}&pickup_date={pickup_date}&pickup_time={pickup_time}"
       "&dropoff_date={return_date}&dropoff_time={return_time}&page=search")
ANS = {"destinations": "ZRH", "departure_date": "2027-03-01", "return_date": "2027-03-08", "car_pickup": "", "car_return": ""}


def vip(iata, answers=ANS):
    with patch.object(public_site, "CAR_RENTAL_SEARCH_URL_TEMPLATE", VIP), \
            patch.object(public_site, "CAR_RENTAL_AFFILIATE_LINK", "https://www.tkqlhce.com/click-qa"):
        q = parse_qs(urlsplit(public_site._car_partner_url(answers, iata, 246)).query)
    return parse_qs(urlsplit(q["url"][0]).query) if "url" in q else None


v = vip("ZRH")
check("ZRH: a real VIP Cars search - the airport on both ends, the dates, a time",
      v is not None and v["pickup_location"] == [str(locs["ZRH"]["location"])] and v["dropoff_location"] == [str(locs["ZRH"]["location"])]
      and v["pickup_date"] == ["2027-03-01"] and v["dropoff_date"] == ["2027-03-08"] and v["pickup_time"] == ["10:00"])
check("a different return airport (both mapped) -> the dropoff is that airport",
      (vip("ZRH", dict(ANS, car_return="להחזיר ב-MUC")) or {}).get("dropoff_location") == [str(locs["MUC"]["location"])])
check("an airport not mapped (HFA) -> the partner's home page, never a guessed place", vip("HFA") is None)

print()
print("ALL PASS" if not FAILED else f"{len(FAILED)} FAILED: {FAILED}")
sys.exit(1 if FAILED else 0)
