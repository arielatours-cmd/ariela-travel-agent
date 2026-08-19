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
        source_he = {
            "serpapi_typical": "הטווח הרגיל של Google Flights",
            "history": "היסטוריית המחירים של אריאלה",
            "search_distribution": "מחירי החיפוש הנוכחי",
        }.get(source, "מחיר הייחוס")
        reasons.append(f"מחיר נמוך ב-{discount:.1f}% לעומת {source_he}: +{points}")
        return points, reasons

    if analysis.get("price_level") == "low":
        reasons.append("Google Flights מסמן את המחיר כנמוך: +30")
        return 30, reasons

    reasons.append("עדיין אין מספיק נתוני מחיר להשוואה: +0")
    return 0, reasons


def calculate_deal_score(deal_analysis: dict, flight: dict) -> dict:
    score = 0
    reasons: list[str] = []
    components: dict[str, int] = {}

    price, price_reasons = _price_points(deal_analysis)
    components["price"] = price
    score += price
    reasons.extend(price_reasons)

    # איכות מסלול — עד 20 נקודות, ללא ספירה כפולה של עצירות ומשך.
    stops = int(flight.get("stops") or 0)
    duration = flight.get("total_duration_minutes")
    if stops == 0:
        route_points = 14
    elif stops == 1:
        route_points = 7
    else:
        route_points = 0
    if isinstance(duration, (int, float)):
        if duration <= 180:
            route_points += 6
        elif duration <= 300:
            route_points += 4
        elif duration <= 480:
            route_points += 2
    route_points = min(20, route_points)
    components["route"] = route_points
    score += route_points
    reasons.append(f"איכות מסלול ({'ישירה' if stops == 0 else str(stops) + ' עצירות'}): +{route_points}")

    # נדירות — לפי המיקום של המחיר מול היסטוריית אריאלה.
    percentile = deal_analysis.get("historical_percentile")
    if isinstance(percentile, (int, float)):
        if percentile <= 5:
            rarity = 15
        elif percentile <= 10:
            rarity = 12
        elif percentile <= 20:
            rarity = 9
        elif percentile <= 35:
            rarity = 5
        else:
            rarity = 0
        reasons.append(f"נדירות היסטורית (אחוזון {percentile:.0f}): +{rarity}")
    else:
        rarity = 0
        reasons.append("עדיין אין מספיק היסטוריה למדד נדירות: +0")
    components["rarity"] = rarity
    score += rarity

    baggage = flight.get("baggage") or {}
    baggage_points = 0
    if baggage.get("checked_bag_23kg", {}).get("included"):
        baggage_points = 10
    elif baggage.get("carry_on_8kg", {}).get("included"):
        baggage_points = 6
    elif baggage.get("personal_item", {}).get("included"):
        baggage_points = 2
    components["baggage"] = baggage_points
    score += baggage_points
    reasons.append(f"כבודה כלולה: +{baggage_points}")

    departure_hour = _hour(flight.get("departure_time"))
    arrival_hour = _hour(flight.get("arrival_time"))
    hours_points = 0
    if departure_hour is not None and 6 <= departure_hour <= 21:
        hours_points += 5
    if arrival_hour is not None and 6 <= arrival_hour <= 23:
        hours_points += 5
    components["hours"] = hours_points
    score += hours_points
    reasons.append(f"שעות טיסה: +{hours_points}")

    # 5 נקודות שמורות לעונתיות/איכות חברת תעופה כשיהיו נתונים אמינים.
    quality_points = 0
    components["season_airline"] = quality_points
    reasons.append("עונתיות ואיכות חברת תעופה: טרם חושב +0")

    score = min(100, score)
    label = "דיל חריג במיוחד" if score >= 85 else "דיל מצוין" if score >= 70 else "דיל טוב" if score >= 55 else "לא לשלוח"
    return {
        "score": score,
        "label": label,
        "send_alert": score >= 70,
        "reasons": reasons,
        "components": components,
    }
