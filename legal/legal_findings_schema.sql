-- legal_findings — טבלת ממצאי התאימות של דין.
-- להדבקה ב-database.py, בתוך אותו בלוק executescript שבו נוצרות שאר הטבלאות
-- (אחרי password_reset_tokens). קונבנציות זהות לשאר הסכמה:
-- INTEGER PRIMARY KEY AUTOINCREMENT, חותמות זמן TEXT ב-ISO (utc_now_iso), status עם DEFAULT.

CREATE TABLE IF NOT EXISTS legal_findings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- מתי ועל מה
    found_at TEXT NOT NULL,              -- utc_now_iso()
    commit_sha TEXT,                     -- ה-commit שנסרק
    report_path TEXT,                    -- legal/reports/<תאריך>.md

    -- סיווג
    area TEXT NOT NULL,                  -- whatsapp | payments | privacy | ai_content | deals | affiliate | tourism_license | legal_pages
    severity TEXT NOT NULL,              -- critical | high | low
    title TEXT NOT NULL,                 -- שורה אחת: מה הפער
    detail TEXT NOT NULL,                -- מה נבדק, מה נמצא, ומה עלול לקרות ללקוח או לחברה

    -- עיגון בקוד
    file_path TEXT,                      -- נתיב יחסי בריפו
    line_no INTEGER,

    -- עיגון בדין
    legal_basis TEXT NOT NULL,           -- שם החוק והסעיף, או 'unverified'
    source_url TEXT,                     -- הקישור שממנו אומת

    -- טיפול
    recommendation TEXT NOT NULL,        -- מה לעשות בפועל; אם זה ניסוח - הטקסט המוצע עצמו
    needs_lawyer INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'open', -- open | resolved | accepted_risk | not_applicable
    owner TEXT,
    resolved_at TEXT,
    resolved_commit_sha TEXT,
    notes TEXT,

    -- מונע כפילות: אותו פער באותו מקום לא נרשם פעמיים
    UNIQUE(area, title, file_path)
);

CREATE INDEX IF NOT EXISTS idx_legal_findings_status
ON legal_findings(status, severity);

CREATE INDEX IF NOT EXISTS idx_legal_findings_found_at
ON legal_findings(found_at DESC);

CREATE INDEX IF NOT EXISTS idx_legal_findings_area
ON legal_findings(area, status);
