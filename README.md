# Ariella Tours v7

גרסה מתקדמת של מנוע הסריקות והדילים של אריאלה.

## חדש בגרסה 7

- לוח בקרה פנימי בעברית: `/admin`
- הצגת כל ההצעות והסיבות לציון: `/offers-preview`
- היסטוריית סריקות: `/scan-history`
- בדיקת בריאות מורחבת: `/health`
- הפעלת סריקה ובניית רשימה יומית מתוך לוח הבקרה
- פירוט מלא יותר של חישוב הציון
- הגנת מנהל אופציונלית באמצעות `ADMIN_TOKEN`

## משתני Environment ב-Render

חובה:
- `SERPAPI_API_KEY`

מומלץ:
- `DB_PATH=/var/data/ariella.db` כאשר מחובר Persistent Disk
- `ADMIN_TOKEN` להגנה על מסכי הניהול

קיימים גם:
- `SCHEDULER_ENABLED=true`
- `MAX_SEARCHES_PER_SCAN=8`
- `MIN_DEAL_SCORE=70`
- `MAX_DAILY_DEALS=5`
- `DAILY_SEND_HOUR=17`
- `DAILY_SEND_MINUTE=0`

כאשר מוגדר `ADMIN_TOKEN`, אפשר לפתוח את לוח הבקרה כך:
`/admin?token=YOUR_TOKEN`

## נקודות בדיקה

- `/health`
- `/admin`
- `/scan-status`
- `/offers-preview`
- `/daily-preview`

## הפעלה מקומית

```bash
pip install -r requirements.txt
python app.py
```
