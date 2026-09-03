from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def _run(script: str):
    subprocess.run([sys.executable, str(ROOT / script)], cwd=str(ROOT), check=True)


def prepare():
    scanner = ROOT / "scanner.py"
    public_site = ROOT / "public_site.py"

    scanner_text = scanner.read_text(encoding="utf-8")
    public_text = public_site.read_text(encoding="utf-8")

    # Render may use dashboard build settings instead of render.yaml. Ensure the
    # real 9.7.136 core patch exists before the application imports scanner/site.
    if "monthly_scan_coverage" not in scanner_text or "db_only_open" not in public_text:
        _run("tools/apply_v136.py")
        scanner_text = scanner.read_text(encoding="utf-8")

    # Fix booking enrichment NameError. The passenger-aware call inside
    # search_flights remains unchanged; only enrich_booking_options must use its
    # own default params because adults/children are not in that function scope.
    bad = "params = _roundtrip_params(departure, arrival, outbound_date, return_date, adults=adults, children=children)"
    good = "params = _roundtrip_params(departure, arrival, outbound_date, return_date)"
    enrich_pos = scanner_text.find("def enrich_booking_options")
    search_pos = scanner_text.find("def search_flights", enrich_pos)
    if enrich_pos >= 0 and search_pos > enrich_pos:
        block = scanner_text[enrich_pos:search_pos]
        if bad in block:
            block = block.replace(bad, good, 1)
            scanner_text = scanner_text[:enrich_pos] + block + scanner_text[search_pos:]
            scanner.write_text(scanner_text, encoding="utf-8")

    # Keep the admin scan-number selector sourced from scan_runs, including
    # stopped/failed scans that produced zero offers.
    admin = ROOT / "admin.py"
    admin_text = admin.read_text(encoding="utf-8")
    old = "{% for sid in offers|map(attribute='scan_run_id')|unique|list %}{% if sid %}<option value=\"{{ sid }}\">#{{ sid }}</option>{% endif %}{% endfor %}"
    new = "{% for scan in scans %}{% if scan.id %}<option value=\"{{ scan.id }}\">#{{ scan.id }}{% if scan.status %} · {{ scan.status }}{% endif %}</option>{% endif %}{% endfor %}"
    if old in admin_text:
        admin.write_text(admin_text.replace(old, new, 1), encoding="utf-8")

    # Hard validation: fail startup rather than silently run a half-patched build.
    scanner_text = scanner.read_text(encoding="utf-8")
    public_text = public_site.read_text(encoding="utf-8")
    enrich_pos = scanner_text.find("def enrich_booking_options")
    search_pos = scanner_text.find("def search_flights", enrich_pos)
    enrich_block = scanner_text[enrich_pos:search_pos] if enrich_pos >= 0 and search_pos > enrich_pos else ""
    assert "monthly_scan_coverage" in scanner_text
    assert "db_only_open" in public_text
    assert bad not in enrich_block

    print("Ariella 9.7.136 runtime preparation verified")
