# בדיקת PR #168: oholiav-booking-links-no-empty (VIP sitemap) — ✅

- **SHA:** `498767ce3bc9b56665e0ac14bc8610f9dc23528a`
- **main:** be9b559 (המשימה ציינה 8b2efae, ו-#168 מבוסס עליו ישירות). המיזוג נקי מול שניהם.
- **קבצים:** `public_site.py` (`_vipcars_page` וה-fallback ב-`_car_partner_url`), `static/vipcars_locations.json` (+48 שורות: `_pages_note` ו-`pages`), `tools/qa_vipcars_locations_ofek.py`
- **ביצעה:** תום, 23.10.2026. GET חינמי אחד ל-`https://www.vipcars.com/location.xml` כדי לבדוק את המקור. בלי לחיצות באתר החי. ערכי `sid` מוסתרים.

| בדיקה | תוצאה |
|---|---|
| JSON תקין, בלי מפתחות כפולים | ✅ (`object_pairs_hook`) |
| בלי URL כפול ב-`pages` ובלי `location` כפול ב-`locations` | ✅ |
| 45 דפים, ואף אחד מהם לא לשדה שכבר יש לו מזהים | ✅ אין חפיפה בין `pages` ל-`locations` |
| כל אחד מה-45 נמצא במקור | ✅ כל 45 ה-URLים קיימים ב-`location.xml` של VIP Cars (17,018 כתובות, נמשך עכשיו). הם גם זהים ל-`unverified.*.vipcars_page` של אופק ב-8dc085c, ואין דף של אופק שחסר |
| התאמה בין IATA לדף | ✅ כל 45 תואמים לפי ה-slug (למשל GVA → geneva-airport, LGW → gatwick, STN → stansted, JNB → o-r-tambo) |
| 132 השדות הקיימים לא השתנו | ✅ `locations` זהה ל-main |
| deep link לשדה ישן (ZRH) | ✅ חיפוש מלא (153/2125/720 ותאריכים), זהה ל-main תו-בתו |
| קישור לשדה חדש (GVA, CIA) | ✅ דף השדה של VIP Cars בתוך `url=` של CJ, ו-`sid` נשמר. ב-main זה היה דף הבית. אין בו תאריכים, וזה מכוון |
| שדה בלי מזהים ובלי דף (HFA) | ✅ דף הבית, זהה ל-main |
| `run_qa` על הענף ועל המיזוג | ✅ 0 כשלים |
| `qa_vipcars_locations_ofek` ו-`qa_car_partner_vipcars` | ✅ ALL PASS |
| מוטציה: דף GVA הוחלף ב-URL בנוי (`/search/?city=geneva`) | ✅ 2 בדיקות נכשלות |

## הערות לא חוסמות
- ℹ️ איסוף בשדה ממופה והחזרה בשדה שיש לו רק דף (ZRH → GVA) מוביל לדף הבית, כמו ב-main. במקרה ההפוך (GVA → ZRH) מתקבל הדף של GVA. זה עקבי: תמיד הולכים לשדה האיסוף.
