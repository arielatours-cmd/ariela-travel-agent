# Dry run 5l - re-run of the two 5k failures (J0/J1: the two-candidate question was replaced by the generic
# "באיזה שדה תרצה לנחות בהלוך?" in _enforce_one_option_question) + J6 as a regression guard + J7, the cost-gate
# case from Shaked's review of 70f8479 (a typo'd correction on an already-settled destination).
# Run: DRY_RUN_COST_APPROVED=1 ARIELLA_MODEL=claude-sonnet-5 qa/dry_run_local.sh <ref> qa/live/scenarios/dryrun5l.sh [OUT]
# Criterion: real doubt -> ONE question naming BOTH options; no doubt -> no question; a correction is always saved.
#  J0 "לברגם"  -> first reply names Bergen AND Bergamo (one question); "ברגן, בנורווגיה" -> BGO
#  J1 "ליון"   -> first reply names Lyon AND Greece (one question);   "ליון בצרפת"     -> LYS
#  J6 Vienna, then "בעצם נעדיף פראג במקום וינה" -> PRG, no delete question, no airport question
#  J7 Vienna, then the typo'd correction "רגע, בעצם נעדיף פראד" -> PRG saved (or one question naming Prague),
#     never silently staying on VIE; summary Prague
P=dr5l; PH=05000993
_pids=""
reg ${P}0 ${PH}0 male
( say ${P}0 "אני, אשתי והתינוק שלנו בן שנה לברגם, 12 עד 17 ביוני"
  drive ${P}0 J0 "ברגן, בנורווגיה" '{"נגישות":"לא","כבודה":"מזוודה לכל אחד","אחידה":"כן, מזוודה לכולם","תקציב":"עד 1500 שקל לאדם","ישיר":"עדיף ישירה","מסלול":"לא","לינה":"מסודר","רכב":"לא"}' ) > ${P}_J0.log 2>&1 &
_pids="${_pids:-} $!"
reg ${P}1 ${PH}1 male
( say ${P}1 "אני ואשתי ליון, 5 עד 10 במאי"
  drive ${P}1 J1 "ליון בצרפת" '{"נגישות":"לא","כבודה":"טרולי לכל אחד","תקציב":"עד 1300 שקל לאדם","ישיר":"לא משנה","מסלול":"לא","לינה":"יש לנו","רכב":"לא"}' ) > ${P}_J1.log 2>&1 &
_pids="${_pids:-} $!"
wait $_pids; _pids=""   # only our drivers - never the dry-run server running in the background
reg ${P}6 ${PH}6 female
drive ${P}6 J6 "אני והחברה שלי לוינה, 1 עד 5 בדצמבר" '{"__inject":["רגע, בעצם נעדיף פראג במקום וינה"],"נגישות":"לא","כבודה":"טרולי לכל אחת","תקציב":"עד 1000 שקל לאחת","ישיר":"עדיף ישירה","מסלול":"לא","לינה":"מסודר","רכב":"לא"}' > ${P}_J6.log 2>&1 &
_pids="${_pids:-} $!"
reg ${P}7 ${PH}7 female
drive ${P}7 J7 "אני ובעלי לוינה, 8 עד 12 בינואר" '{"__inject":["רגע, בעצם נעדיף פראד"],"נגישות":"לא","כבודה":"מזוודה לכל אחד","תקציב":"עד 1200 שקל לאדם","ישיר":"עדיף ישירה","מסלול":"לא","לינה":"יש לנו","רכב":"לא"}' > ${P}_J7.log 2>&1 &
_pids="${_pids:-} $!"
wait $_pids; _pids=""
