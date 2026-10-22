"""Offline regression tests for din_agent.py (Din's runtime arm).

Run: python3 legal/tests/test_din_agent.py
No network: the airline crawl is stubbed.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))

import din_agent  # noqa: E402

FAILS: list[str] = []


def check(name, got, want):
    if got != want:
        FAILS.append(f"{name}: got {got!r}, want {want!r}")


def offer(price=500, direct=True, fares=None, airline="etihad"):
    return {"flight": {"airline": airline, "price": price,
                       "booking_supplier_is_direct": direct,
                       "fare_options": fares or []}}


def stub_policy(text):
    din_agent._CACHE.clear()
    din_agent._fetch_policy_text = lambda url: (text, [url])


LAW = "Israeli Consumer Protection Law"

# --- consumer protection (DEAL-1) ---
cp = din_agent._classify_consumer_protection
check("explicit mention", cp(f"Notice under the {LAW}: you may cancel within 14 days.")["status"], "applies")
check("hebrew mention", cp("הודעה לפי חוק הגנת הצרכן: ניתן לבטל.")["status"], "applies")
check("negated", cp(f"The {LAW} does not apply to tickets bought abroad.")["status"], "check")
check("hebrew negated", cp("חוק הגנת הצרכן אינו חל על כרטיסים אלה.")["status"], "check")
check("conditional", cp(f"The {LAW} applies only to tickets purchased in Israel.")["status"], "check")
check("no mention", cp("Refunds are available on some fares.")["status"], "check")

stub_policy(f"Notice under the {LAW}: you may cancel.")
check("agency booking keeps check", din_agent.enrich_offer_legal_terms(offer(direct=False))["consumer_protection"]["status"], "check")
check("unknown supplier keeps check", din_agent.enrich_offer_legal_terms(offer(direct=None))["consumer_protection"]["status"], "check")
check("direct booking applies", din_agent.enrich_offer_legal_terms(offer(direct=True))["consumer_protection"]["status"], "applies")
check("generic homepage keeps check", din_agent.enrich_offer_legal_terms(offer(airline="lufthansa"))["consumer_protection"]["status"], "check")

# --- change / cancel (DEAL-2) ---
cc = lambda t: din_agent._classify_change_cancel(t, exact_fare=True)["status"]
check("no full refund", cc("No full refund"), "check")
check("no change fee", cc("No change fee"), "check")
check("24h free cancellation", cc("Free cancellation within 24 hours"), "check")
check("non refundable", cc("Non-refundable"), "none")
check("free change", cc("Free changes"), "free")
check("change fee", cc("Change fee applies"), "paid")

stub_policy("")
fares = [{"name": "Basic", "price_ils": 500, "features": ["Carry-on bag"]},
         {"name": "Flex", "price_ils": 700, "features": ["Free changes", "Full refund"]}]
check("flex rules do not leak onto basic price",
      din_agent.enrich_offer_legal_terms(offer(price=500, fares=fares))["change_cancel"]["status"], "check")
check("flex price uses flex rules",
      din_agent.enrich_offer_legal_terms(offer(price=700, fares=fares))["change_cancel"]["status"], "free")
check("agency booking: fare rules ignored",
      din_agent.enrich_offer_legal_terms(offer(price=700, fares=fares, direct=False))["change_cancel"]["status"], "check")

if FAILS:
    print("FAIL\n" + "\n".join(FAILS))
    sys.exit(1)
print("OK - all Din checks passed")
