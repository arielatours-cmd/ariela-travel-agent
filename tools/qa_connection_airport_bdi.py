"""QA: the connection airport name is wrapped in <bdi> (the business owner, 23.10,
via Shlomo - Lisbon card, Hebrew only: 'Athens International Airport ""Eleftherios
Venizelos' - the quotes broke in the RTL pill; English was fine).

A direction problem, not a data problem: the text is unchanged, only isolated
(<bdi>, dir=auto - an English name is LTR, a Hebrew one would stay RTL). Both legs.
Checked visually at 375px he/en when the change was made.

Offline. Run: python3 tools/qa_connection_airport_bdi.py
"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "q.db"))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")
os.environ.setdefault("SCHEDULER_ENABLED", "false")

import app as app_module  # noqa: E402

FAILED = []


def check(name, cond):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        FAILED.append(name)


ATH = 'Athens International Airport "Eleftherios Venizelos"'
offer = {"id": 1, "departure_code": "TLV", "arrival_code": "LIS", "outbound_date": "2027-05-01", "return_date": "2027-05-08",
         "stops": 1, "return_stops": 1, "price_ils": 1900, "airline": "Aegean", "return_airline": "Iberia", "baggage": {},
         "connections": [{"airport": ATH, "duration_minutes": 95}],
         "return_connections": [{"airport": "Madrid-Barajas Adolfo Suárez", "duration_minutes": 120}]}
app = app_module.app
with app.test_request_context("/"):
    for lang in ("he", "en"):
        html = app.jinja_env.from_string('{% from "_deal_card.html" import deal_card %}{{ deal_card(o, lang) }}').render(o=offer, lang=lang)
        check(f"{lang}: outbound connection name isolated in <bdi>, text unchanged",
              '<span class="connection-airport"><bdi>Athens International Airport &#34;Eleftherios Venizelos&#34;</bdi></span>' in html)
        check(f"{lang}: return connection name isolated too",
              '<span class="connection-airport"><bdi>Madrid-Barajas Adolfo Suárez</bdi></span>' in html)

print()
print("ALL PASS" if not FAILED else f"{len(FAILED)} FAILED: {FAILED}")
sys.exit(1 if FAILED else 0)
