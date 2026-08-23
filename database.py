import json
import sqlite3
from urllib.parse import quote_plus
from contextlib import contextmanager
from datetime import datetime, timezone, timedelta
from config import DB_PATH
from baggage_pricing import policy_roundtrip_total, policy_personal_item_included

# Curated destination landmark photography. Wikimedia Commons Special:Redirect/file
# URLs are stable remote image URLs and require no additional flight/search API calls.
DESTINATION_LANDMARK_IMAGES = {"ATH": "https://commons.wikimedia.org/wiki/Special:Redirect/file/Parthenon_from_west.jpg", "LCA": "https://commons.wikimedia.org/wiki/Special:Redirect/file/Church_of_Saint_Lazarus,_Larnaca,_Cyprus.jpg", "BUD": "https://commons.wikimedia.org/wiki/Special:Redirect/file/Hungarian_Parliament_Building_from_Fisherman%27s_Bastion.jpg", "VIE": "https://commons.wikimedia.org/wiki/Special:Redirect/file/Schloss_Schoenbrunn_Wien_2014_%28Zuschnitt_1%29.jpg", "SOF": "https://commons.wikimedia.org/wiki/Special:Redirect/file/Alexander_Nevsky_Cathedral_in_Sofia.jpg", "PRG": "https://commons.wikimedia.org/wiki/Special:Redirect/file/Prague_07-2016_View_from_Old_Town_Hall_Tower_img3.jpg", "FCO": "https://commons.wikimedia.org/wiki/Special:Redirect/file/Colosseum_in_Rome,_Italy_-_April_2007.jpg", "MXP": "https://commons.wikimedia.org/wiki/Special:Redirect/file/Milan_Cathedral_from_Piazza_del_Duomo.jpg", "CDG": "https://commons.wikimedia.org/wiki/Special:Redirect/file/Eiffel_Tower_from_the_Tour_Montparnasse_3,_Paris_May_2014.jpg", "AMS": "https://commons.wikimedia.org/wiki/Special:Redirect/file/KeizersgrachtReguliersgrachtAmsterdam.jpg", "BCN": "https://commons.wikimedia.org/wiki/Special:Redirect/file/Sagrada_Familia_01.jpg", "MAD": "https://commons.wikimedia.org/wiki/Special:Redirect/file/Palacio_de_Comunicaciones_-_47.jpg", "LIS": "https://commons.wikimedia.org/wiki/Special:Redirect/file/Torre_de_Belem_1.jpg", "LHR": "https://commons.wikimedia.org/wiki/Special:Redirect/file/London_Eye_Twilight_April_2006.jpg", "BER": "https://commons.wikimedia.org/wiki/Special:Redirect/file/Brandenburger_Tor_abends.jpg", "MUC": "https://commons.wikimedia.org/wiki/Special:Redirect/file/Neues_Rathaus_Muenchen.jpg", "ZRH": "https://commons.wikimedia.org/wiki/Special:Redirect/file/Zuerichsee_Zuerich.jpg", "BRU": "https://commons.wikimedia.org/wiki/Special:Redirect/file/Brussels_Grote_Markt.jpg", "OTP": "https://commons.wikimedia.org/wiki/Special:Redirect/file/Palace_of_Parliament_Bucharest.jpg", "KRK": "https://commons.wikimedia.org/wiki/Special:Redirect/file/Krakow_-_Main_Market_Square.jpg", "WAW": "https://commons.wikimedia.org/wiki/Special:Redirect/file/Warsaw_Old_Town_Market_Square.jpg", "TBS": "https://commons.wikimedia.org/wiki/Special:Redirect/file/Tbilisi_view.jpg", "EVN": "https://commons.wikimedia.org/wiki/Special:Redirect/file/Yerevan_Opera.jpg", "BEG": "https://commons.wikimedia.org/wiki/Special:Redirect/file/Belgrade_skyline.jpg", "SKP": "https://commons.wikimedia.org/wiki/Special:Redirect/file/Stone_Bridge_Skopje.jpg", "TGD": "https://commons.wikimedia.org/wiki/Special:Redirect/file/Podgorica_Millennium_Bridge.jpg", "ZAG": "https://commons.wikimedia.org/wiki/Special:Redirect/file/Zagreb_Cathedral.jpg", "LJU": "https://commons.wikimedia.org/wiki/Special:Redirect/file/Ljubljana_from_the_castle.jpg", "BKK": "https://commons.wikimedia.org/wiki/Special:Redirect/file/Wat_Arun_Bangkok.jpg", "JFK": "https://commons.wikimedia.org/wiki/Special:Redirect/file/Manhattan_from_Weehawken,_NJ.jpg"}

# Airports serving the same city reuse the same curated destination photography.
DESTINATION_LANDMARK_IMAGES.update({
    "CIA": DESTINATION_LANDMARK_IMAGES["FCO"],
    "BGY": DESTINATION_LANDMARK_IMAGES["MXP"],
    "LIN": DESTINATION_LANDMARK_IMAGES["MXP"],
})


def _full_roundtrip_google_url(departure: str, arrival: str, outbound_date: str, return_date: str) -> str:
    """Always open a NEW full round-trip Google Flights search, never a saved return-stage result."""
    q = f"round trip flights from {departure} to {arrival} departing {outbound_date} returning {return_date}"
    return "https://www.google.com/travel/flights?hl=en&curr=ILS&q=" + quote_plus(q)


def _public_airline_logo(airline: str | None, flight_number: str | None = None, stored_logo: str | None = None) -> str | None:
    if stored_logo:
        return stored_logo
    code = None
    if flight_number:
        token = str(flight_number).strip().upper().split()[0].replace("-", "")
        if 2 <= len(token) <= 3 and token.isalnum():
            code = token
    if not code:
        common = {
            "wizz air": "W6", "arkia": "IZ", "israir": "6H", "israir airlines": "6H",
            "aegean": "A3", "aegean airlines": "A3", "el al": "LY", "bluebird airways": "BZ",
            "ryanair": "FR", "easyjet": "U2", "air france": "AF", "klm": "KL",
            "lufthansa": "LH", "ita airways": "AZ", "british airways": "BA",
            "etihad airways": "EY", "emirates": "EK", "turkish airlines": "TK",
        }
        code = common.get(str(airline or "").strip().lower())
    return f"https://www.gstatic.com/flights/airline_logos/70px/{code}.png" if code else None



def _arrival_days_after(departure_date, arrival_date):
    try:
        dep = datetime.fromisoformat(str(departure_date)[:10]).date()
        arr = datetime.fromisoformat(str(arrival_date)[:10]).date()
        return max(0, (arr - dep).days)
    except Exception:
        return 0


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

            CREATE TABLE IF NOT EXISTS site_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                visitor_id TEXT,
                member_id INTEGER,
                path TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY(member_id) REFERENCES members(id)
            );
            CREATE INDEX IF NOT EXISTS idx_site_events_type_date ON site_events(event_type, created_at);
            CREATE INDEX IF NOT EXISTS idx_site_events_visitor ON site_events(visitor_id);

            CREATE TABLE IF NOT EXISTS payments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                member_id INTEGER,
                trip_id INTEGER,
                plan TEXT,
                amount_ils REAL NOT NULL,
                status TEXT NOT NULL DEFAULT 'paid',
                provider TEXT,
                provider_reference TEXT,
                paid_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(member_id) REFERENCES members(id),
                FOREIGN KEY(trip_id) REFERENCES trip_requests(id)
            );

            CREATE TABLE IF NOT EXISTS booking_clicks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                visitor_id TEXT,
                member_id INTEGER,
                offer_id INTEGER,
                destination_code TEXT,
                airline TEXT,
                supplier TEXT,
                price_ils REAL,
                score INTEGER,
                outbound_date TEXT,
                return_date TEXT,
                booking_url TEXT,
                clicked_at TEXT NOT NULL,
                FOREIGN KEY(member_id) REFERENCES members(id)
            );
            CREATE INDEX IF NOT EXISTS idx_booking_clicks_clicked_at ON booking_clicks(clicked_at);
            CREATE INDEX IF NOT EXISTS idx_booking_clicks_destination ON booking_clicks(destination_code);
            CREATE INDEX IF NOT EXISTS idx_payments_paid_at ON payments(paid_at);
            CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(status);

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
        if "whatsapp_opt_in" not in member_columns:
            conn.execute("ALTER TABLE members ADD COLUMN whatsapp_opt_in INTEGER NOT NULL DEFAULT 0")
        if "whatsapp_opt_in_at" not in member_columns:
            conn.execute("ALTER TABLE members ADD COLUMN whatsapp_opt_in_at TEXT")

        if "free_scan_count" not in trip_columns:
            conn.execute("ALTER TABLE trip_requests ADD COLUMN free_scan_count INTEGER NOT NULL DEFAULT 0")
        if "free_scan_last_at" not in trip_columns:
            conn.execute("ALTER TABLE trip_requests ADD COLUMN free_scan_last_at TEXT")
        if "free_scan_last_status" not in trip_columns:
            conn.execute("ALTER TABLE trip_requests ADD COLUMN free_scan_last_status TEXT")

        offer_columns = {row["name"] for row in conn.execute("PRAGMA table_info(offers)").fetchall()}
        if "trip_id" not in offer_columns:
            conn.execute("ALTER TABLE offers ADD COLUMN trip_id INTEGER")
        if "last_seen_at" not in offer_columns:
            conn.execute("ALTER TABLE offers ADD COLUMN last_seen_at TEXT")
            conn.execute("UPDATE offers SET last_seen_at=observed_at WHERE last_seen_at IS NULL")

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
    with connection() as conn:
        row = conn.execute("SELECT searches_planned FROM scan_runs WHERE id=?", (run_id,)).fetchone()
        planned = int(row["searches_planned"] or 0) if row else completed
        status = "success" if errors == 0 and completed >= planned else "partial" if completed > 0 else "failed"
        conn.execute(
            """UPDATE scan_runs SET finished_at=?,status=?,searches_completed=?,offers_found=?,errors=?,error_message=? WHERE id=?""",
            (utc_now_iso(), status, completed, offers, errors, error_message, run_id),
        )


def update_scan_progress(run_id: int, completed: int, offers: int, errors: int) -> None:
    with connection() as conn:
        conn.execute(
            "UPDATE scan_runs SET searches_completed=?,offers_found=?,errors=? WHERE id=?",
            (completed, offers, errors, run_id),
        )


def request_scan_stop() -> None:
    set_setting("manual_scan_stop_requested", "1")


def clear_scan_stop() -> None:
    set_setting("manual_scan_stop_requested", "0")


def scan_stop_requested() -> bool:
    return get_setting("manual_scan_stop_requested", "0") == "1"


def offers_for_scan_run(run_id: int, limit: int = 200) -> list[dict]:
    with connection() as conn:
        rows = conn.execute(
            """SELECT id,scan_run_id,observed_at,departure_code,arrival_code,outbound_date,return_date,
                      price_ils,score,airline,payload_json
               FROM offers WHERE scan_run_id=? ORDER BY score DESC, observed_at DESC LIMIT ?""",
            (run_id, max(1, min(limit, 500))),
        ).fetchall()
    out=[]
    for row in rows:
        item=dict(row)
        payload=json.loads(item.pop("payload_json"))
        payload.update(item)
        with connection() as conn:
            prior = conn.execute(
                """SELECT 1 FROM offers WHERE id<>? AND route=? AND outbound_date=? AND return_date=?
                   AND price_ils=? AND COALESCE(airline,'')=COALESCE(?, '') AND observed_at < ? LIMIT 1""",
                (item.get("id"), payload.get("route"), item.get("outbound_date"), item.get("return_date"),
                 item.get("price_ils"), item.get("airline"), item.get("observed_at")),
            ).fetchone()
        payload["is_new_in_scan"] = prior is None
        out.append(payload)
    return out


def insert_offer(scan_run_id: int, offer: dict) -> bool:
    flight = offer["flight"]
    analysis = offer["deal_analysis"]
    with connection() as conn:
        existing = conn.execute(
            """SELECT 1 FROM offers WHERE route=? AND outbound_date=? AND return_date=?
               AND price_ils=? AND COALESCE(airline,'')=COALESCE(?, '') LIMIT 1""",
            (offer["route"], offer["outbound_date"], offer["return_date"], flight["price"], flight.get("airline")),
        ).fetchone()
        if existing:
            conn.execute(
                """UPDATE offers SET last_seen_at=?, scan_run_id=?, payload_json=?
                   WHERE route=? AND outbound_date=? AND return_date=? AND price_ils=? AND COALESCE(airline,'')=COALESCE(?, '')""",
                (offer["observed_at"], scan_run_id, json.dumps(offer, ensure_ascii=False),
                 offer["route"], offer["outbound_date"], offer["return_date"], flight["price"], flight.get("airline")),
            )
        conn.execute(
            """
            INSERT OR IGNORE INTO offers(
                scan_run_id,observed_at,route,departure_code,arrival_code,outbound_date,return_date,
                price_ils,typical_low_ils,typical_high_ils,discount_percent,score,score_label,airline,
                stops,total_duration_minutes,actual_flight_duration_minutes,departure_time,arrival_time,
                booking_url,destination_name,country_flag,trip_id,payload_json
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                scan_run_id, offer["observed_at"], offer["route"], offer["departure_code"], offer["arrival_code"],
                offer["outbound_date"], offer["return_date"], flight["price"], analysis.get("typical_price_low"),
                analysis.get("typical_price_high"), analysis.get("below_typical_low_percent"), offer["deal_score"]["score"],
                offer["deal_score"]["label"], flight.get("airline"), flight.get("stops"),
                flight.get("total_duration_minutes"), flight.get("actual_flight_duration_minutes"),
                flight.get("departure_time"), flight.get("arrival_time"), offer.get("booking_url"),
                offer.get("destination_name"), offer.get("country_flag"), offer.get("trip_id"), json.dumps(offer, ensure_ascii=False),
            ),
        )
        if not existing:
            conn.execute(
                """UPDATE offers SET last_seen_at=observed_at
                   WHERE scan_run_id=? AND route=? AND outbound_date=? AND return_date=? AND price_ils=?""",
                (scan_run_id, offer["route"], offer["outbound_date"], offer["return_date"], flight["price"]),
            )
        return existing is None


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
        payload["offer_id"] = item.get("id")
        payload["scan_run_id"] = item.get("scan_run_id")
        payload["observed_at"] = item.get("observed_at") or payload.get("observed_at")
        payload["last_seen_at"] = item.get("last_seen_at") or item.get("observed_at") or payload.get("observed_at")
        if item.get("trip_id") is not None:
            payload["trip_id"] = item.get("trip_id")
        deal_score = payload.get("deal_score") or {}
        components = deal_score.get("components") or {}
        analysis = payload.get("deal_analysis") or {}

        # Always initialize before any branch can reference it.
        display_reasons = []

        source = analysis.get("price_reference_source")
        if source == "history" and analysis.get("price_reference_reliable"):
            reference_price = analysis.get("historical_median")
        elif source == "serpapi_typical" and analysis.get("price_reference_reliable"):
            reference_price = analysis.get("typical_price_low")
        else:
            reference_price = None

        reasons = deal_score.get("reasons") or []
        flight = payload.get("flight") or {}
        booking_choice_reason_he = flight.get("booking_choice_reason_he")
        baggage = flight.get("baggage") or {}
        out_airline = flight.get("outbound_airline_code") or flight.get("outbound_airline") or flight.get("airline_code") or flight.get("airline") or item.get("airline")
        ret_airline = flight.get("return_airline_code") or flight.get("return_airline") or flight.get("airline_code") or flight.get("airline") or item.get("airline")

        personal = baggage.get("personal_item") or {}
        if personal.get("included") is not True and policy_personal_item_included(out_airline, ret_airline):
            personal["included"] = True
            personal["known"] = True
            personal["source"] = "airline_policy"
            baggage["personal_item"] = personal

        for _kind, _key in (("carry", "carry_on_8kg"), ("checked", "checked_bag_23kg")):
            _item = baggage.get(_key) or {}
            if _item.get("included") is not True:
                _out = _item.get("outbound_price_ils")
                _ret = _item.get("return_price_ils")
                _each = _item.get("price_each_way")
                if not isinstance(_out, (int, float)) and isinstance(_each, (int, float)):
                    _out = _each
                if not isinstance(_ret, (int, float)) and isinstance(_each, (int, float)):
                    _ret = _each
                _total = _item.get("roundtrip_price_ils")
                if not isinstance(_total, (int, float)):
                    _total = policy_roundtrip_total(out_airline, ret_airline, _kind, _out, _ret)
                if isinstance(_total, (int, float)):
                    _item["roundtrip_price_ils"] = _total
                    _item["known"] = True
                    _item["price_estimated"] = not (
                        isinstance(_out, (int, float)) and isinstance(_ret, (int, float))
                    )
                    baggage[_key] = _item
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
        display_reasons = [r for r in display_reasons if "טרם חושב" not in r and "היסטוריה" not in r and "נדירות" not in r and "0+" not in r]
        # Add the supplier-choice explanation only after display_reasons exists,
        # so opening the site cannot raise UnboundLocalError and the explanation
        # is not overwritten by the list construction above.
        if booking_choice_reason_he:
            display_reasons.insert(0, booking_choice_reason_he)

        # Never show history/rarity copy unless there is enough actual stored
        # route history to support it.
        has_price_history = bool(
            analysis.get("price_reference_source") == "history"
            and (analysis.get("historical_sample_count") or 0) >= 8
        )
        if not has_price_history:
            display_reasons = [
                reason for reason in display_reasons
                if reason not in ("הזדמנות נדירה", "אין מספיק היסטוריה למדד נדירות")
                and "היסטוריה" not in reason
                and "נדירות" not in reason
            ]

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
            "check": ("יש לבדוק מול הספק", "check"),
            "unknown": ("יש לבדוק מול הספק", "check"),
        }
        protection_label, protection_class = protection_map.get(protection_status, ("יש לבדוק מול הספק", "check"))

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
                        "booking_url": payload.get("booking_url") or item.get("booking_url"),
            "booking_token": flight.get("booking_token"),
            "reference_price_ils": reference_price,
            "price_reference_reliable": bool(analysis.get("price_reference_reliable")),
            "departure_airport_name": payload.get("departure_airport_name") or flight.get("departure_airport_name"),
            "arrival_airport_name": payload.get("arrival_airport_name") or flight.get("arrival_airport_name"),
            "outbound_display": outbound.get("display_he"),
            "return_display": return_trip.get("display_he"),
            "airline_logo": _public_airline_logo(
                item.get("airline") or flight.get("airline"),
                flight.get("flight_number"),
                flight.get("airline_logo"),
            ),
            "return_airline_logo": _public_airline_logo(
                flight.get("return_airline") or item.get("airline") or flight.get("airline"),
                flight.get("return_flight_number"),
                flight.get("return_airline_logo"),
            ),
            "return_airline": flight.get("return_airline"),
            "return_departure_time": flight.get("return_departure_time"),
            "return_arrival_time": flight.get("return_arrival_time"),
            "arrival_days_after": _arrival_days_after(item.get("outbound_date"), flight.get("arrival_date") or item.get("outbound_date")),
            "return_arrival_days_after": _arrival_days_after(item.get("return_date"), flight.get("return_arrival_date") or item.get("return_date")),
            "return_total_duration_minutes": flight.get("return_total_duration_minutes"),
            "return_connections": flight.get("return_connections") or [],
            "return_stops": flight.get("return_stops") or 0,
            "booking_supplier": flight.get("booking_supplier"),
            "booking_supplier_price_ils": flight.get("booking_supplier_price_ils"),
            "booking_supplier_approved": flight.get("booking_supplier_approved"),
            "booking_supplier_is_direct": flight.get("booking_supplier_is_direct"),
            "booking_choice_reason_he": flight.get("booking_choice_reason_he"),
            "booking_choice_reason_en": flight.get("booking_choice_reason_en"),
            "cheapest_any_supplier": flight.get("cheapest_any_supplier"),
            "cheapest_any_price_ils": flight.get("cheapest_any_price_ils"),
            "cheapest_any_is_separate": flight.get("cheapest_any_is_separate"),
            "direct_supplier": flight.get("direct_supplier"),
            "direct_supplier_price_ils": flight.get("direct_supplier_price_ils"),
            "booking_options_checked": flight.get("booking_options_checked"),
            "has_price_history": has_price_history,
            "connections": connections,
            "baggage": {
                "personal_item": baggage.get("personal_item") or {"included": None, "known": False},
                "carry_on_8kg": baggage.get("carry_on_8kg") or {"included": None, "known": False},
                "checked_bag_23kg": baggage.get("checked_bag_23kg") or {"included": None, "known": False},
            },
            "destination_image_url": (
                payload.get("destination_image_url")
                or payload.get("image_url")
                or DESTINATION_LANDMARK_IMAGES.get(str(item.get("arrival_code") or "").upper())
            ),
            "consumer_protection_label": protection_label,
            "consumer_protection_class": protection_class,
            "change_cancel_label": change_cancel_label,
            "cost_score": components.get("price"),
            "route_score": components.get("route"),
            "baggage_score": components.get("baggage"),
            "hours_score": components.get("time_value", components.get("hours")),
            "time_value_score": components.get("time_value", components.get("hours", 0)),
            "rarity_score": components.get("rarity"),
            # The current scoring engine reserves one combined field and does not yet
            # calculate seasonality and reliability separately. Show honest zeroes.
            "seasonality_score": None,
            "reliability_score": None,
            "send_reason": reasons[0].split(": +")[0] if reasons else deal_score.get("label"),
        })
        result.append(item)
    return result



def latest_scan_cycle_index() -> int:
    with connection() as conn:
        row = conn.execute("SELECT COUNT(*) AS n FROM scan_runs").fetchone()
    return int(row["n"] or 0)


def recent_scan_runs(limit: int = 20) -> list[dict]:
    # A web worker can be restarted mid-scan. Do not leave such rows as "running" forever.
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=15)).isoformat()
    with connection() as conn:
        conn.execute(
            """UPDATE scan_runs
               SET status='failed', finished_at=?, error_message=COALESCE(error_message,'Scan interrupted before completion')
               WHERE status='running' AND started_at < ?""",
            (utc_now_iso(), cutoff),
        )
        rows = conn.execute(
            "SELECT * FROM scan_runs ORDER BY id DESC LIMIT ?", (max(1, min(limit, 200)),)
        ).fetchall()
    return [dict(row) for row in rows]



def record_site_event(event_type: str, visitor_id: str | None = None, member_id: int | None = None, path: str | None = None) -> None:
    """Store lightweight first-party analytics. No IP address is stored."""
    try:
        with connection() as conn:
            conn.execute(
                "INSERT INTO site_events(event_type,visitor_id,member_id,path,created_at) VALUES(?,?,?,?,?)",
                (event_type, visitor_id, member_id, path, utc_now_iso()),
            )
    except Exception:
        # Analytics must never break the customer site.
        return


def record_payment(member_id: int | None, trip_id: int | None, plan: str | None,
                   amount_ils: float, provider: str | None = None,
                   provider_reference: str | None = None, status: str = "paid",
                   paid_at: str | None = None) -> None:
    """Payment ledger hook for the future checkout integration."""
    now = utc_now_iso()
    with connection() as conn:
        conn.execute(
            """INSERT INTO payments(member_id,trip_id,plan,amount_ils,status,provider,provider_reference,paid_at,created_at)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (member_id, trip_id, plan, float(amount_ils), status, provider,
             provider_reference, paid_at or now, now),
        )


def _month_key(value: str | None) -> str:
    return str(value or "")[:7]


def _day_key(value: str | None) -> str:
    return str(value or "")[:10]



def record_booking_click(visitor_id: str | None = None, member_id: int | None = None,
                         offer_id: int | None = None, destination_code: str | None = None,
                         airline: str | None = None, supplier: str | None = None,
                         price_ils: float | None = None, score: int | None = None,
                         outbound_date: str | None = None, return_date: str | None = None,
                         booking_url: str | None = None) -> None:
    try:
        with connection() as conn:
            conn.execute(
                """INSERT INTO booking_clicks(
                    visitor_id,member_id,offer_id,destination_code,airline,supplier,
                    price_ils,score,outbound_date,return_date,booking_url,clicked_at
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
                (visitor_id, member_id, offer_id, destination_code, airline, supplier,
                 price_ils, score, outbound_date, return_date, booking_url, utc_now_iso()),
            )
    except Exception:
        return


def business_analytics(months_back: int = 12) -> dict:
    """Business dashboard metrics. Registrations/trips can use historic DB data;
    visits/payments start accumulating from the version that introduced tracking."""
    today = datetime.now(timezone.utc).date()

    def shift_month(year, month, delta):
        x = year * 12 + (month - 1) + delta
        return x // 12, x % 12 + 1

    month_keys = []
    for delta in range(-(months_back - 1), 1):
        y, m = shift_month(today.year, today.month, delta)
        month_keys.append(f"{y:04d}-{m:02d}")

    with connection() as conn:
        members = [dict(r) for r in conn.execute(
            "SELECT id,created_at FROM members WHERE status='active'"
        ).fetchall()]
        trips = [dict(r) for r in conn.execute(
            """SELECT id,member_id,created_at,subscription_plan,subscription_status
               FROM trip_requests"""
        ).fetchall()]
        events = [dict(r) for r in conn.execute(
            """SELECT event_type,visitor_id,member_id,created_at
               FROM site_events WHERE event_type='site_visit'"""
        ).fetchall()]
        payments = [dict(r) for r in conn.execute(
            """SELECT member_id,trip_id,plan,amount_ils,status,paid_at
               FROM payments WHERE status='paid'"""
        ).fetchall()]
        booking_clicks = [dict(r) for r in conn.execute(
            """SELECT visitor_id,member_id,offer_id,destination_code,airline,supplier,
                      price_ils,score,outbound_date,return_date,clicked_at
               FROM booking_clicks"""
        ).fetchall()]

    plan_names = ("calm", "daily", "intensive")

    # First trip date per member = first time they actually used Ariella My.
    first_trip = {}
    for t in trips:
        mid = t.get("member_id")
        day = _day_key(t.get("created_at"))
        if mid and day and (mid not in first_trip or day < first_trip[mid]):
            first_trip[mid] = day

    def aggregate_month(month):
        regs = {m["id"] for m in members if _month_key(m.get("created_at")) == month}
        visitors = {e.get("visitor_id") for e in events
                    if _month_key(e.get("created_at")) == month and e.get("visitor_id")}
        ariella = {mid for mid, day in first_trip.items() if day[:7] == month}
        plan_counts = {
            plan: len({t.get("member_id") for t in trips
                       if _month_key(t.get("created_at")) == month
                       and t.get("subscription_plan") == plan and t.get("member_id")})
            for plan in plan_names
        }
        revenue = sum(float(p.get("amount_ils") or 0) for p in payments
                      if _month_key(p.get("paid_at")) == month)
        return {
            "month": month,
            "registrations": len(regs),
            "visitors": len(visitors),
            "ariella_users": len(ariella),
            "calm": plan_counts["calm"],
            "daily": plan_counts["daily"],
            "intensive": plan_counts["intensive"],
            "revenue": round(revenue, 2),
        }

    monthly = []
    for month in reversed(month_keys):  # newest first
        row = aggregate_month(month)
        prev = aggregate_month(f"{int(month[:4])-1:04d}-{month[5:7]}")
        row["prev_year"] = prev
        monthly.append(row)

    # Daily breakdown for every displayed month.
    daily_by_month = {}
    for month in month_keys:
        days = set()
        for m in members:
            if _month_key(m.get("created_at")) == month:
                days.add(_day_key(m.get("created_at")))
        for e in events:
            if _month_key(e.get("created_at")) == month:
                days.add(_day_key(e.get("created_at")))
        for t in trips:
            if _month_key(t.get("created_at")) == month:
                days.add(_day_key(t.get("created_at")))
        for p in payments:
            if _month_key(p.get("paid_at")) == month:
                days.add(_day_key(p.get("paid_at")))

        rows = []
        for day in sorted(d for d in days if d):
            regs = {m["id"] for m in members if _day_key(m.get("created_at")) == day}
            visitors = {e.get("visitor_id") for e in events
                        if _day_key(e.get("created_at")) == day and e.get("visitor_id")}
            ariella = {mid for mid, first_day in first_trip.items() if first_day == day}
            plans = {
                plan: len({t.get("member_id") for t in trips
                           if _day_key(t.get("created_at")) == day
                           and t.get("subscription_plan") == plan and t.get("member_id")})
                for plan in plan_names
            }
            revenue = sum(float(p.get("amount_ils") or 0) for p in payments
                          if _day_key(p.get("paid_at")) == day)
            rows.append({
                "day": day, "registrations": len(regs), "visitors": len(visitors),
                "ariella_users": len(ariella), "calm": plans["calm"],
                "daily": plans["daily"], "intensive": plans["intensive"],
                "revenue": round(revenue, 2),
            })
        daily_by_month[month] = rows

    # Annual summary for every year represented in any business data, plus current year.
    years = {today.year}
    for rows, key in ((members, "created_at"), (trips, "created_at"), (events, "created_at"), (payments, "paid_at")):
        for row in rows:
            try:
                years.add(int(str(row.get(key) or "")[:4]))
            except Exception:
                pass

    annual = []
    for year in sorted(years, reverse=True):
        prefix = f"{year:04d}-"
        regs = {m["id"] for m in members if str(m.get("created_at") or "").startswith(prefix)}
        visitors = {e.get("visitor_id") for e in events
                    if str(e.get("created_at") or "").startswith(prefix) and e.get("visitor_id")}
        ariella = {mid for mid, day in first_trip.items() if day.startswith(prefix)}
        plans = {
            plan: len({t.get("member_id") for t in trips
                       if str(t.get("created_at") or "").startswith(prefix)
                       and t.get("subscription_plan") == plan and t.get("member_id")})
            for plan in plan_names
        }
        revenue = sum(float(p.get("amount_ils") or 0) for p in payments
                      if str(p.get("paid_at") or "").startswith(prefix))
        annual.append({
            "year": year, "registrations": len(regs), "visitors": len(visitors),
            "ariella_users": len(ariella), "calm": plans["calm"],
            "daily": plans["daily"], "intensive": plans["intensive"],
            "revenue": round(revenue, 2),
        })


    # Demand analytics from Ariella trip requests.
    destination_counts = {}
    month_counts = {}
    party_sizes = []
    composition_counts = {}
    trip_lengths = []

    with connection() as conn:
        trip_rows = [dict(r) for r in conn.execute(
            "SELECT answers_json,created_at FROM trip_requests"
        ).fetchall()]

    for row in trip_rows:
        try:
            answers = json.loads(row.get("answers_json") or "{}")
        except Exception:
            answers = {}

        destinations = answers.get("destinations") or answers.get("destination_codes") or []
        if isinstance(destinations, str):
            destinations = [x.strip().upper() for x in destinations.replace(";", ",").split(",") if x.strip()]
        specific = answers.get("destination") or answers.get("destination_code")
        if specific:
            destinations = list(destinations) + [str(specific).upper()]
        for dest in set(str(x).upper() for x in destinations if x):
            destination_counts[dest] = destination_counts.get(dest, 0) + 1

        travel_month = str(answers.get("travel_month") or "")[:7]
        departure_date = str(answers.get("departure_date") or "")[:10]
        if not travel_month and departure_date:
            travel_month = departure_date[:7]
        if travel_month:
            month_counts[travel_month] = month_counts.get(travel_month, 0) + 1

        adults = answers.get("adults")
        children = answers.get("children")
        infants = answers.get("infants")
        try:
            adults = int(adults or 0); children = int(children or 0); infants = int(infants or 0)
            size = adults + children + infants
            if size > 0:
                party_sizes.append(size)
                if children or infants:
                    key = "משפחה"
                elif adults == 1:
                    key = "יחיד"
                elif adults == 2:
                    key = "זוג"
                else:
                    key = "קבוצה"
                composition_counts[key] = composition_counts.get(key, 0) + 1
        except Exception:
            pass

        try:
            if departure_date and answers.get("return_date"):
                dep = datetime.fromisoformat(departure_date).date()
                ret = datetime.fromisoformat(str(answers.get("return_date"))[:10]).date()
                nights = (ret - dep).days
                if nights > 0:
                    trip_lengths.append(nights)
        except Exception:
            pass

    demand = {
        "top_destinations": sorted(
            [{"destination": k, "count": v} for k, v in destination_counts.items()],
            key=lambda x: (-x["count"], x["destination"])
        )[:20],
        "travel_months": sorted(
            [{"month": k, "count": v} for k, v in month_counts.items()],
            key=lambda x: x["month"]
        ),
        "average_party_size": round(sum(party_sizes)/len(party_sizes), 1) if party_sizes else 0,
        "composition": sorted(
            [{"type": k, "count": v} for k, v in composition_counts.items()],
            key=lambda x: -x["count"]
        ),
        "average_trip_length": round(sum(trip_lengths)/len(trip_lengths), 1) if trip_lengths else 0,
    }

    booking_click_summary = {
        "total_clicks": len(booking_clicks),
        "unique_clickers": len({c.get("member_id") or c.get("visitor_id") for c in booking_clicks if c.get("member_id") or c.get("visitor_id")}),
        "by_destination": sorted(
            [
                {"destination": dest, "clicks": sum(1 for c in booking_clicks if c.get("destination_code") == dest)}
                for dest in {c.get("destination_code") for c in booking_clicks if c.get("destination_code")}
            ],
            key=lambda x: -x["clicks"]
        )[:20],
        "recent": sorted(booking_clicks, key=lambda x: x.get("clicked_at") or "", reverse=True)[:100],
    }


    overview = {
        "registered_total": len({m["id"] for m in members}),
        "visitors_total": len({e.get("visitor_id") for e in events if e.get("visitor_id")}),
        "ariella_users_total": len(first_trip),
        "revenue_current_month": monthly[0]["revenue"] if monthly else 0,
        "revenue_current_year": next((r["revenue"] for r in annual if r["year"] == today.year), 0),
    }
    return {
        "overview": overview,
        "monthly": monthly,
        "daily_by_month": daily_by_month,
        "annual": annual,
        "demand": demand,
        "booking_clicks": booking_click_summary,
        "tracking_started_note": "כניסות לאתר, לחיצות להזמנה והכנסות נאספות מהגרסה שבה הופעל המעקב; הרשמות ובקשות חופשה משתמשות גם בנתונים הקיימים.",
    }


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
