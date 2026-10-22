"""QA for a silent lodging-revenue bug Shaked found live (22.10.2026,
relayed by Shlomo): no lodging commission was ever being recorded, for
three separate reasons, all fixed here:

1. _cj_booking_wrap (public_site.py) was defined but never called from
   anywhere - the Google Hotels result cards' own "view and book" button
   (hotel.get('link') in templates/account.html) sent the customer
   straight to whatever supplier SerpApi's google_hotels engine returned
   (very often booking.com), completely uncredited. Fixed:
   _wrap_booking_com_hotel_links wraps only the results that actually
   point at booking.com (never another supplier - there is no approved CJ
   program for those) through _cj_booking_wrap(url, sid=f"trip{id}"),
   called from _run_lodging_search before persisting lodging_offers.

2. The dedicated lodging-partner card (_lodging_partner_cards /
   _lodging_partner_url / the /trip/<id>/book-lodging/<code> route) only
   ever activated when LODGING_AFFILIATE_LINK was set - a generic CJ
   advertiser link that defaults its display name to Agoda
   (LODGING_PARTNER_NAME), which CJ has never actually approved for this
   account. The one lodging partner approved in CJ today is Booking.com
   MEA, via CJ_BOOKING_EVERGREEN_LINK. Fixed: the card, its URL builder,
   and the booking route all fall back to a Booking.com search URL
   wrapped via _cj_booking_wrap whenever LODGING_AFFILIATE_LINK itself
   isn't configured, instead of showing nothing (or, if ever misconfigured
   together with CJ_BOOKING_EVERGREEN_LINK, crediting the wrong supplier
   name).

3. (Business owner decision, 22.10.2026, relayed by Shlomo, bundled into
   this same fix) - the lodging tab's own "חיפוש מחדש" (search again)
   button is removed from templates/account.html entirely. Only that one
   button: the car tab's identical-looking button (a different form,
   posting to site.search_car) is untouched, and the "no results yet"
   first-search button (site.search_lodging, shown only when
   lodging_offers is empty) is untouched too - the /search-lodging route
   itself still exists and is still reachable from that button and from
   the automatic post-flight-continuation trigger.

Run: python3 tools/qa_lodging_affiliate_booking_cj.py
"""
import os
import sys
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import database
database.init_db()

import public_site
import app as app_module
from datetime import datetime, timezone
from werkzeug.security import generate_password_hash
import sqlite3

DB = database.DB_PATH
client = app_module.app.test_client()

FAILED = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


def _make_member(email):
    with sqlite3.connect(DB) as conn:
        conn.execute("DELETE FROM members WHERE email=?", (email,))
        conn.commit()
        cur = conn.execute(
            "INSERT INTO members (full_name,email,password_hash,created_at,status,whatsapp_opt_in,preferred_airports) "
            "VALUES(?,?,?,?,?,?,?)",
            ("QA Lodging CJ", email, generate_password_hash("Test1234!"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
        )
        return cur.lastrowid


def _make_trip(member_id, answers):
    import json
    with sqlite3.connect(DB) as conn:
        cur = conn.execute(
            "INSERT INTO trip_requests (member_id, request_name, status, answers_json, created_at) "
            "VALUES (?,?,?,?,datetime('now'))",
            (member_id, "QA Lodging CJ Trip", "active", json.dumps(answers, ensure_ascii=False)),
        )
        conn.commit()
        return int(cur.lastrowid)


BOOKING_LINK = "https://www.booking.com/hotel/bg/example.he.html?aid=123"
BOOKING_SUBDOMAIN_LINK = "https://secure.booking.com/hotel/bg/example.he.html"
HOTELS_COM_LINK = "https://www.hotels.com/ho123456/example-hotel"
FAKE_BOOKING_COM_LINK = "https://not-booking.com/hotel/example"

# =====================================================================
# 1. _is_booking_com_url: a real booking.com host (incl. subdomain), and
#    nothing that merely contains "booking.com" somewhere in the URL.
# =====================================================================
check("real booking.com URL recognized", public_site._is_booking_com_url(BOOKING_LINK))
check("booking.com subdomain recognized", public_site._is_booking_com_url(BOOKING_SUBDOMAIN_LINK))
check("a different OTA is not recognized as booking.com", not public_site._is_booking_com_url(HOTELS_COM_LINK))
check("a host that merely CONTAINS 'booking.com' is not fooled", not public_site._is_booking_com_url(FAKE_BOOKING_COM_LINK))
check("empty/None link never crashes and is not booking.com", not public_site._is_booking_com_url(None) and not public_site._is_booking_com_url(""))

# =====================================================================
# 2. _wrap_booking_com_hotel_links: only the booking.com result gets
#    wrapped through CJ; every other supplier's link is left untouched.
# =====================================================================
with patch.object(public_site, "CJ_BOOKING_EVERGREEN_LINK", "https://www.anrdoezrs.net/click-qa-evergreen"):
    hotels = [
        {"name": "Booking Hotel", "link": BOOKING_LINK},
        {"name": "Other OTA Hotel", "link": HOTELS_COM_LINK},
        {"name": "No Link Hotel"},
    ]
    wrapped = public_site._wrap_booking_com_hotel_links(hotels, 555001)
booking_wrapped_url = wrapped[0]["link"]
parsed = urlsplit(booking_wrapped_url)
qs = parse_qs(parsed.query)
check("the booking.com result's link is now routed through the CJ evergreen link",
      booking_wrapped_url.startswith("https://www.anrdoezrs.net/click-qa-evergreen"))
check("the original booking.com destination URL is preserved as the CJ ?url= param",
      qs.get("url") == [BOOKING_LINK])
check("the sid ties the click back to this exact trip",
      qs.get("sid") == ["trip555001"])
check("a different OTA's link is left completely untouched (no approved program for it)",
      wrapped[1]["link"] == HOTELS_COM_LINK)
check("a hotel with no link at all is not given one",
      "link" not in wrapped[2])

# --- CJ_BOOKING_EVERGREEN_LINK not configured yet: never invent a broken
#     wrap - the booking.com link is left as a plain (uncredited) URL,
#     exactly as _cj_booking_wrap's own documented fallback behaves. ---
with patch.object(public_site, "CJ_BOOKING_EVERGREEN_LINK", ""):
    hotels_noevergreen = [{"name": "Booking Hotel", "link": BOOKING_LINK}]
    wrapped_noevergreen = public_site._wrap_booking_com_hotel_links(hotels_noevergreen, 555002)
check("without CJ_BOOKING_EVERGREEN_LINK configured, the booking.com link is left as the plain URL",
      wrapped_noevergreen[0]["link"] == BOOKING_LINK)

# =====================================================================
# 3. Full integration: _run_lodging_search persists wrapped lodging_offers.
# =====================================================================
def _fake_search_hotels(query, checkin_date, checkout_date, adults=1, children=0, children_ages=None, rooms=1, max_price=None, vacation_rentals=False, min_hotel_class=None):
    return {"hotels": [
        {"name": "Booking Hotel", "link": BOOKING_LINK},
        {"name": "Other OTA Hotel", "link": HOTELS_COM_LINK},
    ]}


answers_search = {
    "origin_airports": ["TLV"], "destinations": "SOF",
    "departure_date": "2027-02-10", "return_date": "2027-02-17", "adults": 2,
}
with patch.object(public_site, "CJ_BOOKING_EVERGREEN_LINK", "https://www.anrdoezrs.net/click-qa-evergreen"), \
     patch.object(public_site, "search_hotels", side_effect=_fake_search_hotels):
    public_site._run_lodging_search(555003, answers_search)
offers = answers_search.get("lodging_offers") or []
offer_by_name = {o["name"]: o for o in offers}
check("end-to-end: the Google Hotels booking.com result is wrapped via CJ in lodging_offers",
      offer_by_name.get("Booking Hotel", {}).get("link", "").startswith("https://www.anrdoezrs.net/click-qa-evergreen"))
check("end-to-end: the sid in the persisted offer ties back to this trip",
      "sid=trip555003" in offer_by_name.get("Booking Hotel", {}).get("link", ""))
check("end-to-end: a non-booking.com Google Hotels result is left untouched",
      offer_by_name.get("Other OTA Hotel", {}).get("link") == HOTELS_COM_LINK)

# =====================================================================
# 4. _lodging_partner_cards: falls back to a Booking.com/CJ card when
#    LODGING_AFFILIATE_LINK (Agoda, unapproved) is not configured.
# =====================================================================
answers_cards = {"destinations": "SOF", "_requested_services": ["lodging"], "adults": 2}
with patch.object(public_site, "LODGING_AFFILIATE_LINK", ""), \
     patch.object(public_site, "CJ_BOOKING_EVERGREEN_LINK", ""):
    check("neither LODGING_AFFILIATE_LINK nor CJ_BOOKING_EVERGREEN_LINK set -> no lodging partner card",
          public_site._lodging_partner_cards(555004, answers_cards) == [])

with patch.object(public_site, "LODGING_AFFILIATE_LINK", ""), \
     patch.object(public_site, "CJ_BOOKING_EVERGREEN_LINK", "https://www.anrdoezrs.net/click-qa-evergreen"):
    cards_cj_only = public_site._lodging_partner_cards(555005, answers_cards)
check("CJ_BOOKING_EVERGREEN_LINK alone (today's real prod config) produces a card",
      len(cards_cj_only) == 1)
check("the fallback card is credited to Booking.com, never the unapproved Agoda default",
      cards_cj_only[0]["supplier"] == "Booking.com")

with patch.object(public_site, "LODGING_AFFILIATE_LINK", "https://www.dpbolvw.net/click-qa-agoda"), \
     patch.object(public_site, "LODGING_PARTNER_NAME", "Agoda"), \
     patch.object(public_site, "CJ_BOOKING_EVERGREEN_LINK", ""):
    cards_affiliate_only = public_site._lodging_partner_cards(555006, answers_cards)
check("regression: LODGING_AFFILIATE_LINK alone still works exactly as before, named by LODGING_PARTNER_NAME",
      len(cards_affiliate_only) == 1 and cards_affiliate_only[0]["supplier"] == "Agoda")

# =====================================================================
# 5. _lodging_partner_url: the fallback URL is a real Booking.com search,
#    wrapped via CJ; the pre-existing LODGING_AFFILIATE_LINK path is
#    unchanged when that link is configured.
# =====================================================================
answers_url = {"departure_date": "2027-03-01", "return_date": "2027-03-08", "adults": 2, "children": 1, "lodging_rooms": 1}
with patch.object(public_site, "LODGING_AFFILIATE_LINK", ""), \
     patch.object(public_site, "CJ_BOOKING_EVERGREEN_LINK", "https://www.anrdoezrs.net/click-qa-evergreen"):
    url_fallback = public_site._lodging_partner_url(answers_url, "SOF", 555007)
check("fallback URL goes out through the CJ evergreen link",
      url_fallback.startswith("https://www.anrdoezrs.net/click-qa-evergreen"))
inner_url = parse_qs(urlsplit(url_fallback).query).get("url", [""])[0]
check("the wrapped destination is a real booking.com search URL",
      inner_url.startswith("https://www.booking.com/searchresults.html"))
inner_qs = parse_qs(urlsplit(inner_url).query)
check("the booking.com search URL carries the real dates and party size",
      inner_qs.get("checkin") == ["2027-03-01"] and inner_qs.get("checkout") == ["2027-03-08"]
      and inner_qs.get("group_adults") == ["2"] and inner_qs.get("group_children") == ["1"])

with patch.object(public_site, "LODGING_AFFILIATE_LINK", "https://www.dpbolvw.net/click-qa-agoda"):
    url_affiliate = public_site._lodging_partner_url(answers_url, "SOF", 555008)
check("regression: with LODGING_AFFILIATE_LINK configured, the URL still goes out through it directly",
      url_affiliate.startswith("https://www.dpbolvw.net/click-qa-agoda"))

# =====================================================================
# 6. Full route integration: GET /trip/<id>/book-lodging/<code> actually
#    redirects to the Booking.com/CJ URL (not blocked, not Agoda) when
#    only CJ_BOOKING_EVERGREEN_LINK is configured, and records the click
#    with the correct supplier.
# =====================================================================
member_id = _make_member("qa-lodging-cj-route@example.com")
trip_id = _make_trip(member_id, {
    "destinations": "SOF", "departure_date": "2027-04-01", "return_date": "2027-04-08", "adults": 2,
})
with client.session_transaction() as sess:
    sess["member_id"] = member_id

with patch.object(public_site, "LODGING_AFFILIATE_LINK", ""), \
     patch.object(public_site, "CJ_BOOKING_EVERGREEN_LINK", "https://www.anrdoezrs.net/click-qa-evergreen"):
    resp = client.get(f"/trip/{trip_id}/book-lodging/SOF", follow_redirects=False)
check("the booking route redirects (not blocked) when only CJ_BOOKING_EVERGREEN_LINK is set",
      resp.status_code in (301, 302) and resp.location
      and resp.location.startswith("https://www.anrdoezrs.net/click-qa-evergreen"))
with sqlite3.connect(DB) as conn:
    conn.row_factory = sqlite3.Row
    click_row = conn.execute(
        "SELECT supplier, affiliate_network, booking_url FROM booking_clicks WHERE member_id=? AND destination_code='SOF' ORDER BY id DESC LIMIT 1",
        (member_id,),
    ).fetchone()
check("the recorded click is credited to Booking.com, not the unapproved Agoda default",
      click_row is not None and click_row["supplier"] == "Booking.com")
check("the recorded click is attributed to the cj affiliate network",
      click_row is not None and click_row["affiliate_network"] == "cj")

with patch.object(public_site, "LODGING_AFFILIATE_LINK", ""), \
     patch.object(public_site, "CJ_BOOKING_EVERGREEN_LINK", ""):
    resp_blocked = client.get(f"/trip/{trip_id}/book-lodging/SOF", follow_redirects=False)
check("regression: with neither link configured, the route still redirects back to the account page (blocked)",
      resp_blocked.status_code in (301, 302) and "/account" in (resp_blocked.location or ""))

with sqlite3.connect(DB) as conn:
    conn.execute("DELETE FROM members WHERE email='qa-lodging-cj-route@example.com'")
    conn.commit()

# =====================================================================
# 7. Business owner decision: the lodging tab's own "search again" button
#    is gone from the template source, the car tab's identical-looking
#    button is untouched, and a live render with real lodging_offers never
#    shows a "search again" button anywhere in the lodging section.
# =====================================================================
account_html_src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates", "account.html"), encoding="utf-8").read()
check("the lodging tab's search-lodging search-again form is gone from the template source",
      'action="{{ url_for(\'site.search_lodging\', trip_id=trip.id) }}" class="lodging-search-again"' not in account_html_src)
check("exactly one 'חיפוש מחדש' button remains in the template source (the car tab's)",
      account_html_src.count("חיפוש מחדש") == 1)
check("the surviving 'search again' button still belongs to the car tab (search_car), untouched",
      "action=\"{{ url_for('site.search_car', trip_id=trip.id) }}\" class=\"lodging-search-again\"" in account_html_src)
check("the lodging tab's first-search button (no results yet) is untouched",
      'action="{{ url_for(\'site.search_lodging\', trip_id=trip.id) }}">' in account_html_src
      and "חיפוש לינה אמיתית" in account_html_src)

member_id2 = _make_member("qa-lodging-button-removed@example.com")
trip_with_offers = _make_trip(member_id2, {
    "destinations": "SOF", "departure_date": "2027-04-01", "return_date": "2027-04-08", "adults": 2,
    "lodging_type": "מלון", "_requested_services": ["lodging"],
    "lodging_offers": [{"name": "Test Hotel", "link": "https://www.booking.com/hotel/bg/test.html"}],
})
with client.session_transaction() as sess:
    sess["member_id"] = member_id2
resp_account = client.get("/account")
html_with_offers = resp_account.get_data(as_text=True)
check("live render with lodging results: no 'search again' button anywhere on the page "
      "(this trip requested no car, so the car tab's own button cannot be the explanation)",
      "חיפוש מחדש" not in html_with_offers)
check("live render with lodging results: the hotel result itself still renders normally",
      "Test Hotel" in html_with_offers)

with sqlite3.connect(DB) as conn:
    conn.execute("DELETE FROM members WHERE email='qa-lodging-button-removed@example.com'")
    conn.commit()

if FAILED:
    print(f"\nFAILED ({len(FAILED)}): {FAILED}")
    sys.exit(1)
print("\nALL LODGING-AFFILIATE-BOOKING-CJ TESTS PASSED")
