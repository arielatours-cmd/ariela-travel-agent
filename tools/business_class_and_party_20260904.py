from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Personal booking route: derive the party correctly for regular, ski and business trips.
p = ROOT / 'public_site.py'
t = p.read_text(encoding='utf-8')
old = '''    adults = children = None
    if personal_trip is not None:
        answers = personal_trip.get("answers") or {}
        try:
            adults = max(1, int(answers.get("adults") or 1))
        except (TypeError, ValueError):
            adults = 1
        try:
            children = max(0, int(answers.get("children") or 0))
        except (TypeError, ValueError):
            children = 0
'''
new = '''    adults = children = None
    if personal_trip is not None:
        answers = personal_trip.get("answers") or {}
        vacation_type = str(answers.get("vacation_type") or "standard")
        def _as_int(value, default=0):
            try:
                return int(value)
            except (TypeError, ValueError):
                return default
        if vacation_type == "business":
            adults = max(1, _as_int(answers.get("business_travelers"), 1))
            children = 0
        elif vacation_type == "ski":
            if str(answers.get("ski_travel_party") or "") == "family":
                adults = max(1, _as_int(answers.get("ski_family_adults"), _as_int(answers.get("ski_adults"), 2)))
                children = max(0, _as_int(answers.get("ski_children"), 0))
            else:
                adults = max(1, _as_int(answers.get("ski_adults"), 1))
                children = 0
        else:
            if str(answers.get("travel_party") or "") == "family":
                adults = max(1, _as_int(answers.get("family_adults"), 2))
                children = max(0, _as_int(answers.get("children"), 0))
            else:
                adults = max(1, _as_int(answers.get("adults"), 1))
                children = max(0, _as_int(answers.get("children"), 0))
'''
if old in t:
    t = t.replace(old, new, 1)
else:
    raise RuntimeError('personal party booking block not found')
p.write_text(t, encoding='utf-8')

# Scanner: allow a requested cabin class without changing general-discovery scans.
p = ROOT / 'scanner.py'
t = p.read_text(encoding='utf-8')
t = t.replace(
    'def _roundtrip_params(departure: str, arrival: str, outbound_date: str, return_date: str, adults: int = 1, children: int = 0) -> dict:',
    'def _roundtrip_params(departure: str, arrival: str, outbound_date: str, return_date: str, adults: int = 1, children: int = 0, travel_class: str = "1") -> dict:',
    1,
)
t = t.replace('        "travel_class": "1",\n        "adults": str(max(1, int(adults or 1))),', '        "travel_class": str(travel_class or "1"),\n        "adults": str(max(1, int(adults or 1))),', 1)
t = t.replace(
    'def search_flights(departure: str, arrival: str, outbound_date: str, return_date: str, max_outbounds: int | None = None, adults: int = 1, children: int = 0) -> dict:',
    'def search_flights(departure: str, arrival: str, outbound_date: str, return_date: str, max_outbounds: int | None = None, adults: int = 1, children: int = 0, travel_class: str = "1") -> dict:',
    1,
)
t = t.replace(
    'params = _roundtrip_params(departure, arrival, outbound_date, return_date, adults=adults, children=children)\n    outbound_data = _serpapi_request(params)',
    'params = _roundtrip_params(departure, arrival, outbound_date, return_date, adults=adults, children=children, travel_class=travel_class)\n    outbound_data = _serpapi_request(params)',
    1,
)
# Only customer search gets the business cabin request. General scans remain economy.
old_call = '                result = search_flights(job["departure"], job["arrival"], job["outbound"], job["return"])\n                api_requests += int(result.get("api_requests") or 0)'
new_call = '''                cabin_map = {"economy":"1", "premium":"2", "business":"3", "first":"4", "any":"1"}
                requested_class = cabin_map.get(str(answers.get("business_cabin_class") or "economy").lower(), "1") if str(answers.get("vacation_type") or "standard") == "business" else "1"
                result = search_flights(job["departure"], job["arrival"], job["outbound"], job["return"], travel_class=requested_class)
                api_requests += int(result.get("api_requests") or 0)'''
# The first occurrence inside run_customer_trip_search is the intended one after v136.
idx = t.find(old_call)
if idx < 0:
    raise RuntimeError('customer search_flights call not found')
t = t[:idx] + t[idx:].replace(old_call, new_call, 1)
p.write_text(t, encoding='utf-8')

print('2026-09-04 business cabin + exact passenger booking context active')
