# Shared scenario set for dry run 5 and live run 13 (sourced; needs reg/drive/say and P=<id prefix>, PH=<phone prefix>).
# Owner principle 22.10: every scenario has a real adjacent-key typo; Ariela must understand it, never say
# "אין שדה" for a city that has one, never ask a needless spelling confirmation.
#  A "פפוס" (Paphos, PFO): accessibility "כן" -> medical detail -> only the practical need saved/shown;
#    mixed -> "לא" -> hand bag; car never marked done without being asked.
#  B "זדאק" (Zadar, ZAD, ר->ק) + mixed baggage in the FIRST message: explanation + yes/no; "כן" -> the
#    normal baggage question (Ariela must not pick the type herself); accessibility asked before closing.
#  C Hallstatt (no airport, nearest SZG), relative dates; the airport answer "זלצבורד" (ג->ד) is given
#    together with the date choice, while the dates question is open -> saved (SZG), never asked again.
#  D "המבורד" (Hamburg, HAM, ג->ד): post-summary shift (one date + yes/no), explicit dates (no confirm),
#    suitcase switch (no upsell).
#  E "ברגם" (Bergen, BGO, ן->ם) + baby: accessibility asked, not inferred; mixed -> "כן, מזוודה לכולם".
_pids=""
reg ${P}a ${PH}1 female
drive ${P}a A "אני ואמא שלי לפפוס, 20 עד 25 באפריל" '{"נגישות":["כן","אמא שלי עברה ניתוח בברך והיא מתקשה ללכת מרחקים ארוכים"],"שדה":"פאפוס מתאים לנו","כבודה":"לי מזוודה, לאמא מספיק טרולי","אחידה":"לא","תקציב":"עד 1300 שקל לאחת","ישיר":"לא משנה","מסלול":"לא","לינה":"יש לנו","רכב":"לא"}' > ${P}_A.log 2>&1 &
_pids="${_pids:-} $!"
reg ${P}b ${PH}2 female
drive ${P}b B "אני ושתי חברות לזדאק, 2 עד 6 ביולי. לי מספיק טרולי, לשתיים האחרות מזוודה" '{"נגישות":"לא","אחידה":"כן","כבודה":"טרולי לכל אחת","שדה":"זדאר מתאים לנו","תקציב":"עד 1100 שקל לאחת","ישיר":"לא חובה","מסלול":"לא","לינה":"מסודר","רכב":"לא"}' > ${P}_B.log 2>&1 &
_pids="${_pids:-} $!"
wait $_pids; _pids=""   # only our drivers - never the dry-run server running in the background
reg ${P}c ${PH}3 male
drive ${P}c C "זוג להלשטאט בסוף החודש הבא, לחמישה ימים" '{"תאריכים":["האפשרות הראשונה, ונוח לנו לנחות בזלצבורד","כן"],"שדה":"זלצבורד מתאים לנו","נגישות":"לא צריך","כבודה":"מזוודה לכל אחד","תקציב":"עד 1400 שקל לאדם","ישיר":"לא","מסלול":"לא","לינה":"לא","רכב":"לא"}' > ${P}_C.log 2>&1 &
_pids="${_pids:-} $!"
reg ${P}d ${PH}4 female
( drive ${P}d D "אני והחבר שלי להמבורד, 6 עד 10 במאי" '{"נגישות":"לא","כבודה":"טרולי לכל אחד","תקציב":"עד 1200 שקל לאדם","ישיר":"לא חובה","מסלול":"לא","לינה":"יש לנו","רכב":"לא"}'; say ${P}d "רגע, אפשר לדחות את כל הטיסה ביום אחד?" "כן" "ובעצם אפשר לצאת ב-9.5 ולחזור ב-13.5?" "ונעדיף בעצם מזוודה לכל אחד" ) > ${P}_D.log 2>&1 &
_pids="${_pids:-} $!"
wait $_pids; _pids=""   # only our drivers - never the dry-run server running in the background
reg ${P}e ${PH}5 male
drive ${P}e E "אני, אשתי והתינוק שלנו בן שנה לברגם, 12 עד 17 ביוני" '{"נגישות":"לא","כבודה":"לי ולאשתי מזוודה, לתינוק מספיק תיק קטן","אחידה":"כן, מזוודה לכולם","תקציב":"עד 1500 שקל לאדם","ישיר":"עדיף ישירה","מסלול":"לא","לינה":"מסודר","רכב":"לא"}' > ${P}_E.log 2>&1
