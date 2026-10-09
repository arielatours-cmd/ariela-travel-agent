# QA — 003א: "הדילים החמים" בוואטסאפ — הודעת ברכה + כפתור "הפסקת הדילים"

תוכנית: [003](003-whatsapp-one-inbox.md)

## מה נבדק
`tools/qa_whatsapp_deals_welcome_stop.py`, 24 בדיקות, כולן PASS:
- אישור תשלום מדומה ל-`whatsapp_deals_9` → `whatsapp_opt_in=1`, שורת `opt_in/payment` ב-`whatsapp_opt_events`, הודעת ברכה בתור `whatsapp_outbound_queue` בסטטוס `preview` עם כפתור `STOP_HOT_DEALS`.
- אישור כפול של אותו תשלום → **לא** שולח ברכה פעמיים (נבדק גם ש-`opt_in_changed=False` בפעם השנייה).
- הפסקה ואז תשלום נוסף → ברכה **חדשה** (לא נחסמת ע"י הדדופ הקודם).
- `formatter.build_daily_whatsapp_payload` מחזיר את גוף ההודעה הקיים (`build_daily_message`, ללא שינוי) + כפתור `הפסקת הדילים`/`STOP_HOT_DEALS`.
- `route_inbound(phone, '', button_payload='STOP_HOT_DEALS')`:
  - מלקוח פעיל → `whatsapp_opt_in=0`, `whatsapp_opt_out_source='whatsapp_button'`, שורת `opt_out` ב-`whatsapp_opt_events`, תשובה עם קישור מלא ל-`/deals`.
  - לחיצה שנייה → "כבר לא נשלחים", בלי שורת opt_out נוספת.
  - מספר לא מוכר → "לא מצאנו...", בלי onboarding ובלי יצירת משתמש.
  - לקוח עם מעקב חופשה בתשלום פעיל (`subscription_status='active'`, `mobile_notifications=1`) → שורה נוספת על המשך עדכוני החופשה.
  - הודעת טקסט חופשית "עצור" → **לא** מפסיקה כלום (רק הכפתור).
- המתג באתר (`/whatsapp-opt-in`) ממשיך לעבוד דרך `set_whatsapp_deals_opt(..., source='site')`.
- מיגרציה (`init_db()`) רצה פעמיים ברצף בלי שגיאה.

## ממצא נוסף (לא חלק מהמשימה המקורית, התגלה תוך כדי QA)
בדיוק כפי שהמשימה הזהירה: הטבלאות `whatsapp_member_links` ו-`whatsapp_conversation_state` נקראות ונכתבות ב-nova_conversation.py/nova_whatsapp.py בלי `CREATE TABLE` בשום מקום. תוך כדי הרצת ה-QA התגלתה **גם** `whatsapp_onboarding_state` באותו מצב בדיוק - ובניגוד לשתיים האחרות, זו לא "תשתית עתידית": היא נחוצה לכל קריאה רגילה (לא-כפתור) ל-`route_inbound`, כלומר תהליך ה-onboarding הקיים לכל לקוח וואטסאפ חדש כבר שבור היום בפרודקשן (טבלה חסרה → `sqlite3.OperationalError`), עוד לפני המשימה הזו. שלוש הטבלאות נוספו ל-`init_db()` לפי העמודות שבפועל בשימוש בקוד. `_handle_stop` גם עוטף את `linked_member_for_phone` ב-try/except ונופל ל-`registered_member_for_phone`, למקרה שמסד הנתונים בפרודקשן מריץ גרסה שעדיין לא כוללת את התיקון הזה.

## תוצאה
כל הבדיקות עברו (PASS). ראו commit (יתועד בעדכון הבא).

## הערות
- המתג באתר (`/whatsapp-opt-in`) עדיין לא גובה תשלום אמיתי (אין ספק סליקה מחובר) - בדיוק כמו היום. `/admin/confirm-whatsapp-payment` הוא המקבילה הידנית/מדומה ל-`/admin/confirm-payment` הקיים (למסלולי 19/39 ₪), לפי אותו דפוס בדיוק.
- חיבור ה-webhook בפועל ל-`route_inbound`, שליחה אמיתית דרך `send_template_message`, והגשת התבניות ל-Meta - מחוץ להיקף, כפי שנאמר במשימה.
