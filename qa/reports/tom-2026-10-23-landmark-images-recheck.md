# בדיקה חוזרת PR #165: oholiav-landmark-images-fix — ❌ (ממצא 🔴 מהבדיקה הקודמת לא תוקן)

- **SHA:** `1cb3c20fbb84d4ef57b9303733d4461ec0ba78d9` (במקום 2ececd0)
- **main:** המשימה ציינה `8b2efaeb97a677d801a405b1ab01d09fb638fbd2`. בזמן הבדיקה origin/main היה ב-`be9b559b20cd45ac47e3a0155379775254497442` (‎#162 מוזג). הבדיקות רצו מול be9b559. המיזוג נקי מול שניהם.
- **ביצעה:** תום, 23.10.2026. בקשות GET/HEAD חינמיות ל-upload.wikimedia.org כדי לבדוק אם הקבצים קיימים. בלי בדיקות שעולות כסף ובלי האתר החי.

| בדיקה | תוצאה |
|---|---|
| מיזוג מול main, וגם מיזוג משותף עם #167 ו-#168 | ✅ נקי |
| `run_qa` על הענף ועל המיזוג | ✅ 0 כשלים |
| `qa_landmark_images_fix`, `qa_legal_images`, `qa_kiwi_affiliate_013a`, `qa_deal_card_en_baggage_overlap` | ✅ ALL PASS |
| מוטציה: הסרת `target`/`rel` מקישור הקרדיט | ✅ `qa_landmark_images_fix` נכשל |
| **12 כתובות `url_1200` עם `/1200px-`** | ❌ **עדיין קיימות** (BEG, BRU, EVN, KRK, LIS, LJU, OTP, PRG, TGD, VIE, WAW, ZRH). ZRH נבדק שוב עכשיו ומחזיר `400`. ר' ממצא 1 בדוח הקודם, `tom-2026-10-23-landmark-images.md` |
| קרדיט כקישור | ✅ `<a class="deal-image-credit" href="https://commons.wikimedia.org/wiki/File:…" target="_blank" rel="noopener">`. לכל 29 הקרדיטים יש `page` ב-commons.wikimedia.org |
| ה-CSS לא הופך את הקישור לכפתור | ✅ אין כלל `.deal-visual a` או `.ariella-deal-card a` כללי ב-site.css, ב-mobile-deals-header.css או ב-mobile-deal-card-fixes.css. בצילומים עם שלושת קבצי ה-CSS של העמוד, הקרדיט נראה כמו קודם: טקסט קטן, לבן ובלי קו תחתון (`img/landmark2-BUD-credit-link-he-375.png`, `…-en-1200.png`) |
| `trip["image_url"]` לא מוצג | ✅ אף template לא משתמש בו, ואין צרכן אחר בקוד. 🟡 הוא עדיין מחושב ב-`public_site.py:3332-3354`, כולל הכביש המדברי `photo-1500530855697`. אין לזה השפעה, אבל זה קוד מת שכדאי לנקות |
| אין דריסה ב-`_localize_offer_airports` | ✅ אין. ℹ️ הדריסה ב-`database.py:1183-1185` (על `payload` ב-`recent_offers`) עדיין קיימת, והיא קוד מת (ר' הדוח הקודם) |

## למה ❌
הבעיה המרכזית מהבדיקה הקודמת לא תוקנה: 12 התמונות שה-PR בא לתקן לא נטענות (Wikimedia מחזיר 400 על thumbnail ברוחב 1200). בכרטיס מוצגת כנף המטוס, ועכשיו **קישור** הקרדיט מוביל לדף של תמונה שלא מוצגת (`img/landmark2-LIS-broken-he-375.png`). התיקון לא השתנה: `1200px-` → `1280px-` ב-12 הרשומות, ותנאי offline בבדיקה על רוחב ה-thumbnail.

## הערות לא חוסמות (נשארו)
- 🟡 כיוון הטקסט בקרדיט העברי: הפסיק מוצג במקום הלא נכון (",Dguendel").
- 🟡 `(credit.en or credit.he)` יציג עברית ב-en אם יחסר נוסח אנגלי.
