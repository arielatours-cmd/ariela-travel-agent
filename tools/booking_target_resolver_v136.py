from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOOKER = ROOT / "booker.py"

text = BOOKER.read_text(encoding="utf-8")
start = text.find("def resolve_booking_target(")
if start < 0:
    raise RuntimeError("booking target resolver not found")
next_def = text.find("\ndef ", start + 1)
end = next_def if next_def >= 0 else len(text)

new_func = '''def resolve_booking_target(offer: dict, *, adults: int | None = None, children: int | None = None) -> BookerTarget:
    """Resolve an actionable supplier handoff for the selected round trip.

    Personal clicks always refresh Booking Options with the requested passenger
    counts. A booking request captured for another party size must never be reused
    for a personal vacation.
    """
    recommended = str(offer.get("booking_supplier") or offer.get("airline") or "").strip()
    preferred = _norm(recommended)
    stored_url = offer.get("booking_request_url")
    stored_post = offer.get("booking_request_post_data")
    personal = adults is not None or children is not None

    # Public/general cards may reuse the booking request captured with the offer.
    # Personal cards must refresh because that request can be bound to a different
    # passenger composition.
    if stored_url and not personal:
        return BookerTarget(
            url=stored_url,
            fields=parse_qsl(stored_post, keep_blank_values=True) if stored_post else [],
            supplier=recommended,
            mode="recommended_supplier",
            exact=True,
        )

    token = offer.get("booking_token") or (offer.get("flight") or {}).get("booking_token")
    if token and SERPAPI_API_KEY:
        try:
            params = {
                "engine": "google_flights",
                "booking_token": token,
                "api_key": SERPAPI_API_KEY,
                "hl": "en",
                "gl": "il",
                "currency": "ILS",
            }
            if adults is not None:
                params["adults"] = str(max(1, int(adults)))
            if children is not None:
                params["children"] = str(max(0, int(children)))
            data = requests.get("https://serpapi.com/search.json", params=params, timeout=45).json()

            exact_supplier = []
            direct_airline = []
            approved_supplier = []
            for group in data.get("booking_options") or []:
                if group.get("separate_tickets"):
                    continue
                part = group.get("together") or {}
                req = part.get("booking_request") or {}
                if not req.get("url"):
                    continue
                supplier_norm = _norm(part.get("book_with"))
                candidate = (part, req)
                if preferred and supplier_norm == preferred:
                    exact_supplier.append(candidate)
                elif part.get("airline") is True and not _is_unreliable_direct(part):
                    direct_airline.append(candidate)
                elif supplier_norm in ACTIONABLE_BOOKING_SUPPLIERS:
                    approved_supplier.append(candidate)

            pool = exact_supplier or direct_airline or approved_supplier
            if pool:
                part, req = min(pool, key=lambda x: float(x[0].get("price") or 10**9))
                return BookerTarget(
                    url=req.get("url"),
                    fields=_request_fields(req),
                    supplier=part.get("book_with") or recommended,
                    mode="personal_supplier_refreshed" if personal else "recommended_supplier_refreshed",
                    exact=True,
                )
        except Exception:
            pass

    # For a public/general card, the stored supplier request remains a useful
    # fallback. For a personal vacation it can contain the wrong passenger count,
    # so fail closed instead of opening a stale booking.
    if stored_url and not personal:
        return BookerTarget(
            url=stored_url,
            fields=parse_qsl(stored_post, keep_blank_values=True) if stored_post else [],
            supplier=recommended,
            mode="stored_supplier_fallback",
            exact=False,
            note="יש לוודא את מספר הנוסעים והזמינות אצל הספק.",
        )

    return BookerTarget(
        url=None,
        fields=[],
        supplier=recommended,
        mode="personal_exact_booking_unavailable" if personal else "recommended_supplier_unavailable",
        exact=False,
        note=("לא נמצא כרגע קישור הזמנה ששומר את מספר הנוסעים שבחרתם."
              if personal else "מסלול ההזמנה אצל הספק המומלץ אינו זמין כרגע."),
    )
'''

text = text[:start] + new_func.rstrip() + "\n" + text[end:]
BOOKER.write_text(text, encoding="utf-8")
print("9.7.136 booking target resolver fixed: personal passenger count is exact and stale booking requests are blocked")