"""QA for the lodging tab (22.10, the business owner's decision relayed by
Shlomo/Bezalel - Lisbon 21-25.3.2027 screenshot):

1. A booking button next to every hotel/apartment result: "להזמנה" (instead
   of only "צפייה ופרטים"), to the same hotel - a booking.com result already
   goes through CJ (_wrap_booking_com_hotel_links, #147). Only a real CJ
   link is labelled "קישור שותף", linking to the affiliate-disclosure page.
2. Results grouped by the place agreed in the route, with its nights - not
   the country: "ליסבון · 4 לילות · 21.03.2027 – 25.03.2027".
   lodging.details.location_segments (a text extraction) was empty there,
   so the stops now come from the APPROVED itinerary's own days (base, else
   city): one stop keeps the single search (its query already knows the
   area / ski resort) and only takes its heading from the route; several
   stops -> one search per stop with its own dates.

Offline (search_hotels stubbed - no paid call). Run:
python3 tools/qa_lodging_route_groups.py
"""
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")
os.environ.setdefault("SCHEDULER_ENABLED", "false")

import database  # noqa: E402
database.init_db()

import public_site  # noqa: E402
import app as app_module  # noqa: E402
from werkzeug.security import generate_password_hash  # noqa: E402

FAILED = []


def check(name, cond):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        FAILED.append(name)


def itinerary(*places):
    return {"text": "...", "days": [{"day": i + 1, "city": p, "base": p} for i, p in enumerate(places)]}


LISBON = {"destinations": "LIS", "departure_date": "2027-03-21", "return_date": "2027-03-25", "adults": 2,
          "_requested_services": ["lodging"], "_approved_itinerary": itinerary("ליסבון", "ליסבון", "ליסבון", "ליסבון", "ליסבון")}
ROUTE = dict(LISBON, _approved_itinerary=itinerary("ליסבון", "ליסבון", "פורטו", "פורטו", "פורטו"))
seg = public_site._lodging_segments_from_itinerary

# --- Segments from the approved itinerary ----------------------------------------------------------------
check("Lisbon, 4 nights in one place -> one stop, 4 nights",
      seg(LISBON) == [{"location": "ליסבון", "date_from": "2027-03-21", "date_to": "2027-03-25", "nights": 4}])
check("two stops -> one segment per stop, each with its own nights and dates",
      seg(ROUTE) == [{"location": "ליסבון", "date_from": "2027-03-21", "date_to": "2027-03-23", "nights": 2},
                     {"location": "פורטו", "date_from": "2027-03-23", "date_to": "2027-03-25", "nights": 2}])
check("a day's base wins over its city (where they sleep)",
      seg(dict(LISBON, _approved_itinerary={"days": [{"city": "סינטרה", "base": "ליסבון"}] * 4}))[0]["location"] == "ליסבון")
check("a night with no place -> [] (never a guess)",
      seg(dict(LISBON, _approved_itinerary={"days": [{"city": "ליסבון"}, {"city": ""}, {"city": "ליסבון"}, {"city": "ליסבון"}]})) == [])
check("fewer days than nights -> []", seg(dict(LISBON, _approved_itinerary=itinerary("ליסבון", "ליסבון"))) == [])
check("no itinerary / no dates -> []",
      seg(dict(LISBON, _approved_itinerary=None)) == [] and seg(dict(LISBON, departure_date=None)) == [])

# --- The search itself -------------------------------------------------------------------------------------
calls = []


def fake_search(query, checkin_date, checkout_date, **kw):
    calls.append((query, checkin_date, checkout_date))
    return {"hotels": [{"name": f"H-{query}-{i}", "link": f"https://www.booking.com/hotel/pt/h{i}.html"} for i in range(3)]}


CJ = "https://www.anrdoezrs.net/click-qa-evergreen"
with patch.object(public_site, "search_hotels", side_effect=fake_search), patch.object(public_site, "CJ_BOOKING_EVERGREEN_LINK", CJ), \
        patch.object(public_site, "_save_trip_answers"):
    a1 = json.loads(json.dumps(LISBON))
    public_site._run_lodging_search(901, a1)
    single_calls = list(calls)
    calls.clear()
    a2 = json.loads(json.dumps(ROUTE))
    public_site._run_lodging_search(902, a2)
    multi_calls = list(calls)
offers1 = a1.get("lodging_offers") or []
check("one stop: still the single search over the whole stay", len(single_calls) == 1 and single_calls[0][1:] == ("2027-03-21", "2027-03-25"))
check("one stop: every result is tagged with the route's place + 4 nights (not the country)",
      offers1 and all(h.get("segment_location") == "ליסבון" and h.get("segment_nights") == 4 for h in offers1))
check("two stops: one search per stop with its own dates",
      [(c[0], c[1], c[2]) for c in multi_calls] == [("ליסבון", "2027-03-21", "2027-03-23"), ("פורטו", "2027-03-23", "2027-03-25")])
check("two stops: results tagged per stop with their nights",
      {(h["segment_location"], h["segment_nights"]) for h in a2["lodging_offers"]} == {("ליסבון", 2), ("פורטו", 2)})
check("booking.com results still go through CJ (#147)", all(h["link"].startswith(CJ + "?") for h in offers1))

# --- The account page --------------------------------------------------------------------------------------
offers1.append({"name": "Hotel Own Site", "link": "https://hotel-own-site.example/book",
                "segment_location": "ליסבון", "segment_dates": "2027-03-21 – 2027-03-25", "segment_nights": 4})
with sqlite3.connect(database.DB_PATH) as conn:
    conn.execute("DELETE FROM members WHERE email='qa-lodging-route@example.com'")
    member_id = conn.execute(
        "INSERT INTO members (full_name,email,password_hash,created_at,status,whatsapp_opt_in,preferred_airports) VALUES(?,?,?,?,?,?,?)",
        ("QA", "qa-lodging-route@example.com", generate_password_hash("x"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
    ).lastrowid
    conn.execute("INSERT INTO trip_requests (member_id, request_name, status, answers_json, created_at) VALUES (?,?,?,?,datetime('now'))",
                 (member_id, "QA Lisbon", "active", json.dumps(dict(LISBON, lodging_offers=offers1), ensure_ascii=False)))
    conn.commit()
client = app_module.app.test_client()
with client.session_transaction() as sess:
    sess["member_id"] = member_id
with patch.object(public_site, "CJ_BOOKING_EVERGREEN_LINK", CJ):
    html = client.get("/account").get_data(as_text=True)
headings = re.findall(r'<h4 class="lodging-results-group-title">([^<]*)</h4>', html)
check("page: one heading - the route's place, its nights and dates", headings == ["ליסבון · 4 לילות · 21.03.2027 – 25.03.2027"])
check("page: no country heading", "פורטוגל ·" not in html)
cards = re.findall(r'<div class="lodging-result-card">(.*?)</div>\s*</div>', html, re.S)
check("page: every result card has a 'להזמנה' booking button", len(cards) == 4 and all("להזמנה" in c for c in cards))
check("page: 'צפייה ופרטים' is gone from the lodging results", not any("צפייה ופרטים" in c for c in cards))
aff = [c for c in cards if CJ in c]
own = [c for c in cards if "hotel-own-site.example" in c]
check("page: a CJ (booking.com) result is labelled 'קישור שותף', linking to the disclosure page",
      len(aff) == 3 and all("קישור שותף" in c and "/affiliate-disclosure" in c and "sponsored" in c for c in aff))
check("page: a non-affiliate result is NOT labelled as an affiliate link",
      len(own) == 1 and "קישור שותף" not in own[0] and "sponsored" not in own[0])

with sqlite3.connect(database.DB_PATH) as conn:
    conn.execute("DELETE FROM members WHERE email='qa-lodging-route@example.com'")
    conn.commit()

print()
print("ALL PASS" if not FAILED else f"{len(FAILED)} FAILED: {FAILED}")
sys.exit(1 if FAILED else 0)
