# Live stage-1 run 14 (flight only) - sourced by run14_live.sh (needs reg/drive/say, P, PH).
# Owner rules: recycle 2 of 5 within 48h (B Zadar, E Bergen from run 13), diversify the rest; every scenario has a
# real typo; LIVE_SEARCH=1 per run (owner 23.10). Criteria updated 24.10 (scanned vacation -> subscription only;
# understanding through the model, no word lists).
#  R1 NEW "תמליצי לי" (owner 24.10): no destination -> 2-3 catalog destinations after AT MOST one question; dates/
#     travelers/etc. only after a destination is chosen.
#  R2 RECYCLED run-13 B "זדאק" (Zadar, ZAD): recognised (or ONE question naming Zadar); never a generic airport question.
#  R3 RECYCLED run-13 E "ברגם" + baby: ONE question naming Bergen AND Bergamo; never "אין שדה".
#  R4 NEW "ולנסיע" (Valencia, VLC, ה->ע) + accessibility "כן": owner 24.10 (DECISIONS.md): "כן" to accessibility = treat as wheelchair-level, whatever the reason; no follow-up asking what is needed, no "אדאג להתאמה"; needed=true and the summary shows a wheelchair-level adjustment; a medical detail the customer volunteers is NOT saved (PRV-18).
#     The answer volunteers a medical detail ("עבר אירוע מוחי") - it must not be saved, shown or repeated (PRV-18).
#  R5 NEW "טביליסו" (Tbilisi, TBS, י->ו): after "מאשרת" and the scan, "אפשר לדחות ביום?" -> Ariela recognises the
#     vacation and points to the paid subscription; no new dates, no re-asking, no new scan.
_pids=""
reg ${P}1 ${PH}1 female
( say ${P}1 "אני ובן הזוג שלי רוצים לטוס בפברואר לשבוע, אבל אין לנו מושג לאן. תמליצי לנו?"
  say ${P}1 "משהו לא רחוק, עם אוכל טוב ומזג אוויר נעים"
  drive ${P}1 R1 "נלך על ההמלצה הראשונה שלך" '{"תאריכים":["האפשרות הראשונה","כן"],"נגישות":"לא","כבודה":"טרולי לכל אחד","תקציב":"עד 1300 שקל לאדם","ישיר":"עדיף ישירה","מסלול":"לא","לינה":"יש לנו","רכב":"לא"}' ) > ${P}_R1.log 2>&1 &
_pids="${_pids:-} $!"
reg ${P}2 ${PH}2 female
drive ${P}2 R2 "אני ושתי חברות לזדאק, 2 עד 6 ביולי. לי מספיק טרולי, לשתיים האחרות מזוודה" '{"נגישות":"לא","אחידה":"כן","כבודה":"טרולי לכל אחת","שדה":"זדאר מתאים לנו","תקציב":"עד 1100 שקל לאחת","ישיר":"לא חובה","מסלול":"לא","לינה":"מסודר","רכב":"לא"}' > ${P}_R2.log 2>&1 &
_pids="${_pids:-} $!"
wait $_pids; _pids=""
reg ${P}3 ${PH}3 male
( say ${P}3 "אני, אשתי והתינוק שלנו בן שנה לברגם, 12 עד 17 ביוני"
  drive ${P}3 R3 "ברגן, בנורווגיה" '{"נגישות":"לא","כבודה":"לי ולאשתי מזוודה, לתינוק מספיק תיק קטן","אחידה":"כן, מזוודה לכולם","תקציב":"עד 1500 שקל לאדם","ישיר":"עדיף ישירה","מסלול":"לא","לינה":"מסודר","רכב":"לא"}' ) > ${P}_R3.log 2>&1 &
_pids="${_pids:-} $!"
reg ${P}4 ${PH}4 male
drive ${P}4 R4 "אני ואבא שלי לולנסיע, 3 עד 8 במרץ" '{"נגישות":"כן, אבא שלי עבר אירוע מוחי והוא הולך עם הליכון","כבודה":"מזוודה לכל אחד","תקציב":"עד 1400 שקל לאדם","ישיר":"עדיף ישירה","מסלול":"לא","לינה":"יש לנו","רכב":"לא"}' > ${P}_R4.log 2>&1 &
_pids="${_pids:-} $!"
wait $_pids; _pids=""
reg ${P}5 ${PH}5 female
( drive ${P}5 R5 "אני ואחותי לטביליסו, 10 עד 15 באפריל" '{"נגישות":"לא","כבודה":"טרולי לכל אחת","תקציב":"עד 1000 שקל לאחת","ישיר":"לא חובה","מסלול":"לא","לינה":"יש לנו","רכב":"לא"}'
  echo "---- flight change on the scanned vacation (expect: subscription referral, no change, no scan) ----"
  say ${P}5 "רגע, אפשר לדחות את כל הטיסה ביום אחד?" ) > ${P}_R5.log 2>&1
