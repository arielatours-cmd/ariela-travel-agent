"""QA for the legal image fix (22.10; Din IMG-1 + Shaked's Lisbon finding,
relayed by Bezalel):

1. Din: no xplorer.co.il / krakow.pl photos anywhere (we hold no rights) -
   OTP/KRK use the general image (GENERIC_DESTINATION_IMAGE).
2. Din: never a provider-supplied photo as the fallback - the deal's
   destination image falls back to the general image (not payload
   image_url), and a hotel with no thumbnail gets the general image (not
   SerpApi's full "original_image").
3. Shaked: the deal card's background pointed only at a Wikimedia
   Special:Redirect full-size file, with no fallback (Lisbon came out
   empty). Now a second url() layer (the general image) sits behind it,
   and Wikimedia links ask for a 1200px rendition (?width=1200).

The full Wikimedia replacement + credits is plan 021, not this PR.
Offline. Run: python3 tools/qa_legal_images.py
"""
import os
import re
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.update({"DB_PATH": os.path.join(tempfile.mkdtemp(prefix="ariella-qa-img-"), "qa.db"),
                   "SCHEDULER_ENABLED": "false", "SCANNER_ENABLED": "false"})
os.environ.pop("SERPAPI_API_KEY", None)

FAILED = []


def check(name, cond):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        FAILED.append(name)


import database  # noqa: E402
import scanner  # noqa: E402
import app as app_module  # noqa: E402

GENERIC = database.GENERIC_DESTINATION_IMAGE

# --- 1. No unlicensed hosts ----------------------------------------------------------------------------
bad = []
for dirpath, _dirs, files in os.walk(ROOT):
    if any(part in dirpath for part in (".git", "tools", "qa", "__pycache__", "node_modules")):
        continue
    for f in files:
        if f.endswith((".py", ".html", ".js", ".css")):
            text = open(os.path.join(dirpath, f), encoding="utf-8", errors="ignore").read()
            if re.search(r"https?://[^\s\"']*(xplorer\.co\.il|plikimpi\.krakow\.pl)", text):
                bad.append(os.path.relpath(os.path.join(dirpath, f), ROOT))
check("no xplorer.co.il / plikimpi.krakow.pl image URL in code or templates", not bad)
# 23.10 (Ofek's Commons-verified list, static/img/destinations/landmarks.json): OTP/KRK have a licensed
# Wikimedia photo again, and the general image is our own CC0 file (plane wing) - see qa_landmark_images_fix.py.
check("OTP and KRK: a licensed Wikimedia photo (never the old xplorer/krakow.pl ones)",
      all(database.DESTINATION_LANDMARK_IMAGES[c].startswith("https://upload.wikimedia.org/") for c in ("OTP", "KRK")))
check("the general image is a curated fallback, not a provider photo", GENERIC.endswith("/static/img/destinations/_default.webp"))

# --- 3a. Wikimedia thumbnails --------------------------------------------------------------------------
lis = database.DESTINATION_LANDMARK_IMAGES["LIS"]
check("Lisbon: a direct 1280px Wikimedia rendition (the Special:Redirect file 404'd; 1200px is not an allowed size)",
      lis.startswith("https://upload.wikimedia.org/") and "/1280px-" in lis)
check("every Special:Redirect link carries ?width=1200 (pools too)",
      all("?width=1200" in u for u in database.DESTINATION_LANDMARK_IMAGES.values() if "Special:Redirect" in u)
      and all("?width=1200" in p[0] for p in database.DESTINATION_IMAGE_POOLS.values() if "Special:Redirect" in p[0]))
check("non-Wikimedia links untouched", "?width=" not in database.DESTINATION_LANDMARK_IMAGES["LCA"])

# --- 3b. Deal card: a second url() layer behind the destination image -----------------------------------
app = app_module.app
FULL = '{% from "_deal_card.html" import deal_card %}{{ deal_card(o, lang) }}'


def card(o):
    with app.test_request_context("/"):
        import html as _html
        return _html.unescape(app.jinja_env.from_string(FULL).render(o=o, lang="he"))


base_offer = {"id": 1, "offer_id": 1, "departure_code": "TLV", "arrival_code": "LIS", "outbound_date": "2026-11-10",
              "return_date": "2026-11-17", "stops": 0, "return_stops": 0, "open_jaw": False, "price_ils": 900,
              "airline": "TAP", "booking_url": "https://example.com/b", "baggage": {}, "connections": [], "return_connections": []}
html = card(dict(base_offer, destination_image_url=lis, destination_image_fallback=GENERIC))
check("deal card: Wikimedia image layer + the general image behind it",
      f"url('{lis}'),url('{GENERIC}')" in html)
html = card(dict(base_offer, destination_image_url=GENERIC, destination_image_fallback=GENERIC))
check("deal card: no duplicate layer when the image IS the general one", html.count(f"url('{GENERIC}')") == 1)
html = card(dict(base_offer, destination_image_url=lis, destination_image_pool=database.DESTINATION_IMAGE_POOLS["LIS"]))
check("deal card: an offer without the new key still gets a fallback layer from its pool",
      f"url('{lis}'),url('{database.DESTINATION_IMAGE_POOLS['LIS'][-1]}')" in html)

# --- 2. Provider images never used as the fallback ------------------------------------------------------
src = open(os.path.join(ROOT, "database.py"), encoding="utf-8").read()
check("deal destination image: no payload image_url fallback, the general image instead",
      'or payload.get("image_url")' not in src and '"destination_image_fallback": GENERIC_DESTINATION_IMAGE' in src)


ssrc = open(os.path.join(ROOT, "scanner.py"), encoding="utf-8").read()
check("hotel image: no provider original_image fallback - the general image instead",
      'images[0].get("thumbnail") or GENERIC_DESTINATION_IMAGE' in ssrc and 'get("original_image")' not in ssrc)

print()
print("ALL PASS" if not FAILED else f"{len(FAILED)} FAILED: {FAILED}")
sys.exit(1 if FAILED else 0)
