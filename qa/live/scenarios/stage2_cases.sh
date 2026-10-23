# Stage 2 (flight + route) shared scenario set - dry run and live (sourced; needs reg/drive/say, P=<id prefix>, PH=<phone prefix>).
# Owner 23.10: "חייבים להגיע היום לשלב 2 טיסה ומסלול". Same rules as stage 1 (qa/stage-scenarios.md) plus the route:
# route offered after the flight details -> style -> pace -> a day-by-day route -> approval -> lodging offered
# (and, in S2, lodging built along the route's cities). Every scenario has a real adjacent-key typo
# (principle 22.10): Ariela must understand it, never say "אין שדה" for a city that has one, never ask a
# needless spelling confirmation.
#  S1 "ליסבום" (Lisbon, ן->ם): budget+baggage already in the first message (no re-ask, no confirm);
#     route Lisbon + Sintra day trip; lodging "יש לנו".
#  S2 "פירמצה" (Florence, נ->מ): multi-city Tuscany route (Florence + Siena) -> lodging accepted ->
#     lodging locations must follow the route's cities (not only the landing city); summary flight + route + lodging.
#  S3 "אתומה" (Athens, נ->מ), 2 adults + kids 6 and 9: kid-friendly pace; one change request on the route
#     ("יום 3 ← יום חופשי בחוף") must be applied, not re-asked; then approval.
#  S4 "בודפדט" (Budapest, ש->ד), solo, relative dates ("בעוד שבועיים, לחמישה לילות"): one date proposal,
#     no question on something already said; route; lodging "יש לי".
#  S5 "פראד" (Prague, ג->ד), 3 friends, everything flight-related in the first message: accessibility still
#     asked once; route with a nightlife style; car "לא".
_pids=""
reg ${P}1 ${PH}1 female
drive ${P}1 S1 "אני ובעלי לליסבום, 8 עד 13 בדצמבר, עד 1200 שקל לאדם, טרולי לכל אחד" '{"נגישות":"לא","ישיר":"עדיף ישירה","כבודה":"טרולי לכל אחד","תקציב":"עד 1200 שקל לאדם","מסלול":"כן","סגנון":"אוכל טוב, תצפיות וקצת היסטוריה, ויום אחד בסינטרה","קצב":"רגוע","אישור":"מעולה, מתאים לנו","לינה":"יש לנו","רכב":"לא"}' > ${P}_S1.log 2>&1 &
_pids="${_pids:-} $!"
reg ${P}2 ${PH}2 female
drive ${P}2 S2 "זוג לפירמצה, 15 עד 21 באפריל, ובא לנו גם כמה ימים בסיינה" '{"נגישות":"לא","כבודה":"מזוודה לכל אחד","תקציב":"עד 1500 שקל לאדם","ישיר":"לא משנה","מסלול":"כן","סגנון":"אמנות, יין ואוכל טוב, בלי לרוץ","קצב":"רגוע","אישור":"מושלם, מתאים לנו","לינה":"כן","סוג_לינה":"מלון","תקציב_לינה":"עד 700 שקל ללילה","חדרים":"חדר אחד","אזור":"במרכז, קרוב למה שבמסלול","רכב":"לא"}' > ${P}_S2.log 2>&1 &
_pids="${_pids:-} $!"
wait $_pids; _pids=""   # only our drivers - never the dry-run server running in the background
reg ${P}3 ${PH}3 male
drive ${P}3 S3 "אני, אשתי ושני הילדים, בן 6 ובת 9, לאתומה, 1 עד 7 באוגוסט" '{"נגישות":"לא","כבודה":"מזוודה לכל אחד","תקציב":"עד 1400 שקל לאדם","ישיר":"כן, ישירה","מסלול":"כן","סגנון":"ים, קצת היסטוריה שמתאימה לילדים, וגלידה","קצב":"רגוע, עם הפסקות","אישור":["אפשר להחליף את יום 3 ביום חופשי בחוף?","מעולה, מתאים לנו"],"לינה":"יש לנו","רכב":"לא"}' > ${P}_S3.log 2>&1 &
_pids="${_pids:-} $!"
reg ${P}4 ${PH}4 female
drive ${P}4 S4 "אני לבד לבודפדט, בעוד שבועיים, לחמישה לילות" '{"תאריכים":"כן, מתאים","נגישות":"לא","כבודה":"תיק יד בלבד","תקציב":"עד 900 שקל","ישיר":"לא חובה","מסלול":"כן","סגנון":"מרחצאות, אדריכלות ובתי קפה","קצב":"בינוני","אישור":"נהדר, מתאים לי","לינה":"יש לי","רכב":"לא"}' > ${P}_S4.log 2>&1 &
_pids="${_pids:-} $!"
wait $_pids; _pids=""   # only our drivers - never the dry-run server running in the background
reg ${P}5 ${PH}5 male
drive ${P}5 S5 "אני ושני חברים לפראד, 10 עד 14 בינואר, עד 1000 שקל לאחד, טרולי לכל אחד, לא חייב ישירה" '{"נגישות":"לא","כבודה":"טרולי לכל אחד","תקציב":"עד 1000 שקל לאחד","ישיר":"לא חייב","מסלול":"כן","סגנון":"בירה, חיי לילה והעיר העתיקה","קצב":"עמוס","אישור":"אחלה, מתאים לנו","לינה":"מסודר","רכב":"לא"}' > ${P}_S5.log 2>&1
# S6 return to an existing vacation (owner 23.10: "כשחוזרים לסשן על חופשה קיימת - בסיום הסשן שולחים סיכום של אותו
# סשן בלבד! ללא אפשרות לסריקה נוספת של מידע שכבר ניתן בעבר!"): a flight-only vacation is closed first (live: with
# "מאשרת" and the scan), then the customer comes back in the same chat for a route.
# Expected: (a) the second summary covers the route only - no flight block, no new "כתבי מאשרת" for the flight;
# (b) after approving it, no new /api/ariella/start-flight-search (live: search_${P}6.jsonl keeps exactly 1 entry;
# dry: no start-flight-search in chat_log blocked list after the return); the route is attached to the same vacation;
# (c) nothing already answered is asked again (accessibility, dates, travelers, baggage, budget).
reg ${P}6 ${PH}6 female
( drive ${P}6 S6a "אני ובעלי לרומא, 9 עד 14 במרץ, עד 1300 שקל לאדם, טרולי לכל אחד, עדיף ישירה" '{"נגישות":"לא","כבודה":"טרולי לכל אחד","תקציב":"עד 1300 שקל לאדם","ישיר":"עדיף ישירה","מסלול":"לא","לינה":"יש לנו","רכב":"לא"}'
  echo "---- return to the same vacation ----"
  drive ${P}6 S6b "רגע, בכל זאת נשמח למסלול לחופשה הזו ברומא" '{"מסלול":"כן","סגנון":"היסטוריה, אוכל איטלקי ושכונות יפות","קצב":"רגוע","אישור":"מעולה, מתאים לנו","לינה":"יש לנו","רכב":"לא"}'
  say ${P}6 "מאשרת" ) > ${P}_S6.log 2>&1
