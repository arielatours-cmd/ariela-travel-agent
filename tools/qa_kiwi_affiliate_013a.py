"""QA for task 013a - Kiwi.com affiliate link (Travelpayouts) + disclosure.

Per product/dev-tasks/013a-affiliate-flight-links.md (ofek branch) and Din's
requirements as relayed by Bezalel:
  (a) the disclosure text always sits next to every Kiwi button, and on the
      booking_forward.html transition screen;
  (b) no separate-tickets data exists, so the Kiwi link appears only on
      direct flights (both legs) - unclear data means no link at all;
  (c) never a shield icon or "חלה" next to a Kiwi offer;
  (d) nothing but the trip id (sid) is sent to the partner - no PII.
Plus: deep link only with marker + trs + template, otherwise the honest
home-page fallback ("חיפוש באתר Kiwi.com"); no button at all when nothing is
configured; booking_clicks.affiliate_network is filled.

Offline - no SerpAPI / Claude / WhatsApp calls.
Run: python3 tools/qa_kiwi_affiliate_013a.py
"""
import os
import re
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TMP = tempfile.mkdtemp(prefix="ariella-qa-013a-")
os.environ.update({"DB_PATH": os.path.join(_TMP, "qa.db"), "SCHEDULER_ENABLED": "false",
                   "SCANNER_ENABLED": "false"})
for key in ("SERPAPI_API_KEY", "ANTHROPIC_API_KEY", "WHATSAPP_ACCESS_TOKEN",
            "TRAVELPAYOUTS_KIWI_LINK", "TRAVELPAYOUTS_MARKER", "TRAVELPAYOUTS_TRS",
            "KIWI_SEARCH_URL_TEMPLATE"):
    os.environ.pop(key, None)

FAILED = []


def check(name, cond):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        FAILED.append(name)


import config  # noqa: E402
import booker  # noqa: E402
import app as app_module  # noqa: E402
import public_site  # noqa: E402
from database import connection  # noqa: E402

HE_DISCLOSURE = ("קישור שותף: אם תזמינו דרך Kiwi.com, אריאלה מקבלת עמלה מ-Kiwi.com. "
                 "ההזמנה, התשלום, השינויים והביטולים מתבצעים מול Kiwi.com ובהתאם לתנאיו.")
EN_DISCLOSURE = ("Affiliate link: if you book through Kiwi.com, Ariella receives a commission "
                 "from Kiwi.com. Booking, payment, changes and cancellations are handled by "
                 "Kiwi.com under its terms.")
SHORT_LINK = "https://kiwi.tpk.lu/TESTLINK"
# A made-up template in the shape of a Travelpayouts deep link - not a real
# program id; the real format comes from the Travelpayouts Links tool.
TEMPLATE = ("https://tp.example/r?marker={marker}&trs={trs}&sub_id={sid}&u=https%3A%2F%2Fwww.kiwi.com"
            "%2Fsearch%2Fresults%2F{from}%2F{to}%2F{depart}%2F{return}%3Fadults%3D{adults}%26children%3D{children}")


def configure(link="", marker="", trs="", template=""):
    config.TRAVELPAYOUTS_KIWI_LINK = link
    config.TRAVELPAYOUTS_MARKER = marker
    config.TRAVELPAYOUTS_TRS = trs
    config.KIWI_SEARCH_URL_TEMPLATE = template


def offer(**over):
    base = {
        "id": 501, "offer_id": 501, "departure_code": "TLV", "arrival_code": "ATH",
        "outbound_date": "2026-11-10", "return_date": "2026-11-17",
        "stops": 0, "return_stops": 0, "open_jaw": False,
        "consumer_protection_label": "יש לבדוק מול הספק", "price_ils": 900,
        "airline": "Aegean", "booking_url": "https://example.com/book",
    }
    base.update(over)
    return base


# --- 1. Nothing configured -> no Kiwi button, site unchanged -----------------
configure()
check("nothing configured -> no Kiwi target", booker.kiwi_affiliate_target(offer()) is None)

# --- 2. Only the short link -> honest home-page fallback ---------------------
configure(link=SHORT_LINK)
t = booker.kiwi_affiliate_target(offer())
check("short link only -> target exists", bool(t))
check("short link only -> not a deep link", t and t["deep_link"] is False)
check("short link only -> url is the short link as-is", t and t["url"] == SHORT_LINK)
check("network is travelpayouts", t and t["network"] == "travelpayouts")

# marker / trs missing (either one) -> fallback even with a template
for kw in ({"marker": "M1"}, {"trs": "T1"}, {"template": TEMPLATE}, {"marker": "M1", "template": TEMPLATE},
           {"trs": "T1", "template": TEMPLATE}):
    configure(link=SHORT_LINK, **kw)
    t = booker.kiwi_affiliate_target(offer(), sid="trip7")
    check(f"partial deep-link config {sorted(kw)} -> home-page fallback", t and not t["deep_link"] and t["url"] == SHORT_LINK)

# --- 3. Full config -> deep link with route, dates, passengers ---------------
configure(link=SHORT_LINK, marker="M123", trs="T456", template=TEMPLATE)
t = booker.kiwi_affiliate_target(offer(), adults=2, children=1, sid="trip42")
check("full config -> deep link", t and t["deep_link"] is True)
url = t["url"] if t else ""
for part in ("marker=M123", "trs=T456", "sub_id=trip42", "TLV", "ATH", "2026-11-10", "2026-11-17",
             "adults%3D2", "children%3D1"):
    check(f"deep link contains {part}", part in url)
check("deep link is https", url.startswith("https://"))

# broken template / bad data -> fallback, never a broken button
configure(link=SHORT_LINK, marker="M", trs="T", template="https://x.example/{unknown_placeholder}")
t = booker.kiwi_affiliate_target(offer(), sid="trip1")
check("malformed template -> home-page fallback", t and not t["deep_link"] and t["url"] == SHORT_LINK)
configure(link=SHORT_LINK, marker="M", trs="T", template="javascript:{from}")
t = booker.kiwi_affiliate_target(offer(), sid="trip1")
check("non-https template -> home-page fallback", t and not t["deep_link"])
configure(link=SHORT_LINK, marker="M", trs="T", template=TEMPLATE)
t = booker.kiwi_affiliate_target(offer(return_date=None), sid="trip1")
check("missing return date -> home-page fallback", t and not t["deep_link"])
configure(link="", marker="M", trs="T", template=TEMPLATE)
check("bad data and no short link -> no button at all",
      booker.kiwi_affiliate_target(offer(return_date=None)) is None)
configure(link="http://insecure.example/x")
check("non-https short link -> no button", booker.kiwi_affiliate_target(offer()) is None)

# --- (b) direct flights only; unclear data -> no link -------------------------
configure(link=SHORT_LINK, marker="M", trs="T", template=TEMPLATE)
check("outbound connection -> no Kiwi", booker.kiwi_affiliate_target(offer(stops=1)) is None)
check("return connection -> no Kiwi", booker.kiwi_affiliate_target(offer(return_stops=1)) is None)
check("unknown outbound stops -> no Kiwi", booker.kiwi_affiliate_target(offer(stops=None)) is None)
check("unknown return stops -> no Kiwi", booker.kiwi_affiliate_target(offer(return_stops=None)) is None)
check("open jaw -> no Kiwi", booker.kiwi_affiliate_target(offer(open_jaw=True)) is None)

# --- (c) never next to "consumer protection applies" -------------------------
check("offer labelled 'חלה' -> no Kiwi button", booker.kiwi_affiliate_target(offer(consumer_protection_label="חלה")) is None)

# --- (d) no PII to the partner ------------------------------------------------
pii = {"full_name": "Dana Cohen", "email": "dana@example.com", "phone": "0501234567"}
t = booker.kiwi_affiliate_target(offer(**pii), sid="trip9")
check("PII on the offer never reaches the URL",
      t and not any(v in t["url"] for v in pii.values()) and "dana" not in t["url"].lower())
check("a sid that is not a plain id is refused (fallback, nothing sent)",
      (booker.kiwi_affiliate_target(offer(), sid="dana@example.com") or {}).get("url") == SHORT_LINK)
check("kiwi_affiliate_target accepts no name/email/phone arguments",
      not {"name", "email", "phone"} & set(booker.kiwi_affiliate_target.__code__.co_varnames))

# --- Rendering: deal card (a) + (c) ------------------------------------------
app = app_module.app
CARD = '{% from "_deal_card.html" import kiwi_affiliate %}{{ kiwi_affiliate(o, lang) }}'


def kiwi_block(o, lang):
    with app.test_request_context("/"):
        return app.jinja_env.from_string(CARD).render(o=o, lang=lang)


for deep in (True, False):
    configure(link=SHORT_LINK, **({"marker": "M", "trs": "T", "template": TEMPLATE} if deep else {}))
    he, en = kiwi_block(offer(), "he"), kiwi_block(offer(), "en")
    tag = "deep link" if deep else "fallback"
    check(f"[{tag}] Hebrew card: Kiwi button rendered", "kiwi-affiliate-btn" in he)
    check(f"[{tag}] Hebrew card: disclosure next to the button", HE_DISCLOSURE in he)
    check(f"[{tag}] English card: disclosure next to the button", EN_DISCLOSURE in en)
    check(f"[{tag}] button + disclosure share one block", re.search(r'class="kiwi-affiliate">.*kiwi-affiliate-btn.*affiliate-disclosure', he, re.S) is not None)
    check(f"[{tag}] no shield icon / 'חלה' in the Kiwi block", "🛡" not in he + en and "חלה" not in he)
    check(f"[{tag}] rel includes sponsored", 'rel="noopener noreferrer sponsored"' in he)
    check(f"[{tag}] button wording never says 'book' / 'הזמנה'", "הזמנה" not in he.split("affiliate-disclosure")[0] and "Book" not in en.split("affiliate-disclosure")[0])
    if deep:
        check("deep link label: 'לבדוק גם ב-Kiwi.com'", "לבדוק גם ב-Kiwi.com" in he)
    else:
        check("fallback label: 'חיפוש באתר Kiwi.com'", "חיפוש באתר Kiwi.com" in he and "Search on Kiwi.com" in en)
    check(f"[{tag}] card link goes through Ariella's /go/kiwi route", "/go/kiwi/501" in he)

configure()
check("nothing configured -> card has no Kiwi block", kiwi_block(offer(), "he").strip() == "")
configure(link=SHORT_LINK)
check("connection flight -> card has no Kiwi block", kiwi_block(offer(stops=1), "he").strip() == "")
check("'חלה' card -> no Kiwi block", kiwi_block(offer(consumer_protection_label="חלה"), "he").strip() == "")

# --- Route /go/kiwi: transition screen (a), click recorded, no PII (d) --------
public_site.recent_offers = lambda **kw: [offer(), offer(id=502, offer_id=502, stops=1)]
public_site._offer_is_publicly_bookable = lambda o: True
client = app.test_client()

configure(link=SHORT_LINK, marker="M9", trs="T9", template=TEMPLATE)
r = client.get("/go/kiwi/501?lang=he")
body = r.get_data(as_text=True)
check("/go/kiwi renders the transition screen", r.status_code == 200)
check("transition screen (he) shows the disclosure", HE_DISCLOSURE in body)
check("transition screen redirects to the Kiwi deep link", "tp.example" in body and "redirectUrl" in body)
check("transition screen: no shield / 'חלה'", "🛡" not in body and "חלה" not in body)
r_en = client.get("/go/kiwi/501?lang=en")
check("transition screen (en) shows the disclosure", EN_DISCLOSURE in r_en.get_data(as_text=True))

with connection() as conn:
    rows = [dict(x) for x in conn.execute("SELECT supplier, affiliate_network, booking_url FROM booking_clicks").fetchall()]
check("public deal (no trip): empty sid sent", rows and "sub_id=&u=" in rows[-1]["booking_url"])
check("click recorded with supplier Kiwi.com", rows and rows[-1]["supplier"] == "Kiwi.com")
check("booking_clicks.affiliate_network = travelpayouts", rows and rows[-1]["affiliate_network"] == "travelpayouts")

r = client.get("/go/kiwi/502")
check("connection flight via route -> redirect, no Kiwi screen", r.status_code == 302)
configure()
r = client.get("/go/kiwi/501")
check("nothing configured -> route redirects away", r.status_code == 302)

# normal booking flow screen is unchanged: no Kiwi disclosure there
with app.test_request_context("/"):
    from flask import render_template
    normal = render_template("booking_forward.html", action=None, fields=[], method="post", status_url="/x", site_lang="he")
check("normal booking_forward has no Kiwi disclosure", "Kiwi" not in normal and "affiliate-disclosure\">" not in normal)

# record_booking_click default: empty network for plain links
from database import record_booking_click  # noqa: E402
record_booking_click(supplier="El Al", booking_url="https://elal.example")
with connection() as conn:
    last = dict(conn.execute("SELECT affiliate_network FROM booking_clicks ORDER BY id DESC LIMIT 1").fetchone())
check("plain supplier click -> affiliate_network empty", last["affiliate_network"] == "")

# --- Legal pages -----------------------------------------------------------------
for path in ("/terms?lang=he", "/affiliate-disclosure?lang=he", "/terms?lang=en", "/affiliate-disclosure?lang=en"):
    r = client.get(path)
    text = r.get_data(as_text=True)
    check(f"{path} renders", r.status_code == 200)
    check(f"{path} mentions Travelpayouts", "Travelpayouts" in text)
    check(f"{path} never says the price does not change", "המחיר עבורכם לא משתנה" not in text)
for path in ("/terms?lang=he", "/affiliate-disclosure?lang=he", "/deals?lang=he"):
    check(f"{path}: no 'ללא עמלה' claim", "ללא עמלה" not in client.get(path).get_data(as_text=True))

account = open(os.path.join(os.path.dirname(__file__), "..", "templates", "account.html"), encoding="utf-8").read()
check("lodging + car partner cards carry the affiliate disclosure",
      account.count("קישור שותף: אם תזמינו דרך") == 2)

print()
print("ALL PASS" if not FAILED else f"{len(FAILED)} FAILED: {FAILED}")
sys.exit(1 if FAILED else 0)
