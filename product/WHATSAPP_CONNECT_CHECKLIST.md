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
