"""QA: lodging booking links arrive with the dates AND the travelers (the
business owner, 23.10 - Shaked's booking-links audit,
qa/reports/2026-10-23-booking-links-audit.md on the shaked branch: trip 247,
Munich, 2 adults + a 10-year-old).

(a) The Booking.com partner card: group_adults/group_children were there, but
    no age - Booking.com shows no price for a room with a child without it.
    Now an "age" per child, from the customer's child_ages (never guessed).
    no_rooms is the customer's own lodging answer (default 1).
(b) Hotel results: the Google Hotels booking.com link opened the hotel page
    empty. Now, before the CJ wrap: checkin/checkout (the hotel's own segment
    dates, else the trip's) + the party. Foreign aid/label still stripped;
    non-booking.com links untouched.

Offline (search_hotels stubbed - no paid call). Run: python3 tools/qa_booking_links_stay.py
"""
import json
import os
import sys
from unittest.mock import patch
from urllib.parse import parse_qs, parse_qsl, urlsplit

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")
os.environ.setdefault("SCHEDULER_ENABLED", "false")

import public_site  # noqa: E402

FAILED = []
CJ = "https://www.anrdoezrs.net/click-qa-evergreen"


def check(name, cond):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        FAILED.append(name)


def inner(cj_url):
    """The booking.com URL inside a CJ link, as (path, [(k, v), ...])."""
    url = parse_qs(urlsplit(cj_url).query)["url"][0]
    parts = urlsplit(url)
    return parts.netloc + parts.path, parse_qsl(parts.query)


MUNICH = {"destinations": "MUC", "departure_date": "2027-02-06", "return_date": "2027-02-13",
          "adults": 2, "children": 1, "age_groups": [10], "_requested_services": ["lodging"]}

# --- (a) the partner card ---------------------------------------------------------------------------------
with patch.object(public_site, "CJ_BOOKING_EVERGREEN_LINK", CJ), patch.object(public_site, "LODGING_AFFILIATE_LINK", ""):
    host, q = inner(public_site._lodging_partner_url(MUNICH, "MUC", 247))
    two_kids, q2 = inner(public_site._lodging_partner_url(dict(MUNICH, children=2, age_groups=["4", 12]), "MUC", 247))
    no_age, q3 = inner(public_site._lodging_partner_url(dict(MUNICH, age_groups=[]), "MUC", 247))
    rooms2, q4 = inner(public_site._lodging_partner_url(dict(MUNICH, lodging_rooms=2), "MUC", 247))
check("(a) partner card: still Booking.com search with the city and the dates",
      host == "www.booking.com/searchresults.html" and ("checkin", "2027-02-06") in q and ("checkout", "2027-02-13") in q)
check("(a) partner card: 2 adults + 1 child + the child's age (age=10)",
      ("group_adults", "2") in q and ("group_children", "1") in q and [v for k, v in q if k == "age"] == ["10"])
check("(a) partner card: one 'age' per child, in order", [v for k, v in q2 if k == "age"] == ["4", "12"])
check("(a) a child whose age the chat never got: counted, age not guessed",
      ("group_children", "1") in q3 and not [v for k, v in q3 if k == "age"])
check("(a) no_rooms: the customer's own answer, default 1",
      ("no_rooms", "1") in q and ("no_rooms", "2") in q4)

# --- (b) hotel results, at search time ----------------------------------------------------------------------
GOOGLE = ("https://www.booking.com/hotel/de/munich-central.html?aid=999&label=foreign&utm_source=seogooglelocal"
          "&checkin=2020-01-01&group_adults=7")


def fake_search(query, checkin_date, checkout_date, **kw):
    return {"hotels": [{"name": "Central", "link": GOOGLE},
                       {"name": "Own site", "link": "https://hotel-own.example/book?x=1"}]}


with patch.object(public_site, "search_hotels", side_effect=fake_search), patch.object(public_site, "CJ_BOOKING_EVERGREEN_LINK", CJ), \
        patch.object(public_site, "_save_trip_answers"):
    a = json.loads(json.dumps(MUNICH))
    public_site._run_lodging_search(247, a)
    route = dict(MUNICH, _approved_itinerary={"days": [{"base": "מינכן"}] * 3 + [{"base": "זלצבורג"}] * 4})
    b = json.loads(json.dumps(route))
    public_site._run_lodging_search(248, b)
offers = a.get("lodging_offers") or []
host, q = inner(offers[0]["link"])
check("(b) hotel result: still the same hotel page", host == "www.booking.com/hotel/de/munich-central.html")
check("(b) hotel result: the trip's dates, replacing the link's own stale ones",
      [v for k, v in q if k == "checkin"] == ["2027-02-06"] and [v for k, v in q if k == "checkout"] == ["2027-02-13"])
check("(b) hotel result: the party - 2 adults, 1 child, age 10, 1 room",
      [v for k, v in q if k == "group_adults"] == ["2"] and ("group_children", "1") in q
      and [v for k, v in q if k == "age"] == ["10"] and ("no_rooms", "1") in q)
check("(b) foreign aid/label still stripped; other parameters kept",
      not any(k in ("aid", "label") for k, _ in q) and ("utm_source", "seogooglelocal") in q)
check("(b) a non-booking.com link is untouched", offers[1]["link"] == "https://hotel-own.example/book?x=1")
seg_links = {h["segment_location"]: inner(h["link"])[1] for h in (b.get("lodging_offers") or []) if "booking.com" in h["link"] or CJ in h["link"]}
check("(b) multi-stop: each stop's hotels get that stop's own dates",
      [v for k, v in seg_links.get("מינכן", []) if k in ("checkin", "checkout")] == ["2027-02-06", "2027-02-09"]
      and [v for k, v in seg_links.get("זלצבורג", []) if k in ("checkin", "checkout")] == ["2027-02-09", "2027-02-13"])

# --- Render-time call (no answers): unchanged behaviour -----------------------------------------------------
with patch.object(public_site, "CJ_BOOKING_EVERGREEN_LINK", CJ):
    old = public_site._wrap_booking_com_hotel_links([{"link": GOOGLE}], 9)[0]["link"]
check("render-time wrap without answers: only strip + wrap, as before", ("checkin", "2020-01-01") in inner(old)[1])

# --- Tom's QA follow-ups (23.10) ----------------------------------------------------------------------------
with patch.object(public_site, "CJ_BOOKING_EVERGREEN_LINK", CJ), patch.object(public_site, "LODGING_AFFILIATE_LINK", ""):
    _, q_nodates = inner(public_site._lodging_partner_url(dict(MUNICH, departure_date=None, return_date=None), "MUC", 247))
    # A trip from the site form: age_groups holds groups ("children", "teens"), not ages.
    _, q_groups = inner(public_site._lodging_partner_url(dict(MUNICH, children=2, age_groups=["children", "teens"]), "MUC", 247))
check("no dates yet -> no empty checkin= / checkout=", not any(k in ("checkin", "checkout") for k, _ in q_nodates))
check("site-form age groups ('children', 'teens') are not ages -> no age sent, never a representative guess",
      ("group_children", "2") in q_groups and not [v for k, v in q_groups if k == "age"])
VIP = ("https://www.vipcars.com/search/?language=en&pickup_country={pickup_country}&pickup_city={pickup_city}"
       "&pickup_location={pickup_location}&dropoff_country={dropoff_country}&dropoff_city={dropoff_city}"
       "&dropoff_location={dropoff_location}&pickup_date={pickup_date}&pickup_time={pickup_time}"
       "&dropoff_date={return_date}&dropoff_time={return_time}&page=search")
with patch.object(public_site, "CAR_RENTAL_SEARCH_URL_TEMPLATE", VIP), \
        patch.object(public_site, "CAR_RENTAL_AFFILIATE_LINK", "https://www.tkqlhce.com/click-qa"):
    car_url = parse_qs(urlsplit(public_site._car_partner_url({"destinations": "LIS"}, "LIS", 246)).query)["url"][0]
    car_q = parse_qsl(urlsplit(car_url).query, keep_blank_values=True)
    dated = parse_qs(urlsplit(parse_qs(urlsplit(public_site._car_partner_url(
        {"destinations": "LIS", "departure_date": "2027-05-01", "return_date": "2027-05-08"}, "LIS", 246)).query)["url"][0]).query)
check("car, no dates yet -> no empty pickup_date= / dropoff_date= (and nothing else empty)",
      not any(v == "" for _, v in car_q) and not any(k in ("pickup_date", "dropoff_date") for k, _ in car_q)
      and ("pickup_location", "777") in car_q)
check("car, with dates -> the dates are still there", dated.get("pickup_date") == ["2027-05-01"] and dated.get("dropoff_date") == ["2027-05-08"])

print()
print("ALL PASS" if not FAILED else f"{len(FAILED)} FAILED: {FAILED}")
sys.exit(1 if FAILED else 0)
