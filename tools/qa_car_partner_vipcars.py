"""QA for the VIP Cars car link (22.10, the business owner's decision relayed
by Shlomo/Bezalel):

1. CAR_RENTAL_SEARCH_URL_TEMPLATE goes inside CJ's url= parameter with the
   pickup airport, pickup date and return date;
2. no times at all - the customer picks them on VIP Cars' page; the old
   "10:00" default is gone ({pickup_time}/{return_time} are always empty,
   kept only so an older template still formats);
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
check("2: no time passed, even though the customer said 14:30/18:00", "t1" not in v and "t2" not in v and "14:30" not in out and "18:00" not in out)
out, q, v = inner(dict(ANS, car_pickup="", car_return=""))
check("2: no '10:00' default anywhere", "10%3A00" not in out and "10:00" not in out and "t1" not in v)
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

# Card text
with patch.object(public_site, "CAR_RENTAL_AFFILIATE_LINK", CJ):
    same = public_site._car_partner_cards(7, ANS)
    diff = public_site._car_partner_cards(7, dict(ANS, car_return="החזרה בברגמו"))
check("card: same place -> 'איסוף והחזרה בשדה התעופה ...'", same and same[0]["pickup"].startswith("איסוף והחזרה בשדה התעופה") and "(FCO)" in same[0]["pickup"])
check("card: different return -> both airports named", diff and "איסוף בשדה התעופה" in diff[0]["pickup"] and "(BGY)" in diff[0]["pickup"])
src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "public_site.py"), encoding="utf-8").read()
check("the '10:00' default for the partner link is gone", 'or "10:00"' not in src)

print()
print("ALL PASS" if not FAILED else f"{len(FAILED)} FAILED: {FAILED}")
sys.exit(1 if FAILED else 0)
