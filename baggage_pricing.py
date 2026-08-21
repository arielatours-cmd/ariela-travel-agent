
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



# v9.7.51 central airline baggage policy.
# Live booking-option data always wins. These values are conservative
# fallback estimates per direction in ILS, used only when live pricing is absent.
AIRLINE_BAGGAGE_POLICY = {
    "W6": {"personal": True, "carry": 220, "checked": 420},
    "WIZZ AIR": {"personal": True, "carry": 220, "checked": 420},
    "FR": {"personal": True, "carry": 220, "checked": 420},
    "RYANAIR": {"personal": True, "carry": 220, "checked": 420},
    "U2": {"personal": True, "carry": 220, "checked": 430},
    "EASYJET": {"personal": True, "carry": 220, "checked": 430},
    "VY": {"personal": True, "carry": 220, "checked": 430},
    "VUELING": {"personal": True, "carry": 220, "checked": 430},
    "PC": {"personal": True, "carry": 180, "checked": 380},
    "PEGASUS": {"personal": True, "carry": 180, "checked": 380},
    "A3": {"personal": True, "carry": None, "checked": 350},
    "AEGEAN": {"personal": True, "carry": None, "checked": 350},
    "LY": {"personal": True, "carry": None, "checked": 360},
    "EL AL": {"personal": True, "carry": None, "checked": 360},
    "IZ": {"personal": True, "carry": None, "checked": 360},
    "ARKIA": {"personal": True, "carry": None, "checked": 360},
    "6H": {"personal": True, "carry": None, "checked": 360},
    "ISRAIR": {"personal": True, "carry": None, "checked": 360},
    "TK": {"personal": True, "carry": None, "checked": 450},
    "TURKISH AIRLINES": {"personal": True, "carry": None, "checked": 450},
    "AF": {"personal": True, "carry": None, "checked": 450},
    "AIR FRANCE": {"personal": True, "carry": None, "checked": 450},
    "KL": {"personal": True, "carry": None, "checked": 450},
    "KLM": {"personal": True, "carry": None, "checked": 450},
    "LH": {"personal": True, "carry": None, "checked": 450},
    "LUFTHANSA": {"personal": True, "carry": None, "checked": 450},
    "LX": {"personal": True, "carry": None, "checked": 450},
    "SWISS": {"personal": True, "carry": None, "checked": 450},
    "OS": {"personal": True, "carry": None, "checked": 450},
    "AUSTRIAN": {"personal": True, "carry": None, "checked": 450},
    "BA": {"personal": True, "carry": None, "checked": 480},
    "BRITISH AIRWAYS": {"personal": True, "carry": None, "checked": 480},
    "EY": {"personal": True, "carry": None, "checked": 500},
    "ETIHAD": {"personal": True, "carry": None, "checked": 500},
    "EK": {"personal": True, "carry": None, "checked": 500},
    "EMIRATES": {"personal": True, "carry": None, "checked": 500},
    "QR": {"personal": True, "carry": None, "checked": 500},
    "QATAR AIRWAYS": {"personal": True, "carry": None, "checked": 500},
}

AIRLINE_ALIASES = {
    "WIZZ": "WIZZ AIR", "WIZZ AIR HUNGARY": "WIZZ AIR",
    "RYANAIR DAC": "RYANAIR", "EASY JET": "EASYJET",
    "ELAL": "EL AL", "TURKISH": "TURKISH AIRLINES",
}

def _policy_key(value):
    if not value:
        return ""
    key = str(value).strip().upper()
    return AIRLINE_ALIASES.get(key, key)

def airline_policy(airline):
    return AIRLINE_BAGGAGE_POLICY.get(_policy_key(airline), {})

def policy_personal_item_included(*airlines):
    rows = [airline_policy(a) for a in airlines if a]
    return bool(rows) and all(r.get("personal") is True for r in rows)

def policy_roundtrip_total(out_airline, ret_airline, kind, out_fee=None, ret_fee=None):
    vals = [v for v in (out_fee, ret_fee) if isinstance(v, (int, float)) and v >= 0]
    if not vals:
        for a in (out_airline, ret_airline):
            v = airline_policy(a).get(kind)
            if isinstance(v, (int, float)) and v > 0:
                vals.append(float(v))
    return max(vals) * 2 if vals else None
