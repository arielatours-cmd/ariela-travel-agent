from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]

def replace_once(path, old, new):
    p = ROOT / path
    text = p.read_text(encoding='utf-8')
    if old not in text:
        raise RuntimeError(f'pattern not found in {path}: {old[:80]!r}')
    p.write_text(text.replace(old, new, 1), encoding='utf-8')

# 1) Ariella-chooses is DB/shared-inventory only and scan_count reflects paid API use.
p = ROOT / 'public_site.py'
text = p.read_text(encoding='utf-8')
pattern = re.compile(r'''        # The customer's exact request has priority\..*?        if existing_matches:\n''', re.S)
replacement = '''        # 9.7.136: open "Ariella chooses" is a one-time DB/shared-inventory search.
        # It never launches a customer-specific external scan because the search
        # universe is intentionally unbounded. Bounded destination/ski requests keep
        # the normal DB-first -> external scan flow.
        open_db_only = (
            vacation_type == "standard"
            and str(payload.get("destination_mode") or "open") == "open"
        )
        if not existing_matches and open_db_only:
            scan_status = "db_only_open"
            scan_count = 0
        elif not existing_matches:
            try:
                scan_result = run_customer_trip_search(trip_id, payload)
                api_used = int(scan_result.get("api_requests") or 0)
                scan_count = 1 if api_used > 0 else 0
                scan_status = str(scan_result.get("status") or "external_search")
                refreshed_inventory = [
                    _localize_offer_airports(o)
                    for o in recent_offers(limit=1500, minimum_score=None)
                    if _offer_is_recent(o, 48)
                ]
                existing_matches = _customer_deal_choices(refreshed_inventory, trip_for_match, limit=5)
            except Exception:
                scan_count = 0
                scan_status = "external_search_error"

        if existing_matches:
'''
text2, n = pattern.subn(replacement, text, count=1)
if n != 1:
    raise RuntimeError(f'public_site scan block patch failed: {n}')
p.write_text(text2, encoding='utf-8')

# 2) Monthly scan reuse cache (12h), keyed by origin+gateway+outbound month+return month.
p = ROOT / 'scanner.py'
text = p.read_text(encoding='utf-8')
text = text.replace('import itertools\nimport os\n', 'import itertools\nimport os\nimport sqlite3\nfrom collections import Counter, defaultdict\n', 1)
text = text.replace(
    '    MAX_SEARCHES_PER_SCAN, CUSTOMER_SCAN_MAX_API_REQUESTS, SERPAPI_API_KEY, TRIP_LENGTHS_DAYS,\n)',
    '    MAX_SEARCHES_PER_SCAN, CUSTOMER_SCAN_MAX_API_REQUESTS, SERPAPI_API_KEY, TRIP_LENGTHS_DAYS,\n    DB_PATH, MONTHLY_SCAN_REUSE_HOURS,\n)', 1)
helper = r'''

def _coverage_key(job: dict) -> tuple[str, str, str, str]:
    return (
        str(job.get("departure") or "").upper(),
        str(job.get("arrival") or "").upper(),
        str(job.get("outbound") or "")[:7],
        str(job.get("return") or "")[:7],
    )


def _coverage_connection():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("""
        CREATE TABLE IF NOT EXISTS monthly_scan_coverage (
            departure_code TEXT NOT NULL,
            arrival_code TEXT NOT NULL,
            outbound_month TEXT NOT NULL,
            return_month TEXT NOT NULL,
            scanned_at TEXT NOT NULL,
            status TEXT NOT NULL,
            offers_found INTEGER NOT NULL DEFAULT 0,
            api_requests INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (departure_code, arrival_code, outbound_month, return_month)
        )
    """)
    conn.commit()
    return conn


def _coverage_is_fresh(key, now=None) -> bool:
    now = now or datetime.now(timezone.utc)
    with _coverage_connection() as conn:
        row = conn.execute(
            "SELECT scanned_at,status FROM monthly_scan_coverage WHERE departure_code=? AND arrival_code=? AND outbound_month=? AND return_month=?",
            key,
        ).fetchone()
    if not row or str(row["status"]) != "success":
        return False
    try:
        scanned = datetime.fromisoformat(str(row["scanned_at"]).replace("Z", "+00:00"))
        if scanned.tzinfo is None:
            scanned = scanned.replace(tzinfo=timezone.utc)
    except Exception:
        return False
    return now - scanned <= timedelta(hours=max(1, int(MONTHLY_SCAN_REUSE_HOURS)))


def _mark_coverage_success(key, offers_found=0, api_requests=0):
    with _coverage_connection() as conn:
        conn.execute("""
            INSERT INTO monthly_scan_coverage
            (departure_code,arrival_code,outbound_month,return_month,scanned_at,status,offers_found,api_requests)
            VALUES(?,?,?,?,?,'success',?,?)
            ON CONFLICT(departure_code,arrival_code,outbound_month,return_month)
            DO UPDATE SET scanned_at=excluded.scanned_at,status='success',offers_found=excluded.offers_found,api_requests=excluded.api_requests
        """, (*key, datetime.now(timezone.utc).isoformat(), int(offers_found or 0), int(api_requests or 0)))
        conn.commit()

'''
marker = '\ndef run_customer_trip_search(trip_id: int, answers: dict) -> dict:\n'
if marker not in text:
    raise RuntimeError('scanner run_customer marker missing')
text = text.replace(marker, helper + marker, 1)

# Guard open standard search before any API work.
needle = '''    arrivals = _customer_destination_codes(answers)\n    vacation_type = str(answers.get("vacation_type") or "standard")\n'''
repl = '''    arrivals = _customer_destination_codes(answers)\n    vacation_type = str(answers.get("vacation_type") or "standard")\n    if vacation_type == "standard" and str(answers.get("destination_mode") or "open") == "open" and not answers.get("_alternative_other_destination"):\n        return {"status": "db_only_open", "offers_found": 0, "api_requests": 0, "searches_completed": 0, "errors": 0}\n'''
if needle not in text:
    raise RuntimeError('scanner open guard pattern missing')
text = text.replace(needle, repl, 1)

# Filter fresh route-month coverage immediately before creating the scan run.
needle = '''    run_id = create_scan_run(len(jobs), scan_type=f"personal_{str(answers.get('vacation_type') or 'standard')}", trip_id=trip_id)\n'''
repl = '''    # 9.7.136 monthly reuse: a successful route-month scan (even with zero offers)\n    # is reusable for 12 hours. Failed/partial/stopped coverage is never marked.\n    coverage_expected_all = Counter(_coverage_key(j) for j in jobs)\n    fresh_keys = {key for key in coverage_expected_all if _coverage_is_fresh(key)}\n    if fresh_keys:\n        jobs = [j for j in jobs if _coverage_key(j) not in fresh_keys]\n    if not jobs:\n        return {"status": "monthly_coverage_reused", "offers_found": 0, "api_requests": 0, "searches_completed": 0, "errors": 0, "reused_coverage": len(fresh_keys)}\n    coverage_expected = Counter(_coverage_key(j) for j in jobs)\n    coverage_completed = Counter()\n    coverage_errors = Counter()\n    coverage_offers = Counter()\n    coverage_api = Counter()\n\n    run_id = create_scan_run(len(jobs), scan_type=f"personal_{str(answers.get('vacation_type') or 'standard')}", trip_id=trip_id)\n'''
if needle not in text:
    raise RuntimeError('scanner create_scan_run pattern missing')
text = text.replace(needle, repl, 1)

# Count per-coverage success/errors/API. api delta is measured per job.
needle = '''            try:\n                # Price cards remain strictly per person.'''
repl = '''            try:\n                coverage_key = _coverage_key(job)\n                api_before_job = api_requests\n                offers_before_job = offers_found\n                # Price cards remain strictly per person.'''
if needle not in text:
    raise RuntimeError('scanner job try pattern missing')
text = text.replace(needle, repl, 1)

needle = '''            except Exception as exc:\n                errors += 1\n                messages.append(f"{job['departure']}-{job['arrival']}: {exc}")\n            finally:\n                update_scan_progress(run_id, completed, offers_found, errors, api_requests)\n'''
repl = '''                coverage_completed[coverage_key] += 1\n                coverage_offers[coverage_key] += max(0, offers_found - offers_before_job)\n                coverage_api[coverage_key] += max(0, api_requests - api_before_job)\n            except Exception as exc:\n                errors += 1\n                key = _coverage_key(job)\n                coverage_errors[key] += 1\n                messages.append(f"{job['departure']}-{job['arrival']}: {exc}")\n            finally:\n                update_scan_progress(run_id, completed, offers_found, errors, api_requests)\n'''
if needle not in text:
    raise RuntimeError('scanner job except/finally pattern missing')
text = text.replace(needle, repl, 1)

needle = '''    finally:\n        finish_scan_run(run_id, completed, offers_found, errors, "; ".join(messages)[:2000] or None, api_requests=api_requests)\n    return {"status": "success" if errors == 0 else "partial", "scan_run_id": run_id, "searches_completed": completed, "api_requests": api_requests, "offers_found": offers_found, "errors": errors}\n'''
repl = '''    finally:\n        finish_scan_run(run_id, completed, offers_found, errors, "; ".join(messages)[:2000] or None, api_requests=api_requests)\n    # Only complete, error-free route-month groups become fresh coverage. A successful\n    # zero-result group is valid coverage; a stopped/capped/partial group is not.\n    for key, expected in coverage_expected.items():\n        if coverage_completed[key] == expected and coverage_errors[key] == 0:\n            _mark_coverage_success(key, coverage_offers[key], coverage_api[key])\n    return {"status": "success" if errors == 0 else "partial", "scan_run_id": run_id, "searches_completed": completed, "api_requests": api_requests, "offers_found": offers_found, "errors": errors, "reused_coverage": len(fresh_keys)}\n'''
if needle not in text:
    raise RuntimeError('scanner final block pattern missing')
text = text.replace(needle, repl, 1)
p.write_text(text, encoding='utf-8')

# 3) Ski UI wording: budget is explicitly per person and remove generic "why Ariella" in ski cards.
for rel in ('templates/trip_form.html',):
    p = ROOT / rel
    t = p.read_text(encoding='utf-8')
    # Restrictive wording change requested for the questionnaire; harmless if repeated elsewhere.
    t = t.replace('תקציב', 'תקציב לאדם')
    t = t.replace('Budget', 'Budget per person')
    p.write_text(t, encoding='utf-8')

# 4) Ski resort distance estimates in km for the currently tested Bulgarian catalog.
# These are approximate road-distance values used only for display; gateway-airport logic remains unchanged.
for rel in ('ski_catalog.py', 'data/ski_resorts.json'):
    p = ROOT / rel
    if not p.exists():
        continue
    t = p.read_text(encoding='utf-8')
    if rel.endswith('.py'):
        t = t.replace("'resort': 'Bansko',", "'resort': 'Bansko', 'distance_km_estimate': 160,", 1)
        t = t.replace("'resort': 'Borovets',", "'resort': 'Borovets', 'distance_km_estimate': 70,", 1)
        t = t.replace("'resort': 'Pamporovo',", "'resort': 'Pamporovo', 'distance_km_estimate': 230,", 1)
    else:
        # JSON formatting can vary; inject after resort name when present.
        t = re.sub(r'("resort"\s*:\s*"Bansko"\s*,)', r'\1 "distance_km_estimate": 160,', t, count=1)
        t = re.sub(r'("resort"\s*:\s*"Borovets"\s*,)', r'\1 "distance_km_estimate": 70,', t, count=1)
        t = re.sub(r'("resort"\s*:\s*"Pamporovo"\s*,)', r'\1 "distance_km_estimate": 230,', t, count=1)
    p.write_text(t, encoding='utf-8')

# Decorate ski offers with distance km if catalog provides it.
p = ROOT / 'public_site.py'
t = p.read_text(encoding='utf-8')
needle = '        copy["ski_transfer_minutes"] = row.get("transfer_minutes_estimate")\n'
if needle in t:
    t = t.replace(needle, needle + '        copy["ski_distance_km"] = row.get("distance_km_estimate")\n', 1)
p.write_text(t, encoding='utf-8')

# 5) Changelog included inside the deployable package.
(ROOT / 'V97136_CHANGES_HE.txt').write_text('''Ariella Tours 9.7.136\n\n- חיפוש "אריאלה תבחר" הוא חד-פעמי ומבוסס DB/סריקות משותפות בלבד, ללא סריקה חיצונית אישית.\n- סריקה חיצונית ליעד מוגדר נשמרת ככיסוי חודשי לפי מוצא+יעד+חודש הלוך+חודש חזור.\n- reuse לכיסוי חודשי מוצלח: 12 שעות, כולל סריקה מוצלחת עם 0 תוצאות.\n- סריקה חלקית/שנכשלה/נעצרה אינה נחשבת כיסוי מלא.\n- scan_count אינו נספר כאשר לא נצרכו קריאות API.\n- כל תוצאות סריקה תקינות ממשיכות להישמר ב-DB המשותף.\n- בסקי: תקציב לאדם, הכנת שדה מרחק בק"מ לאתרי בולגריה שנבדקו.\n''', encoding='utf-8')

print('9.7.136 patch applied successfully')
