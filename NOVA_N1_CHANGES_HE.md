# NOVA N1 — אריאלה שלי בנייד

מומש שלב N1 של חיבור האזור האישי ל-WhatsApp:

- כפתור **"אריאלה שלי בנייד"** במסך `/account`.
- יצירת handoff קצר-חיים (ברירת מחדל 10 דקות) ללא חשיפת `member_id`.
- הקוד כולל חתימת HMAC ונשמר במסד הנתונים רק כ-SHA-256 hash.
- כל קוד הוא חד-פעמי; יצירת קוד חדש מבטלת handoff קודם שלא נוצל.
- נוספו הטבלאות `whatsapp_handoffs` ו-`whatsapp_member_links` במיגרציה additive ובטוחה.
- נוספה פונקציית service `consume_member_handoff()` לשימוש ב-Webhook המאומת של Meta בשלב N2. אין endpoint ציבורי שמאפשר לדפדפן לקבוע מספר WhatsApp.
- מנגנון החיבור מונע קישור מספר WhatsApp פעיל לחשבון אחר.
- אם `WHATSAPP_BUSINESS_NUMBER` או `FLASK_SECRET_KEY` אינם מוגדרים, המשתמש מקבל הודעה והאתר אינו נשבר.

## משתני Render חדשים

- `WHATSAPP_BUSINESS_NUMBER` — מספר ה-WhatsApp Business בפורמט בינלאומי, ספרות בלבד (ללא `+`).
- `NOVA_HANDOFF_TTL_MINUTES` — אופציונלי, ברירת מחדל `10`.
- `FLASK_SECRET_KEY` — חייב להיות סוד ארוך ואקראי (כבר נדרש עבור sessions; N1 מסרב לייצר handoff עם ברירת המחדל הלא-בטוחה).

## גבול שלב N1

הקישור בפועל של זהות השולח לחשבון יושלם כאשר N2 יוסיף Meta Webhook מאומת ויקרא ל-`consume_member_handoff(token, sender_phone)`. בכוונה לא נוסף endpoint ציבורי שמקבל מספר טלפון מהלקוח.
