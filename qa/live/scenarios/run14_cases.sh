# Live stage-1 run 14 (flight only) - sourced by run14_live.sh (needs reg/drive/say, P, PH).
# Owner rules: recycle 2 of 5 within 48h (B Zadar, E Bergen from run 13), diversify the rest; every scenario has a
# real typo. NO live search (owner 23.10: one searching run per series - run 13 was it; while fixes are pending
# the runs go without a scan): run WITHOUT LIVE_SEARCH. Criteria updated 24.10 (scanned vacation -> subscription only;
# understanding through the model, no word lists).
#  R1 NEW "תמליצי לי" (owner 24.10, updated): no destination -> Ariela draws the customer out with open questions
#     about the direction (kind of trip, atmosphere, preferences - several allowed), then recommends catalog
#     destinations. Before a destination is chosen: NO dates/budget/travelers/baggage/accessibility questions.
#     A detail the customer said herself ("בפברואר", "לשבוע") is saved.
#  R2 RECYCLED run-13 B "זדאק" (Zadar, ZAD): recognised (or ONE question naming Zadar); never a generic airport question.
#  R3 RECYCLED run-13 E "ברגם" + baby: ONE question naming Bergen AND Bergamo; never "אין שדה".
#  R4 NEW "ולנסיע" (Valencia, VLC, ה->ע) + accessibility "כן": owner 24.10 (DECISIONS.md): "כן" to accessibility = treat as wheelchair-level, whatever the reason; no follow-up asking what is needed, no "אדאג להתאמה"; needed=true and the summary shows a wheelchair-level adjustment; a medical detail the customer volunteers is NOT saved (PRV-18).
#     The answer volunteers a medical detail ("עבר אירוע מוחי") - it must not be saved, shown or repeated (PRV-18).
#  R5 RECYCLED (run-13 D account r13d, vacation 262 - scanned 24.10, inside the 48h window): back in the chat,
#     "אפשר לדחות ביום?" -> Ariela recognises the existing vacation and points to the paid subscription (owner
#     24.10); no new dates, no re-asking, no scan. Uses the existing account - no new vacation, no SerpAPI.
_pids=""
reg ${P}1 ${PH}1 female
( say ${P}1 "אני ובן הזוג שלי רוצים לטוס בפברואר לשבוע, אבל אין לנו מושג לאן. תמליצי לנו?"
  say ${P}1 "משהו לא רחוק, עם אוכל טוב ומזג אוויר נעים"
  say ${P}1 "אנחנו אוהבים לשוטט בעיר עם קצב רגוע, קצת ים זה בונוס"
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
( echo "---- run-13 D vacation 262 (already scanned): flight change -> subscription referral, no change ----"
  say r13d "היי, לגבי החופשה בהמבורג - אפשר לדחות את כל הטיסה ביום אחד?" ) > ${P}_R5.log 2>&1
