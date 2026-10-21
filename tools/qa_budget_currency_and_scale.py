"""QA for the business owner's live-testing report on vacation 259 (20.10.2026,
relayed by Shlomo, after the rematch button/48h fixes went live): "the flights
are shown, but they're all over the budget I asked for, and the card doesn't
say so" ("הן כולן מעל התקציב שביקשתי ולא כתוב עליהן הערה כזו").

Root cause, confirmed by reading the code (no production DB access): EVERY
budget comparison in public_site.py (6 separate call sites - _offer_within_
budget, _over_budget_alternatives, _business_match_details,
_open_customer_point_details x2, _objective_match_details) compared
offer.price_ils DIRECTLY against answers["budget_amount"] (an amount in
whatever currency the customer actually stated - see ariella_chat_clean.py's
budget_per_person state) - with NO currency conversion at all. Compounding
this, ariella_start_flight_search dropped the currency entirely when
building the trip's answers dict (only budget_amount was written, never the
currency).

Fixed (items 1-2 of Shlomo's explicit split, 20.10): a single centralized
_budget_ceiling_ils(trip) - converts the stated budget to ILS via a fixed
exchange-rate table and applies the existing 10% tolerance - used by all 6
former ad-hoc comparisons. ariella_start_flight_search now also saves
answers["budget_currency"] (previously discarded entirely).

Deliberately NOT scaled by party size (adults+children) - whether
offer.price_ils represents the TOTAL price for the whole party or a
per-person price needs verifying against a real SerpApi/Google Flights
payload first (item 3, Shaked's qa/e2e_vacation_card_conditions.py); per
Shlomo's explicit split, that verification and its fix are his to do once
confirmed with the business owner, not part of this PR.

Run: python3 tools/qa_budget_currency_and_scale.py
"""
import os
import sys
import sqlite3
import json
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import database
database.init_db()
import public_site

FAILED = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


TEST_MEMBER_ID = 999501


def make_member():
    with sqlite3.connect(database.DB_PATH) as conn:
        conn.execute("DELETE FROM members WHERE id=? OR email=?", (TEST_MEMBER_ID, "qa-budget-currency@example.com"))
        conn.execute(
            "INSERT INTO members (id, full_name,email,phone,password_hash,created_at,status,whatsapp_opt_in,preferred_airports) "
            "VALUES(?,?,?,?,?,datetime('now'),'active',0,'[]')",
            (TEST_MEMBER_ID, "QA Budget Currency", "qa-budget-currency@example.com", "0500000002", "x"),
        )
        conn.commit()


def make_trip(trip_id, answers):
    with sqlite3.connect(database.DB_PATH) as conn:
        conn.execute("DELETE FROM trip_requests WHERE id=?", (trip_id,))
        conn.execute(
            "INSERT INTO trip_requests (id, member_id, request_name, travel_window, status, answers_json, created_at) "
            "VALUES(?,?,?,?,?,?,datetime('now'))",
            (trip_id, TEST_MEMBER_ID, "ליסבון", "2027-03-21 - 2027-03-25", "active", json.dumps(answers, ensure_ascii=False)),
        )
        conn.commit()
    with sqlite3.connect(database.DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        return public_site._trip_dict(conn.execute("SELECT * FROM trip_requests WHERE id=?", (trip_id,)).fetchone())


def make_offer(price_ils, stops=0):
    return {
        "id": 1, "price_ils": price_ils, "stops": stops,
        "departure_code": "TLV", "arrival_code": "LIS",
        "outbound_date": "2027-03-21", "return_date": "2027-03-25",
        "departure_time": "08:00", "arrival_time": "12:00",
        "return_departure_time": "14:00", "return_arrival_time": "18:00",
        "baggage": {"carry_on_8kg": {"included": True}, "checked_bag_23kg": {"included": True}},
        "score": 70,
        "last_seen_at": datetime.now(timezone.utc).isoformat(),
        "observed_at": datetime.now(timezone.utc).isoformat(),
    }


BASE_ANSWERS = {
    "destinations": "LIS", "origin_airports": ["TLV"],
    "date_mode": "exact", "departure_date": "2027-03-21", "return_date": "2027-03-25",
    "duration_days": 5, "deal_priorities": [], "vacation_type": "standard",
    "adults": 2, "children": 0,
}


def cleanup():
    with sqlite3.connect(database.DB_PATH) as conn:
        conn.execute("DELETE FROM trip_requests WHERE member_id=?", (TEST_MEMBER_ID,))
        conn.execute("DELETE FROM members WHERE id=?", (TEST_MEMBER_ID,))
        conn.commit()


make_member()

# =====================================================================
# 1. Direct unit tests of _budget_ceiling_ils: currency conversion only
#    (no party scaling - see module docstring).
# =====================================================================
trip_eur = make_trip(880001, dict(BASE_ANSWERS, budget_mode="limited", budget_amount=300, budget_currency="EUR"))
ceiling_eur = public_site._budget_ceiling_ils(trip_eur)
check("EUR 300 converts to ILS (not compared as a raw '300' against an ILS price)",
      ceiling_eur is not None and ceiling_eur > 300)
expected_eur = 300 * public_site._BUDGET_FX_TO_ILS["EUR"] * 1.10
check("the EUR ceiling matches amount * fx_rate * 1.10 exactly",
      abs(ceiling_eur - expected_eur) < 0.01)

trip_ils = make_trip(880002, dict(BASE_ANSWERS, budget_mode="limited", budget_amount=300, budget_currency="ILS"))
ceiling_ils = public_site._budget_ceiling_ils(trip_ils)
check("regression: an ILS budget is unaffected by the fx table (rate 1.0)",
      ceiling_ils is not None and abs(ceiling_ils - 300 * 1.10) < 0.01)

trip_usd = make_trip(880003, dict(BASE_ANSWERS, budget_mode="limited", budget_amount=100, budget_currency="USD"))
ceiling_usd = public_site._budget_ceiling_ils(trip_usd)
check("USD budget converts correctly via the fx table",
      ceiling_usd is not None and abs(ceiling_usd - 100 * public_site._BUDGET_FX_TO_ILS["USD"] * 1.10) < 0.01)

trip_unlimited = make_trip(880004, dict(BASE_ANSWERS, budget_mode="unlimited", budget_amount=None))
check("regression: an unlimited budget still returns None (no ceiling at all)",
      public_site._budget_ceiling_ils(trip_unlimited) is None)

trip_no_currency = make_trip(880005, {**BASE_ANSWERS, "budget_mode": "limited", "budget_amount": 300})
ceiling_default = public_site._budget_ceiling_ils(trip_no_currency)
check("regression: an older trip saved before this fix (no budget_currency key at all) "
      "defaults to ILS, never crashes",
      ceiling_default is not None and abs(ceiling_default - 300 * 1.10) < 0.01)

# =====================================================================
# 2. End-to-end: vacation 259's actual reported symptom - a EUR-budget trip
#    whose real total ILS price IS genuinely over budget must be excluded
#    from tier 1 (_customer_deal_choices) and correctly marked "תקציב" via
#    a later tier, never silently shown as a full, unmarked match.
# =====================================================================
trip_259 = make_trip(880006, dict(BASE_ANSWERS, budget_mode="limited", budget_amount=150, budget_currency="EUR"))
# 150 EUR * ~4.0 ILS/EUR * 1.10 tolerance =~ 660 ILS ceiling (no party scaling -
# see module docstring). An offer priced well above that (2800 ILS) is over.
over_budget_offer = make_offer(2800)

check("tier 1 (exact match) correctly EXCLUDES a genuinely over-budget offer "
      "once currency/scale are both accounted for",
      public_site._customer_deal_choices([over_budget_offer], trip_259, limit=5) == [])

alternatives = public_site._over_budget_alternatives([over_budget_offer], trip_259, limit=5)
check("the over-budget tier picks up the same offer and labels it with the "
      "'תקציב' reason on the card (request_missed_reasons)",
      len(alternatives) == 1 and "תקציב" in alternatives[0].get("request_missed_reasons", []))
check("the over-budget tier's offer also carries a customer_choice_label - "
      "the template only renders request_missed_reasons alongside this label",
      bool(alternatives[0].get("customer_choice_label_he")))

# =====================================================================
# 3. Regression: a genuinely within-budget offer (same currency correction
#    applied) still passes tier 1 as a full, unmarked match - this fix must
#    never turn an affordable trip into a false "over budget".
# =====================================================================
within_budget_offer = make_offer(500)
matches = public_site._customer_deal_choices([within_budget_offer], trip_259, limit=5)
check("regression: an offer genuinely within the converted/scaled budget still "
      "passes tier 1 as a full match",
      len(matches) == 1 and not matches[0].get("request_missed_reasons"))

# =====================================================================
# 4. Regression: _objective_match_details and _business_match_details also
#    use the corrected ceiling (not just the two tiers exercised above).
# =====================================================================
_, possible, matched, missed = public_site._objective_match_details(over_budget_offer, trip_259)
check("_objective_match_details reports the over-budget offer as missing the "
      "budget condition (currency/scale corrected)",
      "תקציב" in missed)
_, possible2, matched2, missed2 = public_site._objective_match_details(within_budget_offer, trip_259)
check("regression: _objective_match_details reports the within-budget offer as "
      "meeting the budget condition",
      "תקציב" not in missed2 and "תקציב" in matched2)

cleanup()

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL BUDGET-CURRENCY-AND-SCALE TESTS PASSED")
