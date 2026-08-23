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


## Version 9.0 — WhatsApp

- Dashboard button to send the current daily deal batch to WhatsApp.
- WhatsApp connection-status button.
- Secure configuration through Render Environment Variables.
- Helpful Meta error messages.
- Clickable table headers for sorting; version 8.1 filters remain available.

### Render Environment Variables

Add these under Render → Service → Environment:

- `WHATSAPP_ACCESS_TOKEN`
- `WHATSAPP_PHONE_NUMBER_ID`
- `WHATSAPP_RECIPIENT` — international format, digits only, for example `9725XXXXXXXX`
- `WHATSAPP_API_VERSION` — optional; default `v23.0`

Never store the real access token in GitHub.

A free-form deal message can require an open customer-service conversation window.
If Meta rejects it, send a message from the recipient to the Meta test number and try again.
Production outbound messages will later use approved WhatsApp templates.


## Version 10.0 — Public website

Version 10 adds the first complete public Ariella website:

- Luxury, classic, mobile-friendly home page
- A dedicated public deals page connected to the existing offers database
- Personal “About us” page
- Registration and login
- Personal account area
- A detailed “My next trip” questionnaire
- Storage of member accounts and trip requests in SQLite
- Clear airline/travel-supplier disclaimer across the website
- Preliminary privacy and terms pages

### New Render variable

Add `FLASK_SECRET_KEY` in Render Environment with a long random value.
Do not use the included development fallback in production.

### Current scope

The questionnaire is functional and stores each trip request. The next stage is to
connect stored preferences to the scoring and search engine, add email verification,
password reset, member management, and legally reviewed terms/privacy text.

- v9.7.59: fixed selected-choice checkmark position in RTL questionnaire cards; checkmark now sits on the right side of the label instead of above it.

- v9.7.61: questionnaire hero title uses Assistant for a warmer, happier look; baseline version for live testing.
