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
    """Resolve a supplier handoff for the exact itinerary and passenger party.

    A Google Flights booking_token belongs to the search that created it. For a
    personal vacation we therefore regenerate the outbound + return selection
    with the customer's current adults/children before requesting Booking Options.
    """
    recommended = str(offer.get("booking_supplier") or offer.get("airline") or "").strip()
    preferred = _norm(recommended)
    stored_url = offer.get("booking_request_url")
    stored_post = offer.get("booking_request_post_data")
    personal = adults is not None or children is not None
    pax_adults = max(1, int(adults or 1))
    pax_children = max(0, int(children or 0))

    if stored_url and not personal:
        return BookerTarget(url=stored_url,
            fields=parse_qsl(stored_post, keep_blank_values=True) if stored_post else [],
            supplier=recommended, mode="recommended_supplier", exact=True)

    def _time5(value):
        value = str(value or "")
        return value[-5:] if len(value) >= 5 else value

    def _items(data):
        return (data.get("best_flights") or []) + (data.get("other_flights") or [])

    def _summary(item):
        flights = item.get("flights") or []
        first = flights[0] if flights else {}
        dep = first.get("departure_airport") or {}
        airline = str(first.get("airline") or "").strip().lower()
        return _time5(dep.get("time")), airline, len(item.get("layovers") or [])

    def _choose(items, wanted_time, wanted_airline, wanted_stops):
        wanted_time = _time5(wanted_time)
        wanted_airline = str(wanted_airline or "").strip().lower()
        ranked = []
        for item in items:
            tm, airline, stops = _summary(item)
            score = 0
            if wanted_time and tm == wanted_time: score += 8
            if wanted_airline and airline == wanted_airline: score += 4
            if wanted_stops is not None and stops == int(wanted_stops): score += 2
            ranked.append((score, item))
        ranked.sort(key=lambda x: x[0], reverse=True)
        return ranked[0][1] if ranked and ranked[0][0] >= 8 else None

    token = None
    if personal and SERPAPI_API_KEY:
        # Fresh exact-party search: select the same outbound, expand its returns,
        # then select the same inbound. The resulting booking_token is now tied to
        # the requested passenger composition rather than the shared DB search.
        try:
            departure = offer.get("departure_code") or offer.get("departure_airport")
            arrival = offer.get("arrival_code") or offer.get("arrival_airport")
            outbound_date = offer.get("outbound_date")
            return_date = offer.get("return_date")
            if departure and arrival and outbound_date and return_date:
                base = {"engine":"google_flights", "api_key":SERPAPI_API_KEY,
                        "departure_id":departure, "arrival_id":arrival,
                        "outbound_date":outbound_date, "return_date":return_date,
                        "type":"1", "hl":"en", "gl":"il", "currency":"ILS",
                        "travel_class":"1", "adults":str(pax_adults),
                        "children":str(pax_children), "bags":"0", "sort_by":"2",
                        "no_cache":"false"}
                out_data = requests.get("https://serpapi.com/search.json", params=base, timeout=45).json()
                outbound = _choose(_items(out_data), offer.get("departure_time"),
                                   offer.get("airline"), offer.get("stops"))
                departure_token = (outbound or {}).get("departure_token")
                if departure_token:
                    ret_params = dict(base)
                    ret_params["departure_token"] = departure_token
                    ret_data = requests.get("https://serpapi.com/search.json", params=ret_params, timeout=45).json()
                    inbound = _choose(_items(ret_data), offer.get("return_departure_time"),
                                      offer.get("return_airline") or offer.get("airline"),
                                      offer.get("return_stops"))
                    token = (inbound or {}).get("booking_token")
        except Exception:
            token = None

    if not personal:
        token = offer.get("booking_token") or (offer.get("flight") or {}).get("booking_token")

    if token and SERPAPI_API_KEY:
        try:
            params = {"engine":"google_flights", "booking_token":token,
                      "api_key":SERPAPI_API_KEY, "hl":"en", "gl":"il",
                      "currency":"ILS", "adults":str(pax_adults),
                      "children":str(pax_children)}
            data = requests.get("https://serpapi.com/search.json", params=params, timeout=45).json()
            exact_supplier, direct_airline, approved_supplier = [], [], []
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
                return BookerTarget(url=req.get("url"), fields=_request_fields(req),
                    supplier=part.get("book_with") or recommended,
                    mode="personal_exact_party_regenerated" if personal else "recommended_supplier_refreshed",
                    exact=True)
        except Exception:
            pass

    if stored_url and not personal:
        return BookerTarget(url=stored_url,
            fields=parse_qsl(stored_post, keep_blank_values=True) if stored_post else [],
            supplier=recommended, mode="stored_supplier_fallback", exact=False,
            note="יש לוודא את מספר הנוסעים והזמינות אצל הספק.")

    return BookerTarget(url=None, fields=[], supplier=recommended,
        mode="personal_exact_booking_unavailable" if personal else "recommended_supplier_unavailable",
        exact=False,
        note=("לא נמצא כרגע קישור הזמנה ששומר את הטיסה ומספר הנוסעים שבחרתם."
              if personal else "מסלול ההזמנה אצל הספק המומלץ אינו זמין כרגע."))
'''

text = text[:start] + new_func.rstrip() + "\n" + text[end:]
BOOKER.write_text(text, encoding="utf-8")
print("9.7.136 BOOKER regenerates exact itinerary token for the personal passenger party")
