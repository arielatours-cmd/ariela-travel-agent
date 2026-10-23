# בדיקת PR #170: oholiav-attraction-image-credit — ❌ (ממצא 🟠: "יוצר ידוע" לא נאכף, וקרדיט שגוי בנתונים אמיתיים)

- **SHA:** `a2863c2f1b4e0cdc1a68939e8aa8de29b4093804`
- **main:** `448ac84d26b4b005c8924ee01f6c2f1f26128813`. המיזוג נקי.
- **קבצים:** `itinerary_cards.py` (`_image_license`, `_wiki_image_licensed`), `templates/account.html`, `tools/qa_attraction_image_credit.py`
- **ביצעה:** תום, 23.10.2026. בלי בדיקות שעולות כסף ובלי האתר החי. ברשת: קריאה בלבד, בקשות בודדות.

## 1. קוד
- **ה-API:** שתי הפונקציות (הישנה `_wiki_image` והחדשה) קוראות ל-`https://en.wikipedia.org/w/api.php`. החדשה עושה 2 קריאות: חיפוש `generator=search` עם `pageimages` ב-`pithumbsize=480`, ואחריו `imageinfo` עם `extmetadata` (`LicenseShortName`, `Artist`) לקובץ שנבחר.
- **מה מותר:** `^(public domain|pd\b|cc0|cc by(-sa)?…)` (בלי רגישות לאותיות). נדחה אם יש `\b(NC|ND)\b` (עם רגישות לאותיות), או אם `descriptionurl` לא ב-commons.wikimedia.org, או אם האמן או הרישיון ריקים.
- **בדיקות קצה עם API מדומה (21 מקרים):**

| רישיון / יוצר | תוצאה |
|---|---|
| CC BY-SA 4.0, CC BY 2.0, CC0, Public domain, PD-US | ✅ מותר |
| CC BY-NC-SA 2.0, CC BY-ND 4.0, CC BY-NC 3.0 | ✅ נדחה |
| GFDL, "Attribution", CC-BY-SA-4.0 (במקפים), רישיון ריק או חסר | ✅ נדחה (שמרני) |
| יוצר ריק או חסר | ✅ נדחה |
| קובץ מקומי של enwiki (fair use) | ✅ נדחה |
| יוצר שהוא HTML (`<a href=…>Jane</a>`) | ✅ "Jane" |
| `<script>x</script>` | ✅ "x" (נשאר טקסט בלבד, ו-Jinja מבצע escape) |
| **`<span>Anonymous</span><span style="display:none">Unknown author</span>`** | ❌ **"AnonymousUnknown author"**, מותר ומוצג (ממצא 1) |
| **"Unknown author" (PD)** | ❌ **מותר**, למרות שהיוצר לא ידוע (ממצא 1) |
| 🟡 `cc by-nc 2.0` (אותיות קטנות) | ❌ מותר, כי בדיקת NC/ND רגישה לאותיות. ב-Commons השם בדרך כלל באותיות גדולות, ולכן הסיכון נמוך |
| 🟡 `Tom &amp; Jerry` | מוצג "Tom &amp;amp; Jerry" (בלי `html.unescape`) |
| timeout, JSON לא תקין, שם או כותרת ריקים | ✅ `("", None)`: אין תמונה ואין קריסה |

- ℹ️ **ביצועים:** 2 קריאות רצופות עם timeout של 6 שניות לכל אטרקציה (קודם הייתה קריאה אחת). במקרה הגרוע זה 12 שניות לכרטיס בזמן בניית המסלול.

## 2. API אמיתי — חלקי, כי הרשת חסומה
- **`en.wikipedia.org` חסום בסביבה הזו** (proxy: `CONNECT tunnel failed, response 403`, ו-requests מחזיר ProxyError). אותו דבר עם it.wikipedia.org, wikidata ו-api.wikimedia.org. לכן **לא הצלחתי להריץ את `_wiki_image_licensed` מקצה לקצה** על 5 האטרקציות.
- **מה כן נבדק דרך `commons.wikimedia.org/w/api.php`** (נגיש, עם 429 לסירוגין): הרצתי את `_image_license` עצמה (עם `requests.get` שמופנה ל-Commons) על קבצים שנמצאו בחיפוש ב-Commons:
  - גלריית האקדמיה: `Accademia di Firenze, veduta sul cortile…01.JPG` → `Sailko / CC BY 3.0`, הדף ב-commons נכון ✅
  - אופיצי: `Uffizi Gallery - Daughter of Niobe bent by terror.jpg` → `Petar Milošević / CC BY-SA 4.0` ✅
  - פונטה וקיו: `Ponte Vecchio, Florence.jpg` → PD. Artist מגיע כ-`<span>Anonymous</span><span style="display:none">Unknown author</span>` ומוצג כ-**"AnonymousUnknown author"** ❌
  - פיאצה דל קמפו ומגדל ג'וטו: לא נבדקו (429 מתמשך).
  - ℹ️ אלה לא בהכרח הקבצים ש-enwiki היה בוחר כ-pageimage.
- **רוחב ה-thumbnail (הבעיה של #165):** ✅ `pithumbsize=480` ו-`iiurlwidth=480` מחזירים מה-API כתובת **`/500px-`**, כלומר רוחב סטנדרטי ב-`thumb.wikimedia.org`. כתובת `480px-` ידנית מחזירה 400, אבל ה-API לא בונה כזו. את הטעינה עצמה לא הצלחתי לאמת: thumb.wikimedia.org חסום, ו-upload.wikimedia.org החזיר 429.

## 3. account.html
| בדיקה | תוצאה |
|---|---|
| תמונה רק עם קרדיט | ✅ `{% if item.image and item.image_credit %}`. כרטיס ישן בלי `image_credit` מוצג בלי תמונה |
| קרדיט he/en | ✅ "צילום: … / CC BY-SA 4.0, דרך Wikimedia Commons" / "Photo: … via Wikimedia Commons" |
| קישור | ✅ `<a class="itin-card-credit" href="https://commons.wikimedia.org/wiki/File:…" target="_blank" rel="noopener">` |
| ה-CSS לא הופך אותו לכפתור | ✅ `.itin-card-credit` הוא טקסט קטן, ואין כלל `a` כללי שתופס אותו. צילומים: `img/attr-credit-itin-he-375.png`, `…-en-1200.png` |
| **bdi לשם היוצר** | ❌ אין `<bdi>`. בעברית הפסיק מוצג במקום הלא נכון (",Petar Milošević"), כמו ב-#165 |
| **alt** | 🟡 `alt="{{ name_he }}"` גם ב-en, כלומר עברית בעמוד האנגלי (לא נראה על המסך, אבל קורא מסך יקריא אותו). זה בדיוק מה ש-ron-itin-cards-en מתקן (ר' 4) |

## 4. קונפליקט עם ron-itin-cards-en (`bf8ac89f4069baffac14470dc629251e1934a033`)
- **שים לב:** ron-itin-cards-en **מתנגש בעצמו מול main** (`itinerary_cards.py`, `account.html`), בלי קשר ל-#170. הוא מבוסס על גרסה לפני #148: הוא מחזיר את `"price"` בטקסט חופשי במקום `price_info`, מציג `🎟 {{ item_price }}` ו-"Entry price:", ומשתמש ב-`booking_url` ישירות במקום `attraction_tickets_url`. **פתרון שבוחר בצד של רון יחזיר את הבעיות שתנאי דין ב-#148 תיקנו** (מחיר לא מאומת וקישור למשווק). לכן רון צריך rebase על main.
- **הקונפליקט שקשור ל-#170 (שורת ה-`<img>`)**, הצעת פתרון:
  ```
  {% set item_name = (item.get('name_catalog') or item.get('name_en') or item.get('name_he')|no_hebrew) if site_lang == 'en' else item.get('name_he') %}
  {% if item.get('image') and item.get('image_credit') %}<img class="itin-card-img" src="{{ item.get('image') }}" alt="{{ item_name }}" loading="lazy">{% endif %}
  ```
  כלומר: ה-alt באנגלית של רון, ביחד עם התנאי של #170 (תמונה רק עם קרדיט). שורת הקרדיט של #170 נשארת בלי שינוי.

## 5. run_qa, בדיקות ומוטציה
| בדיקה | תוצאה |
|---|---|
| `run_qa` על הענף ועל המיזוג | ✅ 0 כשלים |
| `qa_attraction_image_credit`, `qa_attraction_price_display`, `qa_attraction_prices`, `qa_legal_images` | ✅ ALL PASS |
| מוטציה: הסרת בדיקת NC/ND | ✅ 2 בדיקות נכשלות (CC BY-NC-SA 2.0, CC BY-ND 3.0) |

## ממצא 1 — 🟠 "יוצר ידוע" לא נאכף, וקרדיט שגוי על קובץ אמיתי
- **מיקום:** `itinerary_cards.py`, `_image_license`: `artist = re.sub(r"<[^>]+>", "", …)`
- **מה קורה:** ב-Commons, השדה `Artist` של יוצר לא ידוע מגיע כ-`<span lang="en">Anonymous</span><span style="display:none">Unknown author</span>`. הסרת התגים מדביקה את שני הטקסטים, והתוצאה "AnonymousUnknown author". זה נחשב "יוצר", והתמונה מוצגת עם הקרדיט "צילום: AnonymousUnknown author / Public domain". גם "Unknown author" לבד מתקבל. לפי ההגדרה של ה-PR ("רק עם יוצר ידוע") צריך לדחות את זה. ב-PD אין חובת קרדיט, אבל ב-CC BY עם יוצר לא ידוע אי אפשר לתת קרדיט כמו שצריך.
- **שחזור:** הקובץ האמיתי `File:Ponte Vecchio, Florence.jpg` ב-Commons. ראו גם את המקרה המדומה בטבלה בסעיף 1.
- **הצעת תיקון:** להסיר קודם רכיבים עם `display:none`, להריץ `html.unescape` ולצמצם רווחים, ואז לדחות "Unknown author", "Anonymous" ו-"unknown" (בלי רגישות לאותיות). כדאי גם לעטוף את שם היוצר ב-`<bdi>` בתבנית, ולהשוות NC/ND בלי רגישות לאותיות.

---

## השלמה לסעיף 2 (אחרי הטיפ של שקד: User-Agent והפסקות של 4–12 שניות)
- `en.wikipedia.org` **עדיין חסום** (proxy 403, לא 429), ולכן הריצה מקצה לקצה של `_wiki_image_licensed` עדיין לא אפשרית בסביבה הזו.
- דרך commons API, `_image_license` על קבצים נוספים:
  - פיאצה דל קמפו: `Piazza del Campo 2014 01.jpg` → `Perituss / CC0` ✅. thumbnail `/500px-`. טעינה דרך upload.wikimedia.org: **206** ✅
  - מגדל ג'וטו: `CampanileGiotto-01.jpg` → `Thermos / CC BY-SA 2.5` ✅. `/500px-`. טעינה: **206** ✅
  - פונטה וקיו (קובץ אחר): `Ponte Vecchio at dusk 1.JPG` → `Martin Falbisoner / CC BY-SA 3.0` ✅. `/500px-`. טעינה: **206** ✅
- **סיכום:** על כל 5 האטרקציות בדקתי את הרישיון, היוצר והדף בקבצים אמיתיים. הקובץ היחיד שנכשל הוא `Ponte Vecchio, Florence.jpg` (ממצא 1). ה-thumbnails שה-API מחזיר הם ברוחב 500 ונטענים (206). ההחלטה ❌ לא משתנה, בגלל ממצא 1.
