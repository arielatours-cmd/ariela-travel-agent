# NOVA N1 — QA

## בדיקות שבוצעו

- `python -m py_compile` עבר עבור `app.py`, `public_site.py`, `database.py`, `nova_whatsapp.py`, `config.py`, `whatsapp.py`.
- מסד נתונים זמני חדש אותחל בהצלחה עם הטבלאות החדשות.
- נוצר handoff עבור member ניסיוני.
- אומת שה-token הגולמי אינו נשמר במסד; נשמר SHA-256 בלבד.
- handoff נצרך בהצלחה וקישר hash של מספר WhatsApp ל-member.
- ניסיון שימוש שני באותו token נחסם כמצופה.

## בדיקה שלא בוצעה מקומית

בדיקת Flask מלאה דרך test client לא בוצעה בקונטיינר העבודה משום שחבילת Flask אינה מותקנת בסביבת הכלים הזו. הפרויקט עצמו כולל Flask ב-`requirements.txt` ונפרס ב-Render דרך `pip install -r requirements.txt`.

## לפני בדיקה ב-Render

יש להגדיר:

1. `FLASK_SECRET_KEY` — סוד ארוך ואקראי.
2. `WHATSAPP_BUSINESS_NUMBER` — מספר ה-WhatsApp Business בפורמט בינלאומי, ספרות בלבד.
3. `NOVA_HANDOFF_TTL_MINUTES=10` — אופציונלי.

לאחר deploy: להתחבר לאתר, לפתוח `/account`, ללחוץ **"אריאלה שלי בנייד"** ולוודא שנפתח `wa.me` עם הודעת handoff מוכנה.
