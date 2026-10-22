"""QA for the contact page (Bezalel's task 6, 22.10): /contact is a form
with an OPTIONAL phone field, linked from the site footer. /feedback keeps
its required phone exactly as before. Nothing in Ariella's chat changes.

Offline, temp DB. Run: python3 tools/qa_contact_form.py
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_TMP = tempfile.mkdtemp(prefix="ariella-qa-contact-")
os.environ.update({"DB_PATH": os.path.join(_TMP, "qa.db"), "SCHEDULER_ENABLED": "false",
                   "SCANNER_ENABLED": "false"})
for key in ("SERPAPI_API_KEY", "ANTHROPIC_API_KEY", "WHATSAPP_ACCESS_TOKEN"):
    os.environ.pop(key, None)

FAILED = []


def check(name, cond):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        FAILED.append(name)


import app as app_module  # noqa: E402
from database import connection  # noqa: E402

client = app_module.app.test_client()


def rows():
    with connection() as conn:
        return [dict(r) for r in conn.execute("SELECT full_name,email,phone,message FROM feedback_messages ORDER BY id").fetchall()]


# --- Page ----------------------------------------------------------------------------------
for lang, title, phone_label in (("he", "יצירת קשר", "טלפון (לא חובה)"), ("en", "Contact", "Phone (optional)")):
    r = client.get(f"/contact?lang={lang}")
    page = r.get_data(as_text=True)
    check(f"/contact ({lang}) renders the form", r.status_code == 200 and 'class="feedback-form"' in page)
    check(f"/contact ({lang}) title + optional phone label", title in page and phone_label in page)
    form = page[page.find('class="feedback-form"'):page.find("</form>")]
    check(f"/contact ({lang}) posts to /contact", 'action="/contact"' in form)
    phone_input = form[form.find('name="phone"'):]
    phone_input = phone_input[:phone_input.find(">")]
    check(f"/contact ({lang}) phone field is not required", "required" not in phone_input)

# --- Footer link on regular pages --------------------------------------------------------
for path in ("/?lang=he", "/deals?lang=he", "/about?lang=en", "/terms?lang=he"):
    page = client.get(path).get_data(as_text=True)
    check(f"footer on {path} links to /contact", 'href="/contact?lang=' in page)

# --- Submitting --------------------------------------------------------------------------------
r = client.post("/contact", data={"full_name": "דנה", "email": "dana@example.com", "phone": "", "message": "שאלה על חופשה"})
check("contact without phone -> accepted, thank-you redirect", r.status_code == 302 and r.headers["Location"].endswith("/contact?sent=1"))
check("contact without phone -> saved with an empty phone", rows()[-1] == {"full_name": "דנה", "email": "dana@example.com", "phone": "", "message": "שאלה על חופשה"})
r = client.post("/contact", data={"full_name": "Dan", "email": "dan@example.com", "phone": "050-1234567", "message": "hello there"})
check("contact with phone -> saved with the phone", r.status_code == 302 and rows()[-1]["phone"] == "050-1234567")
thanks = client.get("/contact?sent=1").get_data(as_text=True)
check("thank-you page after sending", "תודה! קיבלנו את הפנייה שלכם." in thanks)

before = len(rows())
for bad in ({"full_name": "", "email": "a@b.co", "message": "hello"},
            {"full_name": "A", "email": "not-an-email", "message": "hello"},
            {"full_name": "A", "email": "a@b.co", "message": "hi"},
            {"full_name": "A", "email": "a@b.co", "message": "hello", "phone": "1" * 41}):
    r = client.post("/contact", data=bad)
    check(f"invalid contact {sorted(k for k, v in bad.items() if v)} -> back to the form, nothing saved",
          r.status_code == 302 and r.headers["Location"].endswith("/contact") and len(rows()) == before)
r = client.post("/contact", data={"full_name": "Bot", "email": "b@b.co", "message": "spam spam", "website": "x"})
check("honeypot -> silently dropped", len(rows()) == before)

# --- /feedback unchanged: phone still required -----------------------------------------------
page = client.get("/feedback?lang=he").get_data(as_text=True)
form = page[page.find('class="feedback-form"'):page.find("</form>")]
check("/feedback still says 'כתבו לנו' and posts to /feedback", "כתבו לנו" in page and 'action="/feedback"' in form)
phone_input = form[form.find('name="phone"'):]
check("/feedback phone still required", "required" in phone_input[:phone_input.find(">")])
before = len(rows())
r = client.post("/feedback", data={"full_name": "A", "email": "a@b.co", "phone": "", "message": "hello"})
check("/feedback without phone -> rejected as before", r.headers["Location"].endswith("/feedback") and len(rows()) == before)
r = client.post("/feedback", data={"full_name": "A", "email": "a@b.co", "phone": "050", "message": "hello"})
check("/feedback with phone -> accepted as before", r.headers["Location"].endswith("/feedback?sent=1") and len(rows()) == before + 1)

print()
print("ALL PASS" if not FAILED else f"{len(FAILED)} FAILED: {FAILED}")
sys.exit(1 if FAILED else 0)
