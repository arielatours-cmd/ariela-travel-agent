"""QA for a live bug the business owner found herself (15.10.2026,
production): a deal card recommended "Kiwi.com" as the booking supplier,
but clicking "למעבר להזמנה" (go to booking) silently landed on Israir's
homepage - no explanation of why the destination differed from what the
card promised. Her own words: "ניסיתי להיכנס להזמנה של קיווי. זה מכניס
אותי לאתר של ישראייר. לא להזמנה עצמה." (I tried to go to the Kiwi
booking. It takes me to the Israir site. Not to the booking itself.)

Root cause in booker.py's resolve_booking_target: Kiwi.com is an OTA, not
an airline, so it has no entry in OFFICIAL_AIRLINE_BOOKING_FALLBACKS. The
fallback loop over airline_names (recommended, then the operating
airline, ...) skips straight past "Kiwi.com" with no match and lands on
the next name - the actual operating airline (Israir), which DOES have a
homepage fallback - with no indication to the customer that the
destination silently changed from the card's own recommended supplier.

Fixed: when the matched fallback airline differs from the originally
recommended supplier, the note now explicitly names BOTH - the
recommended supplier that couldn't be used, and the airline whose site
Ariella opened instead - exactly what the business owner asked for
("say so honestly instead of promising 'go to booking'").

No SERPAPI_API_KEY is required for this test: resolve_booking_target only
attempts a live booking_options lookup when an API key is configured, so
leaving it unset deterministically exercises the OFFICIAL_AIRLINE_BOOKING_FALLBACKS
fallback path being fixed here - no network mocking needed.

Run: python3 tools/qa_booking_fallback_names_both_suppliers.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.pop("SERPAPI_API_KEY", None)
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import config
config.SERPAPI_API_KEY = ""
import booker

FAILED = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


# --- 1. The exact live bug: Kiwi.com recommended, Israir is the operating
#        airline and the only one with an official fallback URL ---
offer_kiwi = {
    "booking_supplier": "Kiwi.com", "airline": "Israir",
    "departure_code": "TLV", "arrival_code": "BER",
    "outbound_date": "2027-02-08", "return_date": "2027-02-11",
}
target = booker.resolve_booking_target(offer_kiwi, adults=1, children=0, personal=True)
check("still lands on the operating airline's site when the recommended OTA has no booking page",
      target.url == "https://www.israir.co.il/")
check("mode is the official-airline fallback (never claimed exact)",
      target.mode == "official_airline_fallback" and target.exact is False)
check("the note names the recommended supplier that could not be used (Kiwi.com)",
      "Kiwi.com" in (target.note or ""))
check("the note names the actual airline site that was opened instead (Israir)",
      "Israir" in (target.note or ""))
check("the note tells the customer to enter the flight/passenger details themselves",
      "להזין" in (target.note or ""))

# --- 2. Regression guard: when the recommended supplier IS the fallback
#        airline itself (no OTA substitution happened), the note stays the
#        original generic wording - never falsely claims a substitution ---
offer_direct = {
    "booking_supplier": "Lufthansa", "airline": "Lufthansa",
    "departure_code": "TLV", "arrival_code": "FRA",
    "outbound_date": "2027-03-01", "return_date": "2027-03-05",
}
target2 = booker.resolve_booking_target(offer_direct, adults=1, children=0, personal=True)
check("no false 'recommended supplier could not be used' note when they're the same airline",
      "הספק המומלץ" not in (target2.note or ""))
check("still lands on the correct (same) airline's official site",
      target2.url == "https://www.lufthansa.com/")

# --- 3. Regression guard: Bluebird's own note is untouched ---
offer_bluebird = {
    "booking_supplier": "Kiwi.com", "airline": "Bluebird Airways",
    "departure_code": "TLV", "arrival_code": "LCA",
    "outbound_date": "2027-04-01", "return_date": "2027-04-05",
}
target3 = booker.resolve_booking_target(offer_bluebird, adults=1, children=0, personal=True)
check("Bluebird's own note wording is unaffected by this fix",
      target3.note == "אריאלה פתחה עבורכם את מסך ההזמנה של בלו בירד.")

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL BOOKING-FALLBACK-NAMES-BOTH-SUPPLIERS TESTS PASSED")
