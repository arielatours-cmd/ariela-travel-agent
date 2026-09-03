from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public_site.py"

text = PUBLIC.read_text(encoding="utf-8")

helper = r'''
def _personal_offer_visual_signature(offer):
    """Signature for what the customer actually sees as one flight deal.

    Ignore DB ids, scan ids, booking tokens and refresh metadata. If route, dates,
    flight times, airlines and stop pattern are the same, it is the same displayed
    itinerary and must appear only once in a personal vacation.
    """
    return (
        str(offer.get("departure_code") or "").upper(),
        str(offer.get("arrival_code") or "").upper(),
        str(offer.get("outbound_date") or ""),
        str(offer.get("return_date") or ""),
        str(offer.get("airline") or "").strip().casefold(),
        str(offer.get("departure_time") or ""),
        str(offer.get("arrival_time") or ""),
        str(offer.get("return_airline") or offer.get("airline") or "").strip().casefold(),
        str(offer.get("return_departure_time") or ""),
        str(offer.get("return_arrival_time") or ""),
        offer.get("stops"),
        offer.get("return_stops"),
    )


def _dedupe_personal_offer_lists(trip):
    seen = set()

    def clean(rows):
        out = []
        for offer in rows or []:
            sig = _personal_offer_visual_signature(offer)
            if sig in seen:
                continue
            seen.add(sig)
            out.append(offer)
        return out

    trip["offers"] = clean(trip.get("offers"))
    trip["alternative_offers"] = clean(trip.get("alternative_offers"))
    if "over_budget_offers" in trip:
        trip["over_budget_offers"] = clean(trip.get("over_budget_offers"))
    return trip


'''

if "def _personal_offer_visual_signature" not in text:
    marker = "def _offer_signature(offer):\n"
    if marker not in text:
        raise RuntimeError("personal dedup patch: offer signature anchor not found")
    text = text.replace(marker, helper + marker, 1)

append_marker = "personal_trips.append(trip)"
if "_dedupe_personal_offer_lists(trip)\n            personal_trips.append(trip)" not in text and "_dedupe_personal_offer_lists(trip)\n        personal_trips.append(trip)" not in text:
    count = text.count(append_marker)
    if not count:
        raise RuntimeError("personal dedup patch: account render anchor not found")
    text = text.replace(
        "            personal_trips.append(trip)",
        "            _dedupe_personal_offer_lists(trip)\n            personal_trips.append(trip)",
    )
    text = text.replace(
        "        personal_trips.append(trip)",
        "        _dedupe_personal_offer_lists(trip)\n        personal_trips.append(trip)",
    )

compile(text, str(PUBLIC), "exec")
PUBLIC.write_text(text, encoding="utf-8")
print("9.7.136 personal vacation duplicate-deal guard active")
