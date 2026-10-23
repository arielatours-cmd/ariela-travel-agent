"""QA: destination landmark images from Ofek's Commons-verified list (23.10,
the business owner via Shlomo - interim fix until 021a).

- static/img/destinations/landmarks.json = ofek's product/data/
  landmark_images_fix.json: each landmark checked against the Wikimedia
  Commons API (file exists; PD/CC0/CC BY/CC BY-SA only - Din, IMG-1).
- The 9 that 404'd (LIS, VIE, ZRH, BRU, WAW, EVN, BEG, TGD, LJU) are
  replaced, PRG -> Charles Bridge, OTP/KRK get a real photo again, LCA kept.
- The general image: the desert road -> Ofek's CC0 plane wing, our own file.
- credit_text (Din's format) is shown on the deal card when the licence
  requires it; English uses the same format and parts.

Offline. Run: python3 tools/qa_landmark_images_fix.py
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")
os.environ.setdefault("SCHEDULER_ENABLED", "false")

import database  # noqa: E402
import app as app_module  # noqa: E402

FAILED = []


def check(name, cond):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        FAILED.append(name)


fix = json.load(open(os.path.join(ROOT, "static", "img", "destinations", "landmarks.json"), encoding="utf-8"))["images"]
L = database.DESTINATION_LANDMARK_IMAGES
check("every verified/replacement entry's url_1200 is what the card uses",
      all(L[c] == v["url_1200"] for c, v in fix.items() if v["status"] != "keep_current"))
check("the 9 that 404'd + PRG/OTP/KRK are Commons files now, no Special:Redirect anywhere",
      all(L[c].startswith("https://upload.wikimedia.org/") for c in ("LIS", "VIE", "ZRH", "BRU", "WAW", "EVN", "BEG", "TGD", "LJU", "PRG", "OTP", "KRK"))
      and not any("Special:Redirect" in u for u in L.values()))
check("PRG: Charles Bridge", "Charles" in fix["PRG"]["title"] or "Karl" in fix["PRG"]["title"])
check("LCA kept as it was", L["LCA"].startswith("https://images.unsplash.com/photo-1507525428034"))
check("licences: PD / CC0 / CC BY / CC BY-SA only (Din, IMG-1)",
      all(any(x in v.get("license", "") for x in ("Public domain", "CC0", "CC BY")) and "NC" not in v.get("license", "") and "ND" not in v.get("license", "")
          for v in fix.values() if v["status"] != "keep_current"))
check("the general image: our own CC0 file, the desert road is gone",
      database.GENERIC_DESTINATION_IMAGE.endswith("/static/img/destinations/_default.webp")
      and os.path.getsize(os.path.join(ROOT, "static", "img", "destinations", "_default.webp")) > 1000
      and not any("photo-1500530855697" in u for p in database.DESTINATION_IMAGE_POOLS.values() for u in p))
need = {c for c, v in fix.items() if v.get("credit_text") and v["status"] != "keep_current"}
check("a credit for exactly the landmarks whose licence needs one", need and need <= set(database.DESTINATION_IMAGE_CREDITS)
      and not ({"ATH"} & set(database.DESTINATION_IMAGE_CREDITS)))
check("same-city airports share the credit with their photo (CIA <- FCO)",
      L["CIA"] == L["FCO"] and database.DESTINATION_IMAGE_CREDITS.get("CIA") == database.DESTINATION_IMAGE_CREDITS.get("FCO"))

app = app_module.app
FULL = '{% from "_deal_card.html" import deal_card %}{{ deal_card(o, lang) }}'
base = {"id": 1, "departure_code": "TLV", "arrival_code": "LIS", "outbound_date": "2027-05-01", "return_date": "2027-05-08",
        "stops": 0, "return_stops": 0, "price_ils": 900, "airline": "TAP", "booking_url": "https://e.com", "baggage": {},
        "connections": [], "return_connections": [], "destination_image_url": L["LIS"],
        "destination_image_fallback": database.GENERIC_DESTINATION_IMAGE, "destination_image_credit": database.DESTINATION_IMAGE_CREDITS.get("LIS")}
with app.test_request_context("/"):
    he = app.jinja_env.from_string(FULL).render(o=base, lang="he")
    en = app.jinja_env.from_string(FULL).render(o=base, lang="en")
    none = app.jinja_env.from_string(FULL).render(o=dict(base, arrival_code="ATH", destination_image_url=L["ATH"], destination_image_credit=None), lang="he")
check("Shlomo 23.10: no Unsplash city layer left - the general image is the only fallback in every pool",
      database._DESTINATION_IMAGE_FALLBACKS == (database.GENERIC_DESTINATION_IMAGE,)
      and not any("photo-1477959858617" in u for p in database.DESTINATION_IMAGE_POOLS.values() for u in p))
import html as _html  # noqa: E402
lis = fix["LIS"]
check("card HE: Din's credit text on the photo (the Latin part in <bdi> - Tom's QA: the comma jumped in RTL)",
      f"צילום: <bdi>{lis['artist']} / {lis['license']}</bdi>, דרך Wikimedia Commons" in _html.unescape(he)
      and re.sub(r"</?bdi>", "", _html.unescape(he)).count(lis["credit_text"]) == 1)
check("card EN: the fixed English wording, never the Hebrew (Tom's QA)",
      f"Photo: {lis['artist']} / {lis['license']}, via Wikimedia Commons" in _html.unescape(en) and "צילום" not in en)
# Tom's QA (23.10): Wikimedia answers 400 to a 1200px thumbnail ("Use thumbnail sizes listed on w.wiki/GHai"),
# so the card fell back to our plane wing with someone else's credit on it. Offline guard: every thumbnail is 1280px.
thumbs = [v["url_1200"] for v in fix.values() if v.get("url_1200") and "/thumb/" in v["url_1200"]]
check("every Commons thumbnail is 1280px wide (1200px returns HTTP 400)",
      thumbs and all(re.search(r"/1280px-[^/]+$", u) for u in thumbs) and not any("/1200px-" in u for u in L.values()))
dbsrc = open(os.path.join(ROOT, "database.py"), encoding="utf-8").read()
check("no dead destination_image_url override on payload in recent_offers (Tom's QA)", 'payload["destination_image_url"]' not in dbsrc)
check("card: no credit when the licence needs none (ATH, public domain)", "deal-image-credit" not in none)
page = fix["LIS"]["page"]
check("Din 23.10: the whole credit line links to the photo's Commons page (he/en)",
      all(f'<a class="deal-image-credit" href="{page}" target="_blank" rel="noopener"' in h for h in (he, en)))
check("every credit carries its Commons page", all(c.get("page", "").startswith("https://commons.wikimedia.org/")
                                                   for c in database.DESTINATION_IMAGE_CREDITS.values()))
src = "".join(open(os.path.join(ROOT, "templates", f), encoding="utf-8").read() for f in os.listdir(os.path.join(ROOT, "templates")) if f.endswith(".html"))
check("Din 23.10 (b): the 'My vacations' trip card renders no destination image (trip.image_url isn't used by any template)",
      "trip.image_url" not in src and "trip['image_url']" not in src and 'trip["image_url"]' not in src)

print()
print("ALL PASS" if not FAILED else f"{len(FAILED)} FAILED: {FAILED}")
sys.exit(1 if FAILED else 0)
