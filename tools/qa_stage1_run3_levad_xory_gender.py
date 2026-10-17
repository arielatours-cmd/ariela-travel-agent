"""QA for Shaked's stage-1, run-3 live findings (17.10.2026, qa/reports/
2026-10-17-stage1-run3.md on the shaked branch, commit e238e2e): 2/5
scenarios passed on main faa4399 (#56+#57+#58).

Bug 1 (V5): _deterministic_traveler_facts's solo-traveler detector matched
the bare word "לבד" anywhere in the message. "נסתדר לבד" (we'll manage on
our own - answering the ROUTE offer, a couple with a daughter), "תבני
לבד" and "אני אסתדר לבד עם זה" (go ahead and build it yourself/I'll
handle it myself) all matched it and silently overwrote travelers.adults
down to 1, even though the real travelers count (a couple, 2 adults) was
already known. Fixed: "לבד" is now only recognized as stating a solo
traveler when it directly follows "אני" or a travel verb ("טס/ה",
"נוסע/ת") - never after an unrelated verb.

Bug 2 (V3, V4): despite TINKERBELL_SYSTEM's existing one-question/never-
"X או Y" instruction (already reinforced once for baggage in PR #58), the
free generation still produced an enumerated/binary question on an
ordinary first ask - the baggage question again ("...רק תיק קטן, או שיש
גם מזוודות?", V4) and, new this round, the trip_planning continuation
offer skipping its plain yes/no entirely in favor of route content ("יש
לך רעיון למסלול..., או שתרצי שאציע?", V3).

This went through three iterations of _enforce_one_option_question,
wired into _call_tinkerbell's own reply pipeline (so every call site
gets it for free):

1. First version scoped the fix to just these two narrow situations
   (baggage + next-domain offer).
2. Per the business owner (relayed by Shlomo, PR #59 review): the rule
   has no baggage-only exception - "מלון, דירה או וילה?" is just as much
   a violation as the baggage one, in every service. Generalized to a
   fixed topic-keyword table.
3. Per Shaked's own review of THAT version: keyword matching is exactly
   as unreliable as free generation, just differently so - a lodging
   question mentioning "רכב"/"חניה" (car parking) or "מזוודות" got
   rewritten into the wrong domain's question entirely, and a car
   pickup-location question got rewritten into "what vehicle type" - a
   question already answered, risking an actual loop. Replaced with the
   state itself: when active_session names a real session, the fixed
   text is whatever _session_gaps(state, active_session) actually still
   needs for THAT session - the exact field the real missing_required
   pipeline would ask about next, never guessed from words that merely
   appear in the model's own (already-wrong) phrasing. flights reuses
   _flight_gap_question's own richer mapping; lodging/car/trip_planning
   use _GAP_QUESTION_TEXT directly. No mapped gap left -> the question is
   dropped (any earlier statement kept), never guessed.

Also fixed in this same round (Shaked's review): _flight_gap_question's
budget_per_person/flight.connection_preference texts were singular
("שלך"/"לך") while every other fixed text in this file is plural
("לכם") - inconsistent, and reads oddly addressed to a couple/family.
Pluralized to match.

Bug 3 (V3): a customer who wrote "אני טס" (clearly male) got addressed in
feminine mid-conversation ("טסה ללונדון לבד... איזו כבודה תצטרכי?") even
though user_gender was correctly set (the final approval line used the
correct "כתוב מאשר") - rule 188 (profile.gender -> לשון זכר/נקבה) is a
free-text instruction pointing at a key buried in the large state JSON
dump, not reliably followed on its own. Fixed by surfacing it as its own
explicit sentence (_gender_hint_text), the same pattern already used for
_direct_route_hint_text/_multi_gateway_hint.

Stage-1 run-4 (Shaked, 17.10.2026, qa/reports/2026-10-17-stage1-run4.md,
commit 4234cb8): 4/5 on main 9f0c7db (before this branch's generalization
reached main). One failure, W2/Paris:

Bug 4a: the live budget question wasn't caught on 9f0c7db - it only had
the first, narrow version of _enforce_one_option_question. Already fixed
here by the state-driven redesign above; confirmed with Shaked's exact
live wording.

Bug 4b: the customer answered "לא משנה לנו" to the direct-flight
question (flight.connection_preference correctly stored as "אין העדפה"),
but the final summary read "טיסה ישירה: בהתאם לזמינות בפועל" - a vague
paraphrase that reads as if a preference for direct still conditionally
applies. Added an explicit required phrasing for both known values to
the summary-structure rule, naming the live failing phrasing as a
forbidden example.

Stage-1 run-5 (Shaked, 17.10.2026, qa/reports/2026-10-17-stage1-run5.md,
commit 06e2253): 4/5 on main 6586a1b. One failure, X2/Paris: right after
the budget question (flights' own last gap) was answered, the reply came
back as a bare "מעולה, פרטי הטיסה סגורים." with no question at all - the
customer had to ask "מה עכשיו?" herself. Root cause: _enforce_one_option_
question's active_session branch, finding no gap left for "flights" (it
had just closed on this very turn), silently dropped the question
instead of falling through to the next-domain offer that the SAME state
snapshot's post_flight_offer/next_session already correctly named
("trip_planning") - Tinkerbell's own reply had almost certainly free-
worded exactly that offer as another "X או Y" violation. Fixed per the
business owner's standing rule (relayed by Shlomo): a turn before the
final summary must never end with no question. The active_session
branch now falls through to the next-domain offer when its own gap list
is empty, and the function's own last resort - when nothing usable is
found anywhere - returns the original reply entirely unchanged (still a
violation, but a real question) rather than ever dropping to a bare
statement.

Stage-1 run-6 (Shaked, 17.10.2026, qa/reports/2026-10-17-stage1-run6.md,
main 595e29b): 4/5. The Paris fix held (no X/Y questions, no question-less
replies). One new failure, Y4/Athens, first message: "חופשה מעולה לאתונה!
רק עוד שני פרטים קטנים לטיסה - איזו כבודה תצטרכו, ויש הגבלת תקציב
לאדם?" - two gap-questions (baggage, budget) bundled into one sentence
joined by "ו" instead of "או", so _enforce_one_option_question's " או "
check never caught it (still exactly one "?").

Shlomo's follow-up (same day, relaying the business owner's correction):
the rule is "one question at a time", not specifically about "או"/"ו" -
two questions written as fully separate sentences, each with its own "?",
is the same violation and was invisible to the OLD version for a deeper
reason than just missing a keyword: that version only ever inspected the
single sentence containing the LAST "?", so an earlier, already complete
question sentence was never even looked at - it sat untouched in what the
function treated as a plain leading "statement". Generalized:
_enforce_one_option_question now classifies every sentence in the reply
as a question (ends in "?") or a statement, and the violation is either
more than one question sentence, or exactly one that is itself bundled
(the "או"/_BUNDLED_AND_QUESTION_RE cases). On a violation, every
statement sentence is kept and EVERY question sentence - not just the
last - is replaced by the one fixed question the existing state-driven
lookup resolves to (the real first gap in the active topic, same
mechanism as before, unchanged). A normal reply with exactly one,
unbundled question - including the final pre-"מאשר/ת" summary's own
single confirmation question - has exactly one question sentence and is
never touched, so the confirmation question is never at risk of being
dropped.

Shaked's review of that SAME generalization (still 17.10.2026, PR #64):
two further live bugs, both from reconstructing the reply out of stripped-
and-rejoined sentence fragments rather than only ever excising the
question spans from the ORIGINAL string. (1) Splitting on a bare "."
treated the periods inside a date like "15.4.2027" as sentence
boundaries, and single-space-joining the stripped fragments mangled it
into "15. 4. 2027" while silently dropping every real newline/blank line
in the reply. Fixed: _split_sentences only counts "." / "!" / "?" as a
boundary when it is NOT directly between two digits and IS followed by
whitespace or end-of-string; kept statement spans are concatenated with
"".join (never " ".join, never .strip()), since each span already carries
its own original surrounding whitespace. (2) A day-by-day itinerary's own
body can legitimately contain a rhetorical "?" ("מה יותר כיף מאוכל טוב?")
that is not a real gap-question - with style/pace already known
(_session_gaps empty), the generic lookup had nothing real to offer and
instead replaced the real confirmation question with a wrong, from-
scratch style question while also destroying real itinerary content
(dates, day lines) caught up in the same rebuild - a genuine loop risk,
per her report. Fixed: when the reply contains a day marker ("יום 1",
"יום 2", ...) and active_session is "trip_planning", the itinerary body -
rhetorical "?" included - is left completely untouched; only the LAST
question sentence is ever a candidate for replacement, and only with the
fixed trip_planning approval confirmation, never a _session_gaps lookup.

Shlomo's further follow-up on that same PR #64 round: when NO state-driven
replacement exists at all (no gap, no offer anywhere in the state) for a
reply bundling multiple fully separate question sentences, returning the
whole reply untouched (the prior behavior) leaves every extra question in
place too. Fixed: in exactly that case, the FIRST question sentence is
kept exactly as written and every question sentence after it is dropped -
not a single other character is touched. A single, possibly-"או"-bundled
question sentence with no fixed replacement is unaffected by this (the
Paris rule still applies: never drop the only question there is). Also
added, per his explicit request: character-identity checks (.startswith,
not just whole-string ==) confirming the kept itinerary/date portion of
the output is an exact byte-for-byte prefix of the original input.

Run: python3 tools/qa_stage1_run3_levad_xory_gender.py
"""
import os
import sys
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


# A realistic, otherwise-complete trip state - every shared fact known, so
# _session_gaps for whichever domain is under test reflects only that
# domain's own remaining fields, exactly like a real mid-conversation turn.
BASE_STATE = {
    "destination": {"places": ["פריז"], "mode": "specific", "status": "known"},
    "destination_airports": ["CDG"],
    "dates": {"departure": "2027-05-01", "return": "2027-05-10"},
    "travelers": {"adults": 2},
    "trip_type": "vacation",
    "departure_airport": "TLV",
}


# === Bug 1: "לבד" solo-traveler false positives ===

check("'נסתדר לבד' (V5 live repro) is NOT read as a solo traveler",
      not chat._deterministic_traveler_facts("נסתדר לבד"))
check("'תבני לבד' is NOT read as a solo traveler",
      not chat._deterministic_traveler_facts("תבני לבד"))
check("'אני אסתדר לבד עם זה' is NOT read as a solo traveler",
      not chat._deterministic_traveler_facts("אני אסתדר לבד עם זה"))
check("'אני לבד' is still correctly read as a solo traveler (guard)",
      chat._deterministic_traveler_facts("אני לבד") == {"travelers": {"adults": 1}})
check("'אני טס לבד' is still correctly read as a solo traveler (guard)",
      chat._deterministic_traveler_facts("אני טס לבד") == {"travelers": {"adults": 1}})
check("'אני נוסעת לבד' is still correctly read as a solo traveler (guard)",
      chat._deterministic_traveler_facts("אני נוסעת לבד") == {"travelers": {"adults": 1}})
check("an existing real count ('זוג' = 2 adults) is never downgraded by a "
      "false 'לבד' match in the same conversation turn",
      chat._deterministic_traveler_facts("זוג, נסתדר לבד עם המסלול") == {"travelers": {"adults": 2}})


# === Bug 2: deterministic one-option-question enforcer (state-driven) ===

# -- the next-domain offer moment (active_session empty) - unchanged --

check("trip_planning X/Y continuation offer gets replaced with the fixed "
      "yes/no, the earlier statement sentence kept as-is",
      chat._enforce_one_option_question(
          "מצוין, הטיסה מוכנה. בואי נדבר על המסלול ביעד - יש לך רעיון למה בא לך "
          "לעשות בלונדון, או שתרצי שאציע לך מסלול מגוון?",
          {"post_flight_offer": ["trip_planning"], "active_session": None},
      ) == "מצוין, הטיסה מוכנה. לתכנן גם מסלול ואטרקציות לחופשה הזו?")
check("the same fix generalizes to a lodging continuation offer",
      chat._enforce_one_option_question(
          "מצוין, המסלול מאושר. רוצים שאני אסדר גם לינה, או שכבר יש לכם משהו?",
          {"post_flight_offer": ["lodging"], "active_session": None},
      ) == "מצוין, המסלול מאושר. לסדר גם לינה לחופשה הזו?")
check("the fixed next-domain offer text is gender-neutral (infinitive verb "
      "form) - never guesses the customer's gender the way bug #3 did",
      not any(w in q for w in ("תרצי", "תרצה") for q in chat._OFFER_DOMAIN_QUESTIONS.values()))
check("per Shaked/Shlomo's follow-up: two domains illegally bundled into "
      "one offer (post_flight_offer should never list more than one - "
      "rule 112) collapses to the first domain in order, rather than "
      "leaving the violation untouched",
      chat._enforce_one_option_question(
          "רוצים לינה או רכב?", {"post_flight_offer": ["lodging", "car"], "active_session": None},
      ) == "לסדר גם לינה לחופשה הזו?")

# -- mid-domain (active_session set): the real next gap for that session,
#    not a keyword guess. Each case below is Shaked's own stage-1 run-3
#    review finding on the previous (keyword-based) version. --

CAR_STATE = dict(BASE_STATE, active_session="car", requested_services=["flights", "car"])
check("Shaked's PR #59 finding: a genuine CAR-domain luggage-capacity "
      "question that mentions 'מזוודות' resolves to the real open car "
      "gap (vehicle_type, still unanswered) - not the baggage question",
      chat._enforce_one_option_question(
          "מעולה. איזה רכב מתאים - כזה שיכיל את כל המזוודות, או משהו קטן?", CAR_STATE,
      ) == "מעולה. איזה סוג/גודל רכב מתאים לכם?")
check("car pickup-location X/Y resolves to the real open gap too, which "
      "while vehicle_type is still unanswered is genuinely vehicle_type - "
      "steering back to the actual next question, not the one Tinkerbell "
      "jumped ahead to",
      chat._enforce_one_option_question(
          "לאסוף את הרכב בשדה התעופה, או במרכז העיר?", CAR_STATE,
      ) == "איזה סוג/גודל רכב מתאים לכם?")
CAR_STATE_VEHICLE_KNOWN = dict(CAR_STATE, car={"details": {"vehicle_type": "משפחתי", "transmission": "אוטומטי"}})
check("Shaked's PR #60 review finding: once vehicle_type is genuinely "
      "already answered, the SAME pickup-location question correctly "
      "resolves to the pickup question - never re-asks vehicle type "
      "(the loop risk she flagged)",
      chat._enforce_one_option_question(
          "לאסוף את הרכב בשדה התעופה, או במרכז העיר?", CAR_STATE_VEHICLE_KNOWN,
      ) == "איפה תרצו לאסוף את הרכב?")

LODGING_STATE = dict(BASE_STATE, active_session="lodging", requested_services=["flights", "lodging"])
check("Shaked's PR #60 review finding: a lodging question mentioning "
      "'חניה לרכב' (car parking) resolves to the real open lodging gap "
      "(type, still unanswered) - not a car-topic question",
      chat._enforce_one_option_question(
          "תרצו דירה עם חניה לרכב, או שלא צריך חניה?", LODGING_STATE,
      ) == "איזה סוג לינה מתאים לכם?")
check("a lodging question mentioning 'מזוודות' (suitcase space) resolves "
      "to the real open lodging gap too - not the baggage question",
      chat._enforce_one_option_question(
          "דירה עם מקום לכל המזוודות, או משהו קטן יותר?", LODGING_STATE,
      ) == "איזה סוג לינה מתאים לכם?")
check("per the business owner's correction: a multi-option lodging-type "
      "question IS a violation too (not an allowed exception) and now "
      "gets the fixed open question",
      chat._enforce_one_option_question(
          "איזה סוג לינה מתאים לכם - מלון, דירה או וילה?", LODGING_STATE,
      ) == "איזה סוג לינה מתאים לכם?")
LODGING_STATE_TYPE_KNOWN = dict(LODGING_STATE, lodging={"details": {"type": "דירה"}})
check("Shaked's PR #60 review finding: 'כמה חדרים - אחד או שניים?' (not "
      "caught at all by the old keyword table, which has no rooms entry) "
      "now resolves correctly once type is answered and rooms is the "
      "real next gap",
      chat._enforce_one_option_question(
          "כמה חדרים - אחד או שניים?", LODGING_STATE_TYPE_KNOWN,
      ) == "כמה חדרים תרצו?")

PLANNING_STATE = dict(BASE_STATE, active_session="trip_planning", requested_services=["flights", "trip_planning"])
check("Shaked's PR #60 review finding: a pace question ('קצב רגוע או "
      "פעיל?') resolves to the real open trip_planning gap - which while "
      "style is still unanswered is genuinely style, not pace (the gap "
      "order the real missing_required pipeline itself uses)",
      chat._enforce_one_option_question(
          "אתם מעדיפים קצב רגוע או פעיל?", PLANNING_STATE,
      ) == "ספרו לי מה אתם אוהבים לעשות בחופשה.")
PLANNING_STATE_STYLE_KNOWN = dict(PLANNING_STATE, trip_planning={"details": {"style": "תרבות ואוכל"}})
check("once style is genuinely answered, the same pace question "
      "correctly resolves to the real pace gap",
      chat._enforce_one_option_question(
          "אתם מעדיפים קצב רגוע או פעיל?", PLANNING_STATE_STYLE_KNOWN,
      ) == "חשוב לכם שהקצב יהיה רגוע?")

FLIGHTS_STATE = dict(BASE_STATE, active_session="flights", requested_services=["flights"],
                      flight={"baggage": ["carry_on_only"]})
check("a budget question phrased as two alternatives gets the fixed open "
      "question, now correctly pluralized ('שלכם', not 'שלך')",
      chat._enforce_one_option_question(
          "יש לכם תקציב מסוים לאדם לטיסה, או שנחפש את המחיר הכי טוב שיש?", FLIGHTS_STATE,
      ) == "מה התקציב שלכם לאדם לטיסה?")
check("_flight_gap_question's connection_preference text is pluralized "
      "('לכם', not 'לך') - the flight.connection_preference gap itself "
      "only ever fires with a verified direct route in the DB "
      "(_direct_route_available), so this is checked at the function "
      "level directly rather than through a seeded state",
      chat._flight_gap_question(["flight.connection_preference"], {}) == "חשוב לכם שהטיסה תהיה ישירה?")
FLIGHTS_STATE_BAGGAGE_OPEN = dict(BASE_STATE, active_session="flights", requested_services=["flights"],
                                   budget_per_person={"amount": 3000})
check("the baggage topic still fires correctly for a flights-domain "
      "question when baggage is genuinely the real open gap",
      chat._enforce_one_option_question(
          "איזו כבודה תרצו - טרולי, מזוודה, או תיק קטן?", FLIGHTS_STATE_BAGGAGE_OPEN,
      ) == "איזו כבודה תרצו לקחת?")

# -- no active_session and no matching offer: left unchanged (no guessing) --

check("a reply with ' או ' but no active_session and no matching offer "
      "is left unchanged - nothing to anchor a state-driven fix to",
      chat._enforce_one_option_question(
          "תרצו לשמוע סיפור על היעד, או שנמשיך הלאה?", {}
      ) == "תרצו לשמוע סיפור על היעד, או שנמשיך הלאה?")

# -- general mechanics --

check("a leading statement sentence in the same reply is preserved, only "
      "the offending question clause is replaced",
      chat._enforce_one_option_question(
          "מעולה, נרשם. איזו כבודה תרצו לקחת - טרולי, מזוודה, או תיק קטן?",
          FLIGHTS_STATE_BAGGAGE_OPEN,
      ) == "מעולה, נרשם. איזו כבודה תרצו לקחת?")
check("a reply with no '?' at all is returned unchanged",
      chat._enforce_one_option_question("מעולה, נרשם.", {}) == "מעולה, נרשם.")
check("a reply whose last question has no ' או ' at all is left untouched",
      chat._enforce_one_option_question("איזו כבודה תרצו לקחת?", {}) == "איזו כבודה תרצו לקחת?")
FLIGHTS_STATE_NO_GAPS = dict(FLIGHTS_STATE, budget_per_person={"amount": 3000})
check("per Shaked's stage-1 run-5 finding (Paris): active_session set but "
      "genuinely no gap left, AND no next-domain offer in the state either "
      "- the rule 'never end a turn with no question at all' means the "
      "original reply is returned completely unchanged, not dropped",
      chat._enforce_one_option_question(
          "מעולה, הכל ידוע. עוד שאלה סתם, X או Y?", FLIGHTS_STATE_NO_GAPS,
      ) == "מעולה, הכל ידוע. עוד שאלה סתם, X או Y?")
check("same no-gap case with no leading statement at all - returns the "
      "original reply unchanged rather than emitting an empty string",
      chat._enforce_one_option_question("X או Y?", FLIGHTS_STATE_NO_GAPS) == "X או Y?")
check("Shaked's exact stage-1 run-5 repro (Paris, 06e2253): flights' last "
      "gap (budget) just answered - active_session snapshot still reads "
      "'flights' with no gaps left, but the SAME snapshot already has "
      "post_flight_offer/next_session='trip_planning' set. Tinkerbell's "
      "own 'X או Y' reply must resolve to the trip_planning offer, never "
      "drop to a bare 'פרטי הטיסה סגורים.' with no question at all",
      chat._enforce_one_option_question(
          "מעולה, פרטי הטיסה סגורים. רוצה שאציע מסלול לטיול, או שכבר יש לך רעיון משלך?",
          dict(FLIGHTS_STATE_NO_GAPS, post_flight_offer=["trip_planning"], next_session="trip_planning"),
      ) == "מעולה, פרטי הטיסה סגורים. לתכנן גם מסלול ואטרקציות לחופשה הזו?")
check("the same Paris repro also resolves correctly when only next_session "
      "is set (post_flight_offer not yet populated on this snapshot)",
      chat._enforce_one_option_question(
          "פרטי הטיסה סגורים. רוצה שאציע מסלול, או שכבר יש לך רעיון?",
          dict(FLIGHTS_STATE_NO_GAPS, next_session="trip_planning"),
      ) == "פרטי הטיסה סגורים. לתכנן גם מסלול ואטרקציות לחופשה הזו?")

# -- Stage-1 run-6 (Athens): two gap questions bundled with "ו", not "או" --

FLIGHTS_STATE_BOTH_OPEN = dict(BASE_STATE, active_session="flights", requested_services=["flights"])
check("Shaked's exact stage-1 run-6 repro (Athens, 595e29b): baggage AND "
      "budget bundled into one sentence joined by 'ו' ('...איזו כבודה "
      "תצטרכו, ויש הגבלת תקציב לאדם?'), never writing 'או' at all - the "
      "old ' או ' check alone missed this entirely. Resolves to the real "
      "single next gap (budget_per_person, checked first in "
      "_flight_gap_question's own priority order) same as an 'או' case",
      chat._enforce_one_option_question(
          "חופשה מעולה לאתונה! רק עוד שני פרטים קטנים לטיסה - איזו כבודה "
          "תצטרכו, ויש הגבלת תקציב לאדם?",
          FLIGHTS_STATE_BOTH_OPEN,
      ) == "חופשה מעולה לאתונה! מה התקציב שלכם לאדם לטיסה?")
check("the bundled-'ו' detector also fires on a lodging-domain bundle "
      "('וכמה'), resolving through the same state-driven lookup",
      chat._enforce_one_option_question(
          "איזה סוג לינה מתאים לכם, וכמה חדרים תרצו?", LODGING_STATE,
      ) == "איזה סוג לינה מתאים לכם?")
check("an ordinary 'ו' that does not fuse into one of the recognized "
      "question-word seams is left untouched - no false positive on a "
      "plain conjunction inside a single real question",
      chat._enforce_one_option_question(
          "איזו כבודה תרצו לקחת ולסדר מראש?", {}
      ) == "איזו כבודה תרצו לקחת ולסדר מראש?")

# -- Shlomo's follow-up: two FULLY SEPARATE '?' sentences (no "או"/"ו" at "
#    all) - the generalized, sentence-classifying version of the check --

FLIGHTS_STATE_DIRECT_AND_BAGGAGE = dict(BASE_STATE, active_session="flights", requested_services=["flights"],
                                         budget_per_person={"amount": 3000})
with patch.object(chat, "_direct_route_available", return_value=True):
    check("Shlomo's suggested combo (direct-flight + baggage): two fully "
          "separate '?' sentences, no 'או'/'ו' bundling at all - the OLD "
          "version only ever looked at the sentence containing the LAST "
          "'?', so the first, already-complete question sentence would "
          "have sat untouched as a 'prefix'. Now both are recognized as "
          "questions and collapsed to the one real next gap "
          "(flight.connection_preference, checked before flight.baggage "
          "in _flight_gap_question's own order)",
          chat._enforce_one_option_question(
              "חשוב לכם שהטיסה תהיה ישירה? איזו כבודה תרצו לקחת?",
              FLIGHTS_STATE_DIRECT_AND_BAGGAGE,
          ) == "חשוב לכם שהטיסה תהיה ישירה?")

FLIGHTS_STATE_DATES_TRAVELERS = dict(
    trip_type="vacation",
    destination={"places": ["אתונה"], "mode": "specific", "status": "known"},
    destination_airports=["ATH"], departure_airport="TLV",
    budget_per_person={"amount": 3000},
    active_session="flights", requested_services=["flights"],
)
check("Shlomo's second suggested combo (dates + travelers): two fully "
      "separate '?' sentences collapse to the one real next gap (dates, "
      "checked before travelers in _flight_gap_question's own order)",
      chat._enforce_one_option_question(
          "מתי תרצו לטוס? כמה נוסעים, ומי מבוגר ומי ילד?",
          FLIGHTS_STATE_DATES_TRAVELERS,
      ) == "מתי תרצי לצאת ולחזור?")
with patch.object(chat, "_direct_route_available", return_value=True):
    check("a leading statement sentence survives when two fully separate "
          "question sentences follow it - the statement is kept, both "
          "original questions are dropped, and the one real gap question "
          "is appended",
          chat._enforce_one_option_question(
              "מעולה, נרשם. חשוב לכם שהטיסה תהיה ישירה? איזו כבודה תרצו לקחת?",
              FLIGHTS_STATE_DIRECT_AND_BAGGAGE,
          ) == "מעולה, נרשם. חשוב לכם שהטיסה תהיה ישירה?")
check("per Shlomo's explicit caution: a normal final-summary reply with "
      "exactly one, unbundled confirmation question is never touched - "
      "no active_session, no post_flight_offer/next_session, so even "
      "though this is 'more than a sentence', it has exactly one "
      "question sentence and the generalized check leaves it alone",
      chat._enforce_one_option_question(
          "אז לסיכום: טיסה לאתונה, 1-10 במאי, שני מבוגרים, מלון במרכז "
          "העיר. את מאשרת את ההזמנה?",
          {"active_session": None},
      ) == "אז לסיכום: טיסה לאתונה, 1-10 במאי, שני מבוגרים, מלון במרכז "
           "העיר. את מאשרת את ההזמנה?")

# -- Shaked's PR #64 review (same day): the generalized version above still
#    rebuilt the message by stripping/rejoining fragments, which mangled
#    dates and dropped itinerary content - fixed by a digit-safe sentence
#    splitter that only ever splices OUT the question spans, keeping every
#    other character (including newlines) exactly as the original string --

check("Shaked's exact PR #64 review repro (dates): splitting on a bare '.' "
      "used to treat the periods inside '15.4.2027' as sentence boundaries "
      "and single-space-joining the fragments mangled it into "
      "'15. 4. 2027' while dropping the blank line entirely. Now the date "
      "and the blank line before the kept question both survive untouched",
      chat._enforce_one_option_question(
          "טיסה לאתונה 15.4.2027–19.4.2027, 3 נוסעות.\n\n"
          "איזו כבודה תצטרכו? ומה התקציב?",
          FLIGHTS_STATE_BOTH_OPEN,
      ) == "טיסה לאתונה 15.4.2027–19.4.2027, 3 נוסעות.\n\n"
           "מה התקציב שלכם לאדם לטיסה?")

PLANNING_STATE_ITINERARY_KNOWN = {
    "active_session": "trip_planning",
    "trip_planning": {"details": {"style": "תרבות ואוכל", "pace": "רגוע"}},
    "destination": {"places": ["אתונה"]},
    "dates": {"departure": "2027-04-15", "return": "2027-04-19"},
    "travelers": {"adults": 2},
    "trip_type": "vacation",
}
check("Shaked's exact PR #64 review repro (itinerary): active_session="
      "'trip_planning' with style/pace already known (_session_gaps empty) "
      "- the OLD version rebuilt the whole message, destroying the day "
      "lines/dates and replacing the real confirmation question with a "
      "wrong, from-scratch style question (a genuine loop risk, per her "
      "report). The day-marker ('יום 1'/'יום 2') scoped special case now "
      "leaves the entire itinerary body - including its own rhetorical "
      "'?' ('מה יותר כיף מאוכל טוב?') - completely untouched, and replaces "
      "only the real trailing confirmation question with the fixed "
      "trip_planning approval text, never a _session_gaps lookup",
      chat._enforce_one_option_question(
          "יום 1 (15.4, חמישי): נחיתה. מה יותר כיף מאוכל טוב? טברנה "
          "בפלאקה.\nיום 2 (16.4, שישי): אקרופוליס.\n\nהמסלול מתאים לכם?",
          PLANNING_STATE_ITINERARY_KNOWN,
      ) == "יום 1 (15.4, חמישי): נחיתה. מה יותר כיף מאוכל טוב? טברנה "
           "בפלאקה.\nיום 2 (16.4, שישי): אקרופוליס.\n\n"
           "המסלול שהצעתי מתאים לכם?")
check("the same itinerary case also resolves correctly when the trailing "
      "confirmation question is itself an 'X או Y' violation - still only "
      "that last sentence is replaced, the itinerary body untouched",
      chat._enforce_one_option_question(
          "יום 1 (15.4, חמישי): נחיתה. מה יותר כיף מאוכל טוב? טברנה "
          "בפלאקה.\nיום 2 (16.4, שישי): אקרופוליס.\n\n"
          "המסלול מתאים לכם, או שתרצו שינוי?",
          PLANNING_STATE_ITINERARY_KNOWN,
      ) == "יום 1 (15.4, חמישי): נחיתה. מה יותר כיף מאוכל טוב? טברנה "
           "בפלאקה.\nיום 2 (16.4, שישי): אקרופוליס.\n\n"
           "המסלול שהצעתי מתאים לכם?")
check("a non-itinerary message with no day marker at all is NOT routed "
      "through the itinerary special case, even with active_session="
      "'trip_planning' - falls through to the ordinary state-driven path",
      chat._enforce_one_option_question(
          "אתם מעדיפים קצב רגוע או פעיל?", PLANNING_STATE,
      ) == "ספרו לי מה אתם אוהבים לעשות בחופשה.")

# -- per Shlomo's explicit request: character-by-character identity checks
#    on the KEPT portion, not just overall-string equality, on both a real
#    itinerary and a message with dates --

_ITINERARY_INPUT = (
    "יום 1 (15.4, חמישי): נחיתה. מה יותר כיף מאוכל טוב? טברנה "
    "בפלאקה.\nיום 2 (16.4, שישי): אקרופוליס.\n\nהמסלול מתאים לכם?"
)
_ITINERARY_BODY = (
    "יום 1 (15.4, חמישי): נחיתה. מה יותר כיף מאוכל טוב? טברנה "
    "בפלאקה.\nיום 2 (16.4, שישי): אקרופוליס."
)
check("character-by-character: the itinerary body (both day lines, the "
      "dates, the embedded rhetorical '?', and the original '\\n' between "
      "them) is an EXACT prefix of the fixed output, byte for byte - not "
      "merely 'the same when compared as whole strings'",
      chat._enforce_one_option_question(
          _ITINERARY_INPUT, PLANNING_STATE_ITINERARY_KNOWN,
      ).startswith(_ITINERARY_BODY)
      and _ITINERARY_INPUT.startswith(_ITINERARY_BODY))

_DATES_INPUT = "טיסה לאתונה 15.4.2027–19.4.2027, 3 נוסעות.\n\nאיזו כבודה תצטרכו? ומה התקציב?"
_DATES_PREFIX = "טיסה לאתונה 15.4.2027–19.4.2027, 3 נוסעות.\n\n"
check("character-by-character: the date range and the blank line before "
      "it are an EXACT prefix of the fixed output, byte for byte - the "
      "two periods inside '15.4.2027' and the '\\n\\n' are untouched",
      chat._enforce_one_option_question(
          _DATES_INPUT, FLIGHTS_STATE_BOTH_OPEN,
      ).startswith(_DATES_PREFIX)
      and _DATES_INPUT.startswith(_DATES_PREFIX))

# -- Shlomo's further follow-up (same PR #64 round): when NO state-driven
#    replacement exists at all for a reply bundling multiple fully
#    separate questions, keep only the FIRST question and drop the rest,
#    rather than returning the whole reply with every question intact --

check("Shlomo's exact edge case: two fully separate questions, but no gap "
      "and no offer anywhere in the state (fixed stays None) - the first "
      "question is kept exactly as written, the second is dropped, no "
      "other character is touched",
      chat._enforce_one_option_question(
          "חשוב לכם שהטיסה תהיה ישירה? איזו כבודה תרצו לקחת?",
          {"active_session": None},
      ) == "חשוב לכם שהטיסה תהיה ישירה?")
check("the same no-fixed-found rule keeps any leading statement sentence "
      "untouched too, dropping only the extra trailing question(s)",
      chat._enforce_one_option_question(
          "מעולה, נרשם. חשוב לכם שהטיסה תהיה ישירה? איזו כבודה תרצו לקחת? "
          "ומתי תרצו לטוס?",
          {"active_session": None},
      ) == "מעולה, נרשם. חשוב לכם שהטיסה תהיה ישירה?")
check("a SINGLE bundled 'X או Y' question with no fixed replacement found "
      "still follows the Paris rule unchanged - there is only one "
      "question to begin with, so nothing is dropped, the whole reply is "
      "returned exactly as-is",
      chat._enforce_one_option_question(
          "מעולה, הכל ידוע. עוד שאלה סתם, X או Y?", FLIGHTS_STATE_NO_GAPS,
      ) == "מעולה, הכל ידוע. עוד שאלה סתם, X או Y?")


# === Bug 3: explicit gender hint ===

check("_gender_hint_text names masculine form explicitly for a known male customer",
      "זכר" in chat._gender_hint_text({"user_gender": "male"})
      and "תצטרך" in chat._gender_hint_text({"user_gender": "male"}))
check("_gender_hint_text names feminine form explicitly for a known female customer",
      "נקבה" in chat._gender_hint_text({"user_gender": "female"})
      and "תצטרכי" in chat._gender_hint_text({"user_gender": "female"}))
check("_gender_hint_text is empty when gender is unknown - no guess injected",
      chat._gender_hint_text({}) == "" and chat._gender_hint_text({"user_gender": None}) == "")


# === End-to-end: _call_tinkerbell actually applies both fixes ===

def _captured_system_dynamic(message, state, fake_reply):
    captured = {}

    def _fake_post_claude(key, model, system_static, system_dynamic, history, msg, max_tokens, include_history=True, source="other"):
        captured["system_dynamic"] = system_dynamic
        return fake_reply

    with patch.object(chat, "_post_claude", side_effect=_fake_post_claude):
        reply = chat._call_tinkerbell("test-key", "test-model", [], message, state)
    return reply, captured.get("system_dynamic", "")


e2e_reply, _ = _captured_system_dynamic(
    "אין לי רעיון, מה את ממליצה?",
    {"post_flight_offer": ["trip_planning"], "active_session": None, "destination": {"places": ["לונדון"]}},
    "בואי נדבר על המסלול ביעד - יש לך רעיון למה בא לך לעשות בלונדון, או שתרצי שאציע לך מסלול מגוון?",
)
check("end-to-end via _call_tinkerbell: V3's exact bad reply comes back fixed, "
      "with gender-neutral phrasing",
      e2e_reply == "לתכנן גם מסלול ואטרקציות לחופשה הזו?")

e2e_baggage_reply, _ = _captured_system_dynamic(
    "היי", dict(FLIGHTS_STATE_BAGGAGE_OPEN),
    "כל אחת מכן לוקחת רק תיק קטן, או שיש גם מזוודות?",
)
check("end-to-end via _call_tinkerbell: V4's exact bad baggage reply comes "
      "back fixed, with a real flights-domain baggage gap open",
      e2e_baggage_reply == "איזו כבודה תרצו לקחת?")

_, sd_male = _captured_system_dynamic(
    "אני טס ללונדון לבד", {"user_gender": "male", "destination": {"places": ["לונדון"]}}, "תשובה לדוגמה.",
)
check("end-to-end via _call_tinkerbell: a known male customer gets the explicit "
      "masculine-form hint in system_dynamic",
      "זכר" in sd_male and "תצטרך" in sd_male)

_, sd_none = _captured_system_dynamic(
    "היי", {"destination": {"places": ["לונדון"]}}, "תשובה לדוגמה.",
)
check("end-to-end via _call_tinkerbell: no gender hint text leaks in when "
      "user_gender is unknown",
      "מגדר" not in sd_none)


# === Stage-1 run-4 (Shaked, 17.10.2026, 4234cb8, 4/5 on 9f0c7db): W2/Paris ===

check("run-4's exact live budget question (W2, Paris) resolves correctly "
      "once the state-driven redesign is in place",
      chat._enforce_one_option_question(
          "יש לכם תקציב מסוים לאדם לטיסה, או שנחפש את המחיר הכי טוב שיש?", FLIGHTS_STATE,
      ) == "מה התקציב שלכם לאדם לטיסה?")
check("run-4 bug 2: the summary instruction now dictates the exact "
      "phrasing for a known 'אין העדפה' connection_preference, forbidding "
      "the misleading 'בהתאם לזמינות בפועל' paraphrase the live reply used "
      "(the customer answered 'לא משנה לנו', state held 'אין העדפה', but "
      "the summary read 'טיסה ישירה: בהתאם לזמינות בפועל' as if a "
      "preference for direct still applied)",
      'אין העדפה לטיסה ישירה' in chat.TINKERBELL_SYSTEM
      and 'בהתאם לזמינות בפועל' in chat.TINKERBELL_SYSTEM)

# Per Shlomo's explicit follow-up: a summary-wording fix alone doesn't help
# if the underlying STATE was mis-extracted in the first place (the live
# W2/Paris case saved connection_preference="direct" from an indifferent
# answer) - this proves the deterministic writer itself saves the right
# value, not just that the summary phrases a correct value correctly.
DIRECT_QUESTION_HISTORY = [{"role": "assistant", "content": "מעולה, נרשם. חשוב לכם שהטיסה תהיה ישירה?"}]
for _msg in ("לא משנה לנו", "לא חשוב", "גם וגם", "לא חשוב לנו"):
    check(f"_deterministic_connection_preference_facts('{_msg}') saves "
          "connection_preference='אין העדפה' in the STATE itself (not "
          "'direct', not left to the LLM extractor to decide)",
          chat._deterministic_connection_preference_facts(_msg, DIRECT_QUESTION_HISTORY)
          == {"flight": {"connection_preference": "אין העדפה"}})

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL STAGE1-RUN3-LEVAD-XORY-GENDER TESTS PASSED")
