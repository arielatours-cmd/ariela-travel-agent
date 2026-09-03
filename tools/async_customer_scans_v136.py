from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
p = ROOT / "public_site.py"
text = p.read_text(encoding="utf-8")

# Customer-triggered external scans must never block the browser request. Render's
# sync Gunicorn worker has a finite timeout and SerpApi can legitimately take
# longer than that. Keep DB-first synchronous; only the bounded external work runs
# in a daemon thread and writes its result back to the saved vacation.
if "import threading\n" not in text:
    text = text.replace("import sqlite3\n", "import sqlite3\nimport threading\n", 1)

helper_marker = '\n@site.post("/trip/<int:trip_id>/free-alternative")\n'
helper = r'''

_customer_scan_threads = {}
_customer_scan_threads_lock = threading.Lock()


def _customer_scan_worker(trip_id: int, scan_answers: dict, mode: str = "initial", choice: str = ""):
    """Run one bounded personal scan outside the HTTP request and persist results."""
    try:
        result = run_customer_trip_search(trip_id, dict(scan_answers))
        status = str(result.get("status") or "unknown")
        api_used = int(result.get("api_requests") or 0)
    except Exception:
        result = {}
        status = "search_error"
        api_used = 0

    try:
        with _db() as conn:
            row = conn.execute("SELECT * FROM trip_requests WHERE id=?", (trip_id,)).fetchone()
        if not row:
            return
        trip = _trip_dict(row)
        answers = dict(trip.get("answers") or {})
        refreshed = _recent_inventory_48h()

        if mode == "initial":
            matches = _customer_deal_choices(refreshed, trip, limit=5)
            if matches:
                _pin_offer_ids_to_trip(trip_id, answers, matches)
        elif mode == "other_destination":
            answers["_alternative_other_destination"] = True
            answers["_second_chance_used"] = True
            answers["_second_chance_choice"] = "other_destination"
            check_trip = dict(trip)
            check_trip["answers"] = answers
            matches = _same_dates_other_destination_db_matches(refreshed, check_trip, limit=5)
            if matches:
                _pin_offer_ids_to_trip(trip_id, answers, matches)
            else:
                answers["_second_chance_exhausted"] = True
                with _db() as conn:
                    conn.execute("UPDATE trip_requests SET answers_json=? WHERE id=?", (json.dumps(answers, ensure_ascii=False), trip_id))
                    conn.commit()
        elif mode == "nearby_dates":
            answers["_second_chance_used"] = True
            answers["_second_chance_choice"] = "nearby_dates"
            check_trip = dict(trip)
            check_trip["answers"] = answers
            matches = _customer_alternative_choices(refreshed, check_trip, limit=5)
            if matches:
                _pin_offer_ids_to_trip(trip_id, answers, matches)
            else:
                answers["_second_chance_exhausted"] = True
                with _db() as conn:
                    conn.execute("UPDATE trip_requests SET answers_json=? WHERE id=?", (json.dumps(answers, ensure_ascii=False), trip_id))
                    conn.commit()

        with _db() as conn:
            if api_used > 0:
                conn.execute(
                    "UPDATE trip_requests SET free_scan_count=COALESCE(free_scan_count,0)+1, free_scan_last_at=?, free_scan_last_status=? WHERE id=?",
                    (utc_now_iso(), status, trip_id),
                )
            else:
                conn.execute(
                    "UPDATE trip_requests SET free_scan_last_at=?, free_scan_last_status=? WHERE id=?",
                    (utc_now_iso(), status, trip_id),
                )
            conn.commit()
    finally:
        with _customer_scan_threads_lock:
            _customer_scan_threads.pop(trip_id, None)


def _queue_customer_scan(trip_id: int, scan_answers: dict, mode: str = "initial", choice: str = "") -> bool:
    """Queue at most one live customer scan per vacation in this web process."""
    with _customer_scan_threads_lock:
        current = _customer_scan_threads.get(trip_id)
        if current and current.is_alive():
            return False
        thread = threading.Thread(
            target=_customer_scan_worker,
            args=(trip_id, dict(scan_answers), mode, choice),
            daemon=True,
            name=f"ariella-customer-{trip_id}-{mode}",
        )
        _customer_scan_threads[trip_id] = thread
        thread.start()
        return True
'''

if "def _queue_customer_scan(" not in text:
    if helper_marker not in text:
        raise RuntimeError("async patch: free-alternative marker not found")
    text = text.replace(helper_marker, helper + helper_marker, 1)

# Replace the initial synchronous DB->external flow in /trip/new. The vacation is
# committed first, then the customer is redirected immediately. Open "Ariella
# chooses" remains DB/shared-inventory only and never queues an unbounded scan.
initial_pattern = re.compile(
    r'''        # Initial DB match obeys the user's exact date mode\. No hidden date alternatives\..*?        return redirect\(url_for\("site\.account"\) \+ f"#vacation-\{trip_id\}"\)''',
    re.S,
)
initial_replacement = '''        # Initial DB-first match. External work is queued only for a bounded,
        # destination-led request; the browser is never held open for SerpApi.
        existing_matches = _customer_deal_choices(existing_inventory, trip_for_match, limit=5)
        open_db_only = (
            vacation_type == "standard"
            and str(payload.get("destination_mode") or "open") == "open"
        )

        if existing_matches:
            matched_ids = [
                int(o.get("offer_id") or o.get("id"))
                for o in existing_matches
                if (o.get("offer_id") or o.get("id")) is not None
            ]
            payload["_matched_offer_ids"] = matched_ids
            with _db() as conn:
                conn.execute(
                    "UPDATE trip_requests SET answers_json=?, free_scan_count=0, free_scan_last_at=?, free_scan_last_status=? WHERE id=?",
                    (json.dumps(payload, ensure_ascii=False), utc_now_iso(), "database_match", trip_id),
                )
                conn.commit()
        elif open_db_only:
            with _db() as conn:
                conn.execute(
                    "UPDATE trip_requests SET free_scan_count=0, free_scan_last_at=?, free_scan_last_status=? WHERE id=?",
                    (utc_now_iso(), "db_only_open", trip_id),
                )
                conn.commit()
        else:
            with _db() as conn:
                conn.execute(
                    "UPDATE trip_requests SET free_scan_count=0, free_scan_last_at=?, free_scan_last_status=? WHERE id=?",
                    (utc_now_iso(), "external_search_queued", trip_id),
                )
                conn.commit()
            _queue_customer_scan(trip_id, payload, mode="initial")

        return redirect(url_for("site.account") + f"#vacation-{trip_id}")'''
text2, n = initial_pattern.subn(initial_replacement, text, count=1)
if n != 1:
    raise RuntimeError(f"async patch: initial trip flow replacement failed: {n}")
text = text2

# The single second-chance branch can also require SerpApi and therefore must use
# the same asynchronous path. All DB-only checks above this block remain instant.
alt_pattern = re.compile(
    r'''    try:\n        scan_result = run_customer_trip_search\(trip_id, scan_answers\).*?    return redirect\(url_for\("site\.account"\) \+ f"#vacation-\{trip_id\}"\)\n\n\n@site\.post\("/trip/<int:trip_id>/renew-search"\)''',
    re.S,
)
alt_replacement = '''    # No DB match: queue the one allowed external second-chance branch and return
    # immediately. Mark it used now so repeated clicks cannot launch duplicates.
    answers["_second_chance_used"] = True
    answers["_second_chance_choice"] = choice
    if choice == "other_destination":
        answers["_alternative_other_destination"] = True
    with _db() as conn:
        conn.execute(
            "UPDATE trip_requests SET answers_json=?, free_scan_last_at=?, free_scan_last_status=? WHERE id=?",
            (json.dumps(answers, ensure_ascii=False), utc_now_iso(), "alternative_search_queued", trip_id),
        )
        conn.commit()
    _queue_customer_scan(trip_id, scan_answers, mode=choice, choice=choice)
    return redirect(url_for("site.account") + f"#vacation-{trip_id}")


@site.post("/trip/<int:trip_id>/renew-search")'''
text2, n = alt_pattern.subn(alt_replacement, text, count=1)
if n != 1:
    raise RuntimeError(f"async patch: alternative flow replacement failed: {n}")
text = text2

compile(text, str(p), "exec")
p.write_text(text, encoding="utf-8")
print("9.7.136 async customer scan patch applied")
