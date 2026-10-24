"""QA: /affiliate-disclosure in Din's approved wording (23.10.2026, din-reports:
legal/drafts/affiliate-disclosure.md), word for word, in Hebrew and English.

- Shown always - no longer depends on kiwi_enabled() (LEG-9); the old
  "working draft for legal review" note is gone.
- Four parts: what an affiliate link is; the partners (CJ, Travelpayouts incl.
  Kiwi.com); what it means for you (4 sentences); questions (the contact page).
- [Privacy Policy] / [Contact] are real links (site.privacy / site.contact).
- There is no /affiliates route to redirect (Din's note) - the page lives only
  at /affiliate-disclosure.

Offline. Run: python3 tools/qa_affiliate_disclosure_page.py
"""
import html
import os
import re
import sys
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")
os.environ.setdefault("SCHEDULER_ENABLED", "false")

import app as app_module  # noqa: E402

FAILED = []
client = app_module.app.test_client()


def check(name, cond):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        FAILED.append(name)


def text(lang):
    body = client.get(f"/affiliate-disclosure?lang={lang}").get_data(as_text=True)
    body = body[body.index('class="shell narrow article-copy legal-copy"'):]
    body = body[:body.index("</section>")]
    return body, re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", body))).strip()


HE = ["גילוי נאות וקישורי שותפים", 'מה זה "קישור שותף"',
      'חלק מכפתורי ההזמנה באתר הם קישורי שותפים. כשתזמינו דרכם טיסה, לינה או רכב, הספק משלם לאריאלה עמלה. הכפתורים האלה מסומנים במילים "קישור שותף".',
      "מי השותפים", "כרגע אנחנו עובדים עם תוכניות השותפים של CJ ו-Travelpayouts (כולל Kiwi.com). הרשימה תתעדכן אם יתווספו שותפים.",
      "מה זה אומר בשבילכם", "העמלה משולמת על ידי הספק, והיא לא נוספת למחיר שאתם משלמים.",
      "ההזמנה והתשלום נעשים ישירות מול הספק, ובתנאים שלו: מחיר, ביטול ושינויים. אריאלה איננה צד לעסקה.",
      "ההמלצות של אריאלה מבוססות על ההתאמה להעדפות שלכם ועל המחיר, ולא על גובה העמלה.",
      "כשאתם לוחצים על קישור שותף, אנחנו מעבירים לשותף רק מזהה טכני של החופשה, כדי לשייך את ההזמנה. לא מועברים שם, טלפון או אימייל.",
      "שאלות"]
EN = ["Affiliate Disclosure", 'What an "Affiliate link" is',
      'Some booking buttons on the site are affiliate links. When you book a flight, a stay or a car through them, the provider pays Ariella a commission. These buttons are marked "Affiliate link".',
      "Our partners", "We currently work with the CJ and Travelpayouts affiliate programs (including Kiwi.com). This list will be updated if partners are added.",
      "What it means for you", "The commission is paid by the provider and is not added to the price you pay.",
      "The booking and payment are made directly with the provider, under its terms: price, cancellation and changes. Ariella is not a party to the transaction.",
      "Ariella's recommendations are based on how well an option fits your preferences and on price, not on the commission.",
      "When you click an affiliate link, we pass the partner only a technical trip identifier, so the booking can be attributed. No name, phone number or email is passed.",
      "Questions"]

for kiwi_on in (True, False):
    with patch.dict(app_module.app.jinja_env.globals, {"kiwi_enabled": lambda: kiwi_on}):
        he_html, he = text("he")
        en_html, en = text("en")
    tag = "kiwi on" if kiwi_on else "kiwi off"
    check(f"[{tag}] HE: every sentence of Din's wording, word for word", all(s in he for s in HE))
    check(f"[{tag}] EN: every sentence of Din's wording, word for word", all(s in en for s in EN))
    check(f"[{tag}] the same page either way (no kiwi_enabled() branch)", "Working draft" not in en and "נוסח עבודה" not in he)
check("HE links: מדיניות הפרטיות -> /privacy, יצירת קשר -> /contact",
      'href="/privacy">מדיניות הפרטיות</a>' in he_html and 'href="/contact">יצירת קשר</a>' in he_html)
check("EN links: Privacy Policy -> /privacy, Contact -> /contact",
      'href="/privacy">Privacy Policy</a>' in en_html and 'href="/contact">Contact</a>' in en_html)
check("no Hebrew on the English page", not re.search(r"[֐-׿]", en))
src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates", "affiliates.html"), encoding="utf-8").read()
check("template: no kiwi_enabled() branch", "kiwi_enabled" not in src)
check("the label the site uses matches the page ('קישור שותף' / 'Affiliate link')", '"קישור שותף"' in he and '"Affiliate link"' in en)

print()
print("ALL PASS" if not FAILED else f"{len(FAILED)} FAILED: {FAILED}")
sys.exit(1 if FAILED else 0)
