# NOVA N2 — שינויים

- Webhook מאומת של Meta: GET/POST `/whatsapp/webhook`.
- הודעת קוד החיבור מקשרת את מספר ה-WhatsApp למשתמש הקיים באתר; היא אינה יוצרת משתמש חדש.
- לאחר חיבור מוצלח נובה מחזירה תפריט אישי.
- פקודות ראשוניות: החופשות שלי, חופשה חדשה, המשך חופשה, דילים אחרונים, עזרה/תפריט.
- מניעת תגובה כפולה לאותה הודעת Meta באמצעות message_id.
- מצב שיחה נשמר בצד השרת.
- כפתור "אריאלה בנייד" הועבר ליד "תכנון החופשה הבאה", ללא מלבן/טקסט מסביב, ובטורקיז הקיים של האתר (#0b8f9c).

## משתני Render הדרושים ל-N2
- WHATSAPP_BUSINESS_NUMBER — כבר משמש לפתיחת WhatsApp מהאתר.
- WHATSAPP_ACCESS_TOKEN — טוקן Cloud API של Meta.
- WHATSAPP_PHONE_NUMBER_ID — מזהה מספר הטלפון ב-Meta.
- WHATSAPP_WEBHOOK_VERIFY_TOKEN — מחרוזת סודית לבחירתנו, זהה ב-Render ובמסך Webhooks של Meta.
- FLASK_SECRET_KEY — סוד אפליקטיבי מאובטח.

Webhook callback URL: `https://<your-domain>/whatsapp/webhook`
