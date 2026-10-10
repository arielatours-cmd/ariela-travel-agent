"""Task 007a - read-only report on the existing scan_runs/monthly_scan_coverage
history: how much personal-scan sharing has actually been happening so far.

Strictly read-only: never writes, never changes a scan decision. The new
scan_runs measurement columns (reused_coverage_keys, estimated_requests_saved,
stopped_by_cap, coverage_groups_completed/total - see database.finish_scan_run)
only start getting populated going forward from this task; this report also
looks at what the pre-existing data already tells us, using the same
definitions scanner.run_customer_trip_search itself uses:
- "fully reused" run == searches_planned=0 AND api_requests=0 (the exact
  condition that produces status "monthly_coverage_reused").
- "stopped by the safety cap" == error_message mentions the exact Hebrew
  safety-cap message scanner.py writes ("עצירת בטיחות").

The per-route/month "how many runs asked for this group, and was it closed"
breakdown is a best-effort approximation from the offers table (which DOES
record an exact outbound/return date per offer, bucketed here to the month
scanner.py's own coverage key uses) joined against monthly_scan_coverage -
not an exact historical count of coverage-key lookups, since that was never
logged before this task. Documented here rather than silently presented as
exact.

Run directly: python3 tools/report_scan_sharing_history.py
Or via the admin route: GET /admin/scan-sharing/history?token=...
"""
import os
import sys
import sqlite3
import json
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database


def generate_report() -> dict:
    with sqlite3.connect(database.DB_PATH) as conn:
        conn.row_factory = sqlite3.Row

        personal_runs = conn.execute(
            "SELECT COUNT(*) AS n FROM scan_runs WHERE scan_type LIKE 'personal_%'"
        ).fetchone()["n"]

        fully_reused_runs = conn.execute(
            "SELECT COUNT(*) AS n FROM scan_runs "
            "WHERE scan_type LIKE 'personal_%' AND searches_planned=0 AND api_requests=0"
        ).fetchone()["n"]

        stopped_by_cap_runs = conn.execute(
            "SELECT COUNT(*) AS n FROM scan_runs "
            "WHERE scan_type LIKE 'personal_%' AND error_message LIKE '%עצירת בטיחות%'"
        ).fetchone()["n"]

        coverage_row_count = conn.execute(
            "SELECT COUNT(*) AS n FROM monthly_scan_coverage"
        ).fetchone()["n"]

        scanned_at_distribution = {}
        for row in conn.execute(
            "SELECT substr(scanned_at,1,10) AS day, COUNT(*) AS n "
            "FROM monthly_scan_coverage GROUP BY day ORDER BY day"
        ).fetchall():
            scanned_at_distribution[row["day"]] = row["n"]

        # Best-effort per-route/month-group demand: how many distinct personal
        # scan runs touched this exact (departure, arrival, outbound month,
        # return month) group, approximated from the offers each run actually
        # persisted (trip_id is only set for personal/customer scans).
        demand_rows = conn.execute(
            """SELECT departure_code, arrival_code,
                      substr(outbound_date,1,7) AS outbound_month,
                      substr(return_date,1,7) AS return_month,
                      COUNT(DISTINCT scan_run_id) AS runs_requesting
               FROM offers
               WHERE trip_id IS NOT NULL
               GROUP BY departure_code, arrival_code, outbound_month, return_month
               ORDER BY runs_requesting DESC
               LIMIT 25"""
        ).fetchall()

        coverage_status = {}
        for row in conn.execute(
            "SELECT departure_code, arrival_code, outbound_month, return_month, status "
            "FROM monthly_scan_coverage"
        ).fetchall():
            coverage_status[(row["departure_code"], row["arrival_code"], row["outbound_month"], row["return_month"])] = row["status"]

        by_group = []
        groups_closed = 0
        for row in demand_rows:
            key = (row["departure_code"], row["arrival_code"], row["outbound_month"], row["return_month"])
            closed = coverage_status.get(key) == "success"
            if closed:
                groups_closed += 1
            by_group.append({
                "departure_code": row["departure_code"], "arrival_code": row["arrival_code"],
                "outbound_month": row["outbound_month"], "return_month": row["return_month"],
                "runs_requesting": row["runs_requesting"], "currently_closed": closed,
            })

    return {
        "personal_runs_total": personal_runs,
        "fully_reused_runs": fully_reused_runs,
        "stopped_by_cap_runs": stopped_by_cap_runs,
        "monthly_scan_coverage_rows": coverage_row_count,
        "monthly_scan_coverage_scanned_at_by_day": scanned_at_distribution,
        "top_route_month_groups_by_demand": by_group,
        "top_route_month_groups_closed_count": groups_closed,
        "note": (
            "top_route_month_groups_by_demand is a best-effort approximation from "
            "the offers table (grouped by route + outbound/return month), not an "
            "exact historical count of coverage-key lookups - that was never "
            "logged before task 007a."
        ),
    }


if __name__ == "__main__":
    print(json.dumps(generate_report(), ensure_ascii=False, indent=2))
