# משימת פיתוח 004א — שורת פרטי העסק בתחתית האתר

תוכנית: [004](../plans/004-business-details-footer.md) — מאושר
נוצרה: 2026-10-08

## שינויים
1. **config.py** — משתני סביבה (ריקים כברירת מחדל):
   `BUSINESS_TRADE_NAME` (ברירת מחדל `"ARIELA AI TRAVEL"`), `BUSINESS_LEGAL_NAME_HE`, `BUSINESS_LEGAL_NAME_EN`, `BUSINESS_DEALER_TYPE_HE` (למשל "עוסק מורשה"), `BUSINESS_DEALER_NUMBER`, `BUSINESS_ADDRESS_HE`, `BUSINESS_ADDRESS_EN`, `BUSINESS_CONTACT_EMAIL`.
   להוסיף ל-env.example בלי ערכים. **לא לכתוב פרטים אישיים בקוד** — בעלת העסק תזין ב-Render.
2. **context processor** ב-public_site.py שמעביר `business` (dict) לכל התבניות.
3. **templates/_site_footer.html** — מתחת ל-`footer-copyright`, שורה חדשה `footer-business` (אותו עיצוב: אפור, 12px, ממורכז):
   - עברית: `ARIELA AI TRAVEL · {שם חוקי} · {סוג עוסק} {מספר} · {כתובת} · {מייל}`
   - אנגלית: `ARIELA AI TRAVEL · {legal name EN} · Licensed Dealer {number} · {address EN} · {email}`
   - כל חלק מוצג רק אם הוגדר; אם אין שם חוקי ומספר — לא מציגים את השורה בכלל.
   - במובייל: מותר לשבור שורה (`white-space: normal`), בלי גלילה אופקית.
4. **templates/about.html** ו-**terms.html** — אם יש בהם מקום לפרטי העסק, להשתמש באותו `business` ולא לשכפל טקסט.

## קריטריוני קבלה
1. בלי משתני סביבה → הפוטר נראה בדיוק כמו היום.
2. עם כל המשתנים → השורה מופיעה בכל העמודים (חוץ מ-`site.new_trip`, כמו הפוטר הקיים), בעברית ובאנגלית.
3. רוחב 360px → אין גלילה אופקית, הטקסט קריא.
4. אין פרטים אישיים בקוד או ב-git.

## צריך מבעלת העסק
השם החוקי בעברית ובאנגלית, סוג העוסק ומספרו, כתובת מלאה ומייל ליצירת קשר — להזין כמשתני סביבה ב-Render (אסביר איך כשהקוד יהיה מוכן).
