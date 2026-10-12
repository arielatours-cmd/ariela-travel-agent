# משימת פיתוח 006ג — רישום המספר של אריאלה טורס ישירות ל-Cloud API (בלי Coexistence)

תוכנית: [006](../plans/006-whatsapp-inbound-ariela.md) — שלב 1. **החלטת בעלת העסק (2026-10-12): דרך ב'**, כלומר להעביר את המספר כולו לאריאלה ולוותר על אפליקציית WhatsApp Business בטלפון במספר הזה.
נוצרה: 2026-10-12

## הרקע
- `/admin/whatsapp-subscription` מראה: token_ok=true ו-subscribed=true, אבל המספר 551450234708715 (מסתיים ב-4389) במצב `status=DISCONNECTED`, `platform_type=ON_PREMISE`, `code_verification_status=NOT_VERIFIED`. לכן Meta לא מעבירה הודעות.
- תהליך ה-Coexistence (`/whatsapp-coexistence-setup`) נתקע שוב: יש code, ואין FINISH. בעלת העסק בחרה לוותר על Coexistence.

## שינוי: שלושה נתיבי מנהל (app.py, עם `_require_admin`, ב-GET כי בעלת העסק עובדת מטלפון)
1. `GET /admin/whatsapp-number/request-code?method=SMS|VOICE&token=...`
   → `POST /{WHATSAPP_PHONE_NUMBER_ID}/request_code` עם `code_method` ו-`language=he`. מחזיר הצלחה או את שגיאת Meta.
2. `GET /admin/whatsapp-number/verify-code?code=123456&token=...`
   → `POST /{PHONE_NUMBER_ID}/verify_code` עם `code`.
3. `GET /admin/whatsapp-number/register?token=...`
   → `POST /{PHONE_NUMBER_ID}/register` עם `{"messaging_product":"whatsapp","pin": WHATSAPP_REGISTRATION_PIN}`.
   - `WHATSAPP_REGISTRATION_PIN`: משתנה סביבה חדש, 6 ספרות, בעלת העסק תגדיר. זה ה-PIN של אימות דו-שלבי למספר. **לא לרשום אותו בלוג.**
   - אחרי הרישום: GET על המספר והחזרת status, platform_type ו-code_verification_status.
- כל הנתיבים: עם `?confirm=1` בלבד מבצעים פעולה. בלי confirm מחזירים רק הסבר מה יקרה (כדי שלחיצה בטעות לא תשלח SMS).
- לא להחזיר ולא לרשום בלוג את ACCESS_TOKEN או את ה-PIN. מספר טלפון מלא לא מוצג.
- להוסיף `WHATSAPP_REGISTRATION_PIN=` ל-env.example.

## קריטריוני קבלה
1. בלי טוקן מנהל → 401. בלי confirm=1 → שום קריאה ל-Meta.
2. mock: request-code → POST עם code_method; verify-code → POST עם code; register → POST עם pin. כל שגיאה של Meta מוחזרת כמו שהיא, בלי סודות.
3. register בלי PIN מוגדר → הודעה ברורה, בלי קריאה ל-Meta.
4. בדיקת QA עם mock.

## הסדר אצל בעלת העסק (אופק תלווה)
1. גיבוי של הצ'אטים באפליקציית WhatsApp Business, ומחיקת חשבון הוואטסאפ מהאפליקציה בטלפון. לפי Meta, מספר שפעיל באפליקציה לא יכול להירשם ל-Cloud API.
2. הגדרת `WHATSAPP_REGISTRATION_PIN` ב-Render.
3. request-code, אחר כך verify-code עם הקוד שהגיע ב-SMS, ואז register.
4. `/admin/whatsapp-subscription` אמור להראות `status=CONNECTED`. אחר כך הודעת בדיקה מהנייד המורשה.

**לבדוק במהלך המימוש:** אם Meta מחזירה שגיאה שמסבירה שהמספר עדיין מקושר לאפליקציה, להחזיר הודעה ברורה בעברית: "צריך קודם למחוק את החשבון מאפליקציית WhatsApp Business".
