# QA — 006ג: רישום המספר של אריאלה טורס ישירות ל-Cloud API

תוכנית: [006](006-whatsapp-inbound-ariela.md) — שלב 1. החלטת בעלת העסק (2026-10-12): לוותר על Coexistence ולהעביר את המספר כולו ל-Cloud API, אחרי ש-`/admin/whatsapp-subscription` (006ב) חשף שהמספר במצב `DISCONNECTED`/`ON_PREMISE`/`NOT_VERIFIED`, ותהליך ה-Coexistence (`/whatsapp-coexistence-setup`) נתקע שוב (code מתקבל, FINISH לא מגיע).

## מה נבדק
`tools/qa_whatsapp_register_number.py` (mock מלא ל-`requests` - שום קריאה אמיתית ל-Meta), כולן PASS:
1. בלי טוקן מנהל → 401, על כל שלושת הנתיבים.
2. בלי `confirm=1` → שום קריאה ל-Meta בכלל, בכל אחד משלושת השלבים (רק הסבר על מה שיקרה).
3. `request-code` עם `confirm=1` → `POST .../request_code` עם `code_method` (`SMS`/`VOICE`) ו-`language=he`.
4. `verify-code` עם `confirm=1` → `POST .../verify_code` עם `code` (ספרות בלבד - תווים לא-ספרתיים מנוקים אוטומטית).
5. `register` עם `confirm=1` → `POST .../register` עם `messaging_product`+`pin`, ואז בדיקה חוזרת של סטטוס המספר (`status`, `platform_type`, `code_verification_status`).
6. שגיאת Meta שמרמזת שהמספר עדיין מקושר לאפליקציה ("still linked", "migrat", "coexistence" וכו') → מתווספת הודעה ברורה בעברית, **בנוסף** להודעה המקורית של Meta (לא מחליפה אותה).
7. `register` בלי `WHATSAPP_REGISTRATION_PIN` מוגדר → הודעה ברורה, בלי שום קריאה ל-Meta.
8. לא ה-PIN ולא ה-ACCESS_TOKEN מופיעים אי פעם בתוצאה המוחזרת.

## המימוש
שלוש פונקציות ב-`whatsapp.py` (`whatsapp_request_code`, `whatsapp_verify_code`, `whatsapp_register_number`), נחשפות דרך שלושה נתיבי `GET` עם `_require_admin`: `/admin/whatsapp-number/request-code`, `/admin/whatsapp-number/verify-code`, `/admin/whatsapp-number/register`. `WHATSAPP_REGISTRATION_PIN` (משתנה סביבה חדש) נוסף ל-`config.py` ול-`env.example`.

כל חבילת הבדיקות הקיימת (`qa/run_qa.py`) נבדקה ועברה אחרי השינוי.

## הסדר אצל בעלת העסק (אופק מלווה)
1. גיבוי + מחיקת חשבון הוואטסאפ מאפליקציית WhatsApp Business בטלפון (Meta לא מאפשרת רישום ל-Cloud API כשהמספר עדיין פעיל באפליקציה).
2. הגדרת `WHATSAPP_REGISTRATION_PIN` ב-Render (6 ספרות, לבחירתה).
3. `request-code` → `verify-code` עם הקוד מה-SMS → `register`.
4. `/admin/whatsapp-subscription` אמור להראות `status=CONNECTED`.
