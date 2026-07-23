# Ariella Tours v7.1

גרסה משופרת של מנוע הסריקה והניקוד.

## שינויים עיקריים
- סריקת הניסיון בודקת 8 יעדים שונים במקום וריאציות של יעד אחד.
- סדר תור הסריקות שונה כך שכל סריקה קטנה מכסה יעדים מגוונים.
- מחיר מקבל ניקוד לפי מקור הנתונים האמין הזמין: Google Flights, היסטוריית אריאלה או התפלגות המחירים בחיפוש הנוכחי.
- נוסף מדד נדירות היסטורי כאשר קיימות לפחות 8 תצפיות מתאימות.
- הניקוד מוצג לפי החלוקה: מחיר 40, מסלול 20, נדירות 15, כבודה 10, שעות 10, עונתיות/חברת תעופה 5.
- לוח הבקרה מציג כמה נקודות חסרות לכל הצעה שלא עברה את הסף.

## בדיקה
לאחר הפריסה פתחי `/admin` ולחצי "הפעל סריקת ניסיון". הסריקה מבצעת 8 קריאות SerpAPI ועלולה לצרוך 8 חיפושים מהמכסה.


## Version 8.0
Dashboard table now shows deal dates with Hebrew weekdays, the actual scoring reference price, every available score component once, a single final score, and connection color coding only.


## Version 8.1
- Added client-side filters for destination, travel dates, maximum price, route, minimum score and qualified deals.
- Route score now uses a small colored dot instead of a colored background.
- Summary text updates automatically according to active filters.
- Clicking an offer opens a scoring detail window with the saved scoring reasons.
- Dashboard version updated to 8.1.
