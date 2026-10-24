"""QA for the partner-name env var URL/markup guard (Ron, 23.10.2026,
a8d43781, business owner's screenshot): CAR_RENTAL_PARTNER_NAME had a CJ
tracking URL pasted into it on Render instead of the display name "VIP
Cars" - the car card then showed the customer "Live prices and
availability on https://www.jdoqocy.com/click-15734197-123" verbatim,
since a partner NAME is rendered as plain text, never validated as a URL
would be. The business owner's own Render value is already corrected
directly; this is the code-level defense for the same mistake happening
again, for both partner-name env vars that share this risk:
CAR_RENTAL_PARTNER_NAME, LODGING_PARTNER_NAME.

Mirrors tools/qa_affiliate_link_html_guard.py's own pattern for the
sibling _sanitize_affiliate_link_env guard (PR #151) - same class of
env-var misconfiguration, opposite direction (a name env var getting a
URL, instead of a URL env var getting markup).

Run: python3 tools/qa_partner_name_url_guard.py
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


sanitize = config._sanitize_partner_name_env

check("unset (None) -> falls back to the given default",
      sanitize("CAR_RENTAL_PARTNER_NAME", None, "VIP Cars") == "VIP Cars")
check("empty string -> falls back to the given default",
      sanitize("CAR_RENTAL_PARTNER_NAME", "", "VIP Cars") == "VIP Cars")
check("whitespace-only -> falls back to the given default",
      sanitize("CAR_RENTAL_PARTNER_NAME", "   ", "VIP Cars") == "VIP Cars")
check("a genuine partner name -> passes through unchanged",
      sanitize("CAR_RENTAL_PARTNER_NAME", "VIP Cars", "VIP Cars") == "VIP Cars")
check("a genuine partner name with surrounding whitespace -> trimmed, "
      "passes through",
      sanitize("LODGING_PARTNER_NAME", "  Agoda  ", "Agoda") == "Agoda")
check("a genuine Hebrew partner name is accepted unchanged (never assumed "
      "to be English-only)",
      sanitize("CAR_RENTAL_PARTNER_NAME", "חברת השכרה", "VIP Cars") == "חברת השכרה")

# The business owner's own live repro (23.10.2026): a CJ tracking URL
# pasted into the NAME var instead of the display name.
_LIVE_REPRO_URL = "https://www.jdoqocy.com/click-15734197-123"
check("the business owner's exact live repro (a bare CJ tracking URL) is "
      "rejected, never shown to the customer as a 'name'",
      sanitize("CAR_RENTAL_PARTNER_NAME", _LIVE_REPRO_URL, "VIP Cars") == "")
check("an http:// URL (not just https://) is also rejected",
      sanitize("CAR_RENTAL_PARTNER_NAME", "http://example.com", "VIP Cars") == "")
check("a scheme-less 'www.' host is rejected",
      sanitize("LODGING_PARTNER_NAME", "www.agoda.com", "Agoda") == "")
check("an HTML snippet (the sibling CJ 'Get HTML' mistake, name slot this "
      "time) is rejected",
      sanitize("CAR_RENTAL_PARTNER_NAME",
                '<a href="https://example.com">VIP Cars</a>', "VIP Cars") == "")
check("a value with an embedded query string ('=') is rejected even "
      "without a full scheme",
      sanitize("CAR_RENTAL_PARTNER_NAME", "ref=abc123", "VIP Cars") == "")
check("a value with a stray '/' (a path fragment, not a name) is rejected",
      sanitize("LODGING_PARTNER_NAME", "Agoda/partner", "Agoda") == "")
check("regression: a real partner name that merely CONTAINS the substring "
      "'www' as part of a word is not falsely rejected",
      sanitize("CAR_RENTAL_PARTNER_NAME", "Wawanesa Rentals", "VIP Cars") == "Wawanesa Rentals")

# Rejection never silently falls back to the default here - a URL/markup
# value is treated as "no name at all" (the template then hides the
# name-dependent lines entirely), never as "guess the real name for me".
check("rejection returns blank, not the fallback default (never guesses "
      "which of 'the URL' or 'the default' the business owner actually "
      "meant)",
      sanitize("CAR_RENTAL_PARTNER_NAME", _LIVE_REPRO_URL, "VIP Cars") != "VIP Cars")

# Both real config values go through the same guard at import time - just
# confirms the guard ran without raising, whatever this environment's
# actual env var happens to be (unset falls back to the default; a
# genuinely invalid value in some environment would correctly come back
# blank, not raise - blank is a legitimate outcome here, not asserted
# against, mirroring qa_affiliate_link_html_guard.py's own equivalent check).
check("config.CAR_RENTAL_PARTNER_NAME is a string (guard ran without raising)",
      isinstance(config.CAR_RENTAL_PARTNER_NAME, str))
check("config.LODGING_PARTNER_NAME is a string (same)",
      isinstance(config.LODGING_PARTNER_NAME, str))

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL PARTNER-NAME-URL-GUARD TESTS PASSED")
