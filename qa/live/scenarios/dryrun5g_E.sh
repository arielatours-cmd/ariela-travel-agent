# Dry run 5g - scenario E only ("ברגם", ן->ם typo that is equally close to Bergen and Bergamo), 3 variants.
# Run: DRY_RUN_COST_APPROVED=1 ARIELLA_MODEL=claude-sonnet-5 qa/dry_run_local.sh <ref> qa/live/scenarios/dryrun5g_E.sh [OUT]
# Expected (owner principle 22.10: the model decides, the code verifies; a needless confirmation is a failure):
#  E1 "ברגם" alone        -> ONE question naming both (ברגן / ברגמו), nothing saved before the answer;
#                            the answer "ברגן, בנורווגיה" -> BGO, never asked again, summary landing ברגן (BGO).
#  E2 "ברגם בנורווגיה"    -> BGO directly, no question about the city (Norway is real evidence).
#  E3 "ברגם באיטליה"      -> BGY directly, no question about the city (Italy is real evidence).
# ~30 turns. The first turn of E1 goes through `say` so its reply is logged on its own before the answer.
P=dr5g; PH=05000995
_pids=""
reg ${P}1 ${PH}1 male
( say ${P}1 "אני, אשתי והתינוק שלנו בן שנה לברגם, 12 עד 17 ביוני"
  drive ${P}1 E1 "ברגן, בנורווגיה" '{"נגישות":"לא","כבודה":"לי ולאשתי מזוודה, לתינוק מספיק תיק קטן","אחידה":"כן, מזוודה לכולם","תקציב":"עד 1500 שקל לאדם","ישיר":"עדיף ישירה","מסלול":"לא","לינה":"מסודר","רכב":"לא"}' ) > ${P}_E1.log 2>&1 &
_pids="${_pids:-} $!"
reg ${P}2 ${PH}2 female
drive ${P}2 E2 "אני ובעלי לברגם בנורווגיה, 3 עד 8 ביולי" '{"נגישות":"לא","כבודה":"מזוודה לכל אחד","תקציב":"עד 1800 שקל לאדם","ישיר":"לא משנה","מסלול":"לא","לינה":"יש לנו","רכב":"לא"}' > ${P}_E2.log 2>&1 &
_pids="${_pids:-} $!"
wait $_pids; _pids=""   # only our drivers - never the dry-run server running in the background
reg ${P}3 ${PH}3 female
drive ${P}3 E3 "אני ושתי חברות לברגם באיטליה, 10 עד 14 בספטמבר" '{"נגישות":"לא","כבודה":"טרולי לכל אחת","תקציב":"עד 900 שקל לאחת","ישיר":"עדיף ישירה","מסלול":"לא","לינה":"מסודר","רכב":"לא"}' > ${P}_E3.log 2>&1
