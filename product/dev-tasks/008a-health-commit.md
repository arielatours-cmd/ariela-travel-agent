# משימת פיתוח 008א — מזהה commit וזמן עלייה ב-/health

תוכנית: [008](../plans/008-deployed-version-in-health.md) — מאושר (ביוזמת ערן, תפעול)
נוצרה: 2026-10-12

## שינוי (app.py בלבד)
1. ברמת המודול, פעם אחת בעלייה:
   ```python
   _DEPLOYED_COMMIT = (os.getenv("RENDER_GIT_COMMIT") or "").strip()[:7] or None
   _STARTED_AT = datetime.now(timezone.utc).isoformat(timespec="seconds")
   ```
   (לייבא את `datetime` ואת `timezone` אם הם עוד לא מיובאים ב-app.py.)
2. ב-`health()` (app.py, הנתיב `/health`) להוסיף ל-JSON:
   `"commit": _DEPLOYED_COMMIT, "deployed_at": _STARTED_AT`.
3. `APP_VERSION` נשאר כמו שהוא.

## קריטריוני קבלה
1. עם `RENDER_GIT_COMMIT=abcdef1234...` → `"commit": "abcdef1"`.
2. בלי המשתנה → `"commit": null`.
3. `deployed_at` הוא ISO UTC, וזהה בין שתי קריאות באותו תהליך.
4. שאר השדות של /health לא השתנו. כל חבילת הבדיקות עוברת.
5. בדיקה קטנה ב-tools/ או בחבילה של שקד (Flask test client).
