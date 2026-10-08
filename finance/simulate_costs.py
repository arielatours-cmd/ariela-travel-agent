"""Monthly cost simulation for Ariella's recurring scans (and known fixed costs).

Reads finance/assumptions.json and finance/expenses.csv, prints a Hebrew
Markdown report: SerpAPI requests per source, the cheapest plan that fits,
cost vs paid-plan revenue, and the recurring fixed costs on record.

Usage: python finance/simulate_costs.py [--out finance/reports/simulation.md]
"""
from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load_assumptions() -> dict:
    return json.loads((HERE / "assumptions.json").read_text(encoding="utf-8"))


def load_expenses() -> list[dict]:
    path = HERE / "expenses.csv"
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def monthly_requests(a: dict, s: dict) -> dict[str, float]:
    wide = a["wide_scan_avg_requests_per_run"] * a["days_per_month"] if s["wide_scan_active"] else 0
    per_scan_customer = (
        a["paid_scan_requests_single_gateway"] * (1 - a["multi_gateway_share"])
        + a["paid_scan_requests_multi_gateway"] * a["multi_gateway_share"]
    )
    paid = s["scan_customers"] * per_scan_customer * a["paid_scan_days_per_month"]
    free = s["new_trips_per_month"] * min(a["free_scan_avg_requests"], a["free_scan_cap"])
    manual = s["manual_qa_requests_per_month"]
    return {"סריקה רחבה יומית": wide, "סריקה יומית ללקוחות 39 ₪": paid,
            "סריקה ראשונה חינם": free, "ידני / QA": manual}


def cheapest_plan(a: dict, total: float) -> dict | None:
    fitting = [p for p in a["serpapi_plans"] if p["searches"] >= total]
    return min(fitting, key=lambda p: p["usd_per_month"]) if fitting else None


def fixed_monthly_ils(a: dict, expenses: list[dict]) -> tuple[float, list[str]]:
    """Recurring non-SerpAPI costs on record, normalised to a month (ILS)."""
    total, missing = 0.0, []
    for row in expenses:
        if row.get("vendor") == "SerpAPI" or row.get("recurring") not in ("monthly", "yearly"):
            continue
        if not (row.get("amount") or "").strip():
            missing.append(row.get("vendor") or "?")
            continue
        amount = float(row["amount"]) * (a["usd_to_ils"] if row.get("currency") == "USD" else 1)
        total += amount / 12 if row["recurring"] == "yearly" else amount
    return total, missing


def fmt(n: float) -> str:
    return f"{n:,.0f}"


def report(a: dict, expenses: list[dict]) -> str:
    fx = a["usd_to_ils"]
    fixed, missing = fixed_monthly_ils(a, expenses)
    period_factor = a["days_per_month"] / a["search_period_days"]
    lines = ["# סימולציית עלויות חודשית — סריקות ועלויות קבועות", "",
             f"שער דולר: {fx} ₪ · מקור כל הנחה: finance/assumptions.json", ""]
    for s in a["scenarios"]:
        req = monthly_requests(a, s)
        total = sum(req.values())
        plan = cheapest_plan(a, total)
        serp_ils = plan["usd_per_month"] * fx if plan else None
        revenue = (s["scan_customers"] * a["plan_prices_ils"]["scan"]
                   + s["update_customers"] * a["plan_prices_ils"]["update"]) * period_factor
        llm = (s["conversations_per_month"] * a["llm_cost_ils_per_conversation"]
               if a.get("llm_cost_ils_per_conversation") is not None else None)
        lines += [f"## תרחיש: {s['name']}", "",
                  "| מקור | בקשות SerpAPI בחודש |", "|---|---|"]
        lines += [f"| {k} | {fmt(v)} |" for k, v in req.items()]
        lines += [f"| **סה\"כ** | **{fmt(total)}** |", ""]
        if plan:
            used = total / plan["searches"] * 100
            note = "" if plan["verified"] else " (מחיר לא מאומת)"
            lines.append(f"- חבילה מתאימה: **{plan['name']}** — ${plan['usd_per_month']} ≈ {fmt(serp_ils)} ₪ לחודש{note}, ניצול {used:.0f}%")
            if plan["name"] != a["current_serpapi_plan"]:
                lines.append(f"- ⚠️ החבילה הנוכחית ({a['current_serpapi_plan']}) לא מספיקה לתרחיש הזה")
        else:
            lines.append("- ⚠️ אין חבילה ברשימה שמכסה את הנפח — צריך הצעת מחיר")
        lines.append(f"- הכנסה ממנויי חיפוש (חודשי): {fmt(revenue)} ₪")
        lines.append(f"- עלות AI (Claude): {fmt(llm) + ' ₪' if llm is not None else 'לא ידוע — חסר מחיר לשיחה'}")
        lines.append(f"- עלויות קבועות ידועות (ללא SerpAPI): {fmt(fixed)} ₪")
        if serp_ils is not None:
            net = revenue - serp_ils - fixed - (llm or 0)
            lines.append(f"- **רווח/הפסד חודשי משוער: {fmt(net)} ₪**" + (" (ללא AI)" if llm is None else ""))
        lines.append("")
    if missing:
        lines += ["## חסרים נתונים", "", "עלויות קבועות בלי סכום ב-expenses.csv: " + ", ".join(missing), ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out")
    args = parser.parse_args()
    text = report(load_assumptions(), load_expenses())
    if args.out:
        Path(args.out).write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
