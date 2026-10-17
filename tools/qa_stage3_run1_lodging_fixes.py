"""QA for Shaked's stage-3 run-1 findings (ad2f793, 1/5 - London passed), relayed
17.10.2026. Five separate failures, fixed together in ariella_chat_clean.py:

1. Paris (worst - 13x loop, never reached a summary): "אין הגבלה" answering
   the lodging per-night budget question ("מה התקציב שלכם ללילה?") set
   neither lodging.details.budget nor .level, so budget_or_level could never
   close. Fixed: _deterministic_lodging_facts now recognizes a no-limit
   answer gated on the actual question asked (תקציב+ליל both in
   last_question) and closes the gap via level="אין העדפה" (budget itself
   stays null - the correct no-price-cap search behavior).

2. Paris/Athens: apartment bathrooms - "שני חדרי רחצה" (spelled-out "two")
   wasn't parsed (bare digit regex only), and in Athens the question was
   never asked at all (purely prompt-driven, no real gap enforcing it).
   Fixed: spelled-out Hebrew number support for the bathrooms answer, and a
   real missing_required gap (lodging.details.bathrooms) gated on
   type=="דירה", plus a prompt instruction that the count appears in the
   final summary.

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
   rooms check, so "כמה חדרים תרצו?" was asked 4 times. Fixed: a Hebrew
   number-word-near-"חדר" regex, tolerating a few words in between.

5. Rome + Budapest: a bundled two-topic question evaded
   _enforce_one_option_question in two different ways neither existing
   check caught:
   (a) Rome - "לגבی מספר החדרים והתקציב ללילה, מה יתאים לכם?" is ONE
       question sentence (no "או"/"ו" between two question clauses) whose
       own lead-in already names two different still-open lodging topics
       (rooms AND budget). Fixed: a state-gap-driven topic-keyword check for
       the lodging domain specifically (mutually exclusive - bathrooms
       checked before the bare "חדר" rooms check).
   (b) Budapest - "ספרו לי... מה אתם אוהבים לעשות בחופשה, וגם האם חשוב לכם
       קצב רגוע..." has NO "?" anywhere at all, so the function's very first
       line ("if '?' not in text: return reply") let it straight through.
       Fixed: a narrower bundling regex (_BUNDLED_NO_QMARK_RE, requires an
       actual question word right after "וגם" to rule out an ordinary
       statement like "אישרתי את הטיסה, וגם את המלון.") plus a check that
       the text before it already reads as an open question - when both
       hold, the smuggled clause is truncated and the remaining single
       question goes through the exact same resolution path as every other
       case in this function.

6. Shlomo's follow-up on this same report (17.10.2026): regardless of why
   any one parser missed a specific phrasing, no lodging field should ever
   be asked more than twice in the same conversation. Fixed with a
   deterministic safety net (_apply_lodging_ask_limit_fallback) that counts
   how many prior assistant turns already asked about a given still-open
   lodging gap and, once that reaches 2, force-closes it.

   Shaked's review of the FIRST version of #6 (real Paris history, s3a2):
   checking the cue word anywhere in the whole assistant message false-
   positived on ordinary non-question narrative text (a route proposal's
   own "...במלון באזור מרכזי", and a plain recommendation sentence with NO
   "?" at all) - lodging.details.locations got force-closed as "אין
   העדפה" WITHOUT EVER ACTUALLY BEING ASKED, the exact Rome bug (#3) this
   PR exists to fix, just reached a different way. Fixed: only the
   message's own real question clause counts (via _last_question_clause),
   and a message with no "?" at all is skipped entirely. Also, per Shaked
   and Shlomo together: force-closing to "אין העדפה" when the customer
   genuinely replied something (just not in a shape the field's own parser
   recognized) throws that answer away - the raw reply text right after
   the LAST matched question is now saved as the field's value instead;
   "אין העדפה" is reserved for when there truly was no reply at all.

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


# === #1: Paris - lodging budget "no limit" ===

history_budget = [{"role": "assistant", "content": "מה התקציב שלכם ללילה?"}]
for phrase in ("אין הגבלה", "ללא הגבלה", "אין תקרה", "לא מוגבל"):
    facts = chat._deterministic_lodging_facts(phrase, history_budget)
    check(f"Shaked's Paris finding: '{phrase}' answering the lodging budget "
          "question closes the gap via level='אין העדפה' (budget stays null "
          "- the correct no-price-cap search behavior), never stuck open",
          facts.get("lodging", {}).get("details", {}).get("level") == "אין העדפה"
          and facts.get("lodging", {}).get("details", {}).get("budget") is None)

check("the composite gap actually closes end to end once level is set this way",
      "lodging.details.budget_or_level" not in gaps_for(
          ["lodging"], {"type": "דירה", "rooms": 1, "bathrooms": 1, "locations": "מרכז", "level": "אין העדפה"}))

# Regression: a genuine numeric nightly budget answer is untouched by the new check.
facts_numeric = chat._deterministic_lodging_facts("עד 500 ללילה", history_budget)
check("regression: a real numeric nightly budget answer still sets budget, "
      "not level - the no-limit branch never short-circuits it",
      facts_numeric.get("lodging", {}).get("details", {}).get("budget") == 500
      and "level" not in facts_numeric.get("lodging", {}).get("details", {}))

# Regression: the no-limit phrases must not fire when the budget question
# wasn't actually the one just asked (gated on last_question, never blind).
history_other = [{"role": "assistant", "content": "איזה סוג לינה מתאים לכם?"}]
facts_ungated = chat._deterministic_lodging_facts("אין הגבלה", history_other)
check("regression: 'אין הגבלה' answering an UNRELATED lodging question "
      "(type, not budget) never sets level - gated on the real question asked",
      "level" not in facts_ungated.get("lodging", {}).get("details", {}))


# === #2: apartment bathrooms ===

history_bath = [{"role": "assistant", "content": "כמה חדרי רחצה תרצו בדירה?"}]
check("Shaked's Paris finding: 'שני חדרי רחצה' (spelled-out 'two') parsed as bathrooms=2",
      chat._deterministic_lodging_facts("שני חדרי רחצה", history_bath)
      .get("lodging", {}).get("details", {}).get("bathrooms") == 2)
check("regression: a bare digit answer ('2 חדרי רחצה') still works",
      chat._deterministic_lodging_facts("2 חדרי רחצה", history_bath)
      .get("lodging", {}).get("details", {}).get("bathrooms") == 2)
check("regression: 'אחד' (one) still parses as bathrooms=1",
      chat._deterministic_lodging_facts("חדר רחצה אחד מספיק", history_bath)
      .get("lodging", {}).get("details", {}).get("bathrooms") == 1)

check("Shaked's Athens finding: an apartment (type='דירה') with no bathrooms "
      "set is now a real missing_required gap, not left to the model's memory",
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


# === #4: Budapest - rooms with a descriptive word in between ===

history_rooms = [{"role": "assistant", "content": "כמה חדרים תרצו?"}]
check("Shaked's Budapest finding: 'חדר משפחתי אחד עם עריסה' (descriptive "
      "word between 'חדר' and the spelled-out 'אחד') parsed as rooms=1",
      chat._deterministic_lodging_facts("חדר משפחתי אחד עם עריסה", history_rooms)
      .get("lodging", {}).get("details", {}).get("rooms") == 1)
check("regression: a plain digit answer ('3 חדרים') still works",
      chat._deterministic_lodging_facts("3 חדרים", history_rooms)
      .get("lodging", {}).get("details", {}).get("rooms") == 3)
check("regression: the exact bare 'חדר אחד' phrase still works unchanged",
      chat._deterministic_lodging_facts("חדר אחד", history_rooms)
      .get("lodging", {}).get("details", {}).get("rooms") == 1)
check("regression: 'חדר זוגי' (double room, singular) still infers rooms=1 "
      "even when volunteered outside the rooms question",
      chat._deterministic_lodging_facts("עד 600 שקל ללילה לחדר זוגי", [])
      .get("lodging", {}).get("details", {}).get("rooms") == 1)


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
      "never mistaken for a bundled question (no question word right after "
      "'וגם', and no interrogative opener before it)",
      chat._enforce_one_option_question("אישרתי את הטיסה, וגם את המלון.", {}) ==
      "אישרתי את הטיסה, וגם את המלון.")

check("regression: a plain reply with no '?' and no bundling cue at all "
      "passes through completely untouched",
      chat._enforce_one_option_question("מעולה, פרטי הטיסה נקלטו.", {}) ==
      "מעולה, פרטי הטיסה נקלטו.")

# Carried-over regression from the prior PR (#72): the parenthetical
# example-list case must still be allowed (never re-flagged as bundled).
check("regression (PR #72): a parenthetical example-list open question "
      "still survives completely unchanged",
      chat._enforce_one_option_question(
          "מה הסגנון שהכי מדבר אלייך בטיול הזה (תרבות ומוזיאונים, שופינג, "
          "אווירה לוקאלית, אוכל, נוף וטבע וכו׳)?",
          {"active_session": "trip_planning", "requested_services": ["trip_planning"],
           "session_status": {}, "trip_planning": {"details": {}}},
      ) == "מה הסגנון שהכי מדבר אלייך בטיול הזה (תרבות ומוזיאונים, שופינג, "
           "אווירה לוקאלית, אוכל, נוף וטבע וכו׳)?")


# === Shlomo's follow-up: deterministic "never ask the same field more
#     than twice" safety net, independent of any one field's own parser.
#     Fixed per Shaked's PR #73 review (real Paris history, s3a2): only the
#     message's own real question clause counts (never a narrative mention
#     with no "?" at all), and a genuine customer reply after the last ask
#     is saved as raw text rather than overwritten as "אין העדפה" ===

def _history_asking_twice(question_text, last_reply="עדיין לא ברור"):
    return [
        {"role": "assistant", "content": question_text},
        {"role": "user", "content": "משהו שלא נקלט"},
        {"role": "assistant", "content": question_text},
        {"role": "user", "content": last_reply},
    ]


state_budget_loop = {
    "requested_services": ["lodging"], "session_status": {},
    "lodging": {"details": {"type": "מלון", "rooms": 2, "locations": "מרכז"}},
}
out_budget_loop = chat._apply_lodging_ask_limit_fallback(
    state_budget_loop, _history_asking_twice("מה התקציב שלכם ללילה?", "בערך 400 איכשהו"))
check("Shlomo's follow-up: the lodging budget question asked twice saves "
      "the customer's own raw last reply rather than guessing/discarding it "
      "(Paris hit 13x)",
      out_budget_loop["lodging"]["details"].get("level") == "בערך 400 איכשהו")

state_rooms_loop = {
    "requested_services": ["lodging"], "session_status": {},
    "lodging": {"details": {"type": "מלון", "locations": "מרכז", "level": "אין העדפה"}},
}
out_rooms_loop = chat._apply_lodging_ask_limit_fallback(
    state_rooms_loop, _history_asking_twice("כמה חדרים תרצו?", "לא בטוחה כמה בדיוק"))
check("Shlomo's follow-up: 'כמה חדרים תרצו?' asked twice saves the raw "
      "last reply into rooms (Budapest hit 4x)",
      out_rooms_loop["lodging"]["details"].get("rooms") == "לא בטוחה כמה בדיוק")

state_no_reply = {
    "requested_services": ["lodging"], "session_status": {},
    "lodging": {"details": {"type": "מלון", "rooms": 2, "locations": "מרכז"}},
}
out_no_reply = chat._apply_lodging_ask_limit_fallback(
    state_no_reply, [
        {"role": "assistant", "content": "מה התקציב שלכם ללילה?"},
        {"role": "user", "content": ""},
        {"role": "assistant", "content": "מה התקציב שלכם ללילה?"},
    ])
check("Shlomo's follow-up: 'אין העדפה' is still the fallback when the "
      "customer truly never replied to the last ask at all",
      out_no_reply["lodging"]["details"].get("level") == "אין העדפה")

state_once = {
    "requested_services": ["lodging"], "session_status": {},
    "lodging": {"details": {"type": "מלון", "rooms": 2, "locations": "מרכז"}},
}
out_once = chat._apply_lodging_ask_limit_fallback(
    state_once, [{"role": "assistant", "content": "מה התקציב שלכם ללילה?"}])
check("regression: asked only ONCE never force-closes the gap - the normal "
      "parsers still get their fair first (and second) chance",
      "level" not in out_once["lodging"]["details"])

state_already_answered = {
    "requested_services": ["lodging"], "session_status": {},
    "lodging": {"details": {"type": "מלון", "rooms": 2, "locations": "מרכז", "budget": 400}},
}
out_already = chat._apply_lodging_ask_limit_fallback(
    state_already_answered, _history_asking_twice("מה התקציב שלכם ללילה?"))
check("regression: a gap that's already genuinely closed (real budget set) "
      "is never touched even if the question text appears twice in history",
      out_already["lodging"]["details"].get("budget") == 400
      and "level" not in out_already["lodging"]["details"])

# === Shaked's exact PR #73 review repro: a route proposal's own narrative
#     text ("...במלון באזור מרכזי") and a plain non-question recommendation
#     ("הכי הגיוני להישאר באזור מרכזי אחד", no "?" at all) must NEVER be
#     counted as if they were real "where do you want to stay" questions -
#     this is the exact mechanism that silently force-closed
#     lodging.details.locations in Paris (s3a2) without it ever being asked ===

state_paris_repro = {
    "requested_services": ["lodging", "trip_planning"], "session_status": {},
    "lodging": {"details": {"type": "דירה", "rooms": 2, "level": "אין העדפה"}},
}
history_paris_repro = [
    {"role": "assistant", "content": "הנה הצעה למסלול: יום 1 - שיטוט במרכז העיר, "
                                      "התארגנות במלון באזור מרכזי. המסלול מתאים לכם?"},
    {"role": "user", "content": "כן, מתאים"},
    {"role": "assistant", "content": "מעולה. בפריז, עם כל האטרקציות הפזורות במרכז, "
                                      "הכי הגיוני להישאר באזור מרכזי אחד."},
    {"role": "user", "content": "סבבה"},
]
out_paris_repro = chat._apply_lodging_ask_limit_fallback(state_paris_repro, history_paris_repro)
check("Shaked's PR #73 review repro: a route narrative mentioning 'אזור' "
      "(inside its own question about the ROUTE, not lodging) and a "
      "recommendation sentence with NO '?' at all never force-close "
      "lodging.details.locations - it still isn't genuinely asked",
      "locations" not in out_paris_repro["lodging"]["details"])

state_rome_repro = {
    "requested_services": ["lodging"], "session_status": {},
    "lodging": {"details": {"type": "מלון", "rooms": 2}},
}
history_rome_repro = [
    {"role": "assistant", "content": "תקציב הטיסה עד 2000 ש״ח, והחופשה כוללת 4 לילות ברומא. "
                                      "חשוב לכם טיסה ישירה?"},
    {"role": "user", "content": "כן"},
]
out_rome_repro = chat._apply_lodging_ask_limit_fallback(state_rome_repro, history_rome_repro)
check("regression: 'תקציב הטיסה... 4 לילות' (both cue words present, but "
      "in an earlier STATEMENT clause, not the actual question asked - a "
      "direct-flight question) never force-closes the lodging budget gap",
      "level" not in out_rome_repro["lodging"]["details"]
      and "budget" not in out_rome_repro["lodging"]["details"])

if FAILED:
    print(f"\n{len(FAILED)} FAILED: {FAILED}")
    sys.exit(1)
print("\nALL STAGE-3-RUN-1 LODGING-FIX TESTS PASSED")
