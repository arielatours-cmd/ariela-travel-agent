from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public_site.py"

text = PUBLIC.read_text(encoding="utf-8")
old = '''def _decorate_availability_note(offer, trip):
    """Never promise group inventory unless the supplier explicitly confirmed it."""
    copy = dict(offer)
    pax = _requested_passenger_count(trip)'''
new = '''def _decorate_availability_note(offer, trip):
    """Never promise group inventory unless the supplier explicitly confirmed it.

    Every personal-card copy also carries the current trip id. Without this,
    alternative/second-result cards can fall back to the shared offer's stored
    booking request and therefore open the right flight with the wrong party size.
    """
    copy = dict(offer)
    copy["booking_trip_id"] = trip.get("id")
    pax = _requested_passenger_count(trip)'''
if old not in text:
    raise RuntimeError("availability decorator anchor not found")
text = text.replace(old, new, 1)
PUBLIC.write_text(text, encoding="utf-8")
print("9.7.136 every personal deal carries current trip id for exact passenger booking")
