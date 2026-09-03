from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCANNER = ROOT / "scanner.py"
DATABASE = ROOT / "database.py"
DEAL_CARD = ROOT / "templates" / "_deal_card.html"

text = SCANNER.read_text(encoding="utf-8")

helper_marker = "def _extract_bag_number(text: str):\n"
helper_code = r'''
def _fare_family_options_from_booking_data(data: dict, base_price=None) -> list[dict]:
    """Return real airline fare-family alternatives from Google/SerpApi booking data.

    We intentionally do not invent bundle names or inclusions. Only direct-airline,
    non-separate booking options that carry a provider-supplied option_title are shown.
    The existing booking-options request is reused, so this adds zero SerpApi calls.
    """
    rows = []
    seen = set()
    try:
        base = float(base_price) if isinstance(base_price, (int, float)) else None
    except (TypeError, ValueError):
        base = None

    for group in data.get("booking_options") or []:
        if not isinstance(group, dict) or group.get("separate_tickets"):
            continue
        option = group.get("together")
        if not isinstance(option, dict) or option.get("airline") is not True:
            continue
        title = str(option.get("option_title") or "").strip()
        price = _ils_price(option)
        if not title or price is None:
            continue

        features = []
        for value in (option.get("extensions") or []):
            value = str(value or "").strip()
            if value and value not in features:
                features.append(value)
        for value in (option.get("baggage_prices") or []):
            value = str(value or "").strip()
            if value and value not in features:
                features.append(value)

        key = (title.casefold(), round(float(price), 2))
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "name": title,
            "price_ils": float(price),
            "additional_ils": max(0.0, float(price) - base) if base is not None else None,
            "features": features[:8],
            "supplier": str(option.get("book_with") or "").strip() or None,
            "source": "serpapi_booking_options",
        })

    rows.sort(key=lambda x: x["price_ils"])
    return rows


'''
if "def _fare_family_options_from_booking_data" not in text:
    if helper_marker not in text:
        raise RuntimeError("fare options patch: helper insertion marker not found")
    text = text.replace(helper_marker, helper_code + helper_marker, 1)

assign_marker = '    flight["booking_options_checked"] = len(all_priced)\n'
assign_code = '    flight["booking_options_checked"] = len(all_priced)\n    flight["fare_options"] = _fare_family_options_from_booking_data(data, flight.get("price"))\n'
if 'flight["fare_options"] = _fare_family_options_from_booking_data' not in text:
    if assign_marker not in text:
        raise RuntimeError("fare options patch: booking assignment marker not found")
    text = text.replace(assign_marker, assign_code, 1)

if "def _fare_family_options_from_booking_data" not in text or 'flight["fare_options"]' not in text:
    raise RuntimeError("fare options patch: scanner verification failed")
compile(text, str(SCANNER), "exec")
SCANNER.write_text(text, encoding="utf-8")

# Expose stored fare families to the public offer object. They already live in
# payload_json, so no DB schema migration is required.
db_text = DATABASE.read_text(encoding="utf-8")
db_marker = '            "booking_options_checked": flight.get("booking_options_checked"),\n'
db_replacement = db_marker + '            "fare_options": flight.get("fare_options") or [],\n'
if '"fare_options": flight.get("fare_options") or []' not in db_text:
    if db_marker not in db_text:
        raise RuntimeError("fare options patch: database mapping marker not found")
    db_text = db_text.replace(db_marker, db_replacement, 1)
compile(db_text, str(DATABASE), "exec")
DATABASE.write_text(db_text, encoding="utf-8")

# Customer UI: keep the cheapest standard price clean, then reveal real airline
# bundles only on demand. Native <details> gives keyboard/mobile accessibility
# without JavaScript and does not make another API request when opened.
card = DEAL_CARD.read_text(encoding="utf-8")
price_marker = '      <strong>₪{{ \'%.0f\'|format(offer.price_ils) }}</strong>\n'
fare_ui = r'''      <strong>₪{{ '%.0f'|format(offer.price_ils) }}</strong>
      {% if offer.fare_options %}
      <details class="fare-options">
        <summary>{{ 'More options' if lang=='en' else 'אפשרויות נוספות' }}</summary>
        <div class="fare-options-list">
          {% for fare in offer.fare_options %}
          <div class="fare-option">
            <div class="fare-option-head"><b>{{ fare.name }}</b><strong>₪{{ fare.price_ils|round|int }}</strong></div>
            {% if fare.features %}<ul>{% for feature in fare.features %}<li>{{ feature }}</li>{% endfor %}</ul>{% endif %}
          </div>
          {% endfor %}
        </div>
      </details>
      {% endif %}
'''
if 'class="fare-options"' not in card:
    if price_marker not in card:
        raise RuntimeError("fare options patch: deal-card price marker not found")
    card = card.replace(price_marker, fare_ui, 1)
DEAL_CARD.write_text(card, encoding="utf-8")

print("9.7.136 airline fare-family patch applied: real provider bundles + expandable UI")
