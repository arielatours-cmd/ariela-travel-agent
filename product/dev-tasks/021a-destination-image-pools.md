# משימת פיתוח 021א: מאגר תמונות מקומי לכל יעד בדילים

**תוכנית:** [021](../plans/021-destination-image-pools.md). אושרה ב-22.10.2026 על ידי בעלת העסק. דין: IMG-1.
**תזמון:** אחרי 020. התמונות עצמן מגיעות מאופק כעבודת נתונים, ברגע שהרשת מאפשרת.

## 1. נתונים (אופק)
- **קבצים:** `static/img/destinations/<IATA>/<n>.webp`. בשלב א, 4 תמונות לכל אחד מ-37 יעדי הדילים (`DESTINATIONS` ב-config.py). רוחב 1200 פיקסלים, WebP באיכות 80, עד כ-200KB.
- **מטא-דאטה:** `data/destination_images.json`.
```json
{"code":"LIS","file":"static/img/destinations/LIS/1.webp","source":"unsplash|pexels|wikimedia",
 "source_page":"<URL של דף התמונה>","photographer":"...","license":"Unsplash License|Pexels License|CC BY-SA 4.0|...",
 "credit_required":false,"credit_text":null,"downloaded_at":"YYYY-MM-DD"}
```
- **תנאי דין (IMG-1):**
  - בלי Unsplash+.
  - בלי אנשים מזוהים ובלי לוגו בולט.
  - הורדה ידנית בלבד.
  - Wikimedia רק ברישיון PD, CC0, CC BY או CC BY-SA, עם `credit_text` בפורמט של דין.
- **ברירות מחדל:**
  - `static/img/destinations/_country/<CC>.webp`: תמונה אחת למדינה.
  - `static/img/destinations/_default.webp`: תמונה כללית.

## 2. קוד (בצלאל או עידו)
1. **טעינת הקטלוג:** `data/destination_images.json` נטען פעם אחת ונשמר בזיכרון, ממופה לפי קוד.
2. **בחירת תמונה לדיל** (`recent_offers`, database.py:1357):
   - `destination_image_url`: בחירה **אקראית** מהמאגר של הקוד.
   - `destination_image_pool`: כל המאגר.
3. **שדה שני של עיר:** ORY ← CDG, LGW/LTN/STN ← LHR, LGA/EWR ← JFK, CIA ← FCO, BGY/LIN ← MXP. אחרי 020 זה נלקח מ-`same_city_codes` בקטלוג המורחב.
4. **אין מאגר לקוד:** תמונת המדינה (לפי `country` ב-airports.json), ואם אין, `_default.webp`. **לא** משתמשים בתמונה שמגיעה מספק הטיסות.
5. **מחיקות:**
   - `DESTINATION_LANDMARK_IMAGES`, הדריסות שלו ו-`_DESTINATION_IMAGE_FALLBACKS` (database.py:14-37).
   - מילון `dedicated` ב-public_site.py:3077-3102, כולל ה-OTP הכפול. עובר לאותה פונקציה.
6. **קרדיט:** אם `credit_required`, שורה קטנה על התמונה בכרטיס הדיל (`templates/_deal_card.html`), בפורמט של דין.
7. **וואטסאפ:** `image_url` בתור (radar_alerts.py:159) צריך להיות כתובת מלאה ונגישה של הקובץ המקומי. URL מוחלט של האתר.
8. **מה לא כלול כאן:** תמונות האטרקציות בכרטיסי המסלול (itinerary_cards.py:79), שנמשכות מוויקיפדיה בזמן אמת. דין דורש לטפל בזה לפני ההשקה. אכתוב לזה משימה נפרדת (021ב).

## 3. בדיקות לשקד
1. בכל אחד מ-37 יעדי הדילים יש תמונה מקומית. ברענון היא משתנה, ונשארת מתוך המאגר.
2. ORY מציג תמונה של פריז, ו-EWR של ניו יורק.
3. יעד בלי מאגר מקבל את תמונת המדינה, ואם אין, את התמונה הכללית.
4. ליסבון מופיעה עם תמונה באתר החי.
5. אין יותר קישורים ל-commons.wikimedia.org, ל-xplorer.co.il או ל-krakow.pl בכרטיסי הדילים.
6. זמן טעינת עמוד הדילים לא עולה.
7. קרדיט מופיע בתמונה שדורשת אותו.
