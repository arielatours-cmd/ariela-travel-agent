from datetime import datetime, timedelta, timezone
from config import MAX_DAILY_DEALS, MIN_DEAL_SCORE
from database import top_deals_since


def select_daily_deals(hours_back: int = 24) -> list[dict]:
    since = (datetime.now(timezone.utc) - timedelta(hours=hours_back)).isoformat()
    candidates = top_deals_since(since, MIN_DEAL_SCORE, limit=200)

    selected: list[dict] = []
    seen_keys: set[tuple] = set()
    seen_destinations: set[str] = set()

    for deal in candidates:
        key = (deal["route"], deal["outbound_date"], deal["return_date"])
        if key in seen_keys:
            continue
        # Diversity rule: first pass avoids sending multiple dates for same destination.
        if deal["arrival_code"] in seen_destinations and len(selected) < 3:
            continue
        selected.append(deal)
        seen_keys.add(key)
        seen_destinations.add(deal["arrival_code"])
        if len(selected) >= MAX_DAILY_DEALS:
            break

    if len(selected) < MAX_DAILY_DEALS:
        for deal in candidates:
            key = (deal["route"], deal["outbound_date"], deal["return_date"])
            if key in seen_keys:
                continue
            selected.append(deal)
            seen_keys.add(key)
            if len(selected) >= MAX_DAILY_DEALS:
                break

    return selected
