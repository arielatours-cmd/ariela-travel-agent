"""QA for a bug Carmit found live on the production site (2026-10-14), via
manual testing (not Shaked's automated QA run): a day-1 itinerary line read
"...כיכר באן יelačić', הקתדרלה והגן הבוטני..." - the Hebrew letter "י" fused
directly onto a Latin place-name fragment ("elačić", from Zagreb's Ban
Jelačić Square) inside the same token, no space or hyphen between them, mid
sentence.

_strip_garbled_lead_token already drops exactly this Hebrew+Latin
letter-mixing glitch, but only at the very start of a reply.
_strip_mixed_script_garble catches mid-text garbles but never counts Hebrew
as one of its mixed scripts (it only looks at Latin/Cyrillic/Greek).
_strip_mixed_hebrew_latin_token closes that gap: it scans the whole reply,
drops any token where Hebrew and (possibly accented) Latin letters sit
directly adjacent, and explicitly leaves the established house style of a
hyphen-joined Hebrew preposition + Latin term ("ב-JFK", "לינה ב-X") alone,
since a hyphen is never the garble signature, only direct fusion is.

Run: python3 tools/qa_mixed_hebrew_latin_token.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import ariella_chat_clean as chat

FAILED = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


# --- 1. The exact live bug: Hebrew "י" fused onto an accented Latin place
#        name fragment mid-sentence -> the garbled token is dropped, the
#        rest of the sentence survives intact ---
live_bug = "סיור קליל ברחבי העיר העתיקה, כיכר באן יelačić', הקתדרלה והגן הבוטני."
fixed = chat._strip_mixed_hebrew_latin_token(live_bug)
check("garbled Hebrew+Latin token is dropped", "elačić" not in fixed and "יelačić" not in fixed)
check("the rest of the sentence survives (הקתדרלה, הגן הבוטני still present)",
      "הקתדרלה" in fixed and "הגן הבוטני" in fixed)
check("the word just before the garble survives too (כיכר באן)", "כיכר באן" in fixed)

# --- 2. The established house style of a Hebrew preposition hyphen-joined
#        to a Latin term/airport code must NEVER be touched - a hyphen is
#        not the garble signature ---
hyphen_forms = "לנחות ב-JFK ואז לינה ב-Dubrovnik, ולבסוף לטוס ל-Split."
check("legitimate ב-X/ל-X hyphenated forms are left completely untouched",
      chat._strip_mixed_hebrew_latin_token(hyphen_forms) == hyphen_forms)

# --- 3. A genuine Hebrew transliteration with a geresh (׳/') is pure Hebrew
#        script - never flagged just because it has an apostrophe-like mark ---
hebrew_geresh = "לינה בזאגרב, כיכר ילאצ׳יץ׳."
check("Hebrew geresh transliteration is left untouched (not mistaken for Latin)",
      chat._strip_mixed_hebrew_latin_token(hebrew_geresh) == hebrew_geresh)

# --- 4. A legitimate standalone Latin place name as its own separate word
#        next to Hebrew text (never fused) is left untouched ---
standalone_latin = "סיור ב-Plitvice Lakes בשעות הבוקר."
check("standalone Latin term as its own token is left untouched",
      chat._strip_mixed_hebrew_latin_token(standalone_latin) == standalone_latin)

# --- 5. The original lead-token glitch example ("סדחFOSX") is also caught
#        when it appears mid-text, not just at the very start ---
mid_text_glitch = "הגעתם ליעד סדחFOSX בשלום."
fixed_mid = chat._strip_mixed_hebrew_latin_token(mid_text_glitch)
check("a Hebrew+Latin fused glitch mid-text is also caught (not just lead token)",
      "סדחFOSX" not in fixed_mid and "הגעתם" in fixed_mid)

# --- 6. Defensive: text with no mixed tokens at all, or no Hebrew/no Latin
#        at all, passes through completely unchanged; no crash on None ---
check("plain Hebrew text with no Latin at all is unchanged",
      chat._strip_mixed_hebrew_latin_token("שלום, איך אפשר לעזור לך היום?") == "שלום, איך אפשר לעזור לך היום?")
check("plain Latin/English text with no Hebrew at all is unchanged",
      chat._strip_mixed_hebrew_latin_token("JFK to LCA, direct flight.") == "JFK to LCA, direct flight.")
check("None text never crashes", chat._strip_mixed_hebrew_latin_token(None) == "")

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL MIXED-HEBREW-LATIN-TOKEN TESTS PASSED")
