from flask import Flask, jsonify, request
from datetime import datetime, timedelta, date, time as dtime
from zoneinfo import ZoneInfo
import os, time, json, base64, hmac, hashlib

app = Flask(__name__)
TZ = ZoneInfo("Asia/Jerusalem")
DAYS = {0:"יום שני",1:"יום שלישי",2:"יום רביעי",3:"יום חמישי",4:"יום שישי",5:"שבת",6:"יום ראשון"}

def sample_deals():
    now = datetime.now(TZ)
    out = (now + timedelta(days=21)).date().isoformat()
    ret = (now + timedelta(days=25)).date().isoformat()
    return [
        {
            "deal_id": f"AT-{now:%y%m%d}-001",
            "origin_name": "נתב״ג", "origin_code": "TLV",
            "destination_name": "אתונה", "destination_code": "ATH",
            "flag": "🇬🇷", "airline": "Aegean Airlines",
            "outbound_date": out, "outbound_departure": "08:35", "outbound_arrival": "10:45",
            "return_date": ret, "return_departure": "21:10", "return_arrival": "23:20",
            "stops": 0, "connection_cities": [], "flight_time": "2:10", "layovers": [], "total_time": "2:10",
            "regular_price_ils": 1080, "deal_price_ils": 820, "bag_summary": "ללא כבודה",
            "hand_bag": {"included": True},
            "trolley": {"included": False, "price": "35€", "estimated": True},
            "checked_bag": {"included": False, "price": "72€", "estimated": True},
            "last_checked": now.strftime("%H:%M")
        },
        {
            "deal_id": f"AT-{now:%y%m%d}-002",
            "origin_name": "חיפה", "origin_code": "HFA",
            "destination_name": "לרנקה", "destination_code": "LCA",
            "flag": "🇨🇾", "airline": "Air Haifa",
            "outbound_date": out, "outbound_departure": "07:20", "outbound_arrival": "08:20",
            "return_date": ret, "return_departure": "18:40", "return_arrival": "19:40",
            "stops": 0, "connection_cities": [], "flight_time": "1:00", "layovers": [], "total_time": "1:00",
            "regular_price_ils": 930, "deal_price_ils": 655, "bag_summary": "כולל תיק יד",
            "hand_bag": {"included": True},
            "trolley": {"included": False, "price": "40€", "estimated": True},
            "checked_bag": {"included": False, "price": "75€", "estimated": True},
            "last_checked": now.strftime("%H:%M")
        },
        {
            "deal_id": f"AT-{now:%y%m%d}-003",
            "origin_name": "נתב״ג", "origin_code": "TLV",
            "destination_name": "פריז", "destination_code": "CDG",
            "flag": "🇫🇷", "airline": "Lufthansa",
            "outbound_date": out, "outbound_departure": "06:15", "outbound_arrival": "12:05",
            "return_date": ret, "return_departure": "14:20", "return_arrival": "22:15",
            "stops": 1, "connection_cities": ["מינכן"], "flight_time": "4:15", "layovers": ["1:35"], "total_time": "5:50",
            "regular_price_ils": 1680, "deal_price_ils": 1190, "bag_summary": "כולל טרולי",
            "hand_bag": {"included": True},
            "trolley": {"included": True},
            "checked_bag": {"included": False, "price": "85€", "estimated": True},
            "last_checked": now.strftime("%H:%M")
        }
    ]

def enrich(deal):
    regular = deal["regular_price_ils"]
    price = deal["deal_price_ils"]
    saving = max(regular - price, 0)
    stops = deal["stops"]
    score = round((saving / max(regular, 1)) * 65 + ({0:25,1:12}.get(stops,3)), 2)
    fee = int(round(min(max(price * 0.10 - 5, 0), saving / 2)))
    reason = (
        f"טיסה ישירה במחיר נמוך מהרגיל, עם חיסכון של כ־{saving} ₪ לאדם."
        if stops == 0 else
        f"מחיר אטרקטיבי למרות קונקשן אחד, עם חיסכון של כ־{saving} ₪ לאדם."
        if stops == 1 else
        f"חיסכון משמעותי של כ־{saving} ₪ לאדם למרות מספר קונקשנים."
    )
    return {**deal, "score": score, "service_fee_ils": fee, "reason": reason}

def ranked_deals(limit=5):
    return sorted((enrich(d) for d in sample_deals()), key=lambda d: d["score"], reverse=True)[:limit]

def bag_line(label, bag):
    if bag.get("included"):
        return f"✅ {label}"
    estimate = " (הערכה)" if bag.get("estimated") else ""
    return f"❌ {label} — {bag.get('price','המחיר טרם התקבל')}{estimate} לאדם לכל כיוון"

def day_name(iso_date):
    return DAYS[date.fromisoformat(iso_date).weekday()]

def connection_lines(d):
    if d["stops"] == 0:
        return ["🟢 טיסה ישירה", "", f"⏱️ משך הטיסה: {d['flight_time']}"]
    if d["stops"] == 1:
        return [
            f"🟡 קונקשן אחד – {d['connection_cities'][0]}",
            "",
            f"✈️ זמן טיסה: {d['flight_time']} │ ⏳ המתנה: {d['layovers'][0]} │ 🕒 הגעה כוללת: {d['total_time']}"
        ]
    return [f"🔴 {d['stops']} קונקשנים", "", f"✈️ זמן טיסה: {d['flight_time']} │ 🕒 הגעה כוללת: {d['total_time']}"]

def format_deal(d):
    icon = "🟢" if d["stops"] == 0 else "🟡" if d["stops"] == 1 else "🔴"
    lines = [
        f"{icon} {d['flag']} {d['origin_name']} ({d['origin_code']}) ✈ {d['destination_name']} ({d['destination_code']})",
        f"מזהה דיל: {d['deal_id']}", "",
        "🛫 יציאה", "",
        f"{day_name(d['outbound_date'])} · {d['outbound_date']}",
        f"{d['outbound_departure']} המראה │ {d['outbound_arrival']} נחיתה", "",
        "🛬 חזרה", "",
        f"{day_name(d['return_date'])} · {d['return_date']}",
        f"{d['return_departure']} המראה │ {d['return_arrival']} נחיתה", "",
        f"✈️ {d['airline']}", "",
        *connection_lines(d), "",
        f"~~{d['regular_price_ils']} ₪~~ → {d['deal_price_ils']} ₪ לאדם ({d['bag_summary']})", "",
        "🧳 כבודה", "",
        bag_line("תיק יד", d["hand_bag"]), "",
        bag_line("טרולי 8 ק״ג", d["trolley"]), "",
        bag_line("מזוודה עד 23 ק״ג", d["checked_bag"]), "",
        "✨ דמי טיפול", "",
        f"{d['service_fee_ils']} ₪ לאדם", "",
        f"⭐ הדיל הזה נבחר כי {d['reason']}", "",
        "⏳ קישור ההזמנה תקף ל־30 דקות",
        f"🕔 הדיל נבדק לאחרונה בשעה {d['last_checked']}"
    ]
    return "\n".join(lines)

def daily_message():
    deals = ranked_deals()
    header = [
        "✈️ הדילים של אריאלה", "",
        DAYS[datetime.now(TZ).weekday()],
        f"נסרקו {len(sample_deals())} אפשרויות",
        f"רק {len(deals)} דילים עברו את מנגנון האיכות"
    ]
    return "\n".join(header) + "\n\n━━━━━━━━━━━━━━\n\n" + "\n\n━━━━━━━━━━━━━━\n\n".join(format_deal(d) for d in deals)

def shabbat_blocked():
    now = datetime.now(TZ)
    return (now.weekday() == 4 and now.time() >= dtime(17,0)) or (now.weekday() == 5 and now.time() < dtime(20,0))

def secret():
    return os.getenv("BOOKING_LINK_SECRET", "change-me-in-render").encode()

def encode(data):
    return base64.urlsafe_b64encode(data).decode().rstrip("=")

def decode(value):
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))

def create_link(deal_id, supplier_url):
    expires_at = int(time.time()) + 1800
    payload = {"deal_id": deal_id, "supplier_url": supplier_url, "expires_at": expires_at}
    raw = json.dumps(payload, separators=(",",":"), ensure_ascii=False).encode()
    sig = hmac.new(secret(), raw, hashlib.sha256).digest()
    token = f"{encode(raw)}.{encode(sig)}"
    base = os.getenv("PUBLIC_BASE_URL","").rstrip("/")
    path = f"/book?token={token}"
    return {"deal_id": deal_id, "expires_at": expires_at, "valid_for_minutes": 30, "booking_url": base + path if base else path, "token": token}

def verify_link(token):
    try:
        payload_part, sig_part = token.split(".",1)
        raw = decode(payload_part)
        if not hmac.compare_digest(decode(sig_part), hmac.new(secret(), raw, hashlib.sha256).digest()):
            return {"valid": False, "error": "invalid signature"}
        payload = json.loads(raw.decode())
        if payload["expires_at"] < int(time.time()):
            return {"valid": False, "error": "booking link expired"}
        return {"valid": True, **payload}
    except Exception:
        return {"valid": False, "error": "invalid token"}

@app.get("/")
def home():
    return jsonify(service="Ariella Tours", version="5.0.0", status="running")

@app.get("/health")
def health():
    return jsonify(ok=True, version="5.0.0")

@app.get("/deals")
def deals():
    limit = min(max(request.args.get("limit", 5, type=int), 1), 5)
    data = ranked_deals(limit)
    return jsonify(count=len(data), deals=data)

@app.get("/message-preview")
def message_preview():
    return jsonify(message=daily_message())

@app.get("/delivery-status")
def delivery_status():
    blocked = shabbat_blocked()
    return jsonify(
        scheduled_daily_time="17:00",
        max_daily_deals=5,
        shabbat_blocked=blocked,
        send_allowed=not blocked,
        duplicate_protection=True,
        price_recheck_before_send=True
    )

@app.post("/booking-link")
def booking_link():
    data = request.get_json(silent=True) or {}
    if not data.get("deal_id") or not data.get("supplier_url"):
        return jsonify(error="deal_id and supplier_url are required"), 400
    return jsonify(create_link(data["deal_id"], data["supplier_url"]))

@app.get("/book")
def book():
    result = verify_link(request.args.get("token",""))
    return (jsonify(result), 200 if result.get("valid") else 400)
