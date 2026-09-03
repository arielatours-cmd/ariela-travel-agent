from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public_site.py"
CARD = ROOT / "templates" / "_deal_card.html"
BOOKER = ROOT / "booker.py"


def patch_public_site():
    text = PUBLIC.read_text(encoding="utf-8")

    # Every personal result card must carry the CURRENT vacation context, not the
    # trip_id of whichever shared scan originally discovered the offer.
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
        offer=offer,
        supplier=target.supplier,
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

    # Runtime preparation may already have changed this route. Replace it by
    # decorator boundaries instead of depending on one historical body.
    start = text.find('@site.get("/book/<int:offer_id>")')
    if start >= 0:
        next_route = text.find('\n@site.', start + 1)
        if next_route < 0:
            next_route = len(text)
        current = text[start:next_route]
        if 'exact personal context first; never fall through to general deals' not in current:
            text = text[:start] + new_route.rstrip() + '\n' + text[next_route:]
    elif 'exact personal context first; never fall through to general deals' not in text:
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

    old_stored = '''    stored_url = offer.get("booking_request_url")
    stored_post = offer.get("booking_request_post_data")
    if stored_url:
        return BookerTarget(
            url=stored_url,
            fields=parse_qsl(stored_post, keep_blank_values=True) if stored_post else [],
            supplier=recommended,
            mode="recommended_supplier",
            exact=True,
        )
'''
    new_stored = '''    stored_url = offer.get("booking_request_url")
    stored_post = offer.get("booking_request_post_data")
    if stored_url and adults is None and children is None:
        return BookerTarget(
            url=stored_url,
            fields=parse_qsl(stored_post, keep_blank_values=True) if stored_post else [],
            supplier=recommended,
            mode="recommended_supplier",
            exact=True,
        )
'''
    if old_stored in text:
        text = text.replace(old_stored, new_stored, 1)

    old_params = '''        params={"engine":"google_flights","booking_token":token,
                "api_key":SERPAPI_API_KEY,"hl":"en","gl":"il","currency":"ILS"}'''
    new_params = '''        params={"engine":"google_flights","booking_token":token,
                "api_key":SERPAPI_API_KEY,"hl":"en","gl":"il","currency":"ILS"}
        if adults is not None:
            params["adults"] = str(max(1, int(adults)))
        if children is not None:
            params["children"] = str(max(0, int(children)))'''
    if old_params in text:
        text = text.replace(old_params, new_params, 1)

    BOOKER.write_text(text, encoding="utf-8")


patch_public_site()
patch_card()
patch_booker()
print("9.7.136 personal booking context + exact passenger handoff active")
