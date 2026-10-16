# חיבור המספר 058-771-4389 לאריאלה (ממחשב)

עודכן: 2026-10-13. המספר שוחרר מהאפליקציה, ו-Meta אישרו שאפשר להעביר אותו ל-Cloud API.

1. היכנסו ל-developers.facebook.com → My Apps → **ARIELA TOURS** → WhatsApp → **Step 2. Production setup** → **Add new number**.
2. פרטי העסק: בוחרים את התיק העסקי **Ariela TOURS**. אתר: https://ariela-travel-agent.onrender.com. מדינה: Israel.
3. פרופיל: שם תצוגה **ARIELA TOURS**, קטגוריה Travel.
4. מספר: ‎+972 58-771-4389. קבלת קוד ב-SMS (אם לא מגיע: שיחה קולית). מזינים את הקוד.
5. אחרי ההוספה מעתיקים 2 מזהים: **Phone Number ID** ו-**WhatsApp Business Account ID**. אלה מזהים, לא סיסמאות, ואפשר לשלוח אותם לאופק.
6. Business Settings → Users → System users → Employee → **Assign assets**. נותנים ל-Employee גישת Full control לחשבון הוואטסאפ החדש.
7. Render → Environment: מעדכנים את `WHATSAPP_PHONE_NUMBER_ID` ואת `WHATSAPP_WABA_ID` לערכים החדשים.
8. אופק מנחה את השלבים האחרונים: register עם ה-PIN, בדיקת subscription, והודעת בדיקה.

---
## עדכון 15.10: חסום עד סוף אימות העסק
- **המצב:** Meta נועלת את פרטי העסק כשהאימות בבדיקה, ולכן אי אפשר לפתוח חשבון וואטסאפ חדש עכשיו.
- **עקיפה זמנית לבדיקות:** מספר הבדיקה +1 555-162-1759.
  - Phone Number ID: ‏1295170173670062
  - Test WABA: ‏1017318837590194
- **השלבים:**
  1. ב-API Setup: מוסיפים את הנייד שלה כנמען מאושר.
  2. נותנים ל-Employee גישה ל-Test WABA.
  3. ב-Render מעדכנים את ה-IDs ובודקים את ה-ALLOWLIST.
  4. מריצים subscription?apply=1, ושולחים הודעת בדיקה.
- **אחרי שהאימות מסתיים:** חוזרים לשלבים 1–8 שלמעלה עם המספר 4389.

## ✅ 15.10, 20:20: אריאלה עונה בוואטסאפ דרך מספר הבדיקה
- **הושלם:**
  - נמען מאושר.
  - ל-Employee יש גישה ל-Test WABA.
  - ב-Render עודכנו PHONE_NUMBER_ID=1295170173670062, WABA_ID=1017318837590194 ו-ALLOWLIST.
  - הרצנו subscription apply.
- **מה עצר את התשובות:** חסר WHATSAPP_RECIPIENT (whatsapp.py:52). הגדרנו אותו כעקיפה, ובצלאל מתקן בקוד.
- **אבטחה:** ה-ADMIN_TOKEN נרשם בלוגים של Render דרך `?token=`, ולכן הוחלף. **מעכשיו אין הוראות עם token בכתובת.**
- **הבא:** כשאימות העסק יאושר (כ-2 ימי עסקים), עוברים למספר 4389 לפי שלבים 1–8.

---
## מוכן לביצוע: מעבר למספר 4389 אחרי שאימות העסק מאושר
**סימן שאפשר להתחיל:** ב-Security Center כתוב שהעסק **Verified**.
1. **הוספת המספר (רצוי ממחשב):** developers → ARIELA TOURS → WhatsApp → API Setup / Production setup → **Add phone number**. התיק: Ariela TOURS. אתר: https://ariela-travel-agent.onrender.com. מדינה: Israel.
2. **פרופיל:** שם תצוגה ARIELA TOURS, קטגוריה Travel. אפשר שהשם יעבור בדיקה של Meta, וזה לא חוסם.
3. **מספר:** ‎+972 58-771-4389. מקבלים את הקוד ב-SMS, ואם לא מגיע, בשיחה קולית.
4. **מעתיקים את ה-IDs החדשים:** Phone Number ID ו-WABA ID. אלה מזהים ולא סודות, ומעבירים אותם דרך שלמה.
5. **Assign assets:** System users → Employee → נותנים Full control לחשבון הוואטסאפ החדש. אחרת יופיע שוב 100/33.
6. **Render:**
   - מעדכנים את `WHATSAPP_PHONE_NUMBER_ID` ואת `WHATSAPP_WABA_ID` לערכים החדשים.
   - בודקים ש-`WHATSAPP_RECIPIENT` עדיין מוגדר (עקיפה, עד שבצלאל יתקן את whatsapp.py:52).
   - `WHATSAPP_REGISTRATION_PIN` כבר קיים, לא נוגעים בו.
   - `WHATSAPP_INBOUND_ALLOWLIST` נשאר בשלב הבדיקות.
7. **רישום המספר (register) והרשמה ל-webhook (subscription apply):** דרך נתיבי האדמין, **בלי token בכתובת**, בשיטה שבצלאל יקבע (header או POST). עד שזה מוכן, שואלים את שלמה לפני ההרצה.
8. **בדיקה:**
   - בתוצאה צריך לראות status=CONNECTED, platform_type=CLOUD_API ו-subscribed=true.
   - שולחים "שלום" מהנייד הפרטי ל-058-771-4389, ואריאלה אמורה לענות.
9. **ניקוי:**
   - מספר הבדיקה נשאר בצד ולא מפרסמים אותו.
   - מגישים מחדש את תבניות ה-Meta תחת ה-WABA החדש (ראו whatsapp_templates_draft.md).
