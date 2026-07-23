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
            """
        )


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
        item.update({
            "score_reasons": reasons,
            "booking_url": item.get("booking_url") or payload.get("booking_url"),
            "reference_price_ils": reference_price,
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
