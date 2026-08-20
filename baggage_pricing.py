
# Conservative baggage fallback in ILS per direction.
# Live booking-option baggage prices always take precedence.
AIRLINE_BAGGAGE_FALLBACK_ILS = {
    "W6": {"carry": 220, "checked": 420}, "WIZZ AIR": {"carry": 220, "checked": 420},
    "FR": {"carry": 220, "checked": 420}, "RYANAIR": {"carry": 220, "checked": 420},
    "U2": {"carry": 220, "checked": 430}, "EASYJET": {"carry": 220, "checked": 430},
    "LY": {"checked": 360}, "EL AL": {"checked": 360},
    "A3": {"checked": 350}, "AEGEAN": {"checked": 350},
    "TK": {"checked": 450}, "TURKISH AIRLINES": {"checked": 450},
    "AF": {"checked": 450}, "AIR FRANCE": {"checked": 450},
    "KL": {"checked": 450}, "KLM": {"checked": 450},
    "LH": {"checked": 450}, "LUFTHANSA": {"checked": 450},
    "EY": {"checked": 500}, "ETIHAD": {"checked": 500},
    "EK": {"checked": 500}, "EMIRATES": {"checked": 500},
}

def fallback_bag_fee(airline, kind):
    if not airline:
        return None
    row = AIRLINE_BAGGAGE_FALLBACK_ILS.get(str(airline).strip().upper(), {})
    value = row.get(kind)
    return float(value) if isinstance(value, (int, float)) and value > 0 else None

def conservative_rt_bag_fee(out_fee, ret_fee, out_airline, ret_airline, kind):
    """Return conservative round-trip baggage total: highest one-way value x2."""
    values = [v for v in (out_fee, ret_fee) if isinstance(v, (int, float)) and v >= 0]
    if not values:
        values = [v for v in (fallback_bag_fee(out_airline, kind), fallback_bag_fee(ret_airline, kind)) if v is not None]
    if not values:
        return None
    return max(values) * 2
