from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def _run(script: str):
    subprocess.run([sys.executable, str(ROOT / script)], cwd=str(ROOT), check=True)


def prepare():
    scanner = ROOT / "scanner.py"
    public_site = ROOT / "public_site.py"
    admin = ROOT / "admin.py"

    scanner_text = scanner.read_text(encoding="utf-8")
    public_text = public_site.read_text(encoding="utf-8")

    # Materialize the full 9.7.136 core before scanner/public_site are imported.
    if "monthly_scan_coverage" not in scanner_text or "db_only_open" not in public_text:
        _run("tools/apply_v136.py")
        scanner_text = scanner.read_text(encoding="utf-8")
        public_text = public_site.read_text(encoding="utf-8")

    # QA FIX: passenger counts must exist throughout the whole booking chain.
    old_sig = "def enrich_booking_options(flight: dict, departure: str, arrival: str, outbound_date: str, return_date: str) -> tuple[dict, int]:"
    new_sig = "def enrich_booking_options(flight: dict, departure: str, arrival: str, outbound_date: str, return_date: str, adults: int = 1, children: int = 0) -> tuple[dict, int]:"
    if old_sig in scanner_text:
        scanner_text = scanner_text.replace(old_sig, new_sig, 1)

    enrich_pos = scanner_text.find("def enrich_booking_options")
    search_pos = scanner_text.find("def search_flights", enrich_pos)
    if enrich_pos < 0 or search_pos <= enrich_pos:
        raise RuntimeError("QA: enrich_booking_options/search_flights block not found")

    enrich_block = scanner_text[enrich_pos:search_pos]
    default_params = "params = _roundtrip_params(departure, arrival, outbound_date, return_date)"
    passenger_params = "params = _roundtrip_params(departure, arrival, outbound_date, return_date, adults=adults, children=children)"
    if passenger_params not in enrich_block:
        if default_params not in enrich_block:
            raise RuntimeError("QA: booking enrichment params pattern not found")
        enrich_block = enrich_block.replace(default_params, passenger_params, 1)
        scanner_text = scanner_text[:enrich_pos] + enrich_block + scanner_text[search_pos:]

    # Count actual HTTP calls, including calls made before an exception/timeout is
    # returned to the caller. This prevents the admin from showing API=0 after
    # SerpApi quota was actually consumed.
    serp_marker = '\ndef _serpapi_request(params: dict) -> dict:\n'
    counter_decl = '\n_SERPAPI_HTTP_REQUESTS = 0\n'
    if counter_decl not in scanner_text:
        if serp_marker not in scanner_text:
            raise RuntimeError("QA: _serpapi_request marker not found")
        scanner_text = scanner_text.replace(serp_marker, counter_decl + serp_marker, 1)
    serp_sig = 'def _serpapi_request(params: dict) -> dict:\n    """SerpAPI request with bounded retry/backoff for transient 429/5xx errors."""\n'
    serp_sig_counted = 'def _serpapi_request(params: dict) -> dict:\n    """SerpAPI request with bounded retry/backoff for transient 429/5xx errors."""\n    global _SERPAPI_HTTP_REQUESTS\n'
    if serp_sig_counted not in scanner_text:
        if serp_sig not in scanner_text:
            raise RuntimeError("QA: _serpapi_request signature body not found")
        scanner_text = scanner_text.replace(serp_sig, serp_sig_counted, 1)
    request_line = '            response = requests.get(SERPAPI_URL, params=params, timeout=45)\n'
    counted_request_line = '            _SERPAPI_HTTP_REQUESTS += 1\n            response = requests.get(SERPAPI_URL, params=params, timeout=45)\n'
    if counted_request_line not in scanner_text:
        if request_line not in scanner_text:
            raise RuntimeError("QA: SerpApi requests.get pattern not found")
        scanner_text = scanner_text.replace(request_line, counted_request_line, 1)

    # Personal/ski searches must pass requested passenger counts. They also use a
    # bounded outbound depth so a single route cannot burn ~10 API calls and hit
    # the web-request timeout before the scan progress is persisted.
    customer_pos = scanner_text.find("def run_customer_trip_search")
    destination_pos = scanner_text.find("def run_destination_scan", customer_pos)
    if customer_pos < 0 or destination_pos <= customer_pos:
        raise RuntimeError("QA: customer scan block not found")
    customer_block = scanner_text[customer_pos:destination_pos]

    origins_line = '    origins = [str(x).upper() for x in answers.get("origin_airports", []) if x] or list(DEPARTURE_AIRPORTS)\n'
    passenger_parse = '''    try:\n        adults = max(1, int(answers.get("adults") or 1))\n    except (TypeError, ValueError):\n        adults = 1\n    try:\n        children = max(0, int(answers.get("children") or 0))\n    except (TypeError, ValueError):\n        children = 0\n'''
    if passenger_parse not in customer_block:
        if origins_line not in customer_block:
            raise RuntimeError("QA: customer origins pattern not found")
        customer_block = customer_block.replace(origins_line, origins_line + passenger_parse, 1)

    old_search = 'result = search_flights(job["departure"], job["arrival"], job["outbound"], job["return"])'
    passenger_search = 'result = search_flights(job["departure"], job["arrival"], job["outbound"], job["return"], adults=adults, children=children)'
    bounded_search = 'result = search_flights(job["departure"], job["arrival"], job["outbound"], job["return"], max_outbounds=1, adults=adults, children=children)'
    if bounded_search not in customer_block:
        if passenger_search in customer_block:
            customer_block = customer_block.replace(passenger_search, bounded_search, 1)
        elif old_search in customer_block:
            customer_block = customer_block.replace(old_search, bounded_search, 1)
        else:
            raise RuntimeError("QA: customer search_flights call not found")

    old_enrich = '''enrich_booking_options(\n                                flight, job["departure"], job["arrival"], job["outbound"], job["return"]\n                            )'''
    new_enrich = '''enrich_booking_options(\n                                flight, job["departure"], job["arrival"], job["outbound"], job["return"],\n                                adults=adults, children=children\n                            )'''
    if new_enrich not in customer_block:
        if old_enrich not in customer_block:
            raise RuntimeError("QA: customer enrich_booking_options call not found")
        customer_block = customer_block.replace(old_enrich, new_enrich, 1)

    # Track actual HTTP calls from the moment this personal scan starts. The value
    # is reconciled in every job-finally and again before finish_scan_run, so a
    # failed search is still visible in Admin and the safety cap can stop the scan.
    counters_line = '    completed = offers_found = errors = api_requests = 0\n'
    counters_with_http = '    completed = offers_found = errors = api_requests = 0\n    api_counter_start = _SERPAPI_HTTP_REQUESTS\n'
    if counters_with_http not in customer_block:
        if counters_line not in customer_block:
            raise RuntimeError("QA: customer counters pattern not found")
        customer_block = customer_block.replace(counters_line, counters_with_http, 1)

    job_finally = '            finally:\n                update_scan_progress(run_id, completed, offers_found, errors, api_requests)\n'
    job_finally_counted = '            finally:\n                api_requests = max(api_requests, _SERPAPI_HTTP_REQUESTS - api_counter_start)\n                update_scan_progress(run_id, completed, offers_found, errors, api_requests)\n'
    if job_finally_counted not in customer_block:
        if job_finally not in customer_block:
            raise RuntimeError("QA: customer job finally pattern not found")
        customer_block = customer_block.replace(job_finally, job_finally_counted, 1)

    outer_finally = '    finally:\n        finish_scan_run(run_id, completed, offers_found, errors, "; ".join(messages)[:2000] or None, api_requests=api_requests)\n'
    outer_finally_counted = '    finally:\n        api_requests = max(api_requests, _SERPAPI_HTTP_REQUESTS - api_counter_start)\n        finish_scan_run(run_id, completed, offers_found, errors, "; ".join(messages)[:2000] or None, api_requests=api_requests)\n'
    if outer_finally_counted not in customer_block:
        if outer_finally not in customer_block:
            raise RuntimeError("QA: customer outer finally pattern not found")
        customer_block = customer_block.replace(outer_finally, outer_finally_counted, 1)

    scanner_text = scanner_text[:customer_pos] + customer_block + scanner_text[destination_pos:]
    scanner.write_text(scanner_text, encoding="utf-8")

    # Public-site safety: once a vacation has been saved, a later scan/render error
    # must never strand the customer on a raw Internal Server Error page. Redirect
    # authenticated customers back to My Vacations while keeping the error logged.
    public_text = public_site.read_text(encoding="utf-8")
    fallback_marker = '\n_AIRPORTS_FILE = Path(__file__).resolve().parent / "static" / "airports.json"\n'
    fallback_code = '''\n@site.app_errorhandler(500)\ndef _customer_500_fallback(error):\n    if session.get("member_id"):\n        return redirect(url_for("site.account"))\n    return "Internal Server Error", 500\n\n'''
    if '_customer_500_fallback' not in public_text:
        if fallback_marker not in public_text:
            raise RuntimeError("QA: public_site fallback insertion marker not found")
        public_text = public_text.replace(fallback_marker, fallback_code + fallback_marker, 1)
        public_site.write_text(public_text, encoding="utf-8")

    # Keep the admin scan-number selector sourced from scan_runs, including scans
    # that produced zero offers.
    admin_text = admin.read_text(encoding="utf-8")
    old_filter = "{% for sid in offers|map(attribute='scan_run_id')|unique|list %}{% if sid %}<option value=\"{{ sid }}\">#{{ sid }}</option>{% endif %}{% endfor %}"
    new_filter = "{% for scan in scans %}{% if scan.id %}<option value=\"{{ scan.id }}\">#{{ scan.id }}{% if scan.status %} · {{ scan.status }}{% endif %}</option>{% endif %}{% endfor %}"
    if old_filter in admin_text:
        admin_text = admin_text.replace(old_filter, new_filter, 1)
        admin.write_text(admin_text, encoding="utf-8")

    # Hard QA gates: fail startup instead of spending SerpAPI quota on a broken build.
    scanner_text = scanner.read_text(encoding="utf-8")
    public_text = public_site.read_text(encoding="utf-8")
    customer_pos = scanner_text.find("def run_customer_trip_search")
    destination_pos = scanner_text.find("def run_destination_scan", customer_pos)
    customer_block = scanner_text[customer_pos:destination_pos]
    enrich_pos = scanner_text.find("def enrich_booking_options")
    search_pos = scanner_text.find("def search_flights", enrich_pos)
    enrich_block = scanner_text[enrich_pos:search_pos]

    assert "monthly_scan_coverage" in scanner_text
    assert "db_only_open" in scanner_text or "db_only_open" in public_text
    assert new_sig in scanner_text
    assert passenger_params in enrich_block
    assert passenger_parse in customer_block
    assert bounded_search in customer_block
    assert new_enrich in customer_block
    assert '_SERPAPI_HTTP_REQUESTS += 1' in scanner_text
    assert 'api_counter_start = _SERPAPI_HTTP_REQUESTS' in customer_block
    assert '_customer_500_fallback' in public_text

    compile(scanner_text, str(scanner), "exec")
    compile(public_text, str(public_site), "exec")
    compile(admin.read_text(encoding="utf-8"), str(admin), "exec")

    print("Ariella 9.7.136 QA runtime preparation verified: bounded personal scan + API accounting + customer fallback + core + admin")
