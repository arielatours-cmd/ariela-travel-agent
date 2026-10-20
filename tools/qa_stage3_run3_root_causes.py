"""QA for a subset of Shaked's stage-3 run-3 root-cause findings (18.10.2026,
main 4db4653, qa/reports/2026-10-18-stage3-run3.md, branch shaked @80d27f8),
assigned by Shlomo as task 2 (after the urgent loop guard, PR #82). Covers
items (b), (c), (d) of his 5-item list in full, and now (a) too (see below);
(e) (lodging budget currency - a known, larger schema gap, deferred from
#77's review) is NOT in this PR.

Item (a) ("current_question must drive what's actually asked", Madrid V1 +
Milano V2) went through two prior attempts, both reverted:
1. A deterministic topic-keyword enforcer on Ariella's own composed
   question text (_enforce_guided_question_matches_field, analogous to
   _enforce_one_option_question) - reverted after the full regression
   sweep proved it unsafe (rewrote a legitimate post-flight-offer reply
   and a first-turn greeting into a forced guided question).
2. Extending _BUNDLED_AND_QUESTION_RE with "וזה"/"וזאת" for Madrid's own
   fused confirm-and-ask phrasing - shipped briefly, then reverted on
   Shlomo's own follow-up: it's itself a phrase-list growth the business
   owner's 18.10 directive rules out, however incremental it looked next
   to the already-covered forms.

The actual fix (per the business owner's explicit spec, relayed by
Shlomo): the guided extractor, once the live field (current_question)
rejects a message as other_topic, now gets Ariella's own LAST REAL sent
message (the literal text she actually sent, not a hint) plus every
other still-open guided field, and the MODEL decides which of them the
reply actually answers - saved there with a verbatim evidence quote,
never a keyword. current_question itself stays untouched (still
genuinely due - "stays the next one in queue"). See
_guided_redirect_field and its wiring into the other_topic branch of
_handle_guided_extraction_turn, and tools/qa_guided_field_redirect.py for
the Madrid/Milano repros and regressions.

Bug (b) - Madrid: #81's also_mentioned guard for lodging.details.level only
covered ONE write path. The main per-turn extractor (_extract_trip_update,
source="state_extractor") can independently write the same field straight
into its own JSON, bypassing that guard entirely - "מלון חמוד ושקט" (no
budget/level/star word at all) got saved as level="בינוני" through this
exact path. Fixed: _validate_lodging_level_against_message applies the
same _level_stated_in_message check to the extractor's own output, general
to every write path.

Bug (c) - Lisbon: flight.baggage_detail (the per-passenger count/unit
split) got silently reinterpreted by the same main extractor on a later
turn where the customer said nothing new about baggage at all - Tinkerbell
then claimed "I understood this was one bag per passenger", never actually
restated that turn. Fixed: _validate_baggage_detail_against_message reverts
a baggage_detail change unless the current message mentions baggage in
some form (reuses _baggage_answer_by_meaning's own established gate words -
not a new phrase list).

Also fixed, found while reproducing (c): 'baggage' (and in principle any
guided field) could appear twice in guided.answered when current_question
was already independently marked answered by the pre-satisfied scan before
its own "status=answered" handling also appended it - cosmetic (membership
checks still work with a duplicate present) but a clear bug in its own
right, fixed with a one-line not-already-there guard.

Bug (d) - Berlin: trip_planning.details.style came back from the model's
own JSON as a list of English interest-category tags (e.g.
["history","museums","nightlife"]) instead of the customer's own words,
and _to_hebrew_display (added in #81) only translated a bare string, so
the raw Python list (str(list), brackets and quotes included) leaked
straight into the customer-facing route summary line. Fixed in two layers:
_to_hebrew_display now translates list values item-by-item and joins them
(general, not scoped to style); _normalize_trip_planning_style normalizes
the list to a translated, joined string already at parse time (_parse_
trip_update), "already at save time" per Shlomo's own wording, so nothing
downstream ever merges a raw list into state at all.

Also folded into (d), per Shlomo's follow-up after rebasing onto #82:
"הוסטל" (hostel - what the Berlin customer actually booked) was never one
of the 5 original canonical lodging.details.type values, so it could never
be saved at all, leaving the lodging summary line's own type slot empty
forever (and contributing to the same transcript's guided-loop symptom,
fixed separately in #82). Added as a 6th canonical value throughout
(_LODGING_TYPE_VALUES, _LODGING_TYPE_CANON_VALUES, the guided prompt/
schema, the hint text, the system prompt) - "אכסניה" (the formal Hebrew
word for the same thing, already used elsewhere in this file's own
general lodging-topic detection) is accepted as a synonym, canonicalized
the same way "אפרטמנט" already canonicalizes to "דירה".

Also folded in, per Shaked's 2026-10-18 daily QA report (qa/reports/
2026-10-18.md, branch shaked @77173fb) on the stage-2 fail-safe regex
_deterministic_baggage_facts (unrelated to items b/c/d above, but the same
"ship it in the roots PR" instruction): two phrasing gaps in the fail-safe
itself - "מזוודה לכל אחד" (a bare suitcase mention with no "גדולה"/"בבטן"/
"משותפת" qualifier) matched none of the existing specific patterns and
returned {} entirely; and "כל אחד טרולי, ומזוודה אחת משותפת" / "מזוודה אחת
לכולנו וטרולי לכל מבוגר" (the carry-on phrase in reversed word order, or
naming a traveler noun - "מבוגר" - the old pattern didn't list) both kept
the checked-bag half but silently dropped the carry-on half. Fixed with two
general rules: the bare word "מזוודה"/"מזוודות", unless negated nearby,
always means a checked bag was mentioned; and "טרולי" plus a per-person
phrase, in EITHER order and naming any of the traveler nouns actually seen
live, always means a carry-on per traveler. Both added to qa/cases.json too.

Also fixed, per Shaked's actual review of this PR's first commit (not her
daily report): _validate_baggage_detail_against_message's own gate words
were a bug in the same spirit as the extractor bug it exists to catch -
the gate matched only the exact words "כבודה"/"טרולי"/"מזוודה", so
"מזוודות" (plural) and "כבודת יד"/"כבודת עלייה" (both of which diverge
from those exact spellings only at the final letter) were wrongly treated
as NOT mentioning baggage, reverting perfectly normal answers like "שתי
מזוודות לכולנו" back to {}. Fixed by matching the shared stem via regex
instead of the exact word.

Added, then REVERTED the same day: per Shlomo's follow-up relaying
Shaked's PR #83 review (item 2), a style token _INTERNAL_TOKEN_TO_HEBREW
doesn't list yet (e.g. "street art") used to pass through
_to_hebrew_display untouched and leak into the summary in English - first
fixed by dropping any list item that still contained a Latin letter after
translation. The business owner then ruled this out entirely (18.10.2026,
same directive as the evidence-based rewrite below): "only place names or
airport codes may appear in English" - the Latin-letter filter was wrong
in BOTH directions, since it would also delete a legitimately-English
place name this same style/interest list can carry (e.g. "Barceloneta"),
not just hide an untranslated interest. Reverted to plain passthrough;
the real fix is EXTRACTOR_SYSTEM itself now instructing the model to
translate a customer's own free-text style/interest into Hebrew at
extraction time, explicitly excepting place names/airport codes.

SUPERSEDED the same day by the business owner's explicit architectural
directive (18.10.2026, relayed by Shlomo, reacting to this PR): only the
MODEL decides what the customer said - never a word list, phrase list, or
stem/regex match, however general. This ruled out BOTH
_level_stated_in_message (word-list + star-rating regex, the mechanism
bug (b) above originally reused) AND the stem-regex gate added above for
Shaked's own PR review of bug (c)'s guard. Both are now removed entirely.
Replaced with one shared helper, _value_has_verbatim_evidence: the
extractor itself must supply, alongside any new level or baggage_detail
value, a VERBATIM QUOTE from the customer's current message justifying
it (EXTRACTOR_SYSTEM's own schema now requires lodging.details.
level_evidence / flight.baggage_detail_evidence whenever those values
change). The check only confirms the quote is real (found in the message
as-is) - it never re-decides what counts as "the customer said this"; that
judgment stays entirely with the model. No quote (or a fabricated one not
actually in the message) means no value, same outcome as before, reached
a different way. _deterministic_baggage_facts (today's earlier fail-safe-
only fixes, in the section above) is UNCHANGED - it already only runs when
the model call itself fails, which is exactly the role the business owner
said a regex-based fallback may still have.

Run: python3 tools/qa_stage3_run3_root_causes.py
"""
import os
import sys
import json
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-real")

import ariella_chat_clean as chat

FAILED = []


def check(name, cond):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}")
    if not cond:
        FAILED.append(name)


# =====================================================================
# Bug (b) - Madrid: the main extractor's own write path for lodging level.
# =====================================================================
MADRID_STATE = {"lodging": {"details": {"type": "מלון"}}}

check("Madrid repro: 'מלון חמוד ושקט' (no budget/level/star word at all) "
      "invented via the main extractor's own JSON is dropped - no "
      "level_evidence was supplied, so the evidence-only mechanism "
      "rejects it outright regardless of the message text",
      chat._validate_lodging_level_against_message(
          {"lodging": {"details": {"type": "מלון", "level": "בינוני"}}},
          MADRID_STATE, "מלון חמוד ושקט",
      ) == {"lodging": {"details": {"type": "מלון"}}})
check("regression: a genuinely stated level via the same write path still "
      "survives when the extractor supplies real evidence for it "
      "(business owner's directive: the model's own quote, not a word "
      "list, is what makes this count as 'stated')",
      chat._validate_lodging_level_against_message(
          {"lodging": {"details": {"type": "מלון", "level": "יוקרתי", "level_evidence": "מלון יוקרתי"}}},
          MADRID_STATE, "רוצים מלון יוקרתי",
      )["lodging"]["details"]["level"] == "יוקרתי")
check("a level with evidence that doesn't actually appear in the message "
      "(fabricated quote) is rejected just like no evidence at all",
      chat._validate_lodging_level_against_message(
          {"lodging": {"details": {"type": "מלון", "level": "יוקרתי", "level_evidence": "מלון יוקרתי"}}},
          MADRID_STATE, "מלון חמוד ושקט",
      ) == {"lodging": {"details": {"type": "מלון"}}})
check("regression: a level identical to what was ALREADY persisted is "
      "never re-litigated against an unrelated later message",
      chat._validate_lodging_level_against_message(
          {"lodging": {"details": {"type": "מלון", "level": "בינוני"}}},
          {"lodging": {"details": {"type": "מלון", "level": "בינוני"}}},
          "מה השעה שהטיסה נוחתת?",
      )["lodging"]["details"]["level"] == "בינוני")
check("regression: a bare numeric budget is never subject to this guard "
      "at all",
      chat._validate_lodging_level_against_message(
          {"lodging": {"details": {"budget": 150}}}, MADRID_STATE, "מלון חמוד",
      )["lodging"]["details"]["budget"] == 150)
check("defensive: non-dict trip_update/state never crash",
      chat._validate_lodging_level_against_message(None, None, "x") == {})


# =====================================================================
# Bug (c) - Lisbon: baggage_detail reinterpreted with nothing new said.
# =====================================================================
LISBON_PRIOR = {"flight": {"baggage": ["carry_on_only", "checked_bag"],
                            "baggage_detail": {"checked_bag": {"unit": "total", "count": 1}}}}

check("Lisbon repro: baggage_detail silently reinterpreted "
      "(unit total->per_person) on a turn that never mentions baggage at "
      "all is reverted to what was already settled",
      chat._validate_baggage_detail_against_message(
          {"flight": {"baggage": ["carry_on_only", "checked_bag"],
                      "baggage_detail": {"checked_bag": {"unit": "per_person", "count": 1}}}},
          LISBON_PRIOR, "מתי אנחנו נוחתים בליסבון?",
      )["flight"]["baggage_detail"] == {"checked_bag": {"unit": "total", "count": 1}})
check("regression: a genuine new baggage statement this turn is still "
      "accepted when the extractor supplies real evidence for it",
      chat._validate_baggage_detail_against_message(
          {"flight": {"baggage": ["carry_on_only", "checked_bag"],
                      "baggage_detail": {"checked_bag": {"unit": "per_person", "count": 1}},
                      "baggage_detail_evidence": "כל אחד עם מזוודה משלו"}},
          LISBON_PRIOR, "בעצם כל אחד עם מזוודה משלו",
      )["flight"]["baggage_detail"] == {"checked_bag": {"unit": "per_person", "count": 1}})
check("regression: an unchanged baggage_detail (identical to what's "
      "already persisted) is never touched regardless of the message",
      chat._validate_baggage_detail_against_message(
          dict(LISBON_PRIOR), LISBON_PRIOR, "לא קשור בכלל",
      )["flight"]["baggage_detail"] == LISBON_PRIOR["flight"]["baggage_detail"])
check("defensive: no baggage_detail in the new state at all -> untouched, "
      "never crashes",
      chat._validate_baggage_detail_against_message({"flight": {"baggage": ["carry_on_only"]}}, LISBON_PRIOR, "x")
      == {"flight": {"baggage": ["carry_on_only"]}})

# --- duplicate-in-answered fix: reproduced via the real guided dispatcher,
#     a stale current_question already independently marked answered by
#     the pre-satisfied scan must not be appended to `answered` a second
#     time once its own "status=answered" handling runs. ---
os.environ["GUIDED_EXTRACTION_STEPS"] = "dates,travelers,baggage,lodging"
STALE_BAGGAGE_STATE = {
    "requested_services": ["flights", "lodging"],
    "flight": {"baggage": ["carry_on_only", "checked_bag"],
               "baggage_detail": {"checked_bag": {"unit": "total", "count": 1}}},
    "dates": {"departure": "2026-11-10", "return": "2026-11-15"},
    "travelers": {"adults": 4},
    "guided": {"current_question": "baggage", "attempts": 0,
               "answered": ["dates", "travelers", "baggage"]},
}


def _fake_guided_extract(key, model, field, message, history, state):
    return {"status": "answered", "confidence": "high",
            "items": [{"type": "carry_on_only"}, {"type": "checked_bag"}], "also_mentioned": None}


with patch.object(chat, "_guided_extract_answer", side_effect=_fake_guided_extract):
    result = chat._handle_guided_extraction_turn(
        "key", "model", "משהו לא קשור לכבודה בכלל", [], dict(STALE_BAGGAGE_STATE),
        dict(STALE_BAGGAGE_STATE), {"dates", "travelers", "baggage", "lodging"},
    )
answered_list = (result["trip_update"].get("guided") or {}).get("answered") or []
check("duplicate-in-answered repro: 'baggage' never appears twice in "
      "guided.answered even when current_question was stale at an "
      "already-known field",
      answered_list.count("baggage") == 1)
check("duplicate-in-answered repro: baggage_detail itself survives the "
      "same turn untouched (confirms (c)'s fix and this fix don't conflict)",
      result["trip_update"]["flight"]["baggage_detail"] == {"checked_bag": {"unit": "total", "count": 1}})
os.environ.pop("GUIDED_EXTRACTION_STEPS", None)


# =====================================================================
# Bug (d) - Berlin: style as a raw English list, now translated + joined,
# already at parse time.
# =====================================================================
check("_to_hebrew_display translates a list item-by-item and joins it "
      "(general - not scoped to any one field)",
      chat._to_hebrew_display(["history", "museums", "nightlife"]) == "היסטוריה, מוזיאונים, חיי לילה")
check("_to_hebrew_display leaves an already-Hebrew list value untouched",
      chat._to_hebrew_display(["תרבות", "אוכל"]) == "תרבות, אוכל")
check("_to_hebrew_display passes through an unrecognized LATIN token in a "
      "list unchanged, never guesses, never drops it - per the business "
      "owner's 18.10.2026 directive, only place names/airport codes may "
      "stay in English, and this function has no way to tell those apart "
      "from a genuine untranslated interest by letters alone; the real "
      "fix is EXTRACTOR_SYSTEM translating style values to Hebrew at "
      "extraction time (see the style rule added there), not filtering "
      "here",
      chat._to_hebrew_display(["history", "something_unknown"]) == "היסטוריה, something_unknown")
check("_to_hebrew_display passes through an unrecognized HEBREW token in "
      "a list unchanged too (never guesses)",
      chat._to_hebrew_display(["history", "קיאקים"]) == "היסטוריה, קיאקים")
check("regression: a legitimate English place name inside a style/"
      "interest list (e.g. a neighborhood the customer asked about) is "
      "never dropped - exactly what the old Latin-letter filter would "
      "have wrongly deleted",
      chat._to_hebrew_display(["history", "Barceloneta"]) == "היסטוריה, Barceloneta")
check("EXTRACTOR_SYSTEM instructs the model to translate the customer's "
      "own free-text style/interest wording into Hebrew, never leave it "
      "in English (place names/airport codes explicitly excepted)",
      "אמנות רחוב" in chat.EXTRACTOR_SYSTEM and "destination.places" in chat.EXTRACTOR_SYSTEM)

berlin_raw = json.dumps({"trip_update": {"trip_planning": {
    "details": {"style": ["history", "museums", "nightlife"], "pace": "relaxed"},
}}})
berlin_parsed = chat._parse_trip_update(berlin_raw)
check("Berlin repro: _parse_trip_update normalizes trip_planning.details."
      "style from a raw English list to a translated, joined Hebrew "
      "string already at parse time - never a raw list merged into state",
      berlin_parsed["trip_planning"]["details"]["style"] == "היסטוריה, מוזיאונים, חיי לילה")
check("Berlin repro: pace (a plain string, not a list) is left completely "
      "untouched by this normalization - it is _route_summary_line's own "
      "job to translate it at display time",
      berlin_parsed["trip_planning"]["details"]["pace"] == "relaxed")

no_style_raw = json.dumps({"trip_update": {"trip_planning": {"details": {"pace": "active"}}}})
check("regression: a turn with no style list at all is untouched by the "
      "normalization, no crash",
      chat._parse_trip_update(no_style_raw)["trip_planning"]["details"]["pace"] == "active")

already_string_raw = json.dumps({"trip_update": {"trip_planning": {
    "details": {"style": "טיולים בטבע ואוכל מקומי"},
}}})
check("regression: style already a plain Hebrew string (the normal case) "
      "passes through completely unchanged",
      chat._parse_trip_update(already_string_raw)["trip_planning"]["details"]["style"] == "טיולים בטבע ואוכל מקומי")

check("end-to-end: the route summary line (via _final_summary_fallback_text's "
      "own _route_summary_line) never leaks the raw list or English tokens, "
      "once trip_planning.details.style has already been normalized at parse time",
      "history" not in str(chat._route_summary_line({
          "trip_planning": {"approved_text": "x",
                             "details": {"style": "היסטוריה, מוזיאונים, חיי לילה", "pace": "relaxed"}},
      }) or "")
      and "היסטוריה" in str(chat._route_summary_line({
          "trip_planning": {"approved_text": "x",
                             "details": {"style": "היסטוריה, מוזיאונים, חיי לילה", "pace": "relaxed"}},
      }) or ""))

# =====================================================================
# Folded into (d) per Shlomo's own follow-up message (after rebasing onto
# #82): the Berlin lodging summary line was also missing the lodging type
# entirely - "הוסטל" (hostel, what the customer actually booked) was never
# one of the 5 original canonical lodging.details.type values at all, so
# it could never be saved, and the summary line's own "type" slot stayed
# empty forever. "אכסניה" (the formal Hebrew word for the same thing,
# already used elsewhere in this file's own general lodging-topic
# detection) is accepted as a synonym for the same canonical value.
# =====================================================================
check("'הוסטל' is now a recognized canonical lodging type via the direct-"
      "answer guided path",
      chat._guided_field_update_and_confirm("lodging_type", {"value": "הוסטל"})
      == ({"lodging": {"details": {"type": "הוסטל"}}}, "סוג לינה - הוסטל"))
check("'אכסניה' (the formal synonym) is accepted and canonicalized to "
      "'הוסטל', exactly like 'אפרטמנט' already canonicalizes to 'דירה'",
      chat._guided_field_update_and_confirm("lodging_type", {"value": "אכסניה"})
      == ({"lodging": {"details": {"type": "הוסטל"}}}, "סוג לינה - הוסטל"))
check("regression: the existing canonical types (e.g. 'מלון') still work "
      "exactly as before",
      chat._guided_field_update_and_confirm("lodging_type", {"value": "מלון"})
      == ({"lodging": {"details": {"type": "מלון"}}}, "סוג לינה - מלון"))
check("per the business owner's later 18.10 directive (tools/qa_canonical_"
      "value_keeps_customer_wording.py), an unrecognized value is now KEPT "
      "in the customer's own wording, never rejected/guessed",
      chat._guided_field_update_and_confirm("lodging_type", {"value": "משהו אחר"})
      == ({"lodging": {"details": {"type": "משהו אחר"}}}, "סוג לינה - משהו אחר"))
check("the deterministic regex fallback also recognizes 'הוסטל' when the "
      "prior assistant turn genuinely asked about lodging type",
      chat._deterministic_lodging_facts(
          "רוצים הוסטל", [{"role": "assistant", "content": "מה סוג הלינה שתרצו?"}],
      ).get("lodging", {}).get("details", {}).get("type") == "הוסטל")
check("the deterministic regex fallback also recognizes 'אכסניה' the same "
      "way, canonicalized to 'הוסטל'",
      chat._deterministic_lodging_facts(
          "רוצים אכסניה", [{"role": "assistant", "content": "מה סוג הלינה שתרצו?"}],
      ).get("lodging", {}).get("details", {}).get("type") == "הוסטל")
check("Berlin repro end-to-end: once type=הוסטל is known, the lodging "
      "summary line names it instead of staying empty",
      "הוסטל" in str(chat._lodging_summary_line(
          {"lodging": {"details": {"type": "הוסטל", "locations": "מיטה, ברלין"}}},
      ) or ""))

# =====================================================================
# Shaked's 2026-10-18 daily QA report: two _deterministic_baggage_facts
# fail-safe regex gaps found via real-scan transcripts (Milano, Lisbon).
# =====================================================================
check("Milano repro: a bare 'מזוודה לכל אחד' (no גדולה/בבטן/משותפת "
      "qualifier at all) is no longer dropped entirely",
      chat._deterministic_baggage_facts("מזוודה לכל אחד", 5)
      == {"flight": {"baggage": ["checked_bag"],
                      "baggage_detail": {"checked_bag": {"unit": "per_person"}}}})
check("Lisbon repro: 'כל אחד טרולי, ומזוודה אחת משותפת' (traveler-noun "
      "BEFORE טרולי) keeps the carry-on half too, not just the checked bag "
      "- count=1 recovered for the suitcase. Per Shaked's PR #91 review "
      "(20.10, confirmed by the business owner): once a second baggage "
      "kind is also mentioned, no unit is guessed for either kind at all "
      "(an attempt at picking the 'nearest' unit phrase by character "
      "distance was tried and reverted - it still attributed unit words "
      "wrong in other real messages); the guided model path is the real "
      "mechanism for this detail",
      chat._deterministic_baggage_facts("כל אחד טרולי, ומזוודה אחת משותפת", 4)
      == {"flight": {"baggage": ["carry_on_only", "checked_bag"],
                      "baggage_detail": {"checked_bag": {"count": 1}}}})
check("'מזוודה אחת לכולנו וטרולי לכל מבוגר' ('מבוגר', a traveler noun the "
      "old carry-on pattern didn't list) also keeps both halves - count=1 "
      "recovered, no unit guessed for either kind (same 20.10 fix as above)",
      chat._deterministic_baggage_facts("מזוודה אחת לכולנו וטרולי לכל מבוגר", 4)
      == {"flight": {"baggage": ["carry_on_only", "checked_bag"],
                      "baggage_detail": {"checked_bag": {"count": 1}}}})
check("regression: a genuine negated bare mention ('אין לי מזוודה') still "
      "returns {} rather than being wrongly treated as an affirmative "
      "checked-bag statement",
      chat._deterministic_baggage_facts("אין לי מזוודה") == {})
check("regression: the existing specific phrasings (e.g. 'בלי מזוודה רק "
      "טרולי', 'מזוודה גדולה לכל אחד מאיתנו') are unaffected - only ONE "
      "baggage kind is mentioned in each, so the unit is still correctly "
      "recovered",
      chat._deterministic_baggage_facts("בלי מזוודה רק טרולי")
      == {"flight": {"baggage": ["carry_on_only"]}}
      and chat._deterministic_baggage_facts("מזוודה גדולה לכל אחד מאיתנו", 4)
      == {"flight": {"baggage": ["checked_bag"],
                      "baggage_detail": {"checked_bag": {"unit": "per_person"}}}})

# =====================================================================
# Shaked's PR #83 REVIEW, SUPERSEDED the same day by the business owner's
# directive: the original gate matched only the exact spellings "כבודה"/
# "טרולי"/"מזוודה", so "מזוודות" (plural) and "כבודת יד" (which diverge
# from those exact words only at the final letter) were wrongly rejected.
# Shaked's own suggested fix - matching the shared STEM via regex - closed
# that specific gap, but the business owner then ruled out stem/word-list
# matching entirely for this function (and _level_stated_in_message):
# "only the model decides what the customer said". Both the exact-word gate
# AND the stem-regex gate are gone now, replaced by _value_has_verbatim_
# evidence against flight.baggage_detail_evidence - a quote the model
# itself must supply (EXTRACTOR_SYSTEM now requires it). These checks
# confirm the CURRENT mechanism: a real quote from the message is accepted
# regardless of its grammatical form (plural, "כבודת יד", anything) since
# nothing here inspects the quote's wording at all - only that it's really
# there; no quote is rejected, even for the exact same plural/כבודת-יד
# phrasing that used to need special-casing.
# =====================================================================
check("Rome repro, evidence mechanism: a first-turn plural 'שתי מזוודות "
      "לכולנו' is accepted when the extractor supplies it as evidence - "
      "no stem/word list involved, any real quote works",
      chat._validate_baggage_detail_against_message(
          {"flight": {"baggage_detail": {"checked_bag": {"unit": "total", "count": 2}},
                      "baggage_detail_evidence": "שתי מזוודות לכולנו"}},
          {}, "זוג לרומא 10-14 בנובמבר, שתי מזוודות לכולנו",
      )["flight"]["baggage_detail"] == {"checked_bag": {"unit": "total", "count": 2}})
check("the same plural message with NO evidence supplied is rejected - "
      "confirms the mechanism is now evidence-only, not a revived stem "
      "match on the message text itself",
      chat._validate_baggage_detail_against_message(
          {"flight": {"baggage_detail": {"checked_bag": {"unit": "total", "count": 2}}}},
          {}, "זוג לרומא 10-14 בנובמבר, שתי מזוודות לכולנו",
      ) == {"flight": {"baggage_detail": {}}})
check("'כבודת יד' (hand luggage) is accepted the same way, via evidence - "
      "its grammatical form is irrelevant to the check",
      chat._validate_baggage_detail_against_message(
          {"flight": {"baggage_detail": {"checked_bag": {"unit": "total", "count": 1}},
                      "baggage_detail_evidence": "רק כבודת יד"}},
          {"flight": {}}, "רק כבודת יד",
      )["flight"]["baggage_detail"] == {"checked_bag": {"unit": "total", "count": 1}})
check("evidence that does not actually appear in the message (the model "
      "fabricated a quote) is rejected just like no evidence at all",
      chat._validate_baggage_detail_against_message(
          {"flight": {"baggage_detail": {"checked_bag": {"unit": "total", "count": 1}},
                      "baggage_detail_evidence": "רק כבודת יד"}},
          {"flight": {}}, "משהו אחר לגמרי",
      )["flight"]["baggage_detail"] == {})
check("regression: a genuinely unrelated message (no evidence at all) "
      "still reverts to the prior settled detail",
      chat._validate_baggage_detail_against_message(
          {"flight": {"baggage_detail": {"checked_bag": {"unit": "per_person"}}}},
          {"flight": {"baggage_detail": {"checked_bag": {"unit": "total", "count": 1}}}},
          "תקציב 1500 שקל לאדם",
      ) == {"flight": {"baggage_detail": {"checked_bag": {"unit": "total", "count": 1}}}})

# =====================================================================
# SUPERSEDED the same day by the business owner's directive: Shlomo's
# follow-up (relaying Shaked's PR #83 review, item 2) asked for a leftover
# Latin-lettered style token to be dropped so it never leaks in English.
# That was shipped, then the business owner ruled it out entirely: "only
# place names or airport codes may appear in English" - dropping ANY
# Latin text is wrong in both directions (it would also delete a
# legitimate English place name this same list can carry). Reverted;
# see the _to_hebrew_display passthrough checks above and the
# EXTRACTOR_SYSTEM style-translation rule, which is the real fix now.
# =====================================================================
check("regression: 'street art' (no entry in the translation table) "
      "passes through unchanged now - dropping it was the wrong fix; "
      "EXTRACTOR_SYSTEM translating it to Hebrew at extraction time is "
      "the real one",
      chat._to_hebrew_display(["history", "street art", "nightlife"])
      == "היסטוריה, street art, חיי לילה")

if FAILED:
    print(f"\nFAILED ({len(FAILED)}): {FAILED}")
    sys.exit(1)
print("\nALL STAGE-3 RUN-3 ROOT-CAUSE TESTS PASSED")
