"""legal_findings — פונקציות העזר של דין, להדבקה ב-database.py.

סטייל זהה לשאר הקובץ: utc_now_iso() לחותמות זמן, with connection() as conn,
טיפוסים מפורשים, ו-docstring שמסביר למה הפונקציה קיימת ולא רק מה היא עושה.
"""
from __future__ import annotations


def record_legal_finding(
    area: str,
    severity: str,
    title: str,
    detail: str,
    legal_basis: str,
    recommendation: str,
    file_path: str | None = None,
    line_no: int | None = None,
    source_url: str | None = None,
    needs_lawyer: bool = False,
    commit_sha: str | None = None,
    report_path: str | None = None,
) -> int | None:
    """Single place that writes a compliance finding. Returns the finding id, or
    None when this exact finding (area+title+file_path) is already on record -
    so a re-scan of unchanged code does not pile up duplicates, and an already
    resolved finding is not silently reopened. Din decides severity; the UNIQUE
    constraint decides novelty."""
    now = utc_now_iso()
    with connection() as conn:
        existing = conn.execute(
            "SELECT id FROM legal_findings WHERE area=? AND title=? AND IFNULL(file_path,'')=IFNULL(?,'')",
            (area, title, file_path),
        ).fetchone()
        if existing:
            return None
        cursor = conn.execute(
            """
            INSERT INTO legal_findings (
                found_at, commit_sha, report_path,
                area, severity, title, detail,
                file_path, line_no,
                legal_basis, source_url,
                recommendation, needs_lawyer, status
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,'open')
            """,
            (
                now, commit_sha, report_path,
                area, severity, title, detail,
                file_path, line_no,
                legal_basis, source_url,
                recommendation, 1 if needs_lawyer else 0,
            ),
        )
        return int(cursor.lastrowid)


def resolve_legal_finding(
    finding_id: int,
    resolved_commit_sha: str | None = None,
    notes: str | None = None,
    status: str = "resolved",
) -> bool:
    """Closes a finding. Deliberately requires an explicit call: Din may not mark
    a finding resolved because a re-scan stopped flagging it, only after seeing
    the fix in the code. Returns True only when a still-open finding was closed."""
    now = utc_now_iso()
    with connection() as conn:
        cursor = conn.execute(
            """
            UPDATE legal_findings
               SET status=?, resolved_at=?, resolved_commit_sha=?, notes=COALESCE(?, notes)
             WHERE id=? AND status='open'
            """,
            (status, now, resolved_commit_sha, notes, finding_id),
        )
        return cursor.rowcount > 0


def open_legal_findings(area: str | None = None) -> list[dict]:
    """Open findings, worst first - what blocks a commercial launch. Used by the
    admin screen and by Din's own report, so both read the same order."""
    query = """
        SELECT * FROM legal_findings
         WHERE status='open'
    """
    params: list = []
    if area:
        query += " AND area=?"
        params.append(area)
    query += """
         ORDER BY CASE severity
                    WHEN 'critical' THEN 0
                    WHEN 'high' THEN 1
                    ELSE 2
                  END,
                  found_at DESC
    """
    with connection() as conn:
        return [dict(row) for row in conn.execute(query, params).fetchall()]
