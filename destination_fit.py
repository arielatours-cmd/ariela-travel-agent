"""Ariella destination-condition matrix.

Each customer vacation preference is scored transparently: +1 only when the
specific destination is suitable for that preference in the offer's travel
month.  The separate ``best_months`` field contributes the single additional
seasonality point.  Flight price/directness/baggage are dynamic and are never
hard-coded here.
"""
ALL_MONTHS = frozenset(range(1, 13))


def M(*months):
    return frozenset(int(m) for m in months)


# preference keys match Q04 holiday_priorities.
# A missing preference means 0 points for that destination/month.
DESTINATION_CONDITION_MONTHS = {
    "ATH": {
        "beach": M(5,6,7,8,9,10), "nature": M(3,4,5,6,9,10,11), "hiking": M(3,4,5,6,9,10,11),
        "city": ALL_MONTHS, "family": ALL_MONTHS, "food": ALL_MONTHS, "shopping": ALL_MONTHS,
        "quiet": M(1,2,3,4,11,12), "weather": M(4,5,6,9,10,11), "nightlife": ALL_MONTHS, "relax": M(4,5,6,9,10,11),
        "best_months": M(4,5,6,9,10),
    },
    "LCA": {
        "beach": M(4,5,6,7,8,9,10,11), "nature": M(2,3,4,5,6,10,11,12), "hiking": M(2,3,4,5,10,11,12),
        "city": ALL_MONTHS, "family": ALL_MONTHS, "food": ALL_MONTHS, "shopping": ALL_MONTHS,
        "quiet": M(1,2,3,4,11,12), "weather": M(3,4,5,6,9,10,11), "nightlife": M(5,6,7,8,9,10), "relax": ALL_MONTHS,
        "best_months": M(4,5,6,9,10,11),
    },
    "BUD": {
        "nature": M(4,5,6,7,8,9,10), "hiking": M(4,5,6,7,8,9,10), "city": ALL_MONTHS, "family": ALL_MONTHS,
        "food": ALL_MONTHS, "shopping": ALL_MONTHS, "quiet": M(1,2,3,11), "weather": M(4,5,6,9,10),
        "nightlife": ALL_MONTHS, "relax": M(3,4,5,9,10,11), "best_months": M(4,5,6,9,10),
    },
    "VIE": {
        "nature": M(4,5,6,7,8,9,10), "hiking": M(4,5,6,7,8,9,10), "city": ALL_MONTHS, "family": ALL_MONTHS,
        "food": ALL_MONTHS, "shopping": ALL_MONTHS, "quiet": M(1,2,3,11), "weather": M(4,5,6,9,10),
        "nightlife": ALL_MONTHS, "relax": M(3,4,5,9,10,11), "best_months": M(4,5,6,9,10),
    },
    "SOF": {
        "nature": M(4,5,6,7,8,9,10), "hiking": M(5,6,7,8,9,10), "city": ALL_MONTHS, "family": ALL_MONTHS,
        "food": ALL_MONTHS, "shopping": ALL_MONTHS, "quiet": M(1,2,3,4,10,11,12), "weather": M(5,6,7,8,9),
        "nightlife": ALL_MONTHS, "relax": M(4,5,6,9,10), "best_months": M(5,6,9),
    },
    "PRG": {
        "nature": M(4,5,6,7,8,9,10), "hiking": M(4,5,6,7,8,9,10), "city": ALL_MONTHS, "family": ALL_MONTHS,
        "food": ALL_MONTHS, "shopping": ALL_MONTHS, "quiet": M(1,2,3,11), "weather": M(4,5,6,9,10),
        "nightlife": ALL_MONTHS, "relax": M(3,4,5,9,10,11), "best_months": M(4,5,6,9,10),
    },
    "FCO": {
        "nature": M(3,4,5,6,9,10,11), "hiking": M(3,4,5,6,9,10,11), "city": ALL_MONTHS, "family": ALL_MONTHS,
        "food": ALL_MONTHS, "shopping": ALL_MONTHS, "quiet": M(1,2,3,11), "weather": M(3,4,5,6,9,10,11),
        "nightlife": ALL_MONTHS, "relax": M(3,4,5,10,11), "best_months": M(4,5,6,9,10),
    },
    "MXP": {
        "nature": M(4,5,6,7,8,9,10), "hiking": M(5,6,7,8,9,10), "city": ALL_MONTHS, "family": ALL_MONTHS,
        "food": ALL_MONTHS, "shopping": ALL_MONTHS, "quiet": M(1,2,8,11), "weather": M(4,5,6,9,10),
        "nightlife": ALL_MONTHS, "relax": M(4,5,6,9,10), "best_months": M(4,5,6,9,10),
    },
    "CDG": {
        "nature": M(4,5,6,7,8,9,10), "hiking": M(4,5,6,7,8,9,10), "city": ALL_MONTHS, "family": ALL_MONTHS,
        "food": ALL_MONTHS, "shopping": ALL_MONTHS, "weather": M(4,5,6,9,10), "nightlife": ALL_MONTHS,
        "relax": M(4,5,9,10), "best_months": M(4,5,6,9,10),
    },
    "AMS": {
        "nature": M(4,5,6,7,8,9), "hiking": M(4,5,6,7,8,9), "city": ALL_MONTHS, "family": ALL_MONTHS,
        "food": ALL_MONTHS, "shopping": ALL_MONTHS, "quiet": M(1,2,3,11), "weather": M(4,5,6,7,8,9),
        "nightlife": ALL_MONTHS, "relax": M(4,5,6,9), "best_months": M(4,5,6,9),
    },
    "BCN": {
        "beach": M(5,6,7,8,9,10), "nature": M(3,4,5,6,9,10,11), "hiking": M(3,4,5,6,9,10,11),
        "city": ALL_MONTHS, "family": ALL_MONTHS, "food": ALL_MONTHS, "shopping": ALL_MONTHS,
        "quiet": M(1,2,3,11), "weather": M(4,5,6,9,10), "nightlife": ALL_MONTHS, "relax": M(4,5,6,9,10),
        "best_months": M(4,5,6,9,10),
    },
    "MAD": {
        "nature": M(3,4,5,6,9,10,11), "hiking": M(3,4,5,6,9,10,11), "city": ALL_MONTHS, "family": ALL_MONTHS,
        "food": ALL_MONTHS, "shopping": ALL_MONTHS, "quiet": M(1,2,8,11), "weather": M(3,4,5,6,9,10,11),
        "nightlife": ALL_MONTHS, "relax": M(3,4,5,9,10,11), "best_months": M(4,5,6,9,10),
    },
    "LIS": {
        "beach": M(5,6,7,8,9,10), "nature": M(2,3,4,5,6,9,10,11), "hiking": M(2,3,4,5,6,9,10,11),
        "city": ALL_MONTHS, "family": ALL_MONTHS, "food": ALL_MONTHS, "shopping": ALL_MONTHS,
        "quiet": M(1,2,3,11,12), "weather": M(3,4,5,6,9,10,11), "nightlife": ALL_MONTHS, "relax": M(3,4,5,6,9,10,11),
        "best_months": M(4,5,6,9,10),
    },
    "LHR": {
        "nature": M(4,5,6,7,8,9), "hiking": M(4,5,6,7,8,9), "city": ALL_MONTHS, "family": ALL_MONTHS,
        "food": ALL_MONTHS, "shopping": ALL_MONTHS, "weather": M(5,6,7,8,9), "nightlife": ALL_MONTHS,
        "relax": M(5,6,7,8,9), "best_months": M(5,6,7,8,9),
    },
    "BER": {
        "nature": M(4,5,6,7,8,9), "hiking": M(4,5,6,7,8,9), "city": ALL_MONTHS, "family": ALL_MONTHS,
        "food": ALL_MONTHS, "shopping": ALL_MONTHS, "quiet": M(1,2,3,11), "weather": M(5,6,7,8,9),
        "nightlife": ALL_MONTHS, "relax": M(4,5,6,9), "best_months": M(5,6,7,8,9),
    },
    "MUC": {
        "nature": M(4,5,6,7,8,9,10), "hiking": M(5,6,7,8,9,10), "city": ALL_MONTHS, "family": ALL_MONTHS,
        "food": ALL_MONTHS, "shopping": ALL_MONTHS, "quiet": M(1,2,3,11), "weather": M(5,6,7,8,9),
        "nightlife": ALL_MONTHS, "relax": M(4,5,6,9,10), "best_months": M(5,6,9),
    },
    "ZRH": {
        "nature": ALL_MONTHS, "hiking": M(5,6,7,8,9,10), "city": ALL_MONTHS, "family": ALL_MONTHS,
        "food": ALL_MONTHS, "shopping": ALL_MONTHS, "quiet": M(1,2,3,4,10,11,12), "weather": M(5,6,7,8,9),
        "relax": M(4,5,6,7,8,9,10), "best_months": M(5,6,7,8,9),
    },
    "BRU": {
        "nature": M(4,5,6,7,8,9), "hiking": M(4,5,6,7,8,9), "city": ALL_MONTHS, "family": ALL_MONTHS,
        "food": ALL_MONTHS, "shopping": ALL_MONTHS, "quiet": M(1,2,3,11), "weather": M(5,6,7,8,9),
        "nightlife": ALL_MONTHS, "relax": M(4,5,6,9), "best_months": M(5,6,7,8,9),
    },
    "OTP": {
        "nature": M(4,5,6,7,8,9,10), "hiking": M(4,5,6,7,8,9,10), "city": ALL_MONTHS, "family": ALL_MONTHS,
        "food": ALL_MONTHS, "shopping": ALL_MONTHS, "quiet": M(1,2,3,11), "weather": M(4,5,6,9,10),
        "nightlife": ALL_MONTHS, "relax": M(4,5,6,9,10), "best_months": M(5,6,9,10),
    },
    "KRK": {
        "nature": M(4,5,6,7,8,9,10), "hiking": M(5,6,7,8,9,10), "city": ALL_MONTHS, "family": ALL_MONTHS,
        "food": ALL_MONTHS, "shopping": ALL_MONTHS, "quiet": M(1,2,3,11), "weather": M(5,6,7,8,9),
        "nightlife": ALL_MONTHS, "relax": M(4,5,6,9,10), "best_months": M(5,6,9),
    },
    "WAW": {
        "nature": M(4,5,6,7,8,9), "hiking": M(4,5,6,7,8,9), "city": ALL_MONTHS, "family": ALL_MONTHS,
        "food": ALL_MONTHS, "shopping": ALL_MONTHS, "quiet": M(1,2,3,11), "weather": M(5,6,7,8,9),
        "nightlife": ALL_MONTHS, "relax": M(4,5,6,9), "best_months": M(5,6,7,8,9),
    },
    "TBS": {
        "nature": M(3,4,5,6,7,8,9,10,11), "hiking": M(4,5,6,7,8,9,10), "city": ALL_MONTHS, "family": M(3,4,5,6,7,8,9,10,11),
        "food": ALL_MONTHS, "shopping": ALL_MONTHS, "quiet": M(1,2,3,4,10,11,12), "weather": M(4,5,6,9,10),
        "nightlife": ALL_MONTHS, "relax": M(4,5,6,9,10), "best_months": M(5,6,9,10),
    },
    "EVN": {
        "nature": M(4,5,6,7,8,9,10), "hiking": M(5,6,7,8,9,10), "city": ALL_MONTHS, "family": M(4,5,6,7,8,9,10),
        "food": ALL_MONTHS, "shopping": ALL_MONTHS, "quiet": M(1,2,3,4,10,11,12), "weather": M(5,6,9,10),
        "nightlife": ALL_MONTHS, "relax": M(4,5,6,9,10), "best_months": M(5,6,9,10),
    },
    "BEG": {
        "nature": M(4,5,6,7,8,9,10), "hiking": M(4,5,6,7,8,9,10), "city": ALL_MONTHS, "family": ALL_MONTHS,
        "food": ALL_MONTHS, "shopping": ALL_MONTHS, "quiet": M(1,2,3,11), "weather": M(4,5,6,9,10),
        "nightlife": ALL_MONTHS, "relax": M(4,5,6,9,10), "best_months": M(5,6,9,10),
    },
    "SKP": {
        "nature": M(3,4,5,6,7,8,9,10,11), "hiking": M(4,5,6,7,8,9,10), "city": ALL_MONTHS, "family": ALL_MONTHS,
        "food": ALL_MONTHS, "shopping": M(3,4,5,6,7,8,9,10,11), "quiet": M(1,2,3,4,10,11,12), "weather": M(4,5,6,9,10),
        "nightlife": M(4,5,6,7,8,9,10), "relax": M(4,5,6,9,10), "best_months": M(5,6,9,10),
    },
    "TGD": {
        "beach": M(5,6,7,8,9), "nature": M(3,4,5,6,7,8,9,10,11), "hiking": M(4,5,6,7,8,9,10),
        "city": M(3,4,5,6,7,8,9,10,11), "family": M(4,5,6,7,8,9,10), "food": ALL_MONTHS,
        "quiet": M(1,2,3,4,10,11,12), "weather": M(4,5,6,9,10), "relax": M(4,5,6,7,8,9,10),
        "best_months": M(5,6,9),
    },
    "ZAG": {
        "nature": M(3,4,5,6,7,8,9,10,11), "hiking": M(5,6,7,8,9,10), "city": ALL_MONTHS, "family": ALL_MONTHS,
        "food": ALL_MONTHS, "shopping": ALL_MONTHS, "quiet": M(1,2,3,11), "weather": M(4,5,6,9,10),
        "nightlife": ALL_MONTHS, "relax": M(4,5,6,9,10), "best_months": M(5,6,9,10),
    },
    "LJU": {
        "nature": ALL_MONTHS, "hiking": M(5,6,7,8,9,10), "city": ALL_MONTHS, "family": ALL_MONTHS,
        "food": ALL_MONTHS, "shopping": M(3,4,5,6,7,8,9,10,11), "quiet": M(1,2,3,4,10,11,12), "weather": M(5,6,7,8,9),
        "relax": M(4,5,6,7,8,9,10), "best_months": M(5,6,9),
    },
    "BKK": {
        "beach": M(1,2,3,4,11,12), "nature": M(1,2,3,4,11,12), "hiking": M(1,2,3,11,12), "city": ALL_MONTHS,
        "family": ALL_MONTHS, "food": ALL_MONTHS, "shopping": ALL_MONTHS, "quiet": M(1,2,3,4,11,12),
        "weather": M(1,2,3,11,12), "nightlife": ALL_MONTHS, "relax": M(1,2,3,4,11,12), "best_months": M(1,2,3,11,12),
    },
    "JFK": {
        "nature": M(4,5,6,7,8,9,10), "hiking": M(4,5,6,7,8,9,10), "city": ALL_MONTHS, "family": ALL_MONTHS,
        "food": ALL_MONTHS, "shopping": ALL_MONTHS, "quiet": M(1,2), "weather": M(4,5,6,9,10),
        "nightlife": ALL_MONTHS, "relax": M(4,5,6,9,10), "best_months": M(4,5,6,9,10),
    },
}


def condition_met(destination_code: str, preference: str, month: int | None) -> bool:
    if not month:
        return False
    profile = DESTINATION_CONDITION_MONTHS.get(str(destination_code or "").upper(), {})
    return int(month) in profile.get(str(preference), frozenset())


def seasonality_met(destination_code: str, month: int | None) -> bool:
    if not month:
        return False
    profile = DESTINATION_CONDITION_MONTHS.get(str(destination_code or "").upper(), {})
    return int(month) in profile.get("best_months", frozenset())

CONDITION_KEYS = (
    "beach", "nature", "hiking", "city", "family", "food", "shopping",
    "quiet", "weather", "nightlife", "relax",
)
# Make the table explicit for every destination/condition: missing = never/0 points.
for _code, _profile in DESTINATION_CONDITION_MONTHS.items():
    for _key in CONDITION_KEYS:
        _profile.setdefault(_key, frozenset())

# Core destination traits prevent a generic city from receiving nature/hiking/etc.
# Month tables above decide *when* the trait earns its point; this list decides
# whether the destination is genuinely known for that kind of holiday at all.
DESTINATION_BASE_TRAITS = {
    "ATH": {"beach","city","family","food","shopping","nightlife"},
    "LCA": {"beach","nature","hiking","family","food","quiet","weather","relax"},
    "BUD": {"city","family","food","shopping","nightlife"},
    "VIE": {"city","family","food","shopping"},
    "SOF": {"city","nature","hiking","food","quiet"},
    "PRG": {"city","family","food","shopping","nightlife"},
    "FCO": {"city","family","food","shopping"},
    "MXP": {"city","food","shopping","nightlife"},
    "CDG": {"city","family","food","shopping"},
    "AMS": {"city","family","food","nightlife"},
    "BCN": {"beach","city","family","food","shopping","nightlife"},
    "MAD": {"city","food","shopping","nightlife"},
    "LIS": {"city","food","weather","relax"},
    "LHR": {"city","family","food","shopping","nightlife"},
    "BER": {"city","food","shopping","nightlife"},
    "MUC": {"city","nature","hiking","family","food"},
    "ZRH": {"city","nature","hiking","family","quiet","relax"},
    "BRU": {"city","food","shopping"},
    "OTP": {"city","food","shopping","nightlife"},
    "KRK": {"city","food","quiet"},
    "WAW": {"city","food","shopping"},
    "TBS": {"city","nature","hiking","food","quiet"},
    "EVN": {"city","nature","hiking","food","quiet"},
    "BEG": {"city","food","nightlife"},
    "SKP": {"city","nature","hiking","food","quiet"},
    "TGD": {"beach","nature","hiking","family","quiet","relax"},
    "ZAG": {"city","nature","hiking","family","food","quiet"},
    "LJU": {"city","nature","hiking","family","quiet","relax"},
    "BKK": {"beach","city","nature","family","food","shopping","nightlife","weather","relax"},
    "JFK": {"city","family","food","shopping","nightlife"},
}

# Weather is evaluated from the explicit weather-month table even when it is not
# a defining destination trait. All other style conditions require a core trait.
for _code, _profile in DESTINATION_CONDITION_MONTHS.items():
    _traits = DESTINATION_BASE_TRAITS.get(_code, set())
    for _key in CONDITION_KEYS:
        if _key != "weather" and _key not in _traits:
            _profile[_key] = frozenset()
