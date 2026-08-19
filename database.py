import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from config import DB_PATH


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def connection():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connection() as conn:
        conn.executescript(
            """
            PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS scan_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at TEXT NOT NULL,
                finished_at TEXT,
                status TEXT NOT NULL,
                searches_planned INTEGER NOT NULL DEFAULT 0,
                searches_completed INTEGER NOT NULL DEFAULT 0,
                offers_found INTEGER NOT NULL DEFAULT 0,
                errors INTEGER NOT NULL DEFAULT 0,
                error_message TEXT
            );

            CREATE TABLE IF NOT EXISTS offers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                scan_run_id INTEGER NOT NULL,
                observed_at TEXT NOT NULL,
                route TEXT NOT NULL,
                departure_code TEXT NOT NULL,
                arrival_code TEXT NOT NULL,
                outbound_date TEXT NOT NULL,
                return_date TEXT NOT NULL,
                price_ils REAL NOT NULL,
                typical_low_ils REAL,
                typical_high_ils REAL,
                discount_percent REAL,
                score INTEGER NOT NULL,
                score_label TEXT NOT NULL,
                airline TEXT,
                stops INTEGER,
                total_duration_minutes INTEGER,
                actual_flight_duration_minutes INTEGER,
                departure_time TEXT,
                arrival_time TEXT,
                booking_url TEXT,
                destination_name TEXT,
                country_flag TEXT,
                payload_json TEXT NOT NULL,
                UNIQUE(route, outbound_date, return_date, price_ils, airline, departure_time, observed_at),
                FOREIGN KEY(scan_run_id) REFERENCES scan_runs(id)
            );

            CREATE INDEX IF NOT EXISTS idx_offers_observed_at ON offers(observed_at);
            CREATE INDEX IF NOT EXISTS idx_offers_score ON offers(score DESC);
            CREATE INDEX IF NOT EXISTS idx_offers_route_dates ON offers(route, outbound_date, return_date);

            CREATE TABLE IF NOT EXISTS daily_batches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_date TEXT NOT NULL UNIQUE,
                created_at TEXT NOT NULL,
                status TEXT NOT NULL,
                deal_count INTEGER NOT NULL,
                message_text TEXT NOT NULL,
                deals_json TEXT NOT NULL,
                sent_at TEXT,
                send_error TEXT
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS members (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                full_name TEXT NOT NULL,
                email TEXT NOT NULL UNIQUE,
                phone TEXT,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active'
            );

            CREATE TABLE IF NOT EXISTS trip_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                member_id INTEGER NOT NULL,
                request_name TEXT NOT NULL,
                travel_window TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                answers_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(member_id) REFERENCES members(id)
            );

            CREATE INDEX IF NOT EXISTS idx_trip_requests_member
            ON trip_requests(member_id, id DESC);

            -- Columns below are also added by the migration block for existing databases.

            CREATE TABLE IF NOT EXISTS feedback_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                full_name TEXT NOT NULL,
                email TEXT NOT NULL,
                phone TEXT NOT NULL,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL,
                email_status TEXT NOT NULL DEFAULT 'pending',
                email_error TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_feedback_created_at
            ON feedback_messages(created_at DESC);
            """
        )

        # Safe, additive migrations for existing Render databases.
        trip_columns = {row["name"] for row in conn.execute("PRAGMA table_info(trip_requests)").fetchall()}
        if "mobile_notifications" not in trip_columns:
            conn.execute("ALTER TABLE trip_requests ADD COLUMN mobile_notifications INTEGER NOT NULL DEFAULT 0")
        if "ended_at" not in trip_columns:
            conn.execute("ALTER TABLE trip_requests ADD COLUMN ended_at TEXT")
        if "subscription_plan" not in trip_columns:
            conn.execute("ALTER TABLE trip_requests ADD COLUMN subscription_plan TEXT")
        if "subscription_status" not in trip_columns:
            conn.execute("ALTER TABLE trip_requests ADD COLUMN subscription_status TEXT NOT NULL DEFAULT 'none'")
        if "subscription_started_at" not in trip_columns:
            conn.execute("ALTER TABLE trip_requests ADD COLUMN subscription_started_at TEXT")
        if "subscription_cancel_at_period_end" not in trip_columns:
            conn.execute("ALTER TABLE trip_requests ADD COLUMN subscription_cancel_at_period_end INTEGER NOT NULL DEFAULT 0")
        if "search_period_started_at" not in trip_columns:
            conn.execute("ALTER TABLE trip_requests ADD COLUMN search_period_started_at TEXT")
        if "search_period_ends_at" not in trip_columns:
            conn.execute("ALTER TABLE trip_requests ADD COLUMN search_period_ends_at TEXT")
        if "renewal_reminder_sent_at" not in trip_columns:
            conn.execute("ALTER TABLE trip_requests ADD COLUMN renewal_reminder_sent_at TEXT")
        if "has_paid_search" not in trip_columns:
            conn.execute("ALTER TABLE trip_requests ADD COLUMN has_paid_search INTEGER NOT NULL DEFAULT 0")

        member_columns = {row["name"] for row in conn.execute("PRAGMA table_info(members)").fetchall()}
        if "country" not in member_columns:
            conn.execute("ALTER TABLE members ADD COLUMN country TEXT")
        if "preferred_airports" not in member_columns:
            conn.execute("ALTER TABLE members ADD COLUMN preferred_airports TEXT NOT NULL DEFAULT '[]'")


def create_scan_run(searches_planned: int) -> int:
    with connection() as conn:
        cur = conn.execute(
            "INSERT INTO scan_runs(started_at,status,searches_planned) VALUES(?,?,?)",
            (utc_now_iso(), "running", searches_planned),
        )
        return int(cur.lastrowid)


def finish_scan_run(run_id: int, completed: int, offers: int, errors: int, error_message: str | None = None) -> None:
    status = "success" if errors == 0 else "partial" if completed > 0 else "failed"
    with connection() as conn:
        conn.execute(
            """UPDATE scan_runs SET finished_at=?,status=?,searches_completed=?,offers_found=?,errors=?,error_message=? WHERE id=?""",
            (utc_now_iso(), status, completed, offers, errors, error_message, run_id),
        )


def insert_offer(scan_run_id: int, offer: dict) -> None:
    flight = offer["flight"]
    analysis = offer["deal_analysis"]
    with connection() as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO offers(
                scan_run_id,observed_at,route,departure_code,arrival_code,outbound_date,return_date,
                price_ils,typical_low_ils,typical_high_ils,discount_percent,score,score_label,airline,
                stops,total_duration_minutes,actual_flight_duration_minutes,departure_time,arrival_time,
                booking_url,destination_name,country_flag,payload_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                scan_run_id, offer["observed_at"], offer["route"], offer["departure_code"], offer["arrival_code"],
                offer["outbound_date"], offer["return_date"], flight["price"], analysis.get("typical_price_low"),
                analysis.get("typical_price_high"), analysis.get("below_typical_low_percent"), offer["deal_score"]["score"],
                offer["deal_score"]["label"], flight.get("airline"), flight.get("stops"),
                flight.get("total_duration_minutes"), flight.get("actual_flight_duration_minutes"),
                flight.get("departure_time"), flight.get("arrival_time"), offer.get("booking_url"),
                offer.get("destination_name"), offer.get("country_flag"), json.dumps(offer, ensure_ascii=False),
            ),
        )


def latest_scan_run() -> dict | None:
    with connection() as conn:
        row = conn.execute("SELECT * FROM scan_runs ORDER BY id DESC LIMIT 1").fetchone()
        return dict(row) if row else None


def get_setting(key: str, default: str | None = None) -> str | None:
    with connection() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    with connection() as conn:
        conn.execute(
            "INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )


def top_deals_since(since_iso: str, minimum_score: int, limit: int = 50) -> list[dict]:
    with connection() as conn:
        rows = conn.execute(
            """
            SELECT payload_json FROM offers
            WHERE observed_at >= ? AND score >= ?
            ORDER BY score DESC, discount_percent DESC, price_ils ASC
            LIMIT ?
            """,
            (since_iso, minimum_score, limit),
        ).fetchall()
    return [json.loads(r["payload_json"]) for r in rows]


def save_daily_batch(batch_date: str, message: str, deals: list[dict], status: str = "ready") -> dict:
    now = utc_now_iso()
    with connection() as conn:
        conn.execute(
            """
            INSERT INTO daily_batches(batch_date,created_at,status,deal_count,message_text,deals_json)
            VALUES(?,?,?,?,?,?)
            ON CONFLICT(batch_date) DO UPDATE SET
                created_at=excluded.created_at,status=excluded.status,deal_count=excluded.deal_count,
                message_text=excluded.message_text,deals_json=excluded.deals_json
            """,
            (batch_date, now, status, len(deals), message, json.dumps(deals, ensure_ascii=False)),
        )
        row = conn.execute("SELECT * FROM daily_batches WHERE batch_date=?", (batch_date,)).fetchone()
        return dict(row)


def get_daily_batch(batch_date: str) -> dict | None:
    with connection() as conn:
        row = conn.execute("SELECT * FROM daily_batches WHERE batch_date=?", (batch_date,)).fetchone()
        return dict(row) if row else None


def recent_offers(limit: int = 50, minimum_score: int | None = None) -> list[dict]:
    query = "SELECT * FROM offers"
    params: list = []
    if minimum_score is not None:
        query += " WHERE score >= ?"
        params.append(minimum_score)
    query += " ORDER BY observed_at DESC, score DESC LIMIT ?"
    params.append(max(1, min(limit, 500)))
    with connection() as conn:
        rows = conn.execute(query, params).fetchall()

    result = []
    for row in rows:
        item = dict(row)
        payload = json.loads(item.pop("payload_json"))
        deal_score = payload.get("deal_score") or {}
        components = deal_score.get("components") or {}
        analysis = payload.get("deal_analysis") or {}

        source = analysis.get("price_reference_source")
        if source == "history":
            reference_price = analysis.get("historical_median")
        elif source == "search_distribution":
            reference_price = analysis.get("search_median")
        elif source == "serpapi_typical":
            reference_price = analysis.get("typical_price_low")
        else:
            reference_price = (
                analysis.get("historical_median")
                or analysis.get("search_median")
                or analysis.get("typical_price_low")
            )

        reasons = deal_score.get("reasons") or []
        flight = payload.get("flight") or {}
        baggage = flight.get("baggage") or {}
        connections = flight.get("connections") or []
        outbound = payload.get("outbound") or {}
        return_trip = payload.get("return") or {}

        def _reason_label(value):
            text = str(value or "").split(": +", 1)[0].strip()
            replacements = {
                "Price": "מחיר נמוך משמעותית",
                "Route": "מסלול טיסה נוח",
                "Baggage": "תנאי כבודה טובים",
                "Hours": "שעות טיסה נוחות",
                "Rarity": "הזדמנות נדירה",
            }
            return replacements.get(text, text)

        display_reasons = [_reason_label(reason) for reason in reasons if _reason_label(reason)]

        # Never claim that the price is low unless the found price is actually
        # lower than the reference price shown to the customer.
        current_price = item.get("price_ils")
        price_is_lower = False
        try:
            if current_price is not None and reference_price is not None:
                price_is_lower = float(current_price) < float(reference_price)
            elif item.get("discount_percent") is not None:
                price_is_lower = float(item.get("discount_percent") or 0) > 0
        except (TypeError, ValueError):
            price_is_lower = False

        if not price_is_lower:
            display_reasons = [
                reason for reason in display_reasons
                if reason != "מחיר נמוך משמעותית"
            ]

        if not display_reasons:
            # In fallback mode, add a price reason only when it is factually true.
            if price_is_lower and item.get("discount_percent") and item["discount_percent"] >= 15:
                display_reasons.append("מחיר נמוך משמעותית")
            if (item.get("stops") or 0) == 0:
                display_reasons.append("טיסה ישירה")
            elif (item.get("stops") or 0) == 1:
                display_reasons.append("קונקשן אחד")
            else:
                display_reasons.append("מסלול משתלם")
            display_reasons.append("נבחר לאחר השוואת אפשרויות")

        protection = payload.get("consumer_protection") or {}
        if isinstance(protection, str):
            protection = {"status": protection}
        protection_status = str(protection.get("status") or "check").lower()
        protection_map = {
            "applies": ("חלה", "applies"),
            "yes": ("חלה", "applies"),
            "not_applies": ("אינה חלה", "not-applies"),
            "no": ("אינה חלה", "not-applies"),
            "check": ("בדיקה נדרשת", "check"),
            "unknown": ("בדיקה נדרשת", "check"),
        }
        protection_label, protection_class = protection_map.get(protection_status, ("בדיקה נדרשת", "check"))

        change_cancel = payload.get("change_cancel") or payload.get("ticket_change") or {}
        if isinstance(change_cancel, str):
            change_cancel_label = change_cancel
        else:
            change_cancel_label = (
                change_cancel.get("label")
                or change_cancel.get("status_he")
                or "בכפוף לתנאי הספק"
            )

        item.update({
            "score_reasons": reasons,
            "display_reasons": display_reasons,
            "booking_url": item.get("booking_url") or payload.get("booking_url"),
            "reference_price_ils": reference_price,
            "departure_airport_name": payload.get("departure_airport_name") or flight.get("departure_airport_name"),
            "arrival_airport_name": payload.get("arrival_airport_name") or flight.get("arrival_airport_name"),
            "outbound_display": outbound.get("display_he"),
            "return_display": return_trip.get("display_he"),
            "connections": connections,
            "baggage": {
                "personal_item": baggage.get("personal_item") or {"included": True},
                "carry_on_8kg": baggage.get("carry_on_8kg") or {"included": False},
                "checked_bag_23kg": baggage.get("checked_bag_23kg") or {"included": False},
            },
            "destination_image_url": payload.get("destination_image_url") or payload.get("image_url"),
            "consumer_protection_label": protection_label,
            "consumer_protection_class": protection_class,
            "change_cancel_label": change_cancel_label,
            "cost_score": components.get("price"),
            "route_score": components.get("route"),
            "baggage_score": components.get("baggage"),
            "hours_score": components.get("hours"),
            "rarity_score": components.get("rarity"),
            # The current scoring engine reserves one combined field and does not yet
            # calculate seasonality and reliability separately. Show honest zeroes.
            "seasonality_score": 0,
            "reliability_score": 0,
            "send_reason": reasons[0].split(": +")[0] if reasons else deal_score.get("label"),
        })
        result.append(item)
    return result


def recent_scan_runs(limit: int = 20) -> list[dict]:
    with connection() as conn:
        rows = conn.execute(
            "SELECT * FROM scan_runs ORDER BY id DESC LIMIT ?", (max(1, min(limit, 200)),)
        ).fetchall()
    return [dict(row) for row in rows]


def dashboard_stats(minimum_score: int) -> dict:
    with connection() as conn:
        totals = conn.execute(
            """
            SELECT COUNT(*) AS offers_total,
                   SUM(CASE WHEN score >= ? THEN 1 ELSE 0 END) AS offers_qualified,
                   ROUND(AVG(score),1) AS average_score,
                   MAX(score) AS highest_score,
                   MAX(observed_at) AS latest_offer_at
            FROM offers
            """,
            (minimum_score,),
        ).fetchone()
        scans = conn.execute(
            "SELECT COUNT(*) AS scans_total, SUM(errors) AS scan_errors FROM scan_runs"
        ).fetchone()
    return {**dict(totals), **dict(scans)}


def all_settings() -> dict:
    with connection() as conn:
        rows = conn.execute("SELECT key,value FROM settings ORDER BY key").fetchall()
    return {row["key"]: row["value"] for row in rows}


def price_history_reference(departure_code: str, arrival_code: str, outbound_month: int, current_price: float) -> dict:
    """Return robust historical price context for a route and travel month."""
    with connection() as conn:
        rows = conn.execute(
            """
            SELECT price_ils FROM offers
            WHERE departure_code=? AND arrival_code=?
              AND CAST(strftime('%m', outbound_date) AS INTEGER)=?
            ORDER BY price_ils ASC
            LIMIT 500
            """,
            (departure_code, arrival_code, outbound_month),
        ).fetchall()
    prices = sorted(float(r["price_ils"]) for r in rows if r["price_ils"] is not None)
    if len(prices) < 8:
        return {"sample_count": len(prices), "median": None, "percentile": None}
    mid = len(prices) // 2
    median = prices[mid] if len(prices) % 2 else (prices[mid - 1] + prices[mid]) / 2
    below_or_equal = sum(1 for value in prices if value <= current_price)
    percentile = (below_or_equal / len(prices)) * 100
    return {"sample_count": len(prices), "median": round(median, 2), "percentile": round(percentile, 1)}


def save_feedback(full_name: str, email: str, phone: str, message: str) -> int:
    with connection() as conn:
        cur = conn.execute(
            """INSERT INTO feedback_messages
               (full_name,email,phone,message,created_at,email_status)
               VALUES(?,?,?,?,?,?)""",
            (full_name, email, phone, message, utc_now_iso(), "stored"),
        )
        return int(cur.lastrowid)


def mark_feedback_email_result(
    feedback_id: int, status: str, error_message: str | None = None
) -> None:
    with connection() as conn:
        conn.execute(
            """UPDATE feedback_messages
               SET email_status=?, email_error=?
               WHERE id=?""",
            (status, error_message, feedback_id),
        )


def recent_feedback(limit: int = 100) -> list[dict]:
    safe_limit = max(1, min(int(limit), 500))
    with connection() as conn:
        rows = conn.execute(
            """SELECT id,full_name,email,phone,message,created_at,
                      email_status,email_error
               FROM feedback_messages
               ORDER BY id DESC
               LIMIT ?""",
            (safe_limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def unread_feedback_count() -> int:
    """Number of feedback messages added since the admin last opened the feedback tab."""
    try:
        last_seen_id = int(get_setting("admin_feedback_last_seen_id", "0") or 0)
    except (TypeError, ValueError):
        last_seen_id = 0
    with connection() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS count FROM feedback_messages WHERE id > ?",
            (last_seen_id,),
        ).fetchone()
    return int(row["count"] or 0)


def mark_feedback_seen() -> None:
    """Mark all feedback currently in the database as seen by the admin."""
    with connection() as conn:
        row = conn.execute("SELECT MAX(id) AS max_id FROM feedback_messages").fetchone()
        max_id = int(row["max_id"] or 0)
    set_setting("admin_feedback_last_seen_id", str(max_id))
