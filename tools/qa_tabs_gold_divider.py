"""QA: a gold vertical divider between the trip tabs on every row (the
business owner, 23.10, via Shlomo - on mobile the bottom row "Car |
Itinerary" had no divider).

The tabs used border-left, which isn't direction-aware: in Hebrew (RTL) the
bottom row got only the faint beige line, in English (LTR) none at all.
Now border-inline-end in gold, removed from the last tab and, in the
two-column mobile grid, from the end of each row.

Offline (CSS source). Visual check at 375px/1200px, he/en, done with
Playwright when the change was made. Run: python3 tools/qa_tabs_gold_divider.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAILED = []


def check(name, cond):
    print(f"[{'PASS' if cond else 'FAIL'}] {name}")
    if not cond:
        FAILED.append(name)


css = open(os.path.join(ROOT, "static", "site.css"), encoding="utf-8").read()
base = open(os.path.join(ROOT, "templates", "base.html"), encoding="utf-8").read()
check("tabs: gold, direction-aware divider (border-inline-end)", ".vacation-tab{border:0;border-inline-end:1px solid #c99a3f;" in css)
check("tabs: no direction-blind border-left left", ".vacation-tab{border:0;border-left" not in css and ".vacation-tab:last-child{border-left" not in css)
check("tabs: the last tab has no divider", ".vacation-tab:last-child{border-inline-end:0}" in css)
check("mobile 2x2 grid: no divider at the end of each row", ".vacation-tabs:not(.tabs-3) .vacation-tab:nth-child(2n){border-inline-end:0}" in css)
check("site.css cache-busting version bumped", "site.css') }}?v=20261023-tabs-gold" in base)

print()
print("ALL PASS" if not FAILED else f"{len(FAILED)} FAILED: {FAILED}")
sys.exit(1 if FAILED else 0)
