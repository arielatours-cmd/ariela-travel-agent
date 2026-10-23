# Dry run 5j - real spelling mistakes beyond Bergen (owner 23.10: "אתם מתעכבים על עיר אחת. ואם יהיו עוד לקוחות
# שיטעו בכיתוב? לשמל ליון שבצרפת או ליון המדינה?").
# Run: DRY_RUN_COST_APPROVED=1 ARIELLA_MODEL=claude-sonnet-5 qa/dry_run_local.sh <ref> qa/live/scenarios/dryrun5j_typos.sh [OUT]
# Criterion: real doubt -> ONE question naming the options; no doubt -> no question; a customer's correction is
# always saved (never "אעדכן" without the state and the summary following). ~70 turns.
#  J0 "לברגם" (Bergen/Bergamo, no country)       -> one question; "ברגן, בנורווגיה" -> BGO
#  J1 "ליון" (Lyon, France - or "ל-יוון", Greece) -> one question; "ליון בצרפת" -> LYS
#  J2 "למלגה" (Malaga or Malta, one letter each)   -> one question; "מלאגה שבספרד" -> AGP; relative dates
#  J3 "לברצלונע" (adjacent key ה->ע, no rival)    -> BCN, no question
#  J4 "לאמסטרם" (missing ד, no rival)             -> AMS, no question
#  J5 "לסבילה שבספרד" (missing י + country)       -> SVQ, no question
#  J6 correction: Vienna, then "בעצם נעדיף פראג"   -> PRG saved, summary Prague, Vienna gone
P=dr5j; PH=05000994
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
reg ${P}2 ${PH}2 female
( say ${P}2 "זוג למלגה בסוף מרץ, לשבוע"
  drive ${P}2 J2 "מלאגה שבספרד" '{"תאריכים":["האפשרות הראשונה","כן"],"נגישות":"לא","כבודה":"מזוודה לכל אחד","תקציב":"עד 1200 שקל לאדם","ישיר":"עדיף ישירה","מסלול":"לא","לינה":"יש לנו","רכב":"לא"}' ) > ${P}_J2.log 2>&1 &
_pids="${_pids:-} $!"
reg ${P}3 ${PH}3 female
drive ${P}3 J3 "אני ושתי חברות לברצלונע, 14 עד 18 ביוני" '{"נגישות":"לא","כבודה":"טרולי לכל אחת","תקציב":"עד 1100 שקל לאחת","ישיר":"עדיף ישירה","מסלול":"לא","לינה":"מסודר","רכב":"לא"}' > ${P}_J3.log 2>&1 &
_pids="${_pids:-} $!"
wait $_pids; _pids=""
reg ${P}4 ${PH}4 male
drive ${P}4 J4 "אני לבד לאמסטרם, 2 עד 6 בנובמבר" '{"נגישות":"לא","כבודה":"תיק יד בלבד","תקציב":"עד 1000 שקל","ישיר":"לא חובה","מסלול":"לא","לינה":"יש לי","רכב":"לא"}' > ${P}_J4.log 2>&1 &
_pids="${_pids:-} $!"
reg ${P}5 ${PH}5 female
drive ${P}5 J5 "אני ובעלי לסבילה שבספרד, 20 עד 26 באפריל" '{"נגישות":"לא","כבודה":"מזוודה לכל אחד","תקציב":"עד 1500 שקל לאדם","ישיר":"לא משנה","מסלול":"לא","לינה":"יש לנו","רכב":"לא"}' > ${P}_J5.log 2>&1 &
_pids="${_pids:-} $!"
wait $_pids; _pids=""
reg ${P}6 ${PH}6 female
drive ${P}6 J6 "אני והחברה שלי לוינה, 1 עד 5 בדצמבר" '{"__inject":["רגע, בעצם נעדיף פראג במקום וינה"],"נגישות":"לא","כבודה":"טרולי לכל אחת","תקציב":"עד 1000 שקל לאחת","ישיר":"עדיף ישירה","מסלול":"לא","לינה":"מסודר","רכב":"לא"}' > ${P}_J6.log 2>&1
