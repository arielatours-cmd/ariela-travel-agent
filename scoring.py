from datetime import datetime


def _hour(value: str | None):
    if not value:
        return None
    normalized = value.replace("T", " ")[:19]
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(normalized, fmt).hour
        except ValueError:
            pass
    return None


def _price_points(analysis: dict) -> tuple[int, list[str]]:
    """Price is the main deal signal (0..55).

    When no historical/typical comparison exists, the best currently found
    price receives the full price component. This lets a new route/period enter
    the deal pool without inventing a negative reason for missing history.
    """
    reasons: list[str] = []
    discount = analysis.get("best_discount_percent")
    source = analysis.get("price_reference_source")

    if isinstance(discount, (int, float)):
        if discount >= 30:
            points = 55
        elif discount >= 25:
            points = 50
        elif discount >= 20:
            points = 44
        elif discount >= 15:
            points = 37
        elif discount >= 10:
            points = 28
        elif discount >= 5:
            points = 17
        elif discount > 0:
            points = 9
        else:
            points = 0
        if source == "search_distribution":
            points = min(points, 28)
            if points:
                reasons.append(f"מחיר תחרותי ביחס לאפשרויות בחיפוש הנוכחי: +{points}")
            return points, reasons
        source_he = {
            "serpapi_typical": "הטווח הרגיל של Google Flights",
            "history": "היסטוריית המחירים של אריאלה",
        }.get(source, "מחיר הייחוס")
        if points:
            reasons.append(f"מחיר נמוך ב-{discount:.1f}% לעומת {source_he}: +{points}")
        return points, reasons

    if analysis.get("price_level") == "low":
        reasons.append("Google Flights מסמן את המחיר כנמוך: +42")
        return 42, reasons

    # No historical/typical comparison exists yet: treat the current best found
    # price as the benchmark. Do not expose missing comparison data as a reason.
    return 55, reasons


def _minutes_of_day(value: str | None):
    if not value:
        return None
    normalized = value.replace("T", " ")[:19]
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S"):
        try:
            dt = datetime.strptime(normalized, fmt)
            return dt.hour * 60 + dt.minute
        except ValueError:
            pass
    return None


def _time_value_points(flight: dict) -> tuple[int, list[str]]:
    """Combined score for comfort + usable time at destination (0..15)."""
    out_dep = _minutes_of_day(flight.get("departure_time"))
    out_arr = _minutes_of_day(flight.get("arrival_time"))
    ret_dep = _minutes_of_day(flight.get("return_departure_time"))
    ret_arr = _minutes_of_day(flight.get("return_arrival_time"))
    if None in (out_dep, out_arr, ret_dep, ret_arr):
        return 0, []

    first_day = max(0, 20 * 60 - out_arr) / (14 * 60)
    last_day = max(0, ret_dep - 6 * 60) / (16 * 60)
    usable = max(0.0, min(1.0, (first_day + last_day) / 2))

    def comfortable(m):
        h = m / 60
        if 6 <= h < 22:
            return 1.0
        if 5 <= h < 6 or 22 <= h < 24:
            return 0.65
        if 0 <= h < 2:
            return 0.45
        return 0.2

    comfort = sum(comfortable(x) for x in (out_dep, out_arr, ret_dep, ret_arr)) / 4
    points = round(15 * (0.65 * usable + 0.35 * comfort))
    reasons = []
    if usable >= 0.78 and comfort >= 0.65:
        reasons.append("ימים מלאים ביעד ושעות טיסה נוחות")
    elif usable >= 0.78:
        reasons.append("ניצול מצוין של היום הראשון והאחרון")
    elif comfort >= 0.85:
        reasons.append("שעות טיסה נוחות")
    return points, reasons


def calculate_deal_score(deal_analysis: dict, flight: dict) -> dict:
    """Ariella public-deal score, exactly 0..100.

    Weights: price 55, route 20, time/value 15, baggage 10.
    Reliability and historical rarity are not scoring components. Personal
    searches use score for ranking only; the public 70 threshold must not hide
    a flight that matches the customer's explicit request.
    """
    score = 0
    reasons: list[str] = []
    components: dict[str, int] = {}

    price, price_reasons = _price_points(deal_analysis)
    components["price"] = price
    score += price
    reasons.extend(price_reasons)

    stops = int(flight.get("stops") or 0)
    return_stops = int(flight.get("return_stops") or 0)
    worst_stops = max(stops, return_stops)
    duration = max(flight.get("total_duration_minutes") or 0, flight.get("return_total_duration_minutes") or 0)
    if worst_stops == 0:
        route_points = 14
    elif worst_stops == 1:
        route_points = 7
    else:
        route_points = 0
    if duration:
        if duration <= 180:
            route_points += 6
        elif duration <= 300:
            route_points += 4
        elif duration <= 480:
            route_points += 2
    route_points = min(20, route_points)
    components["route"] = route_points
    score += route_points
    if route_points > 0:
        reasons.append(f"איכות מסלול ({'ישירה' if worst_stops == 0 else str(worst_stops) + ' עצירות'}): +{route_points}")

    baggage = flight.get("baggage") or {}
    checked = baggage.get("checked_bag_23kg", {}) or {}
    carry = baggage.get("carry_on_8kg", {}) or {}
    personal = baggage.get("personal_item", {}) or {}
    if checked.get("included"):
        baggage_points, baggage_reason = 10, "מזוודה 23 ק״ג כלולה"
    elif carry.get("included"):
        baggage_points, baggage_reason = 7, "טרולי 8 ק״ג כלול"
    elif personal.get("included"):
        baggage_points, baggage_reason = 2, "תיק אישי כלול"
    else:
        baggage_points, baggage_reason = 0, None
    components["baggage"] = baggage_points
    score += baggage_points
    if baggage_reason:
        reasons.append(f"{baggage_reason}: +{baggage_points}")

    time_points, time_reasons = _time_value_points(flight)
    components["time_value"] = time_points
    score += time_points
    if time_points:
        reasons.append(f"נוחות וזמן ביעד: +{time_points}")
    reasons.extend(time_reasons)

    # Keep reliability visible to admin/validation without affecting score.
    if flight.get("booking_supplier_is_direct") is True:
        reliability = 8
    elif flight.get("booking_supplier_approved") is True:
        reliability = 6
    elif int(flight.get("booking_options_checked") or 0) > 0:
        reliability = 3
    else:
        reliability = 0
    components["reliability"] = reliability

    score = min(100, score)
    label = "דיל חריג במיוחד" if score >= 85 else "דיל מצוין" if score >= 70 else "דיל טוב" if score >= 55 else "לא לשלוח"
    return {"score": score, "label": label, "send_alert": score >= 70, "reasons": reasons, "components": components}
