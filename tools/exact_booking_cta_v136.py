from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DB = ROOT / "database.py"
CARD = ROOT / "templates" / "_deal_card.html"

# Expose whether Ariella can reconstruct the selected itinerary at booking time.
d = DB.read_text(encoding="utf-8")
anchor = '''            "booking_request_post_data": flight.get("booking_request_post_data"),
            "booking_supplier_approved": flight.get("booking_supplier_approved"),'''
replacement = '''            "booking_request_post_data": flight.get("booking_request_post_data"),
            # Exact booking CTA is only honest when we have either the provider's
            # captured booking request or the exact Google Flights booking token
            # needed to refresh Booking Options for the selected itinerary.
            "booking_actionable": bool(
                flight.get("booking_request_url") or flight.get("booking_token")
            ),
            "booking_supplier_approved": flight.get("booking_supplier_approved"),'''
if anchor in d and '"booking_actionable": bool(' not in d:
    d = d.replace(anchor, replacement, 1)
DB.write_text(d, encoding="utf-8")

# Do not label a generic airline-homepage fallback as "Go to booking".
c = CARD.read_text(encoding="utf-8")
variants = [
    '''{% if offer.booking_url %}<a href="{{ url_for('site.book_offer', offer_id=offer.id) }}" target="_blank" rel="noopener noreferrer">{{ 'Go to booking' if lang=='en' else 'למעבר להזמנה' }}</a>{% endif %}''',
    '''{% if offer.booking_url %}<a href="{{ url_for('site.book_offer', offer_id=offer.id, trip_id=offer.booking_trip_id) if offer.booking_trip_id else url_for('site.book_offer', offer_id=offer.id) }}" target="_blank" rel="noopener noreferrer">{{ 'Go to booking' if lang=='en' else 'למעבר להזמנה' }}</a>{% endif %}''',
]
new = '''{% if offer.booking_actionable %}<a href="{{ url_for('site.book_offer', offer_id=offer.id, trip_id=offer.booking_trip_id) if offer.booking_trip_id else url_for('site.book_offer', offer_id=offer.id) }}" target="_blank" rel="noopener noreferrer">{{ 'Go to booking' if lang=='en' else 'למעבר להזמנה' }}</a>{% else %}<span class="booking-link-unavailable">{{ 'Exact booking link unavailable for this older deal' if lang=='en' else 'קישור הזמנה מדויק אינו זמין לדיל הישן הזה' }}</span>{% endif %}'''
for old in variants:
    if old in c:
        c = c.replace(old, new, 1)
        break
CARD.write_text(c, encoding="utf-8")

print("9.7.136 exact booking CTA active: no generic supplier-homepage handoff")
