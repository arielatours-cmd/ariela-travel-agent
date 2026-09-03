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

    # Personal/ski searches must pass the requested passenger counts to both the
    # flight search and the booking-token enrichment. General discovery remains 1 adult.
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
    new_search = 'result = search_flights(job["departure"], job["arrival"], job["outbound"], job["return"], adults=adults, children=children)'
    if new_search not in customer_block:
        if old_search not in customer_block:
            raise RuntimeError("QA: customer search_flights call not found")
        customer_block = customer_block.replace(old_search, new_search, 1)

    old_enrich = '''enrich_booking_options(\n                                flight, job["departure"], job["arrival"], job["outbound"], job["return"]\n                            )'''
    new_enrich = '''enrich_booking_options(\n                                flight, job["departure"], job["arrival"], job["outbound"], job["return"],\n                                adults=adults, children=children\n                            )'''
    if new_enrich not in customer_block:
        if old_enrich not in customer_block:
            raise RuntimeError("QA: customer enrich_booking_options call not found")
        customer_block = customer_block.replace(old_enrich, new_enrich, 1)

    scanner_text = scanner_text[:customer_pos] + customer_block + scanner_text[destination_pos:]
    scanner.write_text(scanner_text, encoding="utf-8")

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
    assert new_search in customer_block
    assert new_enrich in customer_block

    compile(scanner_text, str(scanner), "exec")
    compile(public_text, str(public_site), "exec")
    compile(admin.read_text(encoding="utf-8"), str(admin), "exec")

    print("Ariella 9.7.136 QA runtime preparation verified: passenger chain + core + admin")
