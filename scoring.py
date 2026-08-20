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
    reasons: list[str] = []
    discount = analysis.get("best_discount_percent")
    source = analysis.get("price_reference_source")

    if isinstance(discount, (int, float)):
        if discount >= 30:
            points = 40
        elif discount >= 25:
            points = 36
        elif discount >= 20:
            points = 32
        elif discount >= 15:
            points = 27
        elif discount >= 10:
            points = 20
        elif discount >= 5:
            points = 12
        elif discount > 0:
            points = 6
        else:
            points = 0
        if source == "search_distribution":
            # Same-search median is useful for ranking but too weak for a big
            # customer-facing "X% below average" claim. Cap its score impact.
            points = min(points, 20)
            reasons.append(f"מחיר תחרותי ביחס לאפשרויות בחיפוש הנוכחי: +{points}")
            return points, reasons
        source_he = {
            "serpapi_typical": "הטווח הרגיל של Google Flights",
            "history": "היסטוריית המחירים של אריאלה",
        }.get(source, "מחיר הייחוס")
        reasons.append(f"מחיר נמוך ב-{discount:.1f}% לעומת {source_he}: +{points}")
        return points, reasons

    if analysis.get("price_level") == "low":
        reasons.append("Google Flights מסמן את המחיר כנמוך: +30")
        return 30, reasons

    reasons.append("עדיין אין מספיק נתוני מחיר להשוואה: +0")
    return 0, reasons


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

    # Usable destination time: early arrival on first day + late departure on last day.
    first_day = max(0, 20 * 60 - out_arr) / (14 * 60)   # 06:00 arrival ~= max value
    last_day = max(0, ret_dep - 6 * 60) / (16 * 60)    # 22:00 departure ~= max value
    usable = max(0.0, min(1.0, (first_day + last_day) / 2))

    # Comfort: penalize departures/arrivals in the hardest night hours.
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
        if duration <= 180: route_points += 6
        elif duration <= 300: route_points += 4
        elif duration <= 480: route_points += 2
    route_points = min(20, route_points)
    components["route"] = route_points
    score += route_points
    reasons.append(f"איכות מסלול ({'ישירה' if worst_stops == 0 else str(worst_stops) + ' עצירות'}): +{route_points}")

    percentile = deal_analysis.get("historical_percentile")
    if isinstance(percentile, (int, float)):
        if percentile <= 5: rarity = 15
        elif percentile <= 10: rarity = 12
        elif percentile <= 20: rarity = 9
        elif percentile <= 35: rarity = 5
        else: rarity = 0
        reasons.append(f"נדירות היסטורית (אחוזון {percentile:.0f}): +{rarity}")
    else:
        rarity = 0
    components["rarity"] = rarity
    score += rarity

    baggage = flight.get("baggage") or {}
    if baggage.get("checked_bag_23kg", {}).get("included"): baggage_points = 10
    elif baggage.get("carry_on_8kg", {}).get("included"): baggage_points = 6
    elif baggage.get("personal_item", {}).get("included"): baggage_points = 2
    else: baggage_points = 0
    components["baggage"] = baggage_points
    score += baggage_points
    reasons.append(f"כבודה כלולה: +{baggage_points}")

    time_points, time_reasons = _time_value_points(flight)
    components["time_value"] = time_points
    score += time_points
    reasons.append(f"נוחות וזמן ביעד: +{time_points}")
    reasons.extend(time_reasons)

    score = min(100, score)
    label = "דיל חריג במיוחד" if score >= 85 else "דיל מצוין" if score >= 70 else "דיל טוב" if score >= 55 else "לא לשלוח"
    return {"score": score, "label": label, "send_alert": score >= 70, "reasons": reasons, "components": components}
