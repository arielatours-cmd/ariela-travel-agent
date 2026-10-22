"""QA for the VIP Cars car link (22.10, the business owner's decision relayed
by Shlomo/Bezalel):

1. CAR_RENTAL_SEARCH_URL_TEMPLATE goes inside CJ's url= parameter with the
   pickup airport, pickup date and return date;
2. times (updated 22.10 after the business owner's own test - VIP Cars
   rejects a search with no pick-up time): the HH:MM the customer gave in
   the chat (car.details.pickup / return), else 10:00 - the customer can
   change it on VIP Cars' page;
3. the return place: {return_iata} / {same_return} - a different airport
   only when the customer's own return answer (car.details.return) clearly
   names one (its code, or a single-airport city other than the pickup's);
   otherwise "same place". The card text says it too.
The exact VIP Cars search-URL format couldn't be checked from this
environment (vipcars.com is blocked here) - the template value is the
business owner's to enter in Render once the format is confirmed.

Offline. Run: python3 tools/qa_car_partner_vipcars.py
"""
import os
import sys
import tempfile
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.update({"DB_PATH": os.path.join(tempfile.mkdtemp(prefix="ariella-qa-car-"), "qa.db"),
                   "SCHEDULER_ENABLED": "false", "SCANNER_ENABLED": "false"})

import public_site  # noqa: E402

FAILED = []


def check(name, cond):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        FAILED.append(name)


CJ = "https://www.anrdoezrs.net/click-1-2"
TEMPLATE = ("https://partner.example/search?from={iata}&to={return_iata}&same={same_return}"
            "&d1={pickup_date}&d2={return_date}&t1={pickup_time}&t2={return_time}")
ANS = {"departure_date": "2027-05-01", "return_date": "2027-05-08", "_requested_services": ["car"],
       "destinations": "FCO", "car_pickup": "בשדה התעופה, 14:30", "car_return": "בשדה התעופה, 18:00"}


def inner(answers, iata="FCO", template=TEMPLATE):
    with patch.object(public_site, "CAR_RENTAL_SEARCH_URL_TEMPLATE", template), \
            patch.object(public_site, "CAR_RENTAL_AFFILIATE_LINK", CJ):
        out = public_site._car_partner_url(answers, iata, 7)
    q = parse_qs(urlsplit(out).query)
    return out, q, (parse_qs(urlsplit(q["url"][0]).query) if "url" in q else {})


out, q, v = inner(ANS)
check("1: CJ link with sid and the template inside url=", out.startswith(CJ + "?") and q.get("sid") == ["trip7"] and "url" in q)
check("1: pickup airport + pickup/return dates passed",
      v.get("from") == ["FCO"] and v.get("d1") == ["2027-05-01"] and v.get("d2") == ["2027-05-08"])
check("2: the customer's own times from the chat are passed (14:30 / 18:00)", v.get("t1") == ["14:30"] and v.get("t2") == ["18:00"])
out, q, v = inner(dict(ANS, car_pickup="", car_return=""))
check("2: no time given -> 10:00 (VIP Cars requires one)", v.get("t1") == ["10:00"] and v.get("t2") == ["10:00"])
out, q, v = inner(dict(ANS, car_pickup="בשדה, 9:05", car_return="בשדה"))
check("2: a time is normalized to HH:MM, and each end defaults on its own", v.get("t1") == ["09:05"] and v.get("t2") == ["10:00"])
check("3: no separate return place -> same airport", v.get("to") == ["FCO"] and v.get("same") == ["1"])

for text, expected, label in (
    ("החזרה בברגמו", "BGY", "a single-airport city named in Hebrew"),
    ("return at MXP", "MXP", "an IATA code"),
    ("בפאפוס, 18:00", "PFO", "a city with a time"),
):
    _, _, v = inner(dict(ANS, car_return=text))
    check(f"3: different return ({label}) -> {expected}, same=0", v.get("to") == [expected] and v.get("same") == ["0"])
for text, label in (("ברומא", "the pickup city itself (Rome has 2 airports)"), ("באותו מקום", "'same place'"),
                    ("החזרה במילאנו", "an ambiguous multi-airport city"), ("בפאפוס או בלרנקה", "two places")):
    _, _, v = inner(dict(ANS, car_return=text))
    check(f"3: {label} -> same airport", v.get("to") == ["FCO"] and v.get("same") == ["1"])

out, q, v = inner(ANS, template="https://partner.example/search?from={iata}&d1={pickup_date}&d2={return_date}")
check("a template without the new placeholders still works", v.get("from") == ["FCO"] and "to" not in v)
out, q, v = inner(ANS, template="https://partner.example/search?x={unknown}")
check("a malformed template -> partner home page (no url=)", "url" not in q)

# VIP Cars' own location ids (real search by the business owner, 22.10: Lisbon airport = 120/1788/777)
VIP = ("https://www.vipcars.com/search/?language=en&pickup_country={pickup_country}&pickup_city={pickup_city}"
       "&pickup_location={pickup_location}&dropoff_country={dropoff_country}&dropoff_city={dropoff_city}"
       "&dropoff_location={dropoff_location}&pickup_date={pickup_date}&pickup_time={pickup_time}"
       "&dropoff_date={return_date}&dropoff_time={return_time}&page=search")
LIS_ANS = dict(ANS, destinations="LIS")
out, q, v = inner(LIS_ANS, iata="LIS", template=VIP)
check("VIP: Lisbon -> the verified ids on both ends, the dates and the times",
      v.get("pickup_country") == ["120"] and v.get("pickup_city") == ["1788"] and v.get("pickup_location") == ["777"]
      and v.get("dropoff_location") == ["777"] and v.get("pickup_date") == ["2027-05-01"] and v.get("dropoff_date") == ["2027-05-08"]
      and v.get("pickup_time") == ["14:30"] and v.get("dropoff_time") == ["18:00"])
out, q, v = inner(dict(LIS_ANS, car_pickup="", car_return=""), iata="LIS", template=VIP)
check("VIP: no times in the chat -> pickup_time/dropoff_time 10:00 (never missing - VIP rejects that)",
      v.get("pickup_time") == ["10:00"] and v.get("dropoff_time") == ["10:00"])
check("VIP: the colon is percent-encoded inside CJ's url= (10%3A00), decoded back by CJ",
      "10%253A00" in out or "10%3A00" in out)
check("VIP: no tid / aff in what we build", "tid" not in v and "aff" not in v and "tid=" not in out and "aff=" not in out)
out, q, v = inner(ANS, iata="FCO", template=VIP)
check("VIP: a destination with no verified ids (FCO) -> partner home page, no url=", "url" not in q and q.get("sid") == ["trip7"])
out, q, v = inner(dict(LIS_ANS, car_return="return at FAO"), iata="LIS", template=VIP)
check("VIP: return airport with no verified ids -> home page (never half-filled)", "url" not in q)
src_map = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "vipcars_locations.json"), encoding="utf-8").read()
check("mapping file: LIS = 120/1788/777 (the verified search)", '"LIS": {"country": 120, "city": 1788, "location": 777' in src_map)

# Card text
with patch.object(public_site, "CAR_RENTAL_AFFILIATE_LINK", CJ):
    same = public_site._car_partner_cards(7, ANS)
    diff = public_site._car_partner_cards(7, dict(ANS, car_return="החזרה בברגמו"))
check("card: same place -> 'איסוף והחזרה בשדה התעופה ...'", same and same[0]["pickup"].startswith("איסוף והחזרה בשדה התעופה") and "(FCO)" in same[0]["pickup"])
check("card: different return -> both airports named", diff and "איסוף בשדה התעופה" in diff[0]["pickup"] and "(BGY)" in diff[0]["pickup"])
src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "public_site.py"), encoding="utf-8").read()
check("no driver-age parameters are sent (the chat state has no driver age)", "driver_age" not in src.split("def _car_partner_url", 1)[1].split("def _car_time", 1)[0])

print()
print("ALL PASS" if not FAILED else f"{len(FAILED)} FAILED: {FAILED}")
sys.exit(1 if FAILED else 0)
