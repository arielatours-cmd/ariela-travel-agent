"""QA for the attraction-price display (22.10; the business owner's request,
Din's legal conditions DEAL-18 relayed by Shlomo/Bezalel). Din reviews the PR.

itinerary_cards copies the structured price fields onto each card
(price_info); itinerary_cards.attraction_price_view decides at render time
what may be shown on the "מסלול ואטרקציות" tab. The six conditions:

1. a price only when price_status is verified ("ok") - never "needs_check";
2. validity: price_checked_at older than 90 days (or unknown) -> no price at
   all, only the links;
3. "לאדם" only when everyone in the party certainly pays the same adult
   price; a different price by age (discount / free under free_under_age,
   inclusive), unknown ages or an unreadable child rule -> the adult price
   with "לפי מחיר מבוגר × N";
4. in the source currency (no conversion);
5. "כניסה חינם" only when free_entry is verified (same 1+2);
6. Din's simplified wording, word for word: "מחיר משוער: כ-<amount> <unit>.
   המחיר הסופי באתר ההזמנה." - no check date beside it.
The old free-text price is no longer shown anywhere on the page; the ticket /
official links are untouched.

Offline. Run: python3 tools/qa_attraction_price_display.py
"""
import json
import os
import re
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")
os.environ.setdefault("SCHEDULER_ENABLED", "false")

import database  # noqa: E402
database.init_db()

import itinerary_cards as ic  # noqa: E402
import app as app_module  # noqa: E402
from werkzeug.security import generate_password_hash  # noqa: E402

FAILED = []


def check(name, cond):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        FAILED.append(name)


TODAY = date(2026, 10, 30)
view = ic.attraction_price_view
CABLE = {"price_adult": 30, "price_child": 8, "child_age_range": "4-12", "free_under_age": 3, "currency": "EUR",
         "free_entry": False, "price_status": "ok", "price_checked_at": "2026-10-22"}
COLOSSEUM = {"price_adult": 18, "price_child": 0, "child_age_range": "עד 17", "free_under_age": 17, "currency": "EUR",
             "free_entry": False, "price_status": "ok", "price_checked_at": "2026-10-22"}
FREE = {"price_adult": None, "price_child": None, "child_age_range": None, "free_under_age": None, "currency": None,
        "free_entry": True, "price_status": "ok", "price_checked_at": "2026-10-22"}
COUPLE = {"adults": 2}


def text(info, answers, today=TODAY):
    return (view(info, answers, today) or {}).get("text")


# --- 6. Din's wording, exactly (simplified version, no check date) -----------------------------------------
check("6: Din's wording, word for word, for a same-price party",
      text(CABLE, COUPLE) == "מחיר משוער: כ-€30 לאדם. המחיר הסופי באתר ההזמנה.")
check("6: no check date next to the price", "2026" not in text(CABLE, COUPLE) and "נבדק" not in text(CABLE, COUPLE))

# --- 1. verified only --------------------------------------------------------------------------------------
check("1: needs_check -> no price", view(dict(CABLE, price_status="needs_check"), COUPLE, TODAY) is None)
check("1: any other status / missing -> no price",
      view(dict(CABLE, price_status="pending"), COUPLE, TODAY) is None and view(dict(CABLE, price_status=None), COUPLE, TODAY) is None)
check("1: no data at all -> no price", view(None, COUPLE, TODAY) is None and view({}, COUPLE, TODAY) is None)

# --- 2. 90-day validity (still enforced, though the date isn't shown) --------------------------------------
checked = date(2026, 10, 22)
check("2: checked 90 days ago -> still shown", view(CABLE, COUPLE, checked + timedelta(days=90)) is not None)
check("2: checked 91 days ago -> no price at all", view(CABLE, COUPLE, checked + timedelta(days=91)) is None)
check("2: no check date -> no price", view(dict(CABLE, price_checked_at=None), COUPLE, TODAY) is None)
check("2: a malformed / future date -> no price",
      view(dict(CABLE, price_checked_at="22/10/2026"), COUPLE, TODAY) is None
      and view(dict(CABLE, price_checked_at="2026-12-01"), COUPLE, TODAY) is None)

# --- 3. "לאדם" only for a same-price party; otherwise "לפי מחיר מבוגר × N" ----------------------------------
SAME = "מחיר משוער: כ-€30 לאדם. המחיר הסופי באתר ההזמנה."


def per_adult(n, amount=30, sym="€"):
    # Din's exact wording for a party that doesn't all pay the adult price (PR #148 review).
    return (f"מחיר משוער: כ-{sym}{amount} למבוגר. לפי מחיר מבוגר × {n}: כ-{sym}{amount * n} "
            "(לילדים ייתכן מחיר נמוך יותר). המחיר הסופי באתר ההזמנה.")


check("3: adults only -> 'לאדם'", text(CABLE, {"adults": 4}) == SAME)
check("3: a child above the child range and the free age pays the adult price -> 'לאדם'",
      text(CABLE, {"adults": 2, "children": 1, "age_groups": [15]}) == SAME)
check("3: a reduced child price in the party -> 'לפי מחיר מבוגר × N'", text(CABLE, {"adults": 2, "children": 1, "age_groups": [8]}) == per_adult(3))
check("3: a child free under free_under_age (price differs) -> 'לפי מחיר מבוגר × N'",
      text(COLOSSEUM, {"adults": 2, "children": 2, "age_groups": [5, 17]}) == per_adult(4, 18))
check("3: children's ages unknown -> 'לפי מחיר מבוגר × N'",
      text(CABLE, {"adults": 2, "children": 1}) == per_adult(3) and text(CABLE, {"adults": 2, "children": 2, "age_groups": [15]}) == per_adult(4))
check("3: free_under_age / child_age_range unknown and ages unknown -> 'לפי מחיר מבוגר × N'",
      text(dict(CABLE, free_under_age=None, child_age_range=None, price_child=None), {"adults": 2, "children": 1}) == per_adult(3))
check("3: an unreadable child rule ('אין כניסה מתחת לגיל 14') -> 'לפי מחיר מבוגר × N'",
      text(dict(CABLE, child_age_range="אין כניסה מתחת לגיל 14", free_under_age=None, price_child=None),
           {"adults": 2, "children": 1, "age_groups": [16]}) == per_adult(3))

# --- 4. source currency ------------------------------------------------------------------------------------
check("4: shown in the source currency (EUR, HUF), never converted",
      "€30" in text(CABLE, COUPLE) and "כ-13,200 HUF לאדם" in text(dict(CABLE, price_adult=13200, currency="HUF"), COUPLE)
      and "₪" not in text(CABLE, COUPLE))
check("4: no valid currency -> no price", view(dict(CABLE, currency=None), COUPLE, TODAY) is None)

# --- 5. free entry ------------------------------------------------------------------------------------------
check("5: verified free entry -> 'כניסה חינם'", text(FREE, COUPLE) == "כניסה חינם")
check("5: free_entry not verified (needs_check) -> nothing", view(dict(FREE, price_status="needs_check"), COUPLE, TODAY) is None)
check("5: free_entry without a check date -> nothing (never a guess)", view(dict(FREE, price_checked_at=None), COUPLE, TODAY) is None)
check("5: free_entry False/None never shows 'חינם'",
      all("חינם" not in (text(dict(CABLE, free_entry=v), COUPLE) or "") for v in (False, None)))

check("3: Din's example, word for word",
      text(CABLE, {"adults": 2, "children": 2}) == "מחיר משוער: כ-€30 למבוגר. לפי מחיר מבוגר × 4: כ-€120 (לילדים ייתכן מחיר נמוך יותר). המחיר הסופי באתר ההזמנה.")

# --- Ticket links (Din, PR #148): same domain as the official site, or a listed official operator --------
tl = ic.attraction_tickets_url
check("links: same domain as the official site -> shown",
      tl("https://tickets.colosseo.it/buy", "https://colosseo.it/") == "https://tickets.colosseo.it/buy"
      and tl("https://www.louvre.fr/billets", "https://www.louvre.fr/") == "https://www.louvre.fr/billets")
check("links: a reseller on another domain -> not shown",
      tl("https://www.getyourguide.com/colosseum-t1", "https://colosseo.it/") == ""
      and tl("https://www.tiqets.com/x", "https://www.louvre.fr/") == "")
check("links: an official ticket operator from the manual list -> shown",
      tl("https://www.ticketlouvre.fr/", "https://www.louvre.fr/") == "https://www.ticketlouvre.fr/"
      and tl("https://tickets.atthetop.ae/x", "https://www.burjkhalifa.ae/") == "https://tickets.atthetop.ae/x")
check("links: no official link on the card (it equalled the ticket link) -> shown", tl("https://colosseo.it/t", "") == "https://colosseo.it/t")
check("links: a look-alike domain is not the same site", tl("https://colosseo.it.evil.example/t", "https://colosseo.it/") == "")
check("links: nothing -> nothing", tl("", "https://colosseo.it/") == "" and tl(None, None) == "")

# --- The page itself -----------------------------------------------------------------------------------------
src = open(os.path.join(ROOT, "itinerary_cards.py"), encoding="utf-8").read()
check("cards carry the structured fields (price_info), not the free-text price",
      '"price_info"' in src and '"מחיר/הערת מחיר"' not in src)
fresh = (date.today() - timedelta(days=5)).isoformat()
stale = (date.today() - timedelta(days=120)).isoformat()


def card(name, info):
    return {"name_he": name, "city": "רומא", "description": "", "duration": "", "price": "חופשי-טקסט 99€",
            "price_info": info, "tickets_url": "https://tickets.example/" + name, "official_url": "https://tickets.example/",
            "map_url": "https://maps.example"}


answers = {"destinations": "FCO", "departure_date": "2027-05-01", "return_date": "2027-05-08", "adults": 2,
           "_requested_services": ["trip_planning"],
           "_approved_itinerary": {"text": "יום 1: רומא", "days": [{"day": 1, "items": [
               card("Fresh", dict(COLOSSEUM, price_checked_at=fresh)),
               card("Stale", dict(COLOSSEUM, price_checked_at=stale)),
               card("Unverified", dict(COLOSSEUM, price_status="needs_check", price_checked_at=fresh)),
               card("Legacy", None),
               dict(card("Resold", None), tickets_url="https://reseller.example/x", official_url="https://official.example/"),
           ]}]}}
with sqlite3.connect(database.DB_PATH) as conn:
    conn.execute("DELETE FROM members WHERE email='qa-attraction-price@example.com'")
    member_id = conn.execute(
        "INSERT INTO members (full_name,email,password_hash,created_at,status,whatsapp_opt_in,preferred_airports) VALUES(?,?,?,?,?,?,?)",
        ("QA", "qa-attraction-price@example.com", generate_password_hash("x"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]"),
    ).lastrowid
    conn.execute("INSERT INTO trip_requests (member_id, request_name, status, answers_json, created_at) VALUES (?,?,?,?,datetime('now'))",
                 (member_id, "QA Prices", "active", json.dumps(answers, ensure_ascii=False)))
    conn.commit()
client = app_module.app.test_client()
with client.session_transaction() as sess:
    sess["member_id"] = member_id
html = client.get("/account").get_data(as_text=True)
itin_rendered = "itin-card-name" in html
check("page: the itinerary cards render", itin_rendered)
if itin_rendered:
    blocks = dict(re.findall(r'<strong class="itin-card-name">([^<]+)</strong>(.*?)</article>', html, re.S))
    check("page: a fresh verified price shows in Din's wording",
          "מחיר משוער: כ-€18 לאדם. המחיר הסופי באתר ההזמנה." in blocks.get("Fresh", ""))
    check("page: stale / unverified / legacy cards show no price, only the links",
          all("€" not in blocks.get(n, "") and "מחיר משוער" not in blocks.get(n, "") and "tickets.example/" + n in blocks.get(n, "")
              for n in ("Stale", "Unverified", "Legacy")))
    check("page: the old free-text price is never shown", "חופשי-טקסט" not in html)
    check("page: a reseller ticket link is not rendered, the official one is",
          "reseller.example" not in html and "tickets.example/Fresh" in html)

with sqlite3.connect(database.DB_PATH) as conn:
    conn.execute("DELETE FROM members WHERE email='qa-attraction-price@example.com'")
    conn.commit()

print()
print("ALL PASS" if not FAILED else f"{len(FAILED)} FAILED: {FAILED}")
sys.exit(1 if FAILED else 0)
