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
    """Score price (0..85) against the cheapest comparable current result."""
    reasons: list[str] = []
    gap = analysis.get("current_search_price_gap_percent")
    if not isinstance(gap, (int, float)):
        return 0, reasons
    if gap <= 0: points = 85
    elif gap <= 5: points = 80
    elif gap <= 10: points = 75
    elif gap <= 15: points = 70
    elif gap <= 20: points = 65
    elif gap <= 25: points = 60
    elif gap <= 30: points = 55
    elif gap <= 35: points = 50
    elif gap <= 40: points = 45
    elif gap <= 50: points = 35
    else: points = 25
    reasons.append(f"מחיר נמוך לעומת טיסות דומות: +{points}")
    return points, reasons


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
    """Usable stay score (1..9), based on arrival at destination and return departure."""
    out_dep = _minutes_of_day(flight.get("arrival_time"))
    ret_dep = _minutes_of_day(flight.get("return_departure_time"))
    if None in (out_dep, ret_dep):
        return 0, []

    def band(minutes):
        if 6 * 60 <= minutes < 12 * 60:
            return "morning"
        if 12 * 60 <= minutes < 18 * 60:
            return "afternoon"
        return "evening"

    points = {
        ("morning", "evening"): 9, ("morning", "afternoon"): 8,
        ("afternoon", "evening"): 7, ("morning", "morning"): 6,
        ("afternoon", "afternoon"): 5, ("evening", "evening"): 4,
        ("afternoon", "morning"): 3, ("evening", "afternoon"): 2,
        ("evening", "morning"): 1,
    }[(band(out_dep), band(ret_dep))]
    return points, []


def calculate_deal_score(deal_analysis: dict, flight: dict) -> dict:
    """Ariella public-deal score, exactly 0..100.

    Weights: price 85, time/value 9, baggage 3, route 3.
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
    # Flight quality is absolute, not relative to the weakest search pool:
    # full points only when BOTH outbound and return are direct.
    route_points = 3 if worst_stops == 0 else 0
    components["route"] = route_points
    score += route_points
    if route_points:
        reasons.append("איכות מסלול (ישירה): +3")

    baggage = flight.get("baggage") or {}
    checked = baggage.get("checked_bag_23kg", {}) or {}
    carry = baggage.get("carry_on_8kg", {}) or {}
    personal = baggage.get("personal_item", {}) or {}
    if checked.get("included"):
        baggage_points, baggage_reason = 3, "מזוודה 20 ק״ג ומעלה כלולה"
    elif carry.get("included"):
        baggage_points, baggage_reason = 2, "טרולי כלול"
    elif personal.get("included"):
        baggage_points, baggage_reason = 1, "תיק גב כלול"
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
    return {"score": score, "label": label, "send_alert": score >= 80, "reasons": reasons, "components": components}
