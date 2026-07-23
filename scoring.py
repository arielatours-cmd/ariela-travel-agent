from datetime import datetime


def _hour(value: str | None):
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
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
    else:
        reasons.append("אין אינדיקציה למחיר חריג: +0")

    stops = int(flight.get("stops") or 0)
    if stops == 0:
        score += 20
        reasons.append("טיסה ישירה: +20")
    elif stops == 1:
        score += 8
        reasons.append("קונקשן אחד: +8")
    else:
        reasons.append(f"{stops} קונקשנים: +0")

    duration = flight.get("total_duration_minutes")
    duration_points = 0
    if isinstance(duration, (int, float)):
        if duration <= 180:
            duration_points = 10
        elif duration <= 300:
            duration_points = 6
        elif duration <= 480:
            duration_points = 3
        score += duration_points
        reasons.append(f"משך מסלול: +{duration_points}")
    else:
        reasons.append("משך מסלול חסר: +0")

    departure_hour = _hour(flight.get("departure_time"))
    arrival_hour = _hour(flight.get("arrival_time"))
    if departure_hour is not None and 6 <= departure_hour <= 21:
        score += 5
        reasons.append("שעת המראה נוחה: +5")
    else:
        reasons.append("שעת המראה לא נוחה או חסרה: +0")
    if arrival_hour is not None and 6 <= arrival_hour <= 23:
        score += 5
        reasons.append("שעת נחיתה נוחה: +5")
    else:
        reasons.append("שעת נחיתה לא נוחה או חסרה: +0")

    score = min(100, score)
    label = "דיל חריג במיוחד" if score >= 85 else "דיל מצוין" if score >= 70 else "דיל טוב" if score >= 55 else "לא לשלוח"
    return {"score": score, "label": label, "send_alert": score >= 70, "reasons": reasons}
