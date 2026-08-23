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
.admin-nav{display:grid;grid-template-columns:repeat(3,1fr);gap:0;margin:24px 0 20px;border-bottom:2px solid #d8c49a}.admin-nav a{background:#fff;color:#263a70;border:1px solid #dfe4ed;border-bottom:0;padding:16px 22px;text-decoration:none;font-weight:800;font-size:17px;text-align:center;position:relative}.admin-nav a:first-child{border-radius:0 12px 0 0}.admin-nav a:last-child{border-radius:12px 0 0 0}.admin-nav a.active{background:#fff;color:#182033}.admin-nav a.active:after{content:'';position:absolute;right:12%;left:12%;bottom:-2px;height:4px;background:var(--gold);border-radius:4px 4px 0 0}.admin-nav a:hover{background:#fbf8f1}.unread-count{color:#b8892e;font-weight:900;margin-inline-start:5px}.feedback-card-admin{background:#fff;border-radius:12px;padding:18px;margin-bottom:12px;box-shadow:0 2px 10px #0000000d}.feedback-card-admin .meta{display:flex;gap:16px;flex-wrap:wrap;color:var(--muted);font-size:13px;margin-bottom:10px}.feedback-card-admin .message{white-space:pre-wrap;line-height:1.65}.feedback-card-admin a{color:#263a70}
@media(max-width:900px){.admin-nav{grid-template-columns:1fr 1fr}.admin-nav a{font-size:14px;padding:13px 8px}
    .wrap{width:100%;padding:12px 4px 22px}
    th,td{font-size:11px;padding:4px 2px}
    th{font-size:10px}
    .destination{width:62px}
    .price-col,.average-col{width:51px}
    .score-part{width:38px}
    .total-score{width:45px}
}

/* v9.7.6 dashboard enlargement */
.wrap{width:calc(100vw - 24px)!important;max-width:none!important;margin:0 auto!important;padding:18px 10px 35px!important}
.table-wrap{width:100%!important;max-width:none!important;overflow-x:auto!important}
.table-wrap table{width:100%!important}
.table-wrap:not(.scans-table-wrap) table{min-width:1650px!important}
.table-wrap:not(.scans-table-wrap) th{font-size:14px!important;padding:10px 8px!important}
.table-wrap:not(.scans-table-wrap) td{font-size:15px!important;padding:11px 8px!important;line-height:1.35!important}
.scans-table-wrap .scans{width:100%!important;min-width:1050px!important}
.scans-table-wrap .scans th{font-size:17px!important;padding:15px 14px!important}
.scans-table-wrap .scans td{font-size:18px!important;padding:17px 14px!important;text-align:center!important}


/* v9.7.8 admin maximum-width readability */
.wrap{width:100vw!important;max-width:none!important;margin:0!important;padding:16px 8px 32px!important;box-sizing:border-box!important}
.table-wrap{width:100%!important;max-width:none!important;overflow-x:auto!important}
.table-wrap table{width:100%!important;min-width:1780px!important;table-layout:auto!important}
.table-wrap th{font-size:15px!important;padding:11px 9px!important;white-space:nowrap!important;overflow:visible!important;text-overflow:clip!important}
.table-wrap td{font-size:15px!important;padding:10px 9px!important;white-space:nowrap!important}
.scans-table-wrap .scans{width:100%!important;min-width:1200px!important}
.scans-table-wrap .scans th{font-size:18px!important;padding:15px 14px!important;white-space:nowrap!important}
.scans-table-wrap .scans td{font-size:18px!important;padding:15px 14px!important}


/* v9.7.10 — larger deal list in internal dashboard */
.wrap{width:100vw!important;max-width:none!important;padding-inline:4px!important}
.table-wrap{width:100%!important;max-width:none!important;overflow-x:auto!important}
.table-wrap:not(.scans-table-wrap) table{
  min-width:2200px!important;
  width:100%!important;
  table-layout:auto!important;
}
.table-wrap:not(.scans-table-wrap) th{
  font-size:18px!important;
  line-height:1.25!important;
  padding:15px 14px!important;
  white-space:nowrap!important;
  overflow:visible!important;
  text-overflow:clip!important;
}
.table-wrap:not(.scans-table-wrap) td{
  font-size:17px!important;
  line-height:1.35!important;
  padding:14px 13px!important;
  white-space:nowrap!important;
}
.table-wrap:not(.scans-table-wrap) .destination{min-width:130px!important}
.table-wrap:not(.scans-table-wrap) .price-col,
.table-wrap:not(.scans-table-wrap) .average-col{min-width:105px!important}
.table-wrap:not(.scans-table-wrap) .score-part{min-width:105px!important}
.table-wrap:not(.scans-table-wrap) .total-score{min-width:95px!important}
.table-wrap:not(.scans-table-wrap) .reason-col{
  min-width:430px!important;
  white-space:normal!important;
  overflow:visible!important;
  text-overflow:clip!important
}


.actions select{padding:10px 12px;border:1px solid #cfd6e2;border-radius:8px;background:white;font-weight:700;font-size:14px}

.biz-title{margin-top:26px}
.biz-note{background:#fff8e8;border:1px solid #ead8ad;border-radius:9px;padding:9px 12px;font-size:12px;color:#6c582a;margin:8px 0 12px}
.biz-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(165px,1fr));gap:10px;margin:12px 0 18px}
.biz-card{background:#fff;border-radius:12px;padding:14px;box-shadow:0 2px 10px #00000012}
.biz-card .num{color:var(--gold)}
.business-table th,.business-table td{font-size:12px;padding:7px 5px}
.business-table .month-col{width:85px}
.business-table .money{font-weight:800}
.biz-summary-btn{padding:5px 9px;font-size:11px;background:#65748b}
.daily-detail{display:none;background:#fbfcff}
.daily-detail.open{display:table-row}
.daily-detail td{padding:10px}
.daily-inner{width:100%;table-layout:auto}
.daily-inner th,.daily-inner td{font-size:11px;padding:5px}
.yoy{font-size:10px;color:var(--muted);display:block;margin-top:2px}

</style>
</head>
<body>
<div class="wrap">
<h1>אריאלה — לוח בקרה פנימי</h1>
<div class="muted">גרסה {{ version }} · סף דיל: {{ minimum_score }}</div>
<div class="admin-nav"><a class="active" href="/admin{% if token %}?token={{ token }}{% endif %}">✦ סריקות ודילים</a><a href="/admin/analytics{% if token %}?token={{ token }}{% endif %}">✦ משתמשים ונתונים</a><a href="/admin/feedback{% if token %}?token={{ token }}{% endif %}">✦ הערות והצעות {% if feedback_count %}<span class="unread-count">({{ feedback_count }})</span>{% endif %}</a></div>

<div class="actions">
    <button onclick="runScan()">הפעל סריקת ניסיון</button>
    <select id="targetDestination" aria-label="בחירת יעד לסריקה">
      <option value="FCO">רומא (FCO)</option>
      <option value="ATH">אתונה (ATH)</option>
      <option value="LCA">לרנקה (LCA)</option>
      <option value="BUD">בודפשט (BUD)</option>
      <option value="VIE">וינה (VIE)</option>
      <option value="SOF">סופיה (SOF)</option>
      <option value="PRG">פראג (PRG)</option>
      <option value="MXP">מילאנו (MXP)</option>
      <option value="CDG">פריז (CDG)</option>
      <option value="AMS">אמסטרדם (AMS)</option>
      <option value="BCN">ברצלונה (BCN)</option>
      <option value="MAD">מדריד (MAD)</option>
      <option value="LIS">ליסבון (LIS)</option>
      <option value="LHR">לונדון (LHR)</option>
      <option value="BER">ברלין (BER)</option>
      <option value="MUC">מינכן (MUC)</option>
      <option value="ZRH">ציריך (ZRH)</option>
      <option value="BRU">בריסל (BRU)</option>
      <option value="OTP">בוקרשט (OTP)</option>
      <option value="KRK">קרקוב (KRK)</option>
      <option value="WAW">ורשה (WAW)</option>
      <option value="TBS">טביליסי (TBS)</option>
      <option value="EVN">ירוואן (EVN)</option>
      <option value="BEG">בלגרד (BEG)</option>
      <option value="SKP">סקופיה (SKP)</option>
      <option value="TGD">פודגוריצה (TGD)</option>
      <option value="ZAG">זאגרב (ZAG)</option>
      <option value="LJU">לובליאנה (LJU)</option>
      <option value="BKK">בנגקוק (BKK)</option>
      <option value="JFK">ניו יורק (JFK)</option>
    </select>
    <button onclick="runDestinationScan()">סריקת יעד</button>
    <button onclick="runWideScan()">סריקה רחבה</button>
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
        {{ o.seasonality_score if o.seasonality_score is defined and o.seasonality_score is not none else
           (o.season_score if o.season_score is defined and o.season_score is not none else '—') }}
    </td>
    <td class="score-part" title="ניקוד אמינות">
        {{ o.reliability_score if o.reliability_score is defined and o.reliability_score is not none else '—' }}
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
<div class="table-wrap scans-table-wrap">
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
function toggleDaily(month){
  const row=document.getElementById('daily-'+month);
  if(row) row.classList.toggle('open');
}
const adminToken = {{ token|tojson }};
function withAdminToken(url){
    if(!adminToken) return url;
    const sep = url.includes('?') ? '&' : '?';
    return url + sep + 'token=' + encodeURIComponent(adminToken);
}
async function waitForScan(jobId){
    const e=document.getElementById('actionStatus');
    const started=Date.now();
    while(Date.now()-started < 20*60*1000){
        await new Promise(resolve=>setTimeout(resolve,2500));
        try{
            const r=await fetch(withAdminToken('/manual-scan-status/'+encodeURIComponent(jobId)),{cache:'no-store'});
            const data=await r.json();
            if(data.status==='starting' || data.status==='running'){
                e.textContent='הסריקה מתבצעת ברקע... אפשר לעבור לעמוד אחר.';
                continue;
            }
            if(data.status==='finished'){
                const result=data.result || {};
                e.textContent='הסריקה הסתיימה: '+(result.searches_completed ?? 0)+' חיפושים, '+(result.offers_found ?? 0)+' הצעות. מרעננת...';
                setTimeout(()=>location.reload(),900);
                return;
            }
            if(data.status==='failed'){
                e.textContent='הסריקה נכשלה: '+(data.error || 'שגיאה לא ידועה');
                return;
            }
            if(data.status==='unknown'){
                e.textContent='השרת הופעל מחדש. מרעננת את לוח הבקרה...';
                setTimeout(()=>location.reload(),1000);
                return;
            }
        }catch(_){
            // A temporary status request failure must not cancel the scan.
            e.textContent='הסריקה ממשיכה ברקע...';
        }
    }
    e.textContent='הסריקה עדיין מתבצעת. אפשר לרענן את לוח הבקרה מאוחר יותר.';
}

async function post(url){
    const e=document.getElementById('actionStatus');
    e.textContent='מתחילה סריקה...';
    try{
        const r=await fetch(withAdminToken(url),{method:'POST'});
        const raw=await r.text();
        let data=null;
        try{ data = raw ? JSON.parse(raw) : null; }catch(_){ data=null; }

        if(!data){
            e.textContent='השרת החזיר תשובה לא צפויה.';
            return;
        }
        if(r.status===202 && data.job_id){
            e.textContent=data.message || 'הסריקה התחילה ברקע.';
            waitForScan(data.job_id);
            return;
        }
        if(r.ok){
            e.textContent='הפעולה הסתיימה בהצלחה. מרעננת נתונים...';
            setTimeout(()=>location.reload(),900);
            return;
        }
        e.textContent='שגיאה: '+(data.message || JSON.stringify(data));
    }catch(x){
        e.textContent='לא ניתן היה להתחיל את הפעולה: '+x;
    }
}
function runScan(){if(confirm('סריקת ניסיון תבדוק מסלול אחד בלבד (הלוך + חזור). להמשיך?'))post('/scan?max_searches=1')}
function runDestinationScan(){
  const code=document.getElementById('targetDestination').value;
  if(confirm('לסרוק עכשיו את '+code+' בלבד? הסריקה תבדוק 3 חלונות חופשה ותשמור את הדילים הטובים.'))
    post('/scan-destination?arrival='+encodeURIComponent(code)+'&max_searches=3');
}
function runWideScan(){
  if(confirm('להפעיל סריקה רחבה על 30 יעדים? הסריקה מוגבלת לעד 3 אפשרויות הלוך לכל יעד (עד כ-150 בקשות API לכל היותר) ותמשיך ברקע גם אם תעברי לעמוד אחר.'))
    post('/scan-wide?max_destinations=30');
}
function buildBatch(){post('/daily-batch?force=true')}
</script>
</body>
</html>
"""


def render_dashboard(*, version, minimum_score, stats, offers, scans, feedback_count=0, analytics=None, token=""):
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
        analytics=analytics or {'overview':{},'monthly':[],'daily_by_month':{},'annual':[],'tracking_started_note':''},
        token=token,
    )



ANALYTICS_DASHBOARD_HTML = r"""
<!doctype html>
<html lang="he" dir="rtl">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>אריאלה — משתמשים ונתונים</title>
<style>
:root{--bg:#f5f7fb;--text:#182033;--muted:#697386;--line:#e7eaf0;--gold:#b8892e}
*{box-sizing:border-box}body{font-family:Arial,sans-serif;background:var(--bg);margin:0;color:var(--text)}
.wrap{width:min(1600px,98%);margin:auto;padding:24px 10px 40px}h1{margin:0 0 6px;font-size:34px}h2{margin:30px 0 12px;font-size:25px}.muted{color:var(--muted);font-size:15px}
.admin-nav{display:grid;grid-template-columns:repeat(3,1fr);gap:0;margin:24px 0;border-bottom:2px solid #d8c49a}
.admin-nav a{background:#fff;color:#263a70;border:1px solid #dfe4ed;border-bottom:0;padding:18px 24px;text-decoration:none;font-weight:800;font-size:18px;text-align:center;position:relative}
.admin-nav a.active{color:#182033}.admin-nav a.active:after{content:'';position:absolute;right:12%;left:12%;bottom:-2px;height:4px;background:var(--gold)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(185px,1fr));gap:12px;margin:18px 0}
.card{background:#fff;border-radius:12px;padding:18px;box-shadow:0 2px 10px #00000012;font-size:17px;line-height:1.45}.num{font-size:31px;font-weight:800;color:var(--gold);margin-top:7px}
.note{background:#fff8e8;border:1px solid #ead8ad;border-radius:9px;padding:12px 15px;font-size:15px;line-height:1.5;color:#6c582a}
.table-wrap{width:100%;overflow-x:auto;border-radius:12px;box-shadow:0 2px 10px #0000000d}
table{width:100%;border-collapse:collapse;background:#fff}th,td{padding:12px 10px;border-bottom:1px solid var(--line);text-align:center;font-size:16px;line-height:1.4}
th{background:#eef2f8;font-size:16px;font-weight:800}.money{font-weight:800}.yoy{display:block;color:var(--muted);font-size:13px;margin-top:3px}
button{background:#65748b;color:#fff;border:0;border-radius:7px;padding:8px 13px;font-size:14px;cursor:pointer}
.daily-detail{display:none}.daily-detail.open{display:table-row}.daily-inner{width:100%}
.two-col{display:grid;grid-template-columns:1fr 1fr;gap:14px}@media(max-width:900px){.two-col{grid-template-columns:1fr}}
</style>
</head>
<body><div class="wrap">
<h1>אריאלה — משתמשים ונתונים</h1>
<div class="muted">גרסה {{ version }}</div>
<div class="admin-nav">
<a href="/admin{% if token %}?token={{ token }}{% endif %}">✦ סריקות ודילים</a>
<a class="active" href="/admin/analytics{% if token %}?token={{ token }}{% endif %}">✦ משתמשים ונתונים</a>
<a href="/admin/feedback{% if token %}?token={{ token }}{% endif %}">✦ הערות והצעות</a>
</div>

<div class="note">{{ analytics.tracking_started_note }}</div>
<div class="grid">
<div class="card">משתמשים רשומים<div class="num">{{ analytics.overview.registered_total }}</div></div>
<div class="card">נכנסו לאתר<div class="num">{{ analytics.overview.visitors_total }}</div></div>
<div class="card">בחרו באריאלה שלי<div class="num">{{ analytics.overview.ariella_users_total }}</div></div>
<div class="card">לחיצות להזמנה<div class="num">{{ analytics.booking_clicks.total_clicks }}</div><span class="muted">{{ analytics.booking_clicks.unique_clickers }} משתמשים ייחודיים</span></div>
<div class="card">הכנסות החודש<div class="num">₪{{ analytics.overview.revenue_current_month|round|int }}</div></div>
<div class="card">הכנסות השנה<div class="num">₪{{ analytics.overview.revenue_current_year|round|int }}</div></div>
</div>

<h2>ביקוש — מה המשתמשים מחפשים</h2>
<div class="grid">
<div class="card">הרכב ממוצע<div class="num">{{ analytics.demand.average_party_size }}</div><span class="muted">נוסעים לחופשה</span></div>
<div class="card">משך חופשה ממוצע<div class="num">{{ analytics.demand.average_trip_length }}</div><span class="muted">ימים</span></div>
</div>
<div class="two-col">
<div class="table-wrap"><table><thead><tr><th>יעד</th><th>בקשות</th></tr></thead><tbody>
{% for x in analytics.demand.top_destinations %}<tr><td>{{ x.destination }}</td><td>{{ x.count }}</td></tr>{% else %}<tr><td colspan="2">אין נתונים</td></tr>{% endfor %}
</tbody></table></div>
<div class="table-wrap"><table><thead><tr><th>חודש נסיעה</th><th>בקשות</th></tr></thead><tbody>
{% for x in analytics.demand.travel_months %}<tr><td>{{ x.month }}</td><td>{{ x.count }}</td></tr>{% else %}<tr><td colspan="2">אין נתונים</td></tr>{% endfor %}
</tbody></table></div>
</div>

<h2>הרכבי נוסעים</h2>
<div class="table-wrap"><table><thead><tr><th>סוג</th><th>בקשות</th></tr></thead><tbody>
{% for x in analytics.demand.composition %}<tr><td>{{ x.type }}</td><td>{{ x.count }}</td></tr>{% else %}<tr><td colspan="2">אין נתונים</td></tr>{% endfor %}
</tbody></table></div>

<h2>דילים שעליהם לחצו להזמנה</h2>
<div class="two-col">
<div class="table-wrap"><table><thead><tr><th>יעד</th><th>לחיצות</th></tr></thead><tbody>
{% for x in analytics.booking_clicks.by_destination %}<tr><td>{{ x.destination }}</td><td>{{ x.clicks }}</td></tr>{% else %}<tr><td colspan="2">אין לחיצות עדיין</td></tr>{% endfor %}
</tbody></table></div>
<div class="table-wrap"><table><thead><tr><th>מועד</th><th>יעד</th><th>חברה</th><th>ספק</th><th>מחיר</th><th>ציון</th></tr></thead><tbody>
{% for x in analytics.booking_clicks.recent %}
<tr><td>{{ x.clicked_at[:16] if x.clicked_at else '' }}</td><td>{{ x.destination_code or '—' }}</td><td>{{ x.airline or '—' }}</td><td>{{ x.supplier or '—' }}</td><td>{{ x.price_ils|round|int if x.price_ils is not none else '—' }}</td><td>{{ x.score or '—' }}</td></tr>
{% else %}<tr><td colspan="6">אין לחיצות עדיין</td></tr>{% endfor %}
</tbody></table></div>
</div>

<h2>סיכום חודשי</h2>
<div class="table-wrap"><table>
<thead><tr><th>חודש</th><th>נרשמו</th><th>נכנסו</th><th>אריאלה שלי</th><th>רגוע</th><th>יומי</th><th>אינטנסיבי</th><th>הכנסות</th><th>פירוט</th></tr></thead>
<tbody>{% for m in analytics.monthly %}
<tr><td>{{ m.month }}</td><td>{{ m.registrations }}<span class="yoy">אשתקד: {{ m.prev_year.registrations }}</span></td>
<td>{{ m.visitors }}<span class="yoy">אשתקד: {{ m.prev_year.visitors }}</span></td>
<td>{{ m.ariella_users }}<span class="yoy">אשתקד: {{ m.prev_year.ariella_users }}</span></td>
<td>{{ m.calm }}</td><td>{{ m.daily }}</td><td>{{ m.intensive }}</td>
<td class="money">₪{{ m.revenue|round|int }}<span class="yoy">אשתקד: ₪{{ m.prev_year.revenue|round|int }}</span></td>
<td><button onclick="toggleDaily('{{ m.month }}')">סיכום</button></td></tr>
<tr id="daily-{{ m.month }}" class="daily-detail"><td colspan="9">
<table class="daily-inner"><thead><tr><th>יום</th><th>נרשמו</th><th>נכנסו</th><th>אריאלה שלי</th><th>רגוע</th><th>יומי</th><th>אינטנסיבי</th><th>הכנסות</th></tr></thead><tbody>
{% for day in analytics.daily_by_month.get(m.month, []) %}
<tr><td>{{ day.day }}</td><td>{{ day.registrations }}</td><td>{{ day.visitors }}</td><td>{{ day.ariella_users }}</td><td>{{ day.calm }}</td><td>{{ day.daily }}</td><td>{{ day.intensive }}</td><td>₪{{ day.revenue|round|int }}</td></tr>
{% else %}<tr><td colspan="8">אין נתונים יומיים</td></tr>{% endfor %}
</tbody></table></td></tr>
{% endfor %}</tbody></table></div>

<h2>סיכום שנתי</h2>
<div class="table-wrap"><table><thead><tr><th>שנה</th><th>נרשמו</th><th>נכנסו</th><th>אריאלה שלי</th><th>רגוע</th><th>יומי</th><th>אינטנסיבי</th><th>הכנסות</th></tr></thead>
<tbody>{% for y in analytics.annual %}<tr><td>{{ y.year }}</td><td>{{ y.registrations }}</td><td>{{ y.visitors }}</td><td>{{ y.ariella_users }}</td><td>{{ y.calm }}</td><td>{{ y.daily }}</td><td>{{ y.intensive }}</td><td class="money">₪{{ y.revenue|round|int }}</td></tr>{% endfor %}</tbody></table></div>

<script>
function toggleDaily(month){const row=document.getElementById('daily-'+month);if(row)row.classList.toggle('open');}
</script>
</div></body></html>
"""

def render_analytics_dashboard(*, version, analytics, token=""):
    return render_template_string(
        ANALYTICS_DASHBOARD_HTML,
        version=version,
        analytics=analytics,
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
