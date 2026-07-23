from datetime import datetime
from flask import render_template_string

HEBREW_WEEKDAYS_SHORT = {
    0: "ב׳", 1: "ג׳", 2: "ד׳", 3: "ה׳", 4: "ו׳", 5: "שבת", 6: "א׳",
}


def _date_display(value: str | None) -> str:
    if not value:
        return "—"
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d")
    except (TypeError, ValueError):
        return value
    return f"{HEBREW_WEEKDAYS_SHORT[parsed.weekday()]} {parsed.strftime('%d.%m.%Y')}"


def _prepare_offer(offer: dict) -> dict:
    item = dict(offer)
    item["outbound_display"] = _date_display(item.get("outbound_date"))
    item["return_display"] = _date_display(item.get("return_date"))
    item["route_color"] = "direct" if int(item.get("stops") or 0) == 0 else "one-stop" if int(item.get("stops") or 0) == 1 else "multi-stop"
    item["route_tooltip"] = "טיסה ישירה" if int(item.get("stops") or 0) == 0 else "קונקשן אחד" if int(item.get("stops") or 0) == 1 else "שני קונקשנים ומעלה"
    return item


DASHBOARD_HTML = r"""
<!doctype html>
<html lang="he" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>אריאלה — לוח בקרה</title>
<style>
:root{--bg:#f5f7fb;--text:#182033;--muted:#697386;--line:#e5eaf2;--head:#eef2f8;--navy:#263a70;--good:#16865f;--orange:#e58a19;--bad:#cf3f3f}
*{box-sizing:border-box}
body{font-family:Arial,sans-serif;background:var(--bg);margin:0;color:var(--text)}
.wrap{width:96%;max-width:1450px;margin:auto;padding:22px 12px 34px}
h1{margin:0 0 6px}.muted{color:var(--muted)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin:20px 0}
.card{background:#fff;border-radius:14px;padding:16px;box-shadow:0 2px 10px #00000012}.num{font-size:28px;font-weight:700;margin-top:8px}
.actions{display:flex;gap:10px;flex-wrap:wrap;margin:14px 0}.status{padding:8px 0;font-weight:700}
button,a.btn{background:var(--navy);color:#fff;border:0;border-radius:9px;padding:10px 14px;text-decoration:none;cursor:pointer}.secondary{background:#65748b!important}
h2{margin:24px 0 9px}
.summary{background:#fff;border:1px solid var(--line);border-radius:11px;padding:10px 13px;margin-bottom:9px;font-size:14px;font-weight:700}
.legend{font-size:12px;color:var(--muted);font-weight:400;margin-right:14px;white-space:nowrap}
.dot{display:inline-block;width:10px;height:10px;border-radius:50%;vertical-align:middle;margin:0 3px}.dot.direct{background:var(--good)}.dot.one-stop{background:var(--orange)}.dot.multi-stop{background:var(--bad)}
.table-wrap{width:100%;overflow-x:auto;background:#fff;border-radius:14px;box-shadow:0 2px 10px #0000000d}
table{width:100%;min-width:1180px;border-collapse:collapse;background:#fff}
th,td{padding:9px 7px;border-bottom:1px solid var(--line);text-align:center;font-size:13px;line-height:1.25;white-space:nowrap}
th{background:var(--head);font-size:12px;font-weight:700}tbody tr:hover{background:#fafbfe}
.destination{min-width:90px}.destination-code{display:block;font-size:14px;font-weight:800}.destination-name{display:block;margin-top:3px;font-size:12px}
.dates{min-width:145px;line-height:1.45}.date-line{display:block}
.price{min-width:82px}.points{min-width:62px}.route{min-width:72px}.final{min-width:88px}.reason{min-width:190px;max-width:260px;text-align:right;white-space:normal}
.route-badge{display:inline-flex;align-items:center;justify-content:center;min-width:42px;padding:5px 8px;border-radius:8px;color:#fff;font-weight:800}.route-badge.direct{background:var(--good)}.route-badge.one-stop{background:var(--orange)}.route-badge.multi-stop{background:var(--bad)}
.final-score{font-size:16px;font-weight:800}
.scans{min-width:760px}.empty{padding:20px!important;color:var(--muted)}
@media(max-width:900px){.wrap{width:100%;padding:14px 5px 25px}.grid{grid-template-columns:repeat(2,minmax(130px,1fr))}.legend{display:block;margin:7px 0 0}th,td{font-size:12px;padding:7px 5px}}
</style>
</head>
<body><div class="wrap">
<h1>אריאלה — לוח בקרה פנימי</h1><div class="muted">גרסה {{ version }} · סף דיל: {{ minimum_score }}</div>
<div class="actions"><button onclick="runScan()">הפעל סריקת ניסיון</button><button class="secondary" onclick="buildBatch()">בנה רשימה יומית</button><a class="btn secondary" href="/daily-preview" target="_blank">תצוגת WhatsApp</a></div>
<div id="actionStatus" class="status"></div>
<div class="grid">
<div class="card">סריקות<div class="num">{{ stats.scans_total or 0 }}</div></div>
<div class="card">הצעות שנשמרו<div class="num">{{ stats.offers_total or 0 }}</div></div>
<div class="card">עברו את הסף<div class="num">{{ stats.offers_qualified or 0 }}</div></div>
<div class="card">ציון ממוצע<div class="num">{{ stats.average_score or 0 }}</div></div>
<div class="card">ציון גבוה<div class="num">{{ stats.highest_score or 0 }}</div></div>
<div class="card">שגיאות סריקה<div class="num">{{ stats.scan_errors or 0 }}</div></div>
</div>
<h2>ההצעות האחרונות</h2>
<div class="summary">{{ offers|length }} דילים אחרונים · {{ qualified_count }} עברו את הסף · ציון ממוצע: {{ offers_average }} · ציון גבוה: {{ offers_highest }}
<span class="legend"><span class="dot direct"></span>ישירה <span class="dot one-stop"></span>קונקשן אחד <span class="dot multi-stop"></span>שניים ומעלה</span></div>
<div class="table-wrap"><table><thead><tr>
<th class="destination">יעד</th><th class="dates">תאריכים</th><th class="price">מחיר ₪</th><th class="price">ממוצע ₪</th>
<th class="points">עלות</th><th class="route">מסלול</th><th class="points">כבודה</th><th class="points">שעות</th><th class="points">נדירות</th><th class="points">עונתיות</th><th class="points">אמינות</th><th class="final">ציון סופי</th><th class="reason">סיבת השליחה</th>
</tr></thead><tbody>
{% for o in offers %}<tr>
<td class="destination"><span class="destination-code">{{ o.arrival_code or '—' }}</span><span class="destination-name">{{ o.destination_name or o.arrival_code or '—' }}</span></td>
<td class="dates"><span class="date-line">{{ o.outbound_display }}</span><span class="date-line">{{ o.return_display }}</span></td>
<td class="price">{{ o.price_ils|round|int if o.price_ils is not none else '—' }}</td>
<td class="price" title="מחיר הייחוס שעליו התבסס ניקוד העלות">{{ o.reference_price_ils|round|int if o.reference_price_ils is not none else '—' }}</td>
<td class="points" title="ניקוד עלות">{{ o.cost_score if o.cost_score is not none else '—' }}</td>
<td class="route" title="{{ o.route_tooltip }}"><span class="route-badge {{ o.route_color }}">{{ o.route_score if o.route_score is not none else '—' }}</span></td>
<td class="points" title="ניקוד כבודה">{{ o.baggage_score if o.baggage_score is not none else '—' }}</td>
<td class="points" title="ניקוד שעות">{{ o.hours_score if o.hours_score is not none else '—' }}</td>
<td class="points" title="ניקוד נדירות">{{ o.rarity_score if o.rarity_score is not none else '—' }}</td>
<td class="points" title="ניקוד עונתיות — טרם מחושב בגרסה זו">{{ o.seasonality_score if o.seasonality_score is not none else '—' }}</td>
<td class="points" title="ניקוד אמינות — טרם מחושב בגרסה זו">{{ o.reliability_score if o.reliability_score is not none else '—' }}</td>
<td class="final"><span class="final-score">{{ o.score }}</span></td>
<td class="reason" title="{{ o.score_reasons|join(' · ') }}">{{ o.send_reason or '—' }}</td>
</tr>{% else %}<tr><td class="empty" colspan="13">עדיין אין הצעות. הפעילי סריקה.</td></tr>{% endfor %}
</tbody></table></div>
<h2>סריקות אחרונות</h2><div class="table-wrap"><table class="scans"><thead><tr><th>מס׳</th><th>סטטוס</th><th>התחלה</th><th>חיפושים</th><th>הצעות</th><th>שגיאות</th></tr></thead><tbody>
{% for s in scans %}<tr><td>{{ s.id }}</td><td>{{ s.status }}</td><td>{{ s.started_at }}</td><td>{{ s.searches_completed }}/{{ s.searches_planned }}</td><td>{{ s.offers_found }}</td><td>{{ s.errors }}</td></tr>{% else %}<tr><td class="empty" colspan="6">עדיין אין סריקות.</td></tr>{% endfor %}
</tbody></table></div>
</div><script>
async function post(url){let e=document.getElementById('actionStatus');e.textContent='מבצעת...';try{let r=await fetch(url,{method:'POST'});let j=await r.json();e.textContent=JSON.stringify(j);if(r.ok)setTimeout(()=>location.reload(),1200)}catch(x){e.textContent='שגיאה: '+x}}
function runScan(){post('/scan?max_searches=8')} function buildBatch(){post('/daily-batch?force=true')}
</script></body></html>
"""


def render_dashboard(*, version, minimum_score, stats, offers, scans):
    prepared = [_prepare_offer(o) for o in offers]
    prepared.sort(key=lambda o: float(o.get("score") or 0), reverse=True)
    scores = [float(o.get("score") or 0) for o in prepared]
    return render_template_string(
        DASHBOARD_HTML,
        version=version,
        minimum_score=minimum_score,
        stats=stats,
        offers=prepared,
        scans=scans,
        qualified_count=sum(1 for score in scores if score >= minimum_score),
        offers_average=round(sum(scores) / len(scores), 1) if scores else 0,
        offers_highest=round(max(scores), 1) if scores else 0,
    )
