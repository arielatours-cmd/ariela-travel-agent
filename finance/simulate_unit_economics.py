"""Unit economics: one free customer, one paying customer, many paying customers.

Reads finance/assumptions.json (top-level caps/prices + "unit_economics").
AI (Claude API) cost per customer is unknown, so results are shown BEFORE AI,
together with the maximum AI cost per customer that still breaks even.
"""
import json
import math
from pathlib import Path

A = json.loads((Path(__file__).parent / "assumptions.json").read_text(encoding="utf-8"))
U = A["unit_economics"]

rate = U["usd_to_ils_charged"]
per_search = U["serpapi_pack_usd"] * rate / U["serpapi_pack_searches"]
month_over_period = A["days_per_month"] / A["search_period_days"]
paid_scan_searches = A["paid_scan_requests_single_gateway"] * A["paid_scan_days_per_month"]
paid_scan_searches_multi = A["paid_scan_requests_multi_gateway"] * A["paid_scan_days_per_month"]
wide_searches = A["wide_scan_cap_per_run"] * A["days_per_month"]

free_lo = U["free_scan_searches_low"] * per_search
free_hi = U["free_scan_searches_high"] * per_search

rev = {k: v * month_over_period for k, v in A["plan_prices_ils"].items()}
var = {"update": 0.0, "scan": paid_scan_searches * per_search}
var_multi = paid_scan_searches_multi * per_search


def ils(x):
    return f"{x:,.1f} ₪"


def fixed(wide_on):
    searches = U["testing_searches_per_month"] + (wide_searches if wide_on else 0)
    return {
        "Render": U["render_ils_per_month"],
        "Claude Pro (פיתוח)": U["claude_pro_ils_per_month"],
        "SerpAPI — בדיקות" + (" + סריקה רחבה" if wide_on else ""): searches * per_search,
    }, searches


print("# סימולציית כלכלת לקוח\n")
print(f"שער מחויב: {rate} ₪/$ · עלות חיפוש SerpAPI: {per_search:.3f} ₪ "
      f"(${U['serpapi_pack_usd']}/{U['serpapi_pack_searches']:,}) · כל הסכומים לפני AI ולפני מע\"מ/סליקה\n")

print("## 1. לקוח בודד שלא משלם\n")
print(f"- סריקה ראשונה חינם: {U['free_scan_searches_low']}–{U['free_scan_searches_high']} חיפושים = **{ils(free_lo)}–{ils(free_hi)}** (חד-פעמי)")
print("- הכנסה: 0 ₪ · + עלות שיחות AI (לא ידועה)\n")

print("## 2. לקוח משלם בודד (לחודש, אחרי הסריקה הראשונה)\n")
print("| | הכנסה | עלות SerpAPI | מרווח לפני AI |\n|---|---|---|---|")
print(f"| 19 ₪ (עדכון) | {ils(rev['update'])} | {ils(var['update'])} | {ils(rev['update'] - var['update'])} |")
print(f"| 39 ₪ (סריקה) | {ils(rev['scan'])} | {ils(var['scan'])} | {ils(rev['scan'] - var['scan'])} |")
print(f"| 39 ₪ רב-שדות | {ils(rev['scan'])} | {ils(var_multi)} | {ils(rev['scan'] - var_multi)} |")
print(f"\nבחודש הראשון יורדת גם הסריקה החינמית: {ils(free_lo)}–{ils(free_hi)}.\n")

for wide_on in (False, True):
    f, searches = fixed(wide_on)
    total_fixed = sum(f.values())
    title = "סריקה רחבה פעילה" if wide_on else "סריקה רחבה מושהית (היום)"
    print(f"## 3{'ב' if wide_on else 'א'}. כמה לקוחות משלמים — {title}\n")
    print("עלויות קבועות לחודש: " + " · ".join(f"{k} {ils(v)}" for k, v in f.items()) + f" · **סה\"כ {ils(total_fixed)}**")
    packs = searches / U["serpapi_pack_searches"]
    print(f"(צריכת SerpAPI: {searches:,.0f} חיפושים בחודש ≈ {packs:.2f} חבילות ${U['serpapi_pack_usd']})\n")
    plans = ["scan"] if not wide_on else ["scan", "update"]
    for free_ratio in U["free_users_per_paying_customer"]:
        print(f"**{free_ratio} משתמשים חינמיים חדשים בכל חודש על כל לקוח משלם** (סריקה חינם בממוצע {ils((free_lo + free_hi) / 2)} לכל אחד)\n")
        print("| לקוחות משלמים | " + " | ".join(f"רווח/הפסד — כולם {A['plan_prices_ils'][p]} ₪" for p in plans) + " |")
        print("|---|" + "---|" * len(plans))
        for n in U["paid_customer_counts"]:
            cells = []
            for p in plans:
                acq = n * free_ratio * (free_lo + free_hi) / 2
                cells.append(ils(n * (rev[p] - var[p]) - total_fixed - acq))
            print(f"| {n} | " + " | ".join(cells) + " |")
        be = []
        for p in plans:
            unit = rev[p] - var[p] - free_ratio * (free_lo + free_hi) / 2
            be.append(f"{A['plan_prices_ils'][p]} ₪: " + (f"{math.ceil(total_fixed / unit)} לקוחות" if unit > 0 else "אין איזון"))
        print("\nנקודת איזון (לפני AI): " + " · ".join(be) + "\n")

print("## תקרת עלות AI\n")
print(f"לקוח 39 ₪ מכסה עד {ils(rev['scan'] - var['scan'])} בחודש של AI + חלקו בעלויות הקבועות; לקוח 19 ₪ עד {ils(rev['update'])}.")
