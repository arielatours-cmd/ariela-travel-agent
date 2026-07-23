def _minutes_to_hhmm(minutes):
    if not isinstance(minutes, (int, float)):
        return "לא ידוע"
    return f"{int(minutes)//60}:{int(minutes)%60:02d}"


def _extract_time(value):
    return value[-5:] if value else "לא ידוע"


def _baggage_line(label, item):
    if item.get("included"):
        return f"✅ {label}"
    price = item.get("price_each_way")
    if isinstance(price, (int, float)):
        return f"❌ {label} — {price:.0f} ₪ לאדם לכל כיוון"
    return f"❌ {label} — המחיר יופיע לפני ההזמנה"


def _format_connections(flight):
    stops = int(flight.get("stops") or 0)
    if stops == 0:
        return f"🟢 טיסה ישירה\n⏱️ משך הטיסה: {_minutes_to_hhmm(flight.get('total_duration_minutes'))} שעות"
    connections = flight.get("connections") or []
    if stops == 1:
        place = connections[0].get("airport") if connections else "שדה ביניים"
        wait = _minutes_to_hhmm(connections[0].get("duration_minutes")) if connections else "לא ידוע"
        return f"🟡 קונקשן אחד – {place}\n✈️ זמן טיסה: {_minutes_to_hhmm(flight.get('actual_flight_duration_minutes'))} │ ⏳ המתנה: {wait} │ 🕒 הגעה כוללת: {_minutes_to_hhmm(flight.get('total_duration_minutes'))}"
    places = " │ ".join(f"📍 {x.get('airport', 'שדה ביניים')}: {_minutes_to_hhmm(x.get('duration_minutes'))}" for x in connections)
    return f"🔴 {stops} קונקשנים\n{places}\n✈️ זמן טיסה: {_minutes_to_hhmm(flight.get('actual_flight_duration_minutes'))} │ 🕒 הגעה כוללת: {_minutes_to_hhmm(flight.get('total_duration_minutes'))}"


def format_deal(deal):
    flight = deal["flight"]
    regular = deal.get("deal_analysis", {}).get("typical_price_low")
    current = flight.get("price")
    price_line = f"*{current:.0f} ₪ לאדם*" if isinstance(current, (int, float)) else "*מחיר לא זמין*"
    if isinstance(regular, (int, float)) and isinstance(current, (int, float)):
        price_line = f"~{regular:.0f} ₪~ → *{current:.0f} ₪ לאדם*"

    baggage = flight.get("baggage") or {}
    origin_name = deal.get("departure_airport_name") or deal["departure_code"]
    dest_name = deal.get("arrival_airport_name") or deal["arrival_code"]
    color = "🟢" if flight.get("stops", 0) == 0 else "🟡" if flight.get("stops", 0) == 1 else "🔴"

    return "\n".join([
        f"{color} {deal.get('country_flag', '')} *{origin_name} ({deal['departure_code']}) ✈ {dest_name} ({deal['arrival_code']})*",
        "",
        "🛫 *יציאה*", deal["outbound"]["display_he"],
        f"{_extract_time(flight.get('departure_time'))} המראה │ {_extract_time(flight.get('arrival_time'))} נחיתה",
        "",
        "🛬 *חזרה*", deal["return"]["display_he"],
        "שעות החזרה יוצגו בקישור ההזמנה.",
        "",
        f"✈️ *{flight.get('airline') or 'חברת תעופה'}*",
        _format_connections(flight),
        "",
        price_line,
        "המחיר כולל מיסים ותשלומי חובה לפי תוצאת החיפוש.",
        "",
        "🧳 *כבודה*",
        _baggage_line("תיק יד", baggage.get("personal_item", {})),
        _baggage_line("טרולי 8 ק״ג", baggage.get("carry_on_8kg", {})),
        _baggage_line("מזוודה עד 23 ק״ג", baggage.get("checked_bag_23kg", {})),
        "",
        "⭐ הדיל נבחר לאחר שקלול המחיר ואיכות המסלול.",
        deal.get("booking_url") or "קישור הזמנה לא זמין כרגע",
    ])


def build_daily_message(deals):
    if not deals:
        return ""
    parts = ["✈️ *הדילים של אריאלה*", "החופש שמתאים לך", "", f"היום עברו את הסינון שלנו {len(deals)} דילים:", ""]
    for index, deal in enumerate(deals):
        if index:
            parts.append("━━━━━━━━━━━━━━━━━━")
        parts.append(format_deal(deal))
    return "\n".join(parts)
