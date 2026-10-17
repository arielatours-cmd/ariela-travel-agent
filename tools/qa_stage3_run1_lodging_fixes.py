"""QA for Shaked's stage-3 run-1 findings (ad2f793, 1/5 - London passed), relayed
17.10.2026, plus the business owner's two rounds of follow-up on this same PR
(#73) - all fixed together in ariella_chat_clean.py:

1. Paris (worst - 13x loop, never reached a summary): "אין הגבלה" answering
   the lodging per-night budget question ("מה התקציב שלכם ללילה?") set
   neither lodging.details.budget nor .level, so budget_or_level could never
   close.

2. Paris/Athens: apartment bathrooms - "שני חדרי רחצה" (spelled-out "two")
   wasn't parsed, and in Athens the question was never asked at all (purely
   prompt-driven, no real gap enforcing it).

3. Rome: the approved route's own text ("לינה באזור הר הפלטינו" - a
   landmark mentioned in the day's narrative, never a customer choice) got
   auto-promoted into lodging.details.locations by
   _resolve_lodging_locations_from_route, skipping the real question
   entirely. Fixed: that auto-fill only ever fires with at least 2 distinct
   route bases (the genuinely multi-stop case it was built for, 2026-10-14) -
   a single base is far more likely a stray mention than a real per-stop
   necessity, so a single-destination trip now always asks.

4. Budapest: "חדר משפחתי אחד עם עריסה" (one family room, descriptive word
   between "חדר" and the spelled-out "אחד") never matched the exact-phrase
   rooms check, so "כמה חדרים תרצו?" was asked 4 times.

5. Rome + Budapest: a bundled two-topic question evaded
   _enforce_one_option_question in two different ways neither existing
   check caught:
   (a) Rome - "לגבי מספר החדרים והתקציב ללילה, מה יתאים לכם?" is ONE
       question sentence whose own lead-in already names two different
       still-open lodging topics (rooms AND budget). Fixed: a state-gap-
       driven topic-keyword check for the lodging domain specifically
       (mutually exclusive - bathrooms checked before the bare "חדר" rooms
       check).
   (b) Budapest - "ספרו לי... מה אתם אוהבים לעשות בחופשה, וגם האם חשוב לכם
       קצב רגוע..." has NO "?" anywhere at all, so the function's very first
       line ("if '?' not in text: return reply") let it straight through.
       Fixed: a narrower bundling regex (_BUNDLED_NO_QMARK_RE) plus a check
       that the text before it already reads as an open question - when
       both hold, the smuggled clause is truncated and the remaining single
       question goes through the exact same resolution path as every other
       case in this function.

6. Shlomo's follow-up: regardless of why any one parser missed a specific
   phrasing, no lodging field should ever be asked more than twice in a row.

ARCHITECTURAL CORRECTION, ROUND 1 (business owner, 17.10.2026, relayed by
Shlomo, after reviewing the first version of #1/#2/#4/#6): "כלל גורף, לא
אפשרויות ביטויים" - stop fixing individual cases with growing phrase/word
lists; use general state-driven rules instead. #6's ask-limit counter
(originally scanning assistant message text for topic words) became PURELY
state-driven (_apply_lodging_ask_limit_fallback): it compares
_session_gaps(trip_state, "lodging")'s first entry (the one gap Ariella's
own question-selection pipeline would ask about this turn) against
_session_gaps(trip_update, "lodging") after the message was processed - no
message text is ever inspected for keywords.

ARCHITECTURAL CORRECTION, ROUND 2 (Shaked's follow-up review, same day): a
round-1 attempt to fix #1/#2/#4 with model-based (LLM classifier) calls per
field was ALSO rejected - Shaked tested further phrasings ("שתי מקלחות",
"שלושה", "לפחות שניים" for bathrooms; "שני חדרים", "2", "שלושה חדרי שינה",
"סוויטה אחת", "חדר לנו וחדר לילדים" for rooms; "עד 300 יורו", "בלי מגבלה",
"גמיש", "מה שצריך" for budget; "במרכז העיר", "לא משנה" for locations) and
proposed ONE fully general, deterministic rule instead, which Shlomo
confirmed matches the business owner's decision exactly: identify the ONE
lodging gap _session_gaps names first (the gap Ariella's pipeline would
have asked about last turn); if the reply isn't itself a question, save a
value for that exact gap ALREADY ON THE FIRST REPLY - a number if the reply
names one (via ONE shared number reader, _first_number_in_text, covering
digits and Hebrew number words in both genders - not a list per field),
otherwise the raw reply text. No per-field phrase list anywhere, and no
model call needed for this. Implemented as _capture_lodging_gap_answer,
with _apply_lodging_ask_limit_fallback kept as a backup safety net for
whatever it still doesn't resolve (e.g. a reply that looks like a question).

Run: python3 tools/qa_stage3_run1_lodging_fixes.py
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


def gaps_for(services, lodging_details, extra=None):
    st = {"requested_services": services, "session_status": {}, "lodging": {"details": lodging_details}}
    if extra:
        st.update(extra)
    return chat._required_state_gaps(st)


LODGING_SVC = {
    "requested_services": ["lodging"], "session_status": {},
    "destination": {"places": ["רומא"]},
    "dates": {"departure": "2027-06-01", "return": "2027-06-10", "needs_confirmation": False},
    "travelers": {"adults": 2},
}


def _state(details, ask_counts=None):
    lodging = {"details": dict(details)}
    if ask_counts:
        lodging["ask_counts"] = dict(ask_counts)
    return dict(LODGING_SVC, lodging=lodging)


# === #1/#2/#4, round-2 correction: ONE fully general rule
#     (_capture_lodging_gap_answer), no per-field phrase list, no model
#     call. Covers Shaked's exact second-round test phrasings. ===

# Bathrooms: the one open gap once type/rooms/locations are known.
bath_state = _state({"type": "דירה", "rooms": 2, "locations": "מרכז"})
for phrase, expected in [("שתי מקלחות", 2), ("שלושה", 3), ("לפחות שניים", 2), ("2 מקלחות", 2)]:
    out = chat._capture_lodging_gap_answer(bath_state, bath_state, phrase)
    check(f"Shaked's round-2 bathrooms phrasing '{phrase}' -> bathrooms={expected}, "
          "via the one shared number reader - no phrase list",
          out["lodging"]["details"].get("bathrooms") == expected)

# Rooms: the one open gap once type/bathrooms/locations are known.
rooms_state = _state({"type": "דירה", "bathrooms": 1, "locations": "מרכז"})
for phrase, expected in [("שני חדרים", 2), ("2", 2), ("שלושה חדרי שינה", 3), ("סוויטה אחת", 1)]:
    out = chat._capture_lodging_gap_answer(rooms_state, rooms_state, phrase)
    check(f"Shaked's round-2 rooms phrasing '{phrase}' -> rooms={expected}, "
          "via the one shared number reader - no phrase list",
          out["lodging"]["details"].get("rooms") == expected)
check("Shaked's round-2 rooms phrasing 'חדר לנו וחדר לילדים' (no number at "
      "all) -> the raw reply text is saved rather than dropped - a genuinely "
      "unparseable answer must never silently vanish",
      chat._capture_lodging_gap_answer(rooms_state, rooms_state, "חדר לנו וחדר לילדים")
      ["lodging"]["details"].get("rooms") == "חדר לנו וחדר לילדים")

# Budget: the one open gap once type/rooms/bathrooms/locations are known.
budget_state = _state({"type": "דירה", "rooms": 2, "bathrooms": 1, "locations": "מרכז"})
out_budget_numeric = chat._capture_lodging_gap_answer(budget_state, budget_state, "עד 300 יורו")
check("Shaked's round-2 budget phrasing 'עד 300 יורו' -> budget=300",
      out_budget_numeric["lodging"]["details"].get("budget") == 300)
for phrase in ("בלי מגבלה", "גמיש", "מה שצריך"):
    out = chat._capture_lodging_gap_answer(budget_state, budget_state, phrase)
    check(f"Shaked's round-2 budget phrasing '{phrase}' (no number) -> the "
          "raw text is saved as level (a free-text field) - budget itself "
          "stays null, which is the correct no-price-cap search behavior "
          "regardless of the exact wording",
          out["lodging"]["details"].get("budget") is None
          and out["lodging"]["details"].get("level") == phrase)

# Locations: the one open gap once type/rooms/bathrooms are known.
loc_state = _state({"type": "דירה", "rooms": 2, "bathrooms": 1})
for phrase in ("במרכז העיר", "לא משנה"):
    out = chat._capture_lodging_gap_answer(loc_state, loc_state, phrase)
    check(f"Shaked's round-2 locations phrasing '{phrase}' -> saved as the "
          "raw reply text (locations has always been free text)",
          out["lodging"]["details"].get("locations") == phrase)

# Regressions: the mechanism must never fire when it shouldn't.
check("regression: a reply that looks like a question is never captured as "
      "an answer (e.g. the customer asking something back instead)",
      "bathrooms" not in chat._capture_lodging_gap_answer(
          bath_state, bath_state, "כמה בדרך כלל אנשים לוקחים?")["lodging"]["details"])
check("regression: nothing happens once the gap is already resolved (e.g. "
      "an earlier deterministic parser or the real extractor already set "
      "it this very turn) - the generic rule never overwrites a real value",
      chat._capture_lodging_gap_answer(
          bath_state, _state({"type": "דירה", "rooms": 2, "locations": "מרכז", "bathrooms": 2}), "שתי מקלחות"
      )["lodging"]["details"].get("bathrooms") == 2)
check("regression: with no open lodging gap at all, the state passes "
      "through completely untouched",
      chat._capture_lodging_gap_answer(
          _state({"type": "דירה", "rooms": 2, "bathrooms": 1, "locations": "מרכז", "budget": 300}),
          _state({"type": "דירה", "rooms": 2, "bathrooms": 1, "locations": "מרכז", "budget": 300}),
          "משהו",
      )["lodging"]["details"].get("budget") == 300)

check("Shaked's Athens finding: an apartment (type='דירה') with no bathrooms "
      "set is a real missing_required gap, not left to the model's memory",
      "lodging.details.bathrooms" in gaps_for(
          ["lodging"], {"type": "דירה", "rooms": 3, "locations": "מרכז", "budget": 500}))
check("a hotel/villa never requires the bathrooms gap at all",
      "lodging.details.bathrooms" not in gaps_for(
          ["lodging"], {"type": "מלון", "rooms": 2, "locations": "מרכז", "budget": 500})
      and "lodging.details.bathrooms" not in gaps_for(
          ["lodging"], {"type": "וילה", "rooms": 2, "locations": "מרכז", "budget": 500}))
check("once bathrooms is set, the apartment gap closes",
      "lodging.details.bathrooms" not in gaps_for(
          ["lodging"], {"type": "דירה", "rooms": 3, "locations": "מרכז", "budget": 500, "bathrooms": 2}))

# The pre-existing, specific deterministic parsers (unrelated to this PR's
# correction - they predate it) still work exactly as before.
history_rooms = [{"role": "assistant", "content": "כמה חדרים תרצו?"}]
history_bath = [{"role": "assistant", "content": "כמה חדרי רחצה תרצו בדירה?"}]
check("regression: a plain digit answer ('3 חדרים') still works deterministically",
      chat._deterministic_lodging_facts("3 חדרים", history_rooms)
      .get("lodging", {}).get("details", {}).get("rooms") == 3)
check("regression: the exact bare 'חדר אחד' phrase still works deterministically",
      chat._deterministic_lodging_facts("חדר אחד", history_rooms)
      .get("lodging", {}).get("details", {}).get("rooms") == 1)
check("regression: 'חדר זוגי' (double room, singular) still infers rooms=1 "
      "deterministically even when volunteered outside the rooms question",
      chat._deterministic_lodging_facts("עד 600 שקל ללילה לחדר זוגי", [])
      .get("lodging", {}).get("details", {}).get("rooms") == 1)
check("regression: a bare digit bathrooms answer ('2 חדרי רחצה') still "
      "works deterministically",
      chat._deterministic_lodging_facts("2 חדרי רחצה", history_bath)
      .get("lodging", {}).get("details", {}).get("bathrooms") == 2)


# === #3: Rome - invented lodging region from route ===

state_single = {
    "lodging": {"details": {}},
    "trip_planning": {"details": {"route": [{"base": "הר הפלטינו"}]}},
}
resolved_single = chat._resolve_lodging_locations_from_route(state_single)
check("Shaked's Rome finding: a single-base route (one landmark mention, "
      "not a genuine multi-stop necessity) never auto-fills "
      "lodging.details.locations - the customer is still asked",
      not resolved_single.get("lodging", {}).get("details", {}).get("locations"))

state_multi = {
    "lodging": {"details": {}},
    "trip_planning": {"details": {"route": [{"base": "רומא"}, {"base": "פירנצה"}]}},
}
resolved_multi = chat._resolve_lodging_locations_from_route(state_multi)
check("regression: a genuine multi-stop route (2+ distinct bases - the "
      "feature's actual 2026-10-14 use case) still auto-fills, unchanged",
      resolved_multi.get("lodging", {}).get("details", {}).get("locations") == "רומא, פירנצה")

state_already_set = {
    "lodging": {"details": {"locations": "קרוב למרכז"}},
    "trip_planning": {"details": {"route": [{"base": "רומא"}, {"base": "פירנצה"}]}},
}
check("regression: an already-known lodging.details.locations is never "
      "overwritten by the route, single or multi-base alike",
      chat._resolve_lodging_locations_from_route(state_already_set)
      .get("lodging", {}).get("details", {}).get("locations") == "קרוב למרכז")


# === #5a: Rome - single question sentence bundling two lodging topics ===

state_rome = {
    "active_session": "lodging", "requested_services": ["lodging"], "session_status": {},
    "lodging": {"details": {"type": "דירה"}},
}
out_rome = chat._enforce_one_option_question(
    "לגבי מספר החדרים והתקציב ללילה, מה יתאים לכם?", state_rome)
check("Shaked's Rome finding: a single question whose lead-in names two "
      "different still-open lodging topics (rooms + budget) is rewritten "
      "to the real next single-topic gap question",
      out_rome == "כמה חדרים תרצו?")

state_rome_bath_only = {
    "active_session": "lodging", "requested_services": ["lodging"], "session_status": {},
    "lodging": {"details": {"type": "דירה", "rooms": 2, "locations": "מרכז", "budget": 500}},
}
out_bath_only = chat._enforce_one_option_question("כמה חדרי רחצה תרצו בדירה?", state_rome_bath_only)
check("regression: a genuine single bathrooms-only question is never "
      "mistaken for bundled rooms+bathrooms ('חדרי רחצה' contains 'חדר' as "
      "a substring - must not double-count)",
      out_bath_only == "כמה חדרי רחצה תרצו בדירה?")


# === #5b: Budapest - bundled question with no "?" at all ===

reply_budapest = (
    "ספרו לי מה אתם אוהבים לעשות בחופשה, וגם האם חשוב לכם קצב רגוע או עמוס "
    "יותר - כי יש לכם ילדה קטנה"
)
state_budapest = {"active_session": "trip_planning", "requested_services": ["trip_planning"],
                   "session_status": {}, "trip_planning": {"details": {}}}
out_budapest = chat._enforce_one_option_question(reply_budapest, state_budapest)
check("Shaked's Budapest finding: a bundled two-question message with NO "
      "'?' anywhere is still caught and reduced to a single question",
      out_budapest == "ספרו לי מה אתם אוהבים לעשות בחופשה?")

check("regression: an ordinary statement with ', וגם' and no '?' at all is "
      "never mistaken for a bundled question",
      chat._enforce_one_option_question("אישרתי את הטיסה, וגם את המלון.", {}) ==
      "אישרתי את הטיסה, וגם את המלון.")

check("regression: a plain reply with no '?' and no bundling cue at all "
      "passes through completely untouched",
      chat._enforce_one_option_question("מעולה, פרטי הטיסה נקלטו.", {}) ==
      "מעולה, פרטי הטיסה נקלטו.")

check("regression (PR #72): a parenthetical example-list open question "
      "still survives completely unchanged",
      chat._enforce_one_option_question(
          "מה הסגנון שהכי מדבר אלייך בטיול הזה (תרבות ומוזיאונים, שופינג, "
          "אווירה לוקאלית, אוכל, נוף וטבע וכו׳)?",
          {"active_session": "trip_planning", "requested_services": ["trip_planning"],
           "session_status": {}, "trip_planning": {"details": {}}},
      ) == "מה הסגנון שהכי מדבר אלייך בטיול הזה (תרבות ומוזיאונים, שופינג, "
           "אווירה לוקאלית, אוכל, נוף וטבע וכו׳)?")


# === #6: deterministic "never ask the same field more than twice" backup
#     safety net - PURELY STATE-DRIVEN: no message text is ever inspected
#     for keywords. Only ever needed for whatever _capture_lodging_gap_
#     answer above didn't resolve (e.g. a reply that looked like a
#     question each time). ===

# Turn 1: budget is the one open gap, still open after this message (looked
# like a question, so the general-answer capture above skipped it) -> count 1.
trip_state_1 = _state({"type": "מלון", "rooms": 2, "locations": "מרכז"})
trip_update_1 = _state({"type": "מלון", "rooms": 2, "locations": "מרכז"})
out1 = chat._apply_lodging_ask_limit_fallback(trip_state_1, trip_update_1, "כמה זה בערך?")
check("Shlomo's follow-up, turn 1: the first unanswered ask is just "
      "recorded (count=1) - never force-closed after only one ask",
      out1["lodging"]["details"].get("level") is None
      and out1["lodging"].get("ask_counts", {}).get("lodging.details.budget_or_level") == 1)

# Turn 2: same gap still open, now reaches 2 -> force-closes with the
# customer's own raw reply to THIS turn (never "אין העדפה" when she said
# something real) - this is the true last-resort case: _capture_lodging_
# gap_answer itself would normally already have saved an ordinary reply, so
# this only still fires when every earlier mechanism found nothing usable.
trip_state_2 = out1
trip_update_2 = _state({"type": "מלון", "rooms": 2, "locations": "מרכז"},
                        ask_counts={"lodging.details.budget_or_level": 1})
out2 = chat._apply_lodging_ask_limit_fallback(trip_state_2, trip_update_2, "???")
check("Shlomo's follow-up, turn 2: reaching 2 unanswered asks saves the "
      "customer's own raw reply from THIS turn, not a guessed 'אין העדפה' "
      "(Paris hit 13x before this safety net existed)",
      out2["lodging"]["details"].get("level") == "???")

out2_empty = chat._apply_lodging_ask_limit_fallback(
    trip_state_2,
    _state({"type": "מלון", "rooms": 2, "locations": "מרכז"}, ask_counts={"lodging.details.budget_or_level": 1}),
    "",
)
check("Shlomo's follow-up: 'אין העדפה' is still the fallback when the "
      "customer truly gave no reply at all",
      out2_empty["lodging"]["details"].get("level") == "אין העדפה")

trip_state_resolved = _state({"type": "מלון", "rooms": 2, "locations": "מרכז"})
trip_update_resolved = _state({"type": "מלון", "rooms": 2, "locations": "מרכז", "budget": 400})
out_resolved = chat._apply_lodging_ask_limit_fallback(trip_state_resolved, trip_update_resolved, "400 שקל ללילה")
check("regression: a gap resolved by this very turn's reply is left "
      "completely alone - the real parsers/generic capture get full credit",
      out_resolved["lodging"]["details"].get("budget") == 400
      and "level" not in out_resolved["lodging"]["details"])

trip_state_paris = _state({"type": "דירה", "rooms": 2, "bathrooms": 1, "level": "אין העדפה"})
trip_update_paris = _state({"type": "דירה", "rooms": 2, "bathrooms": 1, "level": "אין העדפה"})
out_paris = chat._apply_lodging_ask_limit_fallback(
    trip_state_paris, trip_update_paris,
    "מעולה. בפריז, עם כל האטרקציות הפזורות במרכז, הכי הגיוני להישאר באזור מרכזי אחד.")
check("Shaked's PR #73 review concern: since locations is still genuinely "
      "open and is the FIRST real gap by state (not asked about in that "
      "message's actual content), it correctly starts tracking it as an "
      "open ask rather than being skipped or wrongly force-closed by text",
      "locations" not in out_paris["lodging"]["details"]
      and out_paris["lodging"].get("ask_counts", {}).get("lodging.details.locations") == 1)

check("regression: lodging untouched when lodging isn't even a requested service",
      chat._apply_lodging_ask_limit_fallback(
          {"requested_services": [], "lodging": {"details": {}}},
          {"requested_services": [], "lodging": {"details": {}}}, "כן",
      ) == {"requested_services": [], "lodging": {"details": {}}})


if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL STAGE-3-RUN-1 LODGING-FIX TESTS PASSED")
