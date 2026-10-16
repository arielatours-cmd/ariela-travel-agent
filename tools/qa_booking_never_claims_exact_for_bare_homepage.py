"""QA for the business owner's "deal 2" false-success finding (15.10.2026,
confirmed via Render logs she photographed: ceo/evidence/2026-10-15-render-
booking-job-logs.jpg): booking job at 15:15:30 UTC logged
"mode=personal_exact_party_regenerated exact=True" - a fresh booking_token
WAS obtained and SerpApi's booking_options DID return a structurally valid
entry - but she landed on the supplier's bare general page, not a specific
booking screen. The waiting page only ever shows "success" when exact=True,
so this was a false positive at the source, not a frontend display bug.

Fixed (per Shlomo's explicit request, a defense that doesn't require
knowing exactly why SerpApi returned a bare link): a URL with no query
string, no POST fields, and an empty/root-only path can never be claimed
as an exact, completed booking - regardless of which branch produced it.
When this happens, resolve_booking_target now falls through to its
existing (already correctly exact=False) fallback chain instead.

Run: python3 tools/qa_booking_never_claims_exact_for_bare_homepage.py
"""
import os
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.pop("SERPAPI_API_KEY", None)
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import config
config.SERPAPI_API_KEY = "qa-fake-key"
import booker

FAILED = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


# --- 1. Unit: the bare-homepage detector itself ---
check("a bare domain with no path is a bare homepage",
      booker._looks_like_bare_homepage("https://www.kiwi.com", []))
check("a bare domain with only '/' is a bare homepage",
      booker._looks_like_bare_homepage("https://www.kiwi.com/", []))
check("a URL with a real query string is never a bare homepage",
      not booker._looks_like_bare_homepage("https://www.kiwi.com/booking?token=abc123", []))
check("a URL with POST fields is never a bare homepage (even with a root path)",
      not booker._looks_like_bare_homepage("https://www.kiwi.com/", [("token", "abc123")]))
check("a URL with a real sub-path is never a bare homepage",
      not booker._looks_like_bare_homepage("https://www.kiwi.com/booking/confirm", []))
check("no URL at all is never flagged (nothing to claim exact on anyway)",
      not booker._looks_like_bare_homepage(None, []))

# --- 2. End to end: the exact live scenario - a fresh personal regeneration
#        that resolves to a booking_options entry whose URL is just the
#        supplier's bare homepage must NEVER come back exact=True ---
def fake_serpapi_response(url, params=None, timeout=None):
    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            if params and params.get("booking_token"):
                return {
                    "booking_options": [
                        {
                            "together": {
                                "book_with": "Kiwi.com",
                                "price": 850,
                                "booking_request": {"url": "https://www.kiwi.com/", "post_data": None},
                            }
                        }
                    ]
                }
            # The outbound/return search calls that produce a departure_token
            # and booking_token in the first place.
            return {
                "best_flights": [{
                    "flights": [{"departure_airport": {"time": "2027-02-08 10:00"}, "airline": "Kiwi.com"}],
                    "layovers": [],
                    "departure_token": "dep-token-abc",
                    "booking_token": "fresh-token-xyz",
                }],
                "other_flights": [],
            }
    return _Resp()


offer = {
    "booking_supplier": "Kiwi.com", "airline": "Israir",
    "departure_code": "TLV", "arrival_code": "BER",
    "outbound_date": "2027-02-08", "return_date": "2027-02-11",
    "departure_time": "2027-02-08 10:00", "airline": "Kiwi.com",
}
with patch("requests.get", side_effect=fake_serpapi_response):
    target = booker.resolve_booking_target(offer, adults=1, children=0, personal=True)

check("a bare-homepage booking_options result is never claimed as exact",
      target.exact is not True)
check("it still falls through to a real (non-exact) fallback target, never leaving the customer with nothing",
      bool(target.url))

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL BOOKING-NEVER-CLAIMS-EXACT-FOR-BARE-HOMEPAGE TESTS PASSED")
