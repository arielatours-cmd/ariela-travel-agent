# בדיקת PR #165: oholiav-landmark-images-fix — ❌ (ממצא 🔴: 12 התמונות החלופיות לא נטענות)

- **SHA:** `2ececd0a0e0cf40cae266383e0eb052ff63111b6`
- **main:** `02e55370e25503363ceada090a2e8cbaa2f77bf4`
- **קבצים:** `database.py`, `static/img/destinations/_default.webp` (חדש, WebP 1200×794), `static/img/destinations/landmarks.json` (חדש), `templates/_deal_card.html`, `tools/qa_landmark_images_fix.py` (חדש), `tools/qa_legal_images.py`
- **ביצעה:** תום, 23.10.2026, ב-worktree נפרד, בלי בדיקות שעולות כסף ובלי האתר החי. כדי לבדוק אם קבצי התמונות קיימים שלחתי בקשות HEAD/GET חינמיות ל-upload.wikimedia.org (29 כתובות, לאט, כדי לא לקבל 429).

| # | בדיקה | תוצאה |
|---|---|---|
| 1 | `landmarks.json`: JSON תקין, בלי קודים כפולים | ✅ נבדק עם `object_pairs_hook`. 30 רשומות: 17 `verified_existing`, 12 `replacement`, ו-LCA `keep_current` |
| 1 | לכל רשומה יש רישיון, מקור (`page`) ואמן, ושם הקובץ ב-URL תואם ל-`title` | ✅ (חוץ מ-LCA, שנשארה בלי שינוי) |
| 1 | **הכתובת קיימת** | ❌ **כל 12 ה-`replacement` מחזירים HTTP 400.** ר' ממצא 1. מתוך 17 ה-`verified_existing`: 11 מחזירים 200/206, ו-6 קיבלו 429 (הגבלת קצב של Wikimedia, לא נבדקו עד הסוף) |
| 1 | התאמה ליעד (דגימה ידנית) | ✅ BUD (פרלמנט בודפשט), LIS (מגדל בלם), ZRH (ציריך מגשר Quaibrücke), PRG (גשר קארל), KRK (ואוול מהוויסלה), OTP ("Bucarest"). 🟡 ל-TGD הכותרת היא "Moj grad - panoramio" ואי אפשר לאמת ממנה שזו פודגוריצה |
| 2 | קרדיט רק כשהרישיון דורש | ✅ ל-29 קודים יש קרדיט (26 + CIA, BGY ו-LIN שמשתמשים באותה תמונה). PD (ATH, TBS) ו-CC0 (MUC) בלי קרדיט. הנוסח כולל את האמן ואת הרישיון |
| 2 | אין עברית ב-en | ✅ לכל 29 יש נוסח אנגלי `Photo: … via Wikimedia Commons`. 🟡 ב-template יש `(credit.en or credit.he)`: אם יחסר נוסח אנגלי, יוצג הנוסח העברי |
| 3 | יעד בלי תמונה מקבל את התמונה הכללית | ✅ HFA: כנף מטוס, בלי קרדיט (`img/landmark-HFA-generic-he-375.png`) |
| 3 | תמונה קיימת ליעד אחר לא נשברה | ✅ 32 כתובות הוחלפו בכוונה. LCA לא השתנה. לא נוספו ולא הוסרו קודים. ❌ אבל 12 מהן לא נטענות (ממצא 1) |
| 4 | מיזוג #165 + #162 (07e6e1d) | ✅ בלי קונפליקט ב-`_deal_card.html` (שני hunks נפרדים). run_qa ו-5 בדיקות tools עוברים על main+#165+#162 |
| (א) | הדריסה של `destination_image_url` | ℹ️ ב-#165 היא קיימת ב-`database.py:1181-1183`, בתוך `recent_offers`, על `payload`. זה **קוד מת**: התוצאה נבנית מהמילון ב-`:1410`, שכבר לוקח `DESTINATION_LANDMARK_IMAGES` או את התמונה הכללית, ו-`payload` לא מוחזר. ב-main יש רק מקום אחד שקובע `destination_image_url` (`database.py:1378`), וכל הכרטיסים האמיתיים עוברים דרך `recent_offers`. לכן **אף כרטיס טיסה לא מקבל תמונה אחרת** בגלל הדריסה, לא ב-#165 ולא ב-#166 (`_localize_offer_airports`). הדריסה ב-#166 משפיעה רק על `_qa_fixture_offers` |
| (ב) | כפילות מול #166 | ✅ אין קונפליקט טקסטואלי בין #165 ל-#166, כי הם בקבצים שונים. ⚠️ ל-#166 עצמו יש קונפליקט מול main ב-`templates/account.html`, לא קשור ל-#165 |
| 5 | `run_qa` על הענף, על המיזוג ועל המיזוג עם #162 | ✅ 0 כשלים |
| 5 | `qa_landmark_images_fix` ו-`qa_legal_images` (וגם kiwi_013a, deal_card_en_baggage_overlap, affiliate_link_html_guard) | ✅ ALL PASS |
| 5 | מוטציה: הסרת בלוק הקרדיט מ-`_deal_card.html` | ✅ `qa_landmark_images_fix` נכשל (2 כשלים, he+en) |
| 6 | צילומים ב-375px וב-1200px | ✅ קרדיט על BUD (he/en), ATH בלי קרדיט, HFA כללית. ❌ LIS: קרדיט על כנף המטוס (ממצא 1) |
| 6 | `<a>` חדש שה-CSS הופך לכפתור | ✅ אין `<a>` חדש. הקרדיט הוא `<small>` עם style מקומי, ולא נתפס ב-`.deal-price-box a` |

## ממצא 1 — 🔴 כל 12 התמונות החלופיות מחזירות 400, ובכרטיס מוצג קרדיט של צלם על התמונה הכללית שלנו
- **מיקום:** `static/img/destinations/landmarks.json`, השדה `url_1200` של LIS, VIE, ZRH, BRU, WAW, EVN, BEG, TGD, LJU, PRG, OTP ו-KRK.
- **מה קורה:** הכתובות הן thumbnails ברוחב `1200px-…`. Wikimedia מחזיר עליהן `HTTP 400 — "Use thumbnail sizes listed on https://w.wiki/GHai"`, כלומר 1200 הוא לא רוחב מותר. ה-17 הקיימות משתמשות ב-`1280px-` (או בקובץ המקורי) ועובדות. בבדיקה, החלפה ל-`1280px-` החזירה 206 ב-VIE, ZRH, WAW, EVN ו-KRK, והשאר קיבלו 429.
- **התוצאה בכרטיס:** הדפדפן לא מצליח לטעון את התמונה ומציג את שכבת הגיבוי (כנף המטוס, CC0). **הקרדיט נשאר** ("צילום: Berthold Werner / CC BY-SA 4.0…"), כי התנאי ב-template הוא `stable_image == offer.destination_image_url`, והוא לא יודע שהטעינה נכשלה. כך מופיע קרדיט שגוי על תמונה שלנו, בדיוק ב-12 היעדים שה-PR בא לתקן. צילומים: `img/landmark-LIS-credit-broken-he-375.png`, `…-1200.png`.
- **שחזור:** `curl -sI -A "x" "https://upload.wikimedia.org/wikipedia/commons/thumb/9/9e/Lisbon_Torre_de_Bel%C3%A9m_BW_2018-10-03_16-33-21.jpg/1200px-Lisbon_Torre_de_Bel%C3%A9m_BW_2018-10-03_16-33-21.jpg"` מחזיר `400`.
- **למה הבדיקות לא תפסו:** הן לא בודקות רשת. בדיקה offline אפשרית: כל `url_1200` הוא `…/thumb/…/<W>px-…` כש-W ברשימת הגדלים המותרים (למשל 1280), או קובץ מקורי.
- **הצעת תיקון (לעידו או לאופק):** להחליף `1200px-` ב-`1280px-` ב-12 הרשומות, ולהוסיף לבדיקה תנאי על הרוחב. כדאי לבדוק שוב את 6 הכתובות שקיבלו 429 (ATH, SOF, LHR, SKP, BKK, וב-1280 גם LIS, BRU, BEG, TGD, LJU, PRG, OTP) מרשת שלא מוגבלת.

## הערות לא חוסמות
1. 🟡 **כיוון טקסט בקרדיט העברי:** "צילום: Dguendel / CC BY 4.0, דרך Wikimedia Commons" מוצג ב-RTL עם הפסיק במקום הלא נכון (`,Dguendel`). אפשר לעטוף את החלק הלטיני ב-`<bdi>`. ר' `img/landmark-BUD-credit-he-375.png`.
2. 🟡 `(credit.en or credit.he)`: אם יחסר נוסח אנגלי, תוצג עברית ב-en. היום אין מקרה כזה.
3. 🟡 שכבת הגיבוי השלישית ב-pools היא עדיין צילום עיר מ-Unsplash (`photo-1477959858617`), וגם הוא עלול להיראות כמו היעד, כמו הכביש המדברי שהוחלף.
4. ℹ️ `GENERIC_DESTINATION_IMAGE` יחסי (`/static/...`) כש-`PUBLIC_BASE_URL` לא מוגדר. באתר זה עובד. בוואטסאפ צריך את המשתנה, כמו שכתוב בהערה בקוד.
5. ℹ️ מגבלה של הצילומים: Chromium בסביבה לא יוצא לרשת, אז התמונות (BUD, ATH) הורדו עם curl והוחלפו בקבצים מקומיים. LIS הוחלף בקובץ שלא קיים, כדי לדמות את ה-400. חפיפות בפריסת הכרטיס ב-1200px באנגלית נובעות מהמעטפת המינימלית שלי (בלי CSS העמוד), ולא מה-PR.
