"""QA: flight card alignment (the business owner, 23.10, via Shlomo - Lisbon card).

1. The "אפשרות שכדאי להכיר" / "לא כולל: ..." note at the top of the card sat on
   the left in Hebrew (the card's layout direction is LTR). Now RTL + right in
   Hebrew, LTR + left in English.
2. "Total flight duration": on mobile the outbound line was pinned right, but in
   English the return line followed text-align:left and sat mid-card. Now both
   legs, both languages: the airline on the left, the duration pinned right.

Measured with Playwright at 375px and 1200px (he/en) when the change was made.
Offline (CSS source). Run: python3 tools/qa_flight_card_alignment.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAILED = []


def check(name, cond):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        FAILED.append(name)


css = open(os.path.join(ROOT, "static", "mobile-deal-card-fixes.css"), encoding="utf-8").read()
base = open(os.path.join(ROOT, "templates", "base.html"), encoding="utf-8").read()
check("note: Hebrew RTL + right", ".deal-card-v970.deal-he .deal-close-match-note{direction:rtl!important;text-align:right!important}" in css)
check("note: English LTR + left", ".deal-card-v970.deal-en .deal-close-match-note{direction:ltr!important;text-align:left!important}" in css)
mobile = css[css.index("/* \"Total flight duration\""):]
check("mobile: both languages' duration pinned right (beats site.css's deal-en text-align:left)",
      "@media (max-width:760px)" in mobile and ".deal-card-v970.deal-he .leg-duration," in mobile
      and ".deal-card-v970.deal-en .leg-duration{text-align:right!important}" in mobile)
check("cache-busting version bumped", "mobile-deal-card-fixes.css') }}?v=20261023-card-align" in base)

print()
print("ALL PASS" if not FAILED else f"{len(FAILED)} FAILED: {FAILED}")
sys.exit(1 if FAILED else 0)
