"""שקד — בדיקה מקצה לקצה: סימון התנאי שלא מתקיים חייב להגיע ל-HTML של כרטיס החופשה ב-/account.

רקע: חופשה 259 (#158, 20.10). אחרי rematch הטיסות הוצגו, אבל בלי "לא כולל: תקציב" ובלי "לא כולל: טיסה ישירה".
הבדיקה בונה חופשה עם חמש הצעות. כל הצעה מפספסת תנאי אחר: תקציב, ישירה, שעה, תאריכים, אורך.
אחר כך היא מצמידה את ההצעות דרך שרשרת ההתאמה האמיתית (_match_and_pin_initial_offers), מרנדרת את /account של הלקוחה,
ובודקת שכל כרטיס מציג את התנאי שהוא מפספס.
עוד שתי בדיקות:
- תקציב במטבע זר (אירו): הסכום שנשמר ב-answers חייב להיות מומר לש"ח, או לפחות לשמור את המטבע.
- מחיר לאדם מול מחיר כולל (2 מבוגרים): השוואה לתקציב לאדם חייבת להיעשות על מחיר לאדם.
הרצה (על עותק של העץ, לא על DB אמיתי): python3 qa/e2e_vacation_card_conditions.py
"""
import json, os, re, sqlite3, sys
from datetime import datetime, timezone
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")
import database
database.init_db()
import public_site
from app import app

FAILED = []
def check(name, cond, detail=""):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}" + (f" — {detail}" if detail and not cond else ""))
    if not cond:
        FAILED.append(name)

MEMBER = 999301
def db():
    c = sqlite3.connect(database.DB_PATH); c.row_factory = sqlite3.Row; return c

with db() as c:
    c.execute("DELETE FROM members WHERE id=?", (MEMBER,))
    c.execute("INSERT INTO members (id, full_name,email,phone,password_hash,created_at,status,whatsapp_opt_in,preferred_airports) "
              "VALUES(?,?,?,?,?,datetime('now'),'active',0,'[]')", (MEMBER, "QA שקד כרטיס", "qa-card@example.com", "0500000301", "x"))
    c.commit()

def make_trip(tid, answers):
    with db() as c:
        c.execute("DELETE FROM trip_requests WHERE id=?", (tid,))
        c.execute("INSERT INTO trip_requests (id, member_id, request_name, travel_window, status, answers_json, created_at) "
                  "VALUES(?,?,?,?,?,?,datetime('now'))", (tid, MEMBER, "ליסבון", "2027-03-21 - 2027-03-25", "active", json.dumps(answers, ensure_ascii=False)))
        c.commit()
    with db() as c:
        return public_site._trip_dict(c.execute("SELECT * FROM trip_requests WHERE id=?", (tid,)).fetchone())

def make_offer(price, out, ret, stops=0, dep_time="2027-03-21 19:00"):
    flight = {"departure_time": dep_time, "arrival_time": out + " 23:00", "return_departure_time": ret + " 14:00",
              "return_arrival_time": ret + " 18:00", "stops": stops,
              "baggage": {"carry_on_8kg": {"included": True}, "checked_bag_23kg": {"included": True}}}
    with db() as c:
        run = c.execute("INSERT INTO scan_runs (started_at, status, searches_planned) VALUES (datetime('now'),'done',1)").lastrowid
        oid = c.execute("""INSERT INTO offers (scan_run_id, observed_at, route, departure_code, arrival_code, outbound_date, return_date,
                 price_ils, score, score_label, departure_time, arrival_time, payload_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                 (run, datetime.now(timezone.utc).isoformat(), "TLV-LIS", "TLV", "LIS", out, ret, price, 70, "good", dep_time,
                  out + " 23:00", json.dumps({"destination_name": "ליסבון", "flight": flight}, ensure_ascii=False))).lastrowid
        c.commit()
    return int(oid)

def pool(ids):
    return [public_site._localize_offer_airports(o) for o in database.recent_offers(limit=5000, minimum_score=None) if o.get("id") in ids]

def account_html(trip_id):
    client = app.test_client()
    with client.session_transaction() as s:
        s["member_id"] = MEMBER
    r = client.get("/account?lang=he")
    return r.status_code, r.get_data(as_text=True)

BASE = {"destinations": "LIS", "origin_airports": ["TLV"], "date_mode": "exact", "departure_date": "2027-03-21",
        "return_date": "2027-03-25", "date_flex_days": 0, "duration_days": 5, "deal_priorities": ["direct"],
        "vacation_type": "standard", "adults": 1, "children": 0, "budget_mode": "limited", "budget_amount": 2000,
        "departure_time_preference": "ערב", "_flight_search_finished": True}

# 1) חמש הצעות, כל אחת מפספסת תנאי אחר
trip = make_trip(259901, BASE)
cases = {
    "תקציב": make_offer(2600, "2027-03-21", "2027-03-25"),
    "טיסה ישירה": make_offer(1600, "2027-03-21", "2027-03-25", stops=1),
    "שעת טיסה הלוך": make_offer(1700, "2027-03-21", "2027-03-25", dep_time="2027-03-21 08:00"),
    "התאריכים שביקשת": make_offer(1500, "2027-04-02", "2027-04-06", dep_time="2027-04-02 19:00"),
    "5 ימים": make_offer(1650, "2027-03-21", "2027-03-28"),
}
with app.test_request_context("/?lang=he"):
    answers = dict(trip["answers"])
    pinned = public_site._match_and_pin_initial_offers(259901, trip, answers, pool(list(cases.values())), require_recent=False)
check("שרשרת ההתאמה מצמידה הצעות לחופשה", pinned)
status, html = account_html(259901)
check("/account נטען", status == 200, f"status={status}")
cards = re.split(r'<article class="ariella-deal-card', html)[1:]
check("מוצגים כרטיסי טיסה בחופשה", len(cards) >= 1, f"cards={len(cards)}")
notes = [re.sub(r"<[^>]+>", " ", (re.search(r'class="deal-close-match-note">(.*?)</div>', c, re.S) or [None, ""])[1]) for c in cards]
for reason in cases:
    check(f"כרטיס שמפספס '{reason}' מציג 'לא כולל: …{reason}' ב-HTML",
          any("לא כולל" in n and reason in n for n in notes), f"notes={[n.strip()[:80] for n in notes]}")
check("כל כרטיס בחופשה בלי התאמה מלאה מסומן כ'הקרוב ביותר'/חלופה", all(n.strip() for n in notes) and len(notes) == len(cards),
      f"{sum(1 for n in notes if n.strip())}/{len(cards)} מסומנים")

# 2) תקציב במטבע זר: 250 אירו לאדם בצ'אט
state = {"budget_per_person": {"amount": 250, "currency": "EUR", "status": "known"}}
saved = {"budget_mode": "limited" if state["budget_per_person"].get("amount") else "unlimited",
         "budget_amount": state["budget_per_person"].get("amount")}  # כפי ש-ariella_start_flight_search ממפה היום (public_site.py)
src = open(public_site.__file__, encoding="utf-8").read()
maps_currency = bool(re.search(r"budget_currency|budget\.get\(\"currency\"\)|budget\.get\('currency'\)", src))
check("תקציב באירו נשמר עם מטבע או מומר לש\"ח לפני השוואה ל-price_ils", maps_currency,
      "answers שומר רק budget_amount=250, ו-price_ils מושווה אליו כאילו זה 250 ש\"ח")

# 3) מחיר לאדם מול כולל: 2 מבוגרים, תקציב 2000 לאדם, הצעה 3600 כולל (1800 לאדם)
trip2 = make_trip(259902, dict(BASE, adults=2, departure_time_preference=""))
oid = make_offer(3600, "2027-03-21", "2027-03-25")
with app.test_request_context("/?lang=he"):
    o = [x for x in pool([oid])][0]
    within = public_site._offer_within_budget(o, trip2)
check("הצעה של 3600 ש\"ח ל-2 נוסעים (1800 לאדם) נחשבת בתוך תקציב של 2000 לאדם — "
      "או ש-price_ils מוגדר במפורש כמחיר לאדם", within,
      "_offer_within_budget משווה price_ils ישירות לתקציב לאדם; צריך לאמת אם price_ils מהסריקה הוא מחיר כולל לכל הנוסעים")

with db() as c:
    c.execute("DELETE FROM trip_requests WHERE member_id=?", (MEMBER,)); c.execute("DELETE FROM members WHERE id=?", (MEMBER,)); c.commit()
print("\nFAILED:", len(FAILED)) if FAILED else print("\nALL PASSED")
sys.exit(1 if FAILED else 0)
