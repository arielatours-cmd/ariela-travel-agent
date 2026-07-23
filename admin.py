from flask import render_template_string


DASHBOARD_HTML = r"""
<!doctype html>
<html lang="he" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>אריאלה — לוח בקרה</title>
<style>
:root{
    --bg:#f5f7fb;
    --text:#182033;
    --muted:#697386;
    --line:#edf0f5;
    --head:#eef2f8;
    --good:#087f5b;
    --medium:#b26a00;
    --bad:#c92a2a;
}
*{box-sizing:border-box}
body{
    font-family:Arial,sans-serif;
    background:var(--bg);
    margin:0;
    color:var(--text);
}
.wrap{
    width:98%;
    max-width:none;
    margin:auto;
    padding:18px 10px 28px;
}
h1{margin:0 0 6px}
h2{margin:22px 0 8px}
.muted{color:var(--muted)}
.grid{
    display:grid;
    grid-template-columns:repeat(auto-fit,minmax(145px,1fr));
    gap:10px;
    margin:16px 0;
}
.card{
    background:white;
    border-radius:12px;
    padding:13px;
    box-shadow:0 2px 10px #00000012;
}
.num{
    font-size:25px;
    font-weight:700;
    margin-top:6px;
}
.actions{
    display:flex;
    gap:8px;
    flex-wrap:wrap;
    margin:12px 0;
}
button,a.btn{
    background:#263a70;
    color:white;
    border:0;
    border-radius:8px;
    padding:9px 12px;
    text-decoration:none;
    cursor:pointer;
}
.secondary{background:#65748b!important}
.status{padding:6px 0;font-weight:700}
.table-summary{
    background:white;
    border:1px solid var(--line);
    border-radius:10px;
    padding:8px 10px;
    margin-bottom:7px;
    font-size:13px;
    font-weight:700;
}
.table-wrap{
    width:100%;
    overflow-x:hidden;
    border-radius:12px;
    box-shadow:0 2px 10px #0000000d;
}
table{
    width:100%;
    table-layout:fixed;
    border-collapse:collapse;
    background:white;
}
th,td{
    padding:5px 3px;
    border-bottom:1px solid var(--line);
    text-align:center;
    font-size:12px;
    line-height:1.15;
    white-space:nowrap;
    overflow:hidden;
    text-overflow:ellipsis;
}
th{
    background:var(--head);
    font-size:11px;
    font-weight:700;
}
tbody tr:hover{background:#fafbfe}
.destination{
    width:70px;
    white-space:normal;
    line-height:1.05;
}
.destination-code{
    display:block;
    font-size:12px;
    font-weight:800;
}
.destination-name{
    display:block;
    margin-top:2px;
    font-size:11px;
}
.price-col{width:57px}
.average-col{width:57px}
.score-part{width:43px}
.total-score{width:50px}
.reason-col{
    width:auto;
    min-width:100px;
    text-align:right;
    white-space:nowrap;
}
.score-badge{
    display:inline-block;
    min-width:34px;
    padding:4px 5px;
    border-radius:7px;
    color:white;
    font-weight:800;
}
.score-good{background:var(--good)}
.score-medium{background:var(--medium)}
.score-bad{background:var(--bad)}
.scans th,.scans td{font-size:12px;padding:6px 4px}
.scans .scan-id{width:48px}
.scans .scan-status{width:75px}
.scans .scan-date{width:155px}
.scans .scan-number{width:75px}
.empty{padding:18px!important;color:var(--muted)}
@media(max-width:900px){
    .wrap{width:100%;padding:12px 4px 22px}
    th,td{font-size:11px;padding:4px 2px}
    th{font-size:10px}
    .destination{width:62px}
    .price-col,.average-col{width:51px}
    .score-part{width:38px}
    .total-score{width:45px}
}
</style>
</head>
<body>
<div class="wrap">
<h1>אריאלה — לוח בקרה פנימי</h1>
<div class="muted">גרסה {{ version }} · סף דיל: {{ minimum_score }}</div>

<div class="actions">
    <button onclick="runScan()">הפעל סריקת ניסיון</button>
    <button class="secondary" onclick="buildBatch()">בנה רשימה יומית</button>
    <a class="btn secondary" href="/daily-preview" target="_blank">תצוגת WhatsApp</a>
</div>
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
<div class="table-summary">
    {{ offers|length }} דילים אחרונים ·
    {{ offers|selectattr('score', 'ge', minimum_score)|list|length }} עברו את הסף ·
    ציון ממוצע:
    {% if offers %}
        {{ ((offers|sum(attribute='score')) / (offers|length))|round(1) }}
    {% else %}0{% endif %} ·
    ציון גבוה:
    {% if offers %}{{ offers|max(attribute='score')|attr('score') }}{% else %}0{% endif %}
</div>

<div class="table-wrap">
<table>
<thead>
<tr>
    <th class="destination">יעד</th>
    <th class="price-col">מחיר</th>
    <th class="average-col">ממוצע</th>
    <th class="score-part">עלות</th>
    <th class="score-part">מסלול</th>
    <th class="score-part">כבודה</th>
    <th class="score-part">שעות</th>
    <th class="score-part">נדירות</th>
    <th class="score-part">עונתיות</th>
    <th class="score-part">אמינות</th>
    <th class="total-score">ציון</th>
    <th class="reason-col">סיבת השליחה</th>
</tr>
</thead>
<tbody>
{% for o in offers %}
<tr>
    <td class="destination">
        <span class="destination-code">{{ o.arrival_code or '—' }}</span>
        <span class="destination-name">{{ o.destination_name or o.arrival_code or '—' }}</span>
    </td>
    <td class="price-col" title="מחיר נוכחי בש״ח">
        {{ o.price_ils|round|int if o.price_ils is not none else '—' }}
    </td>
    <td class="average-col" title="מחיר ממוצע בש״ח">
        {{ o.average_price_ils|round|int if o.average_price_ils is defined and o.average_price_ils is not none else
           (o.avg_price_ils|round|int if o.avg_price_ils is defined and o.avg_price_ils is not none else '—') }}
    </td>
    <td class="score-part" title="ניקוד עלות">
        {{ o.cost_score if o.cost_score is defined else
           (o.price_score if o.price_score is defined else '—') }}
    </td>
    <td class="score-part" title="ניקוד מסלול">
        {{ o.route_score if o.route_score is defined else '—' }}
    </td>
    <td class="score-part" title="ניקוד כבודה">
        {{ o.baggage_score if o.baggage_score is defined else '—' }}
    </td>
    <td class="score-part" title="ניקוד שעות">
        {{ o.time_score if o.time_score is defined else
           (o.schedule_score if o.schedule_score is defined else '—') }}
    </td>
    <td class="score-part" title="ניקוד נדירות">
        {{ o.rarity_score if o.rarity_score is defined else '—' }}
    </td>
    <td class="score-part" title="ניקוד עונתיות">
        {{ o.seasonality_score if o.seasonality_score is defined else
           (o.season_score if o.season_score is defined else '—') }}
    </td>
    <td class="score-part" title="ניקוד אמינות">
        {{ o.reliability_score if o.reliability_score is defined else '—' }}
    </td>
    <td class="total-score">
        <span class="score-badge {% if o.score >= minimum_score %}score-good{% elif o.score >= minimum_score-10 %}score-medium{% else %}score-bad{% endif %}">
            {{ o.score }}
        </span>
    </td>
    <td class="reason-col"
        title="{{ o.score_reasons|join(' · ') if o.score_reasons else (o.send_reason or '') }}">
        {% if o.send_reason is defined and o.send_reason %}
            {{ o.send_reason }}
        {% elif o.score_reasons %}
            {{ o.score_reasons|first }}
        {% else %}
            —
        {% endif %}
    </td>
</tr>
{% else %}
<tr><td class="empty" colspan="12">עדיין אין הצעות. הפעילי סריקה.</td></tr>
{% endfor %}
</tbody>
</table>
</div>

<h2>סריקות אחרונות</h2>
<div class="table-wrap">
<table class="scans">
<thead>
<tr>
    <th class="scan-id">מס׳</th>
    <th class="scan-status">סטטוס</th>
    <th class="scan-date">התחלה</th>
    <th class="scan-number">חיפושים</th>
    <th class="scan-number">הצעות</th>
    <th class="scan-number">שגיאות</th>
</tr>
</thead>
<tbody>
{% for s in scans %}
<tr>
    <td>{{ s.id }}</td>
    <td>{{ s.status }}</td>
    <td>{{ s.started_at }}</td>
    <td>{{ s.searches_completed }}/{{ s.searches_planned }}</td>
    <td>{{ s.offers_found }}</td>
    <td>{{ s.errors }}</td>
</tr>
{% else %}
<tr><td class="empty" colspan="6">עדיין אין סריקות.</td></tr>
{% endfor %}
</tbody>
</table>
</div>
</div>

<script>
async function post(url){
    const e=document.getElementById('actionStatus');
    e.textContent='מבצעת...';
    try{
        const r=await fetch(url,{method:'POST'});
        const j=await r.json();
        e.textContent=JSON.stringify(j);
        if(r.ok)setTimeout(()=>location.reload(),1200);
    }catch(x){
        e.textContent='שגיאה: '+x;
    }
}
function runScan(){post('/scan?max_searches=8')}
function buildBatch(){post('/daily-batch?force=true')}
</script>
</body>
</html>
"""


def render_dashboard(*, version, minimum_score, stats, offers, scans):
    offers = sorted(
        offers,
        key=lambda offer: float(offer.get("score") or 0),
        reverse=True,
    )
    return render_template_string(
        DASHBOARD_HTML,
        version=version,
        minimum_score=minimum_score,
        stats=stats,
        offers=offers,
        scans=scans,
    )
