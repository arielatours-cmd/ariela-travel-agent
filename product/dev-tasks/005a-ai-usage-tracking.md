# משימת פיתוח 005א — רישום שימוש ב-Claude API ועלות משוערת

תוכנית: [005](../plans/005-ai-usage-tracking.md) — מאושר
נוצרה: 2026-10-08

## מה קיים
- נקודת קריאה יחידה: `_post_claude(key, model, system_static, system_dynamic, history, message, max_tokens, include_history=True)` — ariella_chat_clean.py:325. נקראת מ: 1405, 1934 (טינקרבל — תשובה), 1970 (חילוץ מצב), 2475, 3251, 3398 (סיווגים קצרים), public_site.py:2987, ו-attractions_coverage.py (בתוך thread, דרך import).
- `response.usage` לא נשמר.

## שינויים

### 1. טבלה (database.py)
```sql
CREATE TABLE IF NOT EXISTS ai_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    source TEXT NOT NULL,          -- 'ariella_reply' | 'tinkerbell_reply' | 'state_extractor' | 'classifier' | 'internal_attractions' | 'other'
    member_id INTEGER,
    trip_id INTEGER,
    conversation_id INTEGER,
    model TEXT NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cache_read_input_tokens INTEGER NOT NULL DEFAULT 0,
    cache_creation_input_tokens INTEGER NOT NULL DEFAULT 0,
    is_test INTEGER NOT NULL DEFAULT 0,   -- 1 כשמצב בדיקה פעיל / חשבון בדיקה
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_ai_usage_created ON ai_usage(created_at);
CREATE INDEX IF NOT EXISTS idx_ai_usage_member ON ai_usage(member_id, created_at);
CREATE INDEX IF NOT EXISTS idx_ai_usage_conversation ON ai_usage(conversation_id);
```

### 2. הקשר לכל קריאה — `ai_usage.py` (מודול חדש)
- `contextvars.ContextVar` בשם `ai_usage_context` עם dict: `member_id`, `trip_id`, `conversation_id`, `is_test`.
- `set_ai_usage_context(**kw)` — נקרא בנקודת הכניסה של בקשת הצ'אט ב-public_site.py (הנתיב שמטפל בהודעת לקוח לאריאלה/טינקרבל), עם ה-member, החופשה והשיחה הנוכחיים. `is_test` = מצב בדיקה (`qa_test_mode`) או חשבון בדיקה.
- `record_ai_usage(source, model, usage, error=None)` — כותב שורה; **לעולם לא זורק חריגה** (try/except + log), כדי שכשל ברישום לא יפיל שיחה.

### 3. `_post_claude`
- פרמטר חדש אופציונלי `source: str = "other"`.
- אחרי `messages.create` מוצלח: `record_ai_usage(source, model, response.usage)` (השדות: `input_tokens`, `output_tokens`, `cache_read_input_tokens`, `cache_creation_input_tokens` — לקרוא עם `getattr(..., 0) or 0`).
- בשגיאת API: שורה עם `error=str(status_code)` וטוקנים 0.
- לעדכן את כל הקריאות עם `source` מתאים (טבלה למעלה). ב-attractions_coverage: `source='internal_attractions'` (ה-thread לא יורש contextvars — זה בסדר, אין לקוח).
- לא לשנות שום התנהגות אחרת (מודל, מטמון, max_tokens).

### 4. עלות משוערת
- מחירון כהגדרה, לא קבוע בקוד: `AI_PRICING_JSON` (env) או `settings` — מבנה `{"<model>": {"input": $/MTok, "output": $/MTok, "cache_read": $/MTok, "cache_write": $/MTok}}`. **את המספרים למלא מדף התמחור הרשמי של Anthropic למודל שבשימוש (`ARIELLA_MODEL`)** — לא לנחש. מודל בלי מחירון → עלות "לא ידוע".
- `estimate_cost_usd(row)` לפי המחירון.

### 5. מסך מנהל (app.py, `_require_admin`)
- `GET /admin/ai-usage?days=30&include_test=0` — JSON: סה"כ טוקנים ועלות; פילוח לפי יום, לפי `source`, לפי לקוח (20 הגבוהים), ולפי שיחה (20 הגבוהות); אחוז פגיעה במטמון.
- `GET /admin/ai-usage.csv?days=30` — ייצוא שורה-שורה ליוסף (כל עמודות הטבלה + עלות משוערת).
- `GET /admin/ai-usage/conversation/<id>` — כל הקריאות של שיחה אחת (כך אפשר למדוד שיחת בדיקה בודדת).

## קריטריוני קבלה
1. הודעה אחת בצ'אט → שורות ב-`ai_usage` עם `member_id`, `conversation_id`, `source` נכון לכל קריאה (תשובה + חילוץ מצב), וטוקנים > 0.
2. קריאה מ-attractions_coverage → `source='internal_attractions'`, בלי member.
3. כשל בכתיבה ל-DB (למשל טבלה נעולה) → השיחה ממשיכה כרגיל.
4. שגיאת API → שורה עם `error`.
5. מצב בדיקה פעיל → `is_test=1`; המסך מסתיר אותן כברירת מחדל.
6. `/admin/ai-usage` ו-`.csv` עובדים, בלי טוקן מנהל → 401.
7. מודל בלי מחירון → עלות "לא ידוע", בלי קריסה.
8. אין שינוי בתשובות של אריאלה (בדיקה ידנית של 3 שיחות).

## בדיקות QA
- סקריפט ב-tools/ עם mock ל-`client.messages.create` שמחזיר usage קבוע: מאמת כתיבה, הקשר, שגיאות, וחישוב עלות לפי מחירון בדיקה.
- בדיקה ידנית: שיחת בדיקה אחת באתר → `/admin/ai-usage/conversation/<id>`.
- דוח QA_REPORT בסגנון הקיים.
