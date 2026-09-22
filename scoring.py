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


def _price_points(analysis: dict, max_points: int = 85) -> tuple[int, list[str]]:
    """Score price against the cheapest comparable current result.

    max_points scales the same relative tiers for a different scoring
    profile (e.g. business trips, where price matters far less).
    """
    reasons: list[str] = []
    gap = analysis.get("current_search_price_gap_percent")
    if not isinstance(gap, (int, float)):
        return 0, reasons
    if gap <= 0: fraction = 1.0
    elif gap <= 5: fraction = 0.94
    elif gap <= 10: fraction = 0.88
    elif gap <= 15: fraction = 0.82
    elif gap <= 20: fraction = 0.76
    elif gap <= 25: fraction = 0.71
    elif gap <= 30: fraction = 0.65
    elif gap <= 35: fraction = 0.59
    elif gap <= 40: fraction = 0.53
    elif gap <= 50: fraction = 0.41
    else: fraction = 0.29
    points = round(max_points * fraction)
    # The point curve keeps tapering all the way to a 50%+ gap so ranking stays
    # smooth, but touting a flight that costs up to 50% more as "a low price"
    # is simply false. Only surface this as a customer-facing reason when the
    # flight is genuinely near the cheapest in its own comparison pool -
    # otherwise several flights at different prices for the same search would
    # all claim "good price" as a reason, which cannot be true for more than
    # the actual cheapest one(s).
    if gap <= 0:
        reasons.append(f"המחיר הזול ביותר שנמצא לתאריכים האלה: +{points}")
    elif gap <= 10:
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


def _time_value_points(flight: dict, max_points: int = 9) -> tuple[int, list[str]]:
    """Usable stay score, based on arrival at destination and return departure.

    max_points=9 preserves the original 1..9 scale; a business profile scales
    this up since maximizing usable same-day time matters more there.
    """
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

    tier = {
        ("morning", "evening"): 9, ("morning", "afternoon"): 8,
        ("afternoon", "evening"): 7, ("morning", "morning"): 6,
        ("afternoon", "afternoon"): 5, ("evening", "evening"): 4,
        ("afternoon", "morning"): 3, ("evening", "afternoon"): 2,
        ("evening", "morning"): 1,
    }[(band(out_dep), band(ret_dep))]
    points = round(max_points * tier / 9)
    return points, []


def calculate_deal_score(deal_analysis: dict, flight: dict, vacation_type: str = "standard") -> dict:
    """Ariella deal score, 0..100.

    Standard profile weights: price 85, time/value 9, baggage 3, route 3 -
    price dominates because a leisure customer is choosing between many
    otherwise-similar options and the price is usually the deciding factor.

    Business profile weights: route 45, price 30, time/value 15, baggage 3 -
    a business traveler has a fixed date tied to a meeting and cares far more
    about directness and not losing a workday to a layover than about saving
    a bit more on the fare.
    """
    is_business = str(vacation_type or "").strip().lower() == "business"
    score = 0
    reasons: list[str] = []
    components: dict[str, int] = {}

    price, price_reasons = _price_points(deal_analysis, max_points=30 if is_business else 85)
    components["price"] = price
    score += price
    reasons.extend(price_reasons)

    stops = int(flight.get("stops") or 0)
    return_stops = int(flight.get("return_stops") or 0)
    worst_stops = max(stops, return_stops)
    duration = max(flight.get("total_duration_minutes") or 0, flight.get("return_total_duration_minutes") or 0)
    # Flight quality is absolute, not relative to the weakest search pool, and
    # graded by the worse leg of the two. Standard: direct scores full, then
    # one point is lost per additional connection. Business: the drop from
    # direct to even one connection is steep, since a layover risks the
    # whole day's schedule, not just adds travel time.
    if is_business:
        route_points = {0: 45, 1: 20, 2: 5}.get(worst_stops, 0)
    else:
        route_points = max(0, 3 - worst_stops)
    components["route"] = route_points
    score += route_points
    route_max = 45 if is_business else 3
    # A connecting flight is never a selling point, even when it still scores
    # some points relative to a worse alternative - it should not be
    # presented to the customer as a "reason this deal was chosen" when a
    # direct flight might have been available instead. Only a genuinely
    # direct route is worth surfacing as a reason.
    if route_points == route_max:
        reasons.append("איכות מסלול (ישירה): +" + str(route_points))

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

    time_points, time_reasons = _time_value_points(flight, max_points=15 if is_business else 9)
    components["time_value"] = time_points
    score += time_points
    time_alert_threshold = 13 if is_business else 8
    if time_points >= time_alert_threshold:
        reasons.append(f"מקסימום ניצול זמן היום: +{time_points}" if is_business else f"מקסימום ניצול זמן חופשה: +{time_points}")
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
