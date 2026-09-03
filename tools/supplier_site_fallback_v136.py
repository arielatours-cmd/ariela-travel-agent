from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BOOKER = ROOT / "booker.py"

text = BOOKER.read_text(encoding="utf-8")
start = text.find("def resolve_booking_target(")
if start < 0:
    raise RuntimeError("booking target resolver not found")
next_def = text.find("\ndef ", start + 1)
end = next_def if next_def >= 0 else len(text)
current = text[start:end]

needle = '''    return BookerTarget(
        url=None,
        fields=[],
        supplier=recommended,
        mode="recommended_supplier_unavailable",
        exact=False,
        note="מסלול ההזמנה אצל הספק המומלץ אינו זמין כרגע.",
    )
'''
replacement = '''    # Historical/shared offers can predate persisted Booking Options. Do not bounce
    # a customer back to Ariella when we still know the operating airline. In that
    # case open the airline's official booking site as the final safe fallback.
    official_sites = {
        "wizz air": "https://wizzair.com/",
        "wizzair": "https://wizzair.com/",
        "w6": "https://wizzair.com/",
        "ryanair": "https://www.ryanair.com/",
        "fr": "https://www.ryanair.com/",
        "easyjet": "https://www.easyjet.com/",
        "u2": "https://www.easyjet.com/",
        "el al": "https://www.elal.com/",
        "elal": "https://www.elal.com/",
        "ly": "https://www.elal.com/",
        "arkia": "https://www.arkia.co.il/",
        "iz": "https://www.arkia.co.il/",
        "israir": "https://www.israir.co.il/",
        "6h": "https://www.israir.co.il/",
        "aegean": "https://en.aegeanair.com/",
        "aegean airlines": "https://en.aegeanair.com/",
        "a3": "https://en.aegeanair.com/",
        "lufthansa": "https://www.lufthansa.com/",
        "lh": "https://www.lufthansa.com/",
        "air france": "https://wwws.airfrance.co.il/",
        "af": "https://wwws.airfrance.co.il/",
        "klm": "https://www.klm.co.il/",
        "british airways": "https://www.britishairways.com/",
        "ba": "https://www.britishairways.com/",
        "turkish airlines": "https://www.turkishairlines.com/",
        "tk": "https://www.turkishairlines.com/",
        "emirates": "https://www.emirates.com/",
        "ek": "https://www.emirates.com/",
        "etihad airways": "https://www.etihad.com/",
        "etihad": "https://www.etihad.com/",
        "ey": "https://www.etihad.com/",
        "ita airways": "https://www.ita-airways.com/",
        "az": "https://www.ita-airways.com/",
    }
    airline_candidates = [
        recommended,
        offer.get("airline"),
        (offer.get("flight") or {}).get("airline"),
        (offer.get("flight") or {}).get("airline_code"),
        (offer.get("flight") or {}).get("outbound_airline_code"),
    ]
    for value in airline_candidates:
        site = official_sites.get(_norm(value))
        if site:
            return BookerTarget(
                url=site,
                fields=[],
                supplier=str(value or recommended),
                mode="official_airline_site_fallback",
                exact=False,
                note="יש לבחור באתר חברת התעופה את התאריכים והטיסות המוצגים בדיל.",
            )

    # If the stored booking_url is already a non-Google supplier URL, use it.
    raw_booking_url = str(offer.get("booking_url") or "").strip()
    if raw_booking_url and "google.com/travel/flights" not in raw_booking_url.lower():
        return BookerTarget(
            url=raw_booking_url,
            fields=[],
            supplier=recommended,
            mode="stored_non_google_booking_url_fallback",
            exact=False,
        )

    return BookerTarget(
        url=None,
        fields=[],
        supplier=recommended,
        mode="recommended_supplier_unavailable",
        exact=False,
        note="מסלול ההזמנה אצל הספק המומלץ אינו זמין כרגע.",
    )
'''
if needle not in current:
    raise RuntimeError("supplier fallback insertion point not found")
current = current.replace(needle, replacement, 1)
text = text[:start] + current + text[end:]
BOOKER.write_text(text, encoding="utf-8")
print("9.7.136 official supplier site fallback active")
