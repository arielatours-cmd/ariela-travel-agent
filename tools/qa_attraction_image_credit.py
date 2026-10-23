"""QA: attraction photos on the itinerary cards (Din, IMG-1, 23.10 via Shlomo).

The cards' photos come from the Wikipedia page image. Now the file's licence is
fetched too (imageinfo extmetadata): only a Commons file under PD / CC0 / CC BY /
CC BY-SA, with a known author, is shown - with a credit line in Din's format
linking to its Commons page:
  "צילום: X / רישיון, דרך Wikimedia Commons" / "Photo: X / license, via Wikimedia Commons"
Anything else (a local "fair use" file, NC/ND, no author) -> the card without a
photo. Cards built before this (no image_credit) show no photo either.

Offline (the Wikipedia API is stubbed). Run: python3 tools/qa_attraction_image_credit.py
"""
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")
os.environ.setdefault("SCHEDULER_ENABLED", "false")

import database  # noqa: E402
database.init_db()

import app as app_module  # noqa: E402
import itinerary_cards  # noqa: E402
from werkzeug.security import generate_password_hash  # noqa: E402

FAILED = []


def check(name, cond):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        FAILED.append(name)


class Resp:
    def __init__(self, data):
        self.data = data

    def json(self):
        return self.data


def fake_api(license_name, artist="Jane <a href='x'>Doe</a>", page="https://commons.wikimedia.org/wiki/File:Belem.jpg"):
    def get(url, headers=None, timeout=None, params=None):
        if params.get("generator") == "search":
            return Resp({"query": {"pages": {"1": {"thumbnail": {"source": "https://upload.wikimedia.org/thumb/Belem.jpg"},
                                                   "pageimage": "Belem.jpg"}}}})
        return Resp({"query": {"pages": {"-1": {"imageinfo": [{"descriptionurl": page, "extmetadata": {
            "LicenseShortName": {"value": license_name}, "Artist": {"value": artist}}}]}}}})
    return get


for lic in ("CC BY-SA 4.0", "CC BY 2.0", "CC0", "Public domain"):
    with patch.object(itinerary_cards.requests, "get", side_effect=fake_api(lic)):
        img, credit = itinerary_cards._wiki_image_licensed("Belem Tower", "Lisbon")
    check(f"allowed licence '{lic}' -> photo + credit (author without HTML, Commons page)",
          img and credit == {"artist": "Jane Doe", "license": lic, "page": "https://commons.wikimedia.org/wiki/File:Belem.jpg"})
for lic in ("CC BY-NC-SA 2.0", "CC BY-ND 3.0", "Fair use", ""):
    with patch.object(itinerary_cards.requests, "get", side_effect=fake_api(lic)):
        check(f"licence '{lic or '(none)'}' -> no photo", itinerary_cards._wiki_image_licensed("Belem Tower", "Lisbon") == ("", None))
with patch.object(itinerary_cards.requests, "get", side_effect=fake_api("CC BY-SA 4.0", artist="")):
    check("no known author -> no photo", itinerary_cards._wiki_image_licensed("Belem Tower", "Lisbon") == ("", None))
# Tom's QA (23.10): the real Artist HTML of File:Ponte Vecchio, Florence.jpg - stripping the tags alone gave
# "AnonymousUnknown author", which passed as an author.
PONTE = '<span>Anonymous</span><span style="display:none">Unknown author</span>'
with patch.object(itinerary_cards.requests, "get", side_effect=fake_api("CC BY-SA 3.0", artist=PONTE)):
    check("Ponte Vecchio's real Artist HTML (Anonymous + hidden 'Unknown author') -> no photo",
          itinerary_cards._wiki_image_licensed("Ponte Vecchio", "Florence") == ("", None))
for unknown in ("Unknown author", "unknown", "Anonymous", "<i>Unknown photographer</i>"):
    with patch.object(itinerary_cards.requests, "get", side_effect=fake_api("CC BY 4.0", artist=unknown)):
        check(f"author '{unknown}' -> no photo", itinerary_cards._wiki_image_licensed("X", "Y") == ("", None))
with patch.object(itinerary_cards.requests, "get", side_effect=fake_api("CC BY 4.0", artist='<a href="u">Jane &amp;amp; Co</a>')):
    check("entities decoded, double-escaped too ('&amp;amp;' -> '&')",
          (itinerary_cards._wiki_image_licensed("X", "Y")[1] or {}).get("artist") == "Jane & Co")
with patch.object(itinerary_cards.requests, "get", side_effect=fake_api("cc by-nc 2.0")):
    check("NC/ND rejected whatever the case ('cc by-nc')", itinerary_cards._wiki_image_licensed("X", "Y") == ("", None))
with patch.object(itinerary_cards.requests, "get", side_effect=fake_api("CC BY-SA 4.0", page="https://en.wikipedia.org/wiki/File:Belem.jpg")):
    check("a local (non-Commons) file -> no photo", itinerary_cards._wiki_image_licensed("Belem Tower", "Lisbon") == ("", None))

# --- The account page --------------------------------------------------------------------------------------
CREDIT = {"artist": "Jane Doe", "license": "CC BY-SA 4.0", "page": "https://commons.wikimedia.org/wiki/File:Belem.jpg"}
days = [{"day": 1, "title": "ליסבון", "items": [
    {"name_he": "מגדל בלם", "image": "https://upload.wikimedia.org/thumb/Belem.jpg", "image_credit": CREDIT, "map_url": "https://maps.example/1"},
    {"name_he": "ישן", "image": "https://upload.wikimedia.org/thumb/Old.jpg", "map_url": "https://maps.example/2"}]}]
EMAIL = "qa-attraction-credit@example.com"
with sqlite3.connect(database.DB_PATH) as conn:
    conn.execute("DELETE FROM members WHERE email=?", (EMAIL,))
    member_id = conn.execute(
        "INSERT INTO members (full_name,email,password_hash,created_at,status,whatsapp_opt_in,preferred_airports) VALUES(?,?,?,?,?,?,?)",
        ("QA", EMAIL, generate_password_hash("x"), datetime.now(timezone.utc).isoformat(), "active", 0, "[]")).lastrowid
    conn.execute("INSERT INTO trip_requests (member_id, request_name, status, answers_json, created_at) VALUES (?,?,?,?,datetime('now'))",
                 (member_id, "QA Credit", "active", json.dumps({"destinations": "LIS", "departure_date": "2027-05-01", "return_date": "2027-05-08",
                                                                "_approved_itinerary": {"text": "...", "days": days}}, ensure_ascii=False)))
    conn.commit()
client = app_module.app.test_client()
with client.session_transaction() as sess:
    sess["member_id"] = member_id
he = client.get("/account?lang=he").get_data(as_text=True)
en = client.get("/account?lang=en").get_data(as_text=True)
check("a licensed photo is shown", "thumb/Belem.jpg" in he)
check("HE credit in Din's format, linking to the Commons page, the author/licence in <bdi> (Tom's QA, as in #165)",
      '<a class="itin-card-credit" href="https://commons.wikimedia.org/wiki/File:Belem.jpg" target="_blank" rel="noopener" dir="rtl">'
      "צילום: <bdi>Jane Doe / CC BY-SA 4.0</bdi>, דרך Wikimedia Commons</a>" in he)
check("EN credit in Din's format", "Photo: Jane Doe / CC BY-SA 4.0, via Wikimedia Commons</a>" in en)
check("a card built before this (no licence info) -> no photo", "thumb/Old.jpg" not in he and "thumb/Old.jpg" not in en)
with sqlite3.connect(database.DB_PATH) as conn:
    conn.execute("DELETE FROM members WHERE email=?", (EMAIL,))
    conn.commit()

print()
print("ALL PASS" if not FAILED else f"{len(FAILED)} FAILED: {FAILED}")
sys.exit(1 if FAILED else 0)
