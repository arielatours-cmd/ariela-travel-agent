# בדיקת PRים לקישורי הזמנה: #163 (לינה) ✅, #164 (רכב VIP) ✅

- **main:** `02e55370e25503363ceada090a2e8cbaa2f77bf4`
- **#163:** `0d75ce2d8b7804980fa52afe1fadfce3dae6ae4a` (oholiav-booking-links-lodging): `public_site.py`, `tools/qa_booking_links_stay.py`
- **#164:** `857dc9e1faf5490e76397899b93969952fdcf38b` (oholiav-vipcars-locations): `static/vipcars_locations.json`, `tools/qa_car_partner_vipcars.py`, `tools/qa_vipcars_locations_ofek.py`
- **ביצעה:** תום, 23.10.2026, ב-worktree נפרד, בלי רשת חיצונית, בלי האתר החי ובלי בדיקות שעולות כסף. בקישורים בדוח הערכים של `aid`, `sid`, `tid` ו-`aff` מוסתרים (`***`). קישור CJ בבדיקות הוא דמה (`click-111-222`).

## משותף לשניהם
| בדיקה | #163 | #164 |
|---|---|---|
| `git merge-tree` מול main | ✅ נקי | ✅ נקי |
| `run_qa` על הענף | ✅ 0 כשלים | ✅ 0 כשלים |
| `run_qa` על המיזוג מול main | ✅ 0 כשלים | ✅ 0 כשלים |
| מיזוג של שני ה-PRים יחד על main + run_qa + שלוש הבדיקות החדשות | ✅ | ✅ |
| בדיקה חדשה | ✅ `qa_booking_links_stay`: ALL PASS | ✅ `qa_vipcars_locations_ofek` ו-`qa_car_partner_vipcars`: ALL PASS |
| בדיקות קיימות (lodging_* ×6, partner_cards_affiliate_label, car_partner_vipcars) | ✅ | ✅ |
| מוטציה | ✅ מחיקת שורת `age` ב-`_booking_com_party_params` מפילה 3 בדיקות | ✅ מחיקת ZRH מה-JSON מפילה את בדיקת ה-132 (והבדיקה של ZRH קורסת ב-KeyError) |

## #163 — לינה ✅
כל הבדיקות רצו על המיזוג. CJ מוגדר כדמה. `LODGING_AFFILIATE_LINK` ריק, כמו היום בייצור.

### 1. כרטיס השותף (`_lodging_partner_url`): פרמטר `age` לכל ילד
| מקרה (answers) | מה נשלח (בלי `ss`) |
|---|---|
| 2 מבוגרים, 2 ילדים, `age_groups=[4,12]` | `checkin, checkout, group_adults=2, group_children=2, age=4, age=12, no_rooms=1` ✅ בסדר הנכון |
| 0 ילדים | `group_adults=2, group_children=0, no_rooms=1`, בלי `age` ✅ |
| 2 ילדים, גיל אחד ידוע `[7]` | `group_children=2, age=7`. **הילד שגילו חסר נספר, אבל לא נשלח לו `age`**. אין ניחוש, אבל ב-Booking הספירה והגילים לא יתאימו, ו-Booking יבקש מהלקוח את הגיל החסר |
| טופס האתר: `age_groups=["children"]` (קבוצה, לא גיל) | `group_children=1`, **בלי `age` בכלל** (ר' הערה 🟡 1) |
| גילים כמחרוזות `["5","9"]` | `age=5, age=9` ✅ |
| יותר גילים מילדים (`children=1, [3,8]`) | `age=3` בלבד ✅ |
| אין `adults` ואין `children` | `group_adults=2, group_children=0`. ברירת המחדל היא 2 מבוגרים, כמו ב-main |

### 2. קישורי מלונות (`_wrap_booking_com_hotel_links`)
- `/hotel/de/x.html` מקבל `checkin`, `checkout`, `group_adults`, `group_children`, `age` (אחד לכל ילד) ו-`no_rooms` ✅
- תאריכים לפי מקטע (`segment_dates="2026-11-12 – 2026-11-14"`): נשלחים התאריכים של המקטע ולא של הטיול ✅
- **קידוד כפול:** `https://www.anrdoezrs.net/click-111-222?url=https%3A%2F%2Fwww.booking.com%2Fhotel%2Fde%2Fx.html%3Flang%3Dhe%26checkin%3D2026-11-10%26…%26age%3D4%26age%3D12%26no_rooms%3D1&sid=***` ✅. ה-`&` וה-`=` של Booking מקודדים בתוך `url=`, והפרמטרים של CJ (`sid`) נשארים מחוץ לו.

### 3. בלי כפילויות, וקישור שאינו Booking לא נפגע
- קישור עם תאריכים ונוסעים ישנים (`checkin=2020-01-01`, `group_adults=1`, `age=3`, `no_rooms=3`, `req_adults=5`) וגם `aid` ו-`label`: כל ערכי השהות הישנים הוחלפו ולא הוכפלו. `aid` ו-`label` הוסרו. `lang=he` נשמר ✅
- `checkin` שמופיע פעמיים: נשאר פעם אחת, עם הערך מהחופשה ✅. פרמטר אחר (`srpvid=a b+c`) נשמר, מקודד מחדש כ-`%20`, וזה שקול ✅
- `https://hotel-own.example/book?checkin=1&x=1` לא השתנה ולא נעטף ✅

### 4. בלי תאריכים או נוסעים
- **מלון בלי תאריכים:** `checkin` ו-`checkout` לא נשלחים בכלל ✅. נשלחים `group_adults=2, group_children=0, no_rooms=1`.
- **כרטיס שותף בלי תאריכים:** ❗ נשלחים `checkin=` ו-`checkout=` **ריקים** (ר' הערה 🟡 2). זה קיים ככה גם ב-main ולא נגרם ב-PR.
- **`group_children=0`** נשלח תמיד, גם כשאין ילדים. זה אפס מפורש. Booking מתייחס לזה כברירת המחדל, ואין לזה השפעה, אבל ביקשת לציין.
- כשאין מבוגרים בתשובות נשלח `group_adults=2` (ברירת מחדל, לא ריק).

### 5. `no_rooms`: מה נשלח בפועל
`no_rooms` מגיע מ-`answers["lodging_rooms"]` (מהחילוץ, `lodging.details.rooms`). כשהוא ריק, null או 0 נשלח `no_rooms=1`. `lodging_rooms=2` שולח `no_rooms=2`. ההחלטה נשארת אצל בצלאל.

### הערות לא חוסמות ל-#163
1. 🟡 **טיולים מטופס האתר לא מקבלים `age` אף פעם.** בטופס `age_groups` הוא רשימת קבוצות (`infants`, `children`, `teens`) ולא גילים, ולכן `int()` נכשל והכול מסונן. Booking יפתח בלי גילי ילדים, ולא יציג מחיר לחדר עם ילד, וזו בדיוק הבעיה שה-PR בא לפתור. בטיולים מהצ'אט (`child_ages` מספריים) זה עובד.
2. 🟡 **כרטיס שותף בלי תאריכים שולח `checkin=&checkout=` ריקים** (`_lodging_partner_url`). זה קיים כבר ב-main. אפשר לסנן כמו שה-PR עשה בקישורי המלונות.
3. ℹ️ קישורים שנשמרו לפני ה-PR עוברים ברינדור דרך `_wrap_booking_com_hotel_links(offers, trip_id)` בלי `answers` (`public_site.py:3369`), ולכן לא יקבלו תאריכים ונוסעים עד חיפוש חדש. זו התנהגות מכוונת, ויש עליה בדיקה.
4. ℹ️ במסלול `LODGING_AFFILIATE_LINK` + `LODGING_SEARCH_URL_TEMPLATE` (כבוי היום) לא נוספו `age`.

## #164 — רכב VIP ✅
### 1. הקובץ `static/vipcars_locations.json`
- JSON תקין. אין מפתחות כפולים (נבדק עם `object_pairs_hook`, גם בקובץ וגם בטיוטה). ✅
- **132 שדות**, והם בדיוק 132 ה-`airports` ב-`product/data/vipcars_locations_draft.json` של אופק (`8dc085c`): אין שדה עודף, אין שדה חסר, ואין אף הבדל ב-country/city/location. רשימת ה-`unverified` לא נכללה. ✅
- כל המפתחות הם קודי IATA בני 3 אותיות. כל המזהים מספרים שלמים. אין שני שדות עם אותו `location`. ✅
- ZRH: `153/2125/720` "Zurich Airport (ZRH)" ✅

### 2. ZRH מקבל deep link
`url=` של CJ מכיל חיפוש VIP Cars עם `pickup_location=720`, `dropoff_location=720`, `pickup_date=2027-03-01`, `dropoff_date=2027-03-08` ו-`pickup_time=10:00`, ולא את דף הבית ✅ (ב-main: דף הבית).

### 3. שדה בלי מיפוי ו-LIS
- HFA ו-GVA: דף הבית של השותף, בלי `url=`. הפלט זהה ל-main ✅
- ZRH עם החזרה ב-HFA (שדה לא ממופה): דף הבית, בלי מילוי חלקי. זהה ל-main ✅
- LIS: הקישור זהה תו-בתו ל-main (`777/777`, אותם תאריכים) ✅

### הערות לא חוסמות ל-#164
1. 🟡 ZRH (וכל שדה ממופה) בלי תאריכים בחופשה: נבנה deep link עם `pickup_date=` ו-`dropoff_date=` ריקים. זה קיים כבר ב-main עבור LIS, אבל עכשיו זה חל על 132 שדות. השאלה אם VIP Cars מציג חיפוש או שגיאה לא נבדקה, כי אין רשת חיצונית.
