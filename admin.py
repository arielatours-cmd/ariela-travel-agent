from flask import render_template_string

DASHBOARD_HTML = r"""
<!doctype html>
<html lang="he" dir="rtl">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>אריאלה — לוח בקרה</title>
<style>
body{font-family:Arial,sans-serif;background:#f5f7fb;margin:0;color:#182033}.wrap{max-width:1200px;margin:auto;padding:22px}
h1{margin:0 0 6px}.muted{color:#697386}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin:20px 0}
.card{background:white;border-radius:14px;padding:16px;box-shadow:0 2px 10px #00000012}.num{font-size:28px;font-weight:700;margin-top:8px}
table{width:100%;border-collapse:collapse;background:white;border-radius:14px;overflow:hidden}th,td{padding:10px;border-bottom:1px solid #edf0f5;text-align:right;font-size:14px}th{background:#eef2f8}.ok{color:#087f5b;font-weight:700}.bad{color:#c92a2a;font-weight:700}
.actions{display:flex;gap:10px;flex-wrap:wrap;margin:14px 0}button,a.btn{background:#263a70;color:white;border:0;border-radius:9px;padding:10px 14px;text-decoration:none;cursor:pointer}.secondary{background:#65748b!important}
pre{white-space:pre-wrap}.reason{font-size:12px;color:#697386;max-width:330px}.status{padding:8px 0;font-weight:700}
</style></head>
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
<table><thead><tr><th>יעד</th><th>תאריכים</th><th>מחיר</th><th>מסלול</th><th>ציון</th><th>עבר?</th><th>פירוט</th></tr></thead><tbody>
{% for o in offers %}<tr><td>{{ o.country_flag or '' }} {{ o.destination_name or o.arrival_code }}</td><td>{{ o.outbound_date }}–{{ o.return_date }}</td><td>₪{{ o.price_ils|round|int }}</td><td>{{ 'ישירה' if o.stops == 0 else (o.stops|string + ' עצירות') }}</td><td><b>{{ o.score }}</b> · {{ o.score_label }}</td><td class="{{ 'ok' if o.score >= minimum_score else 'bad' }}">{% if o.score >= minimum_score %}עבר ב-{{ o.score-minimum_score }}{% else %}חסרות {{ minimum_score-o.score }} נק׳{% endif %}</td><td class="reason">{{ o.score_reasons|join(' · ') }}</td></tr>{% else %}<tr><td colspan="7">עדיין אין הצעות. הפעילי סריקה.</td></tr>{% endfor %}
</tbody></table>
<h2>סריקות אחרונות</h2>
<table><thead><tr><th>מס׳</th><th>סטטוס</th><th>התחלה</th><th>חיפושים</th><th>הצעות</th><th>שגיאות</th></tr></thead><tbody>
{% for s in scans %}<tr><td>{{ s.id }}</td><td>{{ s.status }}</td><td>{{ s.started_at }}</td><td>{{ s.searches_completed }}/{{ s.searches_planned }}</td><td>{{ s.offers_found }}</td><td>{{ s.errors }}</td></tr>{% endfor %}
</tbody></table>
</div>
<script>
async function post(url){let e=document.getElementById('actionStatus');e.textContent='מבצעת...';try{let r=await fetch(url,{method:'POST'});let j=await r.json();e.textContent=JSON.stringify(j);if(r.ok)setTimeout(()=>location.reload(),1200)}catch(x){e.textContent='שגיאה: '+x}}
function runScan(){post('/scan?max_searches=8')} function buildBatch(){post('/daily-batch?force=true')}
</script></body></html>
"""


def render_dashboard(*, version, minimum_score, stats, offers, scans):
    return render_template_string(
        DASHBOARD_HTML, version=version, minimum_score=minimum_score,
        stats=stats, offers=offers, scans=scans,
    )
