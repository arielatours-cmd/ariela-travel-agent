"""QA for a subset of Shaked's stage-3 run-3 root-cause findings (18.10.2026,
main 4db4653, qa/reports/2026-10-18-stage3-run3.md, branch shaked @80d27f8),
assigned by Shlomo as task 2 (after the urgent loop guard, PR #82). Covers
items (b), (c) and (d) of his 5-item list; items (a) (current_question must
drive what's actually asked) and (e) (lodging budget currency - a known,
larger schema gap, deferred from #77's review) are NOT in this PR - see the
PR description for why.

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
      "invented via the main extractor's own JSON is dropped",
      chat._validate_lodging_level_against_message(
          {"lodging": {"details": {"type": "מלון", "level": "בינוני"}}},
          MADRID_STATE, "מלון חמוד ושקט",
      ) == {"lodging": {"details": {"type": "מלון"}}})
check("regression: a genuinely stated level via the same write path still "
      "survives (e.g. 'מלון יוקרתי')",
      chat._validate_lodging_level_against_message(
          {"lodging": {"details": {"type": "מלון", "level": "יוקרתי"}}},
          MADRID_STATE, "רוצים מלון יוקרתי",
      )["lodging"]["details"]["level"] == "יוקרתי")
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
      "accepted (the message itself mentions baggage)",
      chat._validate_baggage_detail_against_message(
          {"flight": {"baggage": ["carry_on_only", "checked_bag"],
                      "baggage_detail": {"checked_bag": {"unit": "per_person", "count": 1}}}},
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
check("_to_hebrew_display passes through an unrecognized token in a list "
      "unchanged (never guesses)",
      chat._to_hebrew_display(["history", "something_unknown"]) == "היסטוריה, something_unknown")

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
check("regression: an unrecognized value is still rejected, never guessed",
      chat._guided_field_update_and_confirm("lodging_type", {"value": "משהו אחר"})
      == ({}, None))
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
      "BEFORE טרולי) keeps the carry-on half too, not just the checked bag",
      chat._deterministic_baggage_facts("כל אחד טרולי, ומזוודה אחת משותפת", 4)
      == {"flight": {"baggage": ["carry_on_only", "checked_bag"],
                      "baggage_detail": {"checked_bag": {"unit": "total", "count": 1}}}})
check("'מזוודה אחת לכולנו וטרולי לכל מבוגר' ('מבוגר', a traveler noun the "
      "old carry-on pattern didn't list) also keeps both halves",
      chat._deterministic_baggage_facts("מזוודה אחת לכולנו וטרולי לכל מבוגר", 4)
      == {"flight": {"baggage": ["carry_on_only", "checked_bag"],
                      "baggage_detail": {"checked_bag": {"unit": "total", "count": 1}}}})
check("regression: a genuine negated bare mention ('אין לי מזוודה') still "
      "returns {} rather than being wrongly treated as an affirmative "
      "checked-bag statement",
      chat._deterministic_baggage_facts("אין לי מזוודה") == {})
check("regression: the existing specific phrasings (e.g. 'בלי מזוודה רק "
      "טרולי', 'מזוודה גדולה לכל אחד מאיתנו') are unaffected",
      chat._deterministic_baggage_facts("בלי מזוודה רק טרולי")
      == {"flight": {"baggage": ["carry_on_only"]}}
      and chat._deterministic_baggage_facts("מזוודה גדולה לכל אחד מאיתנו", 4)
      == {"flight": {"baggage": ["checked_bag"],
                      "baggage_detail": {"checked_bag": {"unit": "per_person"}}}})

if FAILED:
    print(f"\nFAILED ({len(FAILED)}): {FAILED}")
    sys.exit(1)
print("\nALL STAGE-3 RUN-3 ROOT-CAUSE TESTS PASSED")
