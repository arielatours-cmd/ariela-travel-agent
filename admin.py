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
    --gold:#b8892e;
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
.feedback-table th,.feedback-table td{white-space:normal;text-align:right;vertical-align:top;padding:10px 8px;line-height:1.45}
.feedback-table .feedback-date{width:165px;direction:ltr;text-align:center}
.feedback-table .feedback-name{width:130px}
.feedback-table .feedback-phone{width:120px;direction:ltr;text-align:center}
.feedback-table .feedback-email{width:210px;direction:ltr;text-align:left}
.feedback-table .feedback-message{width:auto}
.feedback-count{color:var(--gold);font-weight:800}
.admin-nav{display:grid;grid-template-columns:1fr 1fr;gap:0;margin:24px 0 20px;border-bottom:2px solid #d8c49a}.admin-nav a{background:#fff;color:#263a70;border:1px solid #dfe4ed;border-bottom:0;padding:16px 22px;text-decoration:none;font-weight:800;font-size:17px;text-align:center;position:relative}.admin-nav a:first-child{border-radius:0 12px 0 0}.admin-nav a:last-child{border-radius:12px 0 0 0}.admin-nav a.active{background:#fff;color:#182033}.admin-nav a.active:after{content:'';position:absolute;right:12%;left:12%;bottom:-2px;height:4px;background:var(--gold);border-radius:4px 4px 0 0}.admin-nav a:hover{background:#fbf8f1}.unread-count{color:#b8892e;font-weight:900;margin-inline-start:5px}.feedback-card-admin{background:#fff;border-radius:12px;padding:18px;margin-bottom:12px;box-shadow:0 2px 10px #0000000d}.feedback-card-admin .meta{display:flex;gap:16px;flex-wrap:wrap;color:var(--muted);font-size:13px;margin-bottom:10px}.feedback-card-admin .message{white-space:pre-wrap;line-height:1.65}.feedback-card-admin a{color:#263a70}
@media(max-width:900px){.admin-nav{grid-template-columns:1fr 1fr}.admin-nav a{font-size:14px;padding:13px 8px}
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
<div class="admin-nav"><a class="active" href="/admin{% if token %}?token={{ token }}{% endif %}">✦ סריקות ודילים</a><a href="/admin/feedback{% if token %}?token={{ token }}{% endif %}">✦ הערות והצעות {% if feedback_count %}<span class="unread-count">({{ feedback_count }})</span>{% endif %}</a></div>

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


def render_dashboard(*, version, minimum_score, stats, offers, scans, feedback_count=0, token=""):
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
        feedback_count=feedback_count,
        token=token,
    )


FEEDBACK_DASHBOARD_HTML = r"""
<!doctype html>
<html lang="he" dir="rtl">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>אריאלה — הערות והצעות</title>
<style>
:root{--bg:#f5f7fb;--text:#182033;--muted:#697386;--line:#e7eaf0;--gold:#b8892e}
*{box-sizing:border-box}body{font-family:Arial,sans-serif;background:var(--bg);margin:0;color:var(--text)}
.wrap{width:min(1250px,96%);margin:auto;padding:20px 8px 35px}h1{margin:0 0 6px}.muted{color:var(--muted)}
.admin-nav{display:grid;grid-template-columns:1fr 1fr;gap:0;margin:24px 0 24px;border-bottom:2px solid #d8c49a}.admin-nav a{background:#fff;color:#263a70;border:1px solid #dfe4ed;border-bottom:0;padding:16px 22px;text-decoration:none;font-weight:800;font-size:17px;text-align:center;position:relative}.admin-nav a:first-child{border-radius:0 12px 0 0}.admin-nav a:last-child{border-radius:12px 0 0 0}.admin-nav a.active{background:#fff;color:#182033}.admin-nav a.active:after{content:'';position:absolute;right:12%;left:12%;bottom:-2px;height:4px;background:var(--gold);border-radius:4px 4px 0 0}.admin-nav a:hover{background:#fbf8f1}.unread-count{color:#b8892e;font-weight:900;margin-inline-start:5px}
.summary{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin-bottom:22px}.summary .box{background:#fff;border-radius:12px;padding:16px;box-shadow:0 2px 10px #0000000d}.summary strong{display:block;font-size:28px;color:var(--gold);margin-top:5px}
.feedback-list{display:grid;gap:13px}.feedback-card{background:#fff;border-radius:12px;padding:18px 20px;box-shadow:0 2px 10px #0000000d;border-right:4px solid var(--gold)}.feedback-card .top{display:flex;justify-content:space-between;gap:20px;align-items:flex-start}.feedback-card h2{font-size:18px;margin:0}.date{direction:ltr;color:var(--muted);font-size:13px}.contacts{display:flex;gap:16px;flex-wrap:wrap;margin:8px 0 13px;color:var(--muted);font-size:14px}.contacts a{color:#263a70;text-decoration:none}.message{border-top:1px solid var(--line);padding-top:13px;white-space:pre-wrap;line-height:1.7}.empty{background:#fff;text-align:center;padding:45px;border-radius:12px;color:var(--muted)}
@media(max-width:650px){.admin-nav a{font-size:14px;padding:13px 8px}.feedback-card .top{flex-direction:column;gap:5px}}
</style></head>
<body><div class="wrap">
<h1>הערות והצעות</h1><div class="muted">כל ההודעות שנשלחו מטופס המשוב באתר נשמרות כאן במסד הנתונים.</div>
<div class="admin-nav"><a href="/admin{% if token %}?token={{ token }}{% endif %}">✦ סריקות ודילים</a><a class="active" href="/admin/feedback{% if token %}?token={{ token }}{% endif %}">✦ הערות והצעות</a></div>
<div class="summary"><div class="box">סה״כ הודעות<strong>{{ feedback|length }}</strong></div><div class="box">הודעה אחרונה<strong style="font-size:16px">{% if feedback %}{{ feedback[0].created_at|replace('T',' ')|truncate(19, True, '') }}{% else %}—{% endif %}</strong></div></div>
<div class="feedback-list">
{% for f in feedback %}<article class="feedback-card"><div class="top"><h2>{{ f.full_name }}</h2><span class="date">{{ f.created_at|replace('T',' ')|truncate(19, True, '') }}</span></div><div class="contacts"><a href="tel:{{ f.phone }}">{{ f.phone }}</a><a href="mailto:{{ f.email }}">{{ f.email }}</a></div><div class="message">{{ f.message }}</div></article>{% else %}<div class="empty">עדיין לא התקבלו הערות או הצעות.</div>{% endfor %}
</div></div></body></html>
"""


def render_feedback_dashboard(*, feedback, token=""):
    return render_template_string(FEEDBACK_DASHBOARD_HTML, feedback=feedback, token=token)
