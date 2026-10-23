"""QA for the affiliate-link env var HTML/junk guard, per Shlomo's relay
(22.10.2026): CJ_BOOKING_EVERGREEN_LINK was pasted into Render as the FULL
HTML snippet CJ's dashboard shows next to a tracking link
(<a href="..."><img .../></a>), not just the bare URL inside it - silently
breaking every lodging link built from it (the "href" of an <a> tag is not
itself a valid destination to wrap further or deep-link into). The business
owner is fixing the Render value directly; this is the code-level defense
for the same class of mistake happening again, for all three affiliate-link
env vars that share this CJ-dashboard copy/paste risk:
CJ_BOOKING_EVERGREEN_LINK, CAR_RENTAL_AFFILIATE_LINK, LODGING_AFFILIATE_LINK.

Run: python3 tools/qa_affiliate_link_html_guard.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import config

FAILED = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


sanitize = config._sanitize_affiliate_link_env

check("empty value -> blank, no warning raised as an exception",
      sanitize("CJ_BOOKING_EVERGREEN_LINK", "") == "")
check("whitespace-only value -> blank",
      sanitize("CJ_BOOKING_EVERGREEN_LINK", "   ") == "")
check("a genuine bare https URL -> passes through unchanged",
      sanitize("CJ_BOOKING_EVERGREEN_LINK", "https://www.anrdoezrs.net/click-123-456")
      == "https://www.anrdoezrs.net/click-123-456")

# Shlomo's exact live repro: CJ's dashboard "Get HTML" snippet, pasted whole.
_CJ_HTML_SNIPPET = (
    '<a href="https://www.anrdoezrs.net/click-123-456" target="_blank">'
    '<img src="https://www.ftjcfx.com/image-123-456" width="1" height="1" '
    'border="0"/></a>'
)
check("CJ's full <a href><img/></a> HTML snippet -> the href alone is "
      "extracted, not treated as junk",
      sanitize("CJ_BOOKING_EVERGREEN_LINK", _CJ_HTML_SNIPPET)
      == "https://www.anrdoezrs.net/click-123-456")
check("same HTML snippet, single-quoted href attribute -> NOT matched by "
      "the double-quote-only extractor, so it falls through to the plain "
      "validity check and is correctly rejected as junk (contains '<')",
      sanitize("CJ_BOOKING_EVERGREEN_LINK",
               "<a href='https://www.anrdoezrs.net/click-1'>text</a>") == "")
check("an <a> tag with no href at all -> no match, falls through to the "
      "plain validity check, rejected (contains '<')",
      sanitize("CJ_BOOKING_EVERGREEN_LINK", "<a>https://example.com</a>") == "")
check("a bare value that still contains a stray '<' -> rejected",
      sanitize("CJ_BOOKING_EVERGREEN_LINK", "https://example.com<script>") == "")
check("a bare value with embedded whitespace -> rejected (not one single URL)",
      sanitize("CJ_BOOKING_EVERGREEN_LINK", "https://example.com extra") == "")
check("a value with no https:// scheme at all -> rejected",
      sanitize("CJ_BOOKING_EVERGREEN_LINK", "http://example.com") == "")
check("a value with no scheme at all -> rejected",
      sanitize("CJ_BOOKING_EVERGREEN_LINK", "www.example.com") == "")

# All three real config values go through the same guard at import time.
check("config.CJ_BOOKING_EVERGREEN_LINK is a string (guard ran without "
      "raising, whatever this environment's actual value is)",
      isinstance(config.CJ_BOOKING_EVERGREEN_LINK, str))
check("config.CAR_RENTAL_AFFILIATE_LINK is a string (guard ran without "
      "raising)",
      isinstance(config.CAR_RENTAL_AFFILIATE_LINK, str))
check("config.LODGING_AFFILIATE_LINK is a string (guard ran without "
      "raising)",
      isinstance(config.LODGING_AFFILIATE_LINK, str))

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL AFFILIATE-LINK-HTML-GUARD TESTS PASSED")
