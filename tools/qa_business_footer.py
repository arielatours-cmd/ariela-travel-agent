"""QA for task 004a - business details footer.

Renders a real page (GET /terms) through the Flask test client, with and
without the BUSINESS_* env vars set, and checks the footer line's presence/
absence and content.

Run: python3 tools/qa_business_footer.py
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

FAILED = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


# --- Case 1: no business env vars set -> footer unchanged (no footer-business div) ---
for var in [
    "BUSINESS_LEGAL_NAME_HE", "BUSINESS_LEGAL_NAME_EN", "BUSINESS_DEALER_TYPE_HE",
    "BUSINESS_DEALER_NUMBER", "BUSINESS_ADDRESS_HE", "BUSINESS_ADDRESS_EN", "BUSINESS_CONTACT_EMAIL",
]:
    os.environ.pop(var, None)

import app as app_module

client = app_module.app.test_client()
r = client.get("/terms?lang=he")
check("terms page renders (no business vars)", r.status_code == 200)
check("no footer-business div without legal name/number", b'class="footer-business"' not in r.data)
check("legal footer buttons still render as before", b"footer-legal-buttons" in r.data)

# --- Case 2: all business vars set -> line appears, in both languages ---
import importlib
os.environ["BUSINESS_LEGAL_NAME_HE"] = "אריאלה בע\"מ"
os.environ["BUSINESS_LEGAL_NAME_EN"] = "Ariela Ltd."
os.environ["BUSINESS_DEALER_TYPE_HE"] = "עוסק מורשה"
os.environ["BUSINESS_DEALER_NUMBER"] = "123456789"
os.environ["BUSINESS_ADDRESS_HE"] = "רחוב הדוגמה 1, תל אביב"
os.environ["BUSINESS_ADDRESS_EN"] = "1 Example St, Tel Aviv"
os.environ["BUSINESS_CONTACT_EMAIL"] = "info@example.com"

import config
importlib.reload(config)
import public_site
importlib.reload(public_site)
# app.py already imported public_site.site at import time; re-registering the
# same blueprint object's context processor after reload re-binds the
# function public_site.inject_site_context points to, but the Flask app
# already holds the blueprint's *original* registered function reference.
# For this QA script we exercise _business_details() directly (the unit
# the task actually introduces) plus one live render to confirm wiring,
# rather than fighting Flask's blueprint-registration-is-one-shot design.
business = public_site._business_details()
check("show=True when legal name + number set", business["show"] is True)
check("HE line contains trade name", "ARIELA AI TRAVEL" in business["line_he"])
check("HE line contains legal name", "אריאלה בע\"מ" in business["line_he"])
check("HE line contains dealer type+number", "עוסק מורשה 123456789" in business["line_he"])
check("HE line contains address", "רחוב הדוגמה 1" in business["line_he"])
check("HE line contains email", "info@example.com" in business["line_he"])
check("EN line contains 'Licensed Dealer 123456789'", "Licensed Dealer 123456789" in business["line_en"])
check("EN line contains legal name EN", "Ariela Ltd." in business["line_en"])
check("EN line contains address EN", "1 Example St" in business["line_en"])

# --- Case 3: only dealer number set (no legal name at all) -> still shows (per spec: hidden only when BOTH legal name and number are absent) ---
for var in ["BUSINESS_LEGAL_NAME_HE", "BUSINESS_LEGAL_NAME_EN", "BUSINESS_DEALER_TYPE_HE", "BUSINESS_ADDRESS_HE", "BUSINESS_ADDRESS_EN", "BUSINESS_CONTACT_EMAIL"]:
    os.environ.pop(var, None)
os.environ["BUSINESS_DEALER_NUMBER"] = "999"
importlib.reload(config)
importlib.reload(public_site)
business3 = public_site._business_details()
check("show=True with only dealer number set", business3["show"] is True)
check("line omits missing parts cleanly (no stray separators)", "· ·" not in business3["line_he"])

# --- Case 4: nothing at all set -> show=False ---
os.environ.pop("BUSINESS_DEALER_NUMBER", None)
importlib.reload(config)
importlib.reload(public_site)
business4 = public_site._business_details()
check("show=False with nothing set", business4["show"] is False)

# --- Case 5: a real page render with the context processor's business dict
# patched directly (avoids Flask's one-shot blueprint context-processor
# registration, while still exercising the actual template) ---
from unittest.mock import patch

fake_business = {
    "show": True, "trade_name": "ARIELA AI TRAVEL",
    "line_he": "ARIELA AI TRAVEL · חברת בדיקה בעמ · עוסק מורשה 555",
    "line_en": "ARIELA AI TRAVEL · QA Test Ltd. · Licensed Dealer 555",
}
with patch.object(public_site, "_business_details", return_value=fake_business):
    r_he = client.get("/terms?lang=he")
    r_en = client.get("/terms?lang=en")
check("HE page shows the business line in the actual rendered footer", "חברת בדיקה בעמ".encode() in r_he.data)
check("EN page shows the business line in the actual rendered footer", b"QA Test Ltd." in r_en.data)
check("EN page uses the EN line, not the HE one", b"Licensed Dealer 555" in r_en.data and "חברת בדיקה".encode() not in r_en.data)

print()
if FAILED:
    print(f"FAILED ({len(FAILED)}): {FAILED}")
    sys.exit(1)
print("ALL CHECKS PASSED")
