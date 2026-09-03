from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public_site.py"
CARD = ROOT / "templates" / "_deal_card.html"
BOOKER = ROOT / "booker.py"


def patch_public_site():
    text = PUBLIC.read_text(encoding="utf-8")

    needle = '        copy = _decorate_availability_note(offer, trip)\n        copy["customer_match_points"] = '
    replacement = '        copy = _decorate_availability_note(offer, trip)\n        copy["booking_trip_id"] = trip.get("id")\n        copy["customer_match_points"] = '
    if needle in text and 'copy["booking_trip_id"] = trip.get("id")' not in text:
        text = text.replace(needle, replacement, 1)

    new_route = '''@site.get("/book/<int:offer_id>")
def book_offer(offer_id):
    """BOOKER: exact personal context first; never fall through to general deals."""
    trip_id = request.args.get("trip_id", type=int)
    personal_trip = None
    if trip_id:
        member_id = session.get("member_id")
        if member_id:
            with _db() as conn:
                row = conn.execute(
                    "SELECT * FROM trip_requests WHERE id=? AND member_id=?",
                    (trip_id, member_id),
                ).fetchone()
            if row:
                personal_trip = _trip_dict(row)

    offer = next(
        (o for o in recent_offers(limit=1500, minimum_score=None)
         if int(o.get("id") or o.get("offer_id") or 0) == offer_id),
        None,
    )

    if not offer:
        if trip_id:
            flash("הקישור להזמנה אינו זמין כרגע. החופשה נשמרה וניתן לנסות דיל אחר.", "warning")
            return redirect(url_for("site.account") + f"#vacation-{trip_id}")
        return redirect(url_for("site.deals"))
    if personal_trip is None and not _offer_is_publicly_bookable(offer):
        return redirect(url_for("site.deals"))

    adults = children = None
    if personal_trip is not None:
        answers = personal_trip.get("answers") or {}
        try:
            adults = max(1, int(answers.get("adults") or 1))
        except (TypeError, ValueError):
            adults = 1
        try:
            children = max(0, int(answers.get("children") or 0))
        except (TypeError, ValueError):
            children = 0

    target = resolve_booking_target(offer, adults=adults, children=children)

    record_booking_click(
        visitor_id=session.get("_ariella_visitor_id"),
        member_id=session.get("member_id"),
        offer_id=int(offer.get("offer_id") or offer.get("id") or offer_id),
        destination_code=offer.get("arrival_code"),
        airline=offer.get("airline") or (offer.get("flight") or {}).get("airline"),
        supplier=target.supplier,
        price_ils=offer.get("price_ils"),
        score=offer.get("score"),
        outbound_date=offer.get("outbound_date"),
        return_date=offer.get("return_date"),
        booking_url=target.url,
    )

    if target.url and target.fields:
        return render_template("booking_forward.html", action=target.url, fields=target.fields)
    if target.url:
        return redirect(target.url)

    if personal_trip is not None:
        flash("לא ניתן לפתוח כרגע הזמנה מדויקת אצל הספק לדיל הזה. לא העברנו אותך להזמנה כללית או עם מספר נוסעים שגוי.", "warning")
        return redirect(url_for("site.account") + f"#vacation-{trip_id}")
    return redirect(url_for("site.deals"))
'''

    start = text.find('@site.get("/book/<int:offer_id>")')
    if start >= 0:
        next_route = text.find('\n@site.', start + 1)
        if next_route < 0:
            next_route = len(text)
        current = text[start:next_route]
        # Always replace this route so runtime gets the latest booking-click fix.
        text = text[:start] + new_route.rstrip() + '\n' + text[next_route:]
    else:
        raise RuntimeError("personal booking route decorator not found")

    PUBLIC.write_text(text, encoding="utf-8")


def patch_card():
    text = CARD.read_text(encoding="utf-8")
    old = '''{% if offer.booking_url %}<a href="{{ url_for('site.book_offer', offer_id=offer.id) }}" target="_blank" rel="noopener noreferrer">{{ 'Go to booking' if lang=='en' else 'למעבר להזמנה' }}</a>{% endif %}'''
    new = '''{% if offer.booking_url %}<a href="{{ url_for('site.book_offer', offer_id=offer.id, trip_id=offer.booking_trip_id) if offer.booking_trip_id else url_for('site.book_offer', offer_id=offer.id) }}" target="_blank" rel="noopener noreferrer">{{ 'Go to booking' if lang=='en' else 'למעבר להזמנה' }}</a>{% endif %}'''
    if old in text:
        text = text.replace(old, new, 1)
    CARD.write_text(text, encoding="utf-8")


def patch_booker():
    text = BOOKER.read_text(encoding="utf-8")
    old_sig = 'def resolve_booking_target(offer: dict) -> BookerTarget:'
    new_sig = 'def resolve_booking_target(offer: dict, *, adults: int | None = None, children: int | None = None) -> BookerTarget:'
    if old_sig in text:
        text = text.replace(old_sig, new_sig, 1)
    BOOKER.write_text(text, encoding="utf-8")


patch_public_site()
patch_card()
patch_booker()
print("9.7.136 personal booking route fixed: valid analytics args + supplier redirect")
