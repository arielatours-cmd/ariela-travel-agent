from datetime import datetime


def _hour(value: str | None):
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt).hour
        except ValueError:
            pass
    return None


def calculate_deal_score(deal_analysis: dict, flight: dict) -> dict:
    score = 0
    reasons: list[str] = []

    discount = deal_analysis.get("below_typical_low_percent")
    if isinstance(discount, (int, float)):
        points = min(50, max(0, round(discount * 2)))
        score += points
        reasons.append(f"מחיר נמוך מהטווח הרגיל: +{points}")
    elif deal_analysis.get("price_level") == "low":
        score += 35
        reasons.append("המחיר מסומן כנמוך: +35")

    stops = int(flight.get("stops") or 0)
    if stops == 0:
        score += 20
        reasons.append("טיסה ישירה: +20")
    elif stops == 1:
        score += 8
        reasons.append("קונקשן אחד: +8")

    duration = flight.get("total_duration_minutes")
    if isinstance(duration, (int, float)):
        if duration <= 180:
            score += 10
        elif duration <= 300:
            score += 6
        elif duration <= 480:
            score += 3

    departure_hour = _hour(flight.get("departure_time"))
    arrival_hour = _hour(flight.get("arrival_time"))
    if departure_hour is not None and 6 <= departure_hour <= 21:
        score += 5
    if arrival_hour is not None and 6 <= arrival_hour <= 23:
        score += 5

    score = min(100, score)
    label = "דיל חריג במיוחד" if score >= 85 else "דיל מצוין" if score >= 70 else "דיל טוב" if score >= 55 else "לא לשלוח"
    return {"score": score, "label": label, "send_alert": score >= 70, "reasons": reasons}
