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

    stops = int(item.get("stops") or 0)
    item["route_color"] = (
        "direct" if stops == 0 else
        "one-stop" if stops == 1 else
        "multi-stop"
    )
    item["route_tooltip"] = (
        "טיסה ישירה" if stops == 0 else
        "קונקשן אחד" if stops == 1 else
        "שני קונקשנים ומעלה"
    )
    item["route_filter"] = "direct" if stops == 0 else "one" if stops == 1 else "multi"

    reasons = item.get("score_reasons") or []
    item["details_reasons"] = reasons
    return item


DASHBOARD_HTML = r"""
<!doctype html>
<html lang="he" dir="rtl">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>אריאלה — לוח בקרה</title>
<style>
:root{
    --bg:#f5f7fb;--text:#182033;--muted:#697386;--line:#e5eaf2;
    --head:#eef2f8;--navy:#263a70;--good:#16865f;--orange:#e58a19;
    --bad:#cf3f3f;--white:#fff;
}
*{box-sizing:border-box}
body{font-family:Arial,sans-serif;background:var(--bg);margin:0;color:var(--text)}
.wrap{width:96%;max-width:1450px;margin:auto;padding:22px 12px 34px}
h1{margin:0 0 6px}.muted{color:var(--muted)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:12px;margin:20px 0}
.card{background:#fff;border-radius:14px;padding:16px;box-shadow:0 2px 10px #00000012}
.num{font-size:28px;font-weight:700;margin-top:8px}
.actions{display:flex;gap:10px;flex-wrap:wrap;margin:14px 0}.status{padding:8px 0;font-weight:700}
button,a.btn{background:var(--navy);color:#fff;border:0;border-radius:9px;padding:10px 14px;text-decoration:none;cursor:pointer}
.secondary{background:#65748b!important}
h2{margin:24px 0 9px}
.summary{background:#fff;border:1px solid var(--line);border-radius:11px;padding:10px 13px;margin-bottom:9px;font-size:14px;font-weight:700}
.legend{font-size:12px;color:var(--muted);font-weight:400;margin-right:14px;white-space:nowrap}
.dot{display:inline-block;width:10px;height:10px;border-radius:50%;vertical-align:middle;margin:0 3px}
.dot.direct{background:var(--good)}.dot.one-stop{background:var(--orange)}.dot.multi-stop{background:var(--bad)}

.filters{
    display:grid;
    grid-template-columns:1.25fr 1fr 1fr .9fr .9fr auto auto;
    gap:8px;
    align-items:end;
    background:#fff;
    border:1px solid var(--line);
    border-radius:12px;
    padding:11px;
    margin-bottom:10px;
}
.filter-group{display:flex;flex-direction:column;gap:4px}
.filter-group label{font-size:11px;color:var(--muted);font-weight:700}
.filters input,.filters select{
    width:100%;border:1px solid #cfd7e5;border-radius:8px;padding:8px 9px;
    font-family:inherit;background:#fff;color:var(--text)
}
.checkbox-filter{display:flex;align-items:center;gap:6px;height:36px;white-space:nowrap;font-size:12px;font-weight:700}
.checkbox-filter input{width:auto}
.clear-filter{height:36px;background:#65748b}

.table-wrap{width:100%;overflow-x:auto;background:#fff;border-radius:14px;box-shadow:0 2px 10px #0000000d}
table{width:100%;min-width:1180px;border-collapse:collapse;background:#fff}
th,td{padding:9px 7px;border-bottom:1px solid var(--line);text-align:center;font-size:13px;line-height:1.25;white-space:nowrap}
th{background:var(--head);font-size:12px;font-weight:700}
tbody tr.offer-row{cursor:pointer}
tbody tr.offer-row:hover{background:#f7f9fd}
.destination{min-width:90px}.destination-code{display:block;font-size:14px;font-weight:800}.destination-name{display:block;margin-top:3px;font-size:12px}
.dates{min-width:145px;line-height:1.45}.date-line{display:block}
.price{min-width:82px}.points{min-width:62px}.route{min-width:72px}.final{min-width:88px}
.reason{min-width:190px;max-width:260px;text-align:right;white-space:normal}
.route-value{display:inline-flex;align-items:center;justify-content:center;gap:7px;font-weight:800}
.route-value .route-dot{width:10px;height:10px;border-radius:50%;display:inline-block;flex:none}
.route-value.direct .route-dot{background:var(--good)}
.route-value.one-stop .route-dot{background:var(--orange)}
.route-value.multi-stop .route-dot{background:var(--bad)}
.final-score{font-size:16px;font-weight:800}
.scans{min-width:760px}.empty{padding:20px!important;color:var(--muted)}
.no-results{display:none;padding:18px;text-align:center;color:var(--muted);background:#fff}

.modal-backdrop{
    position:fixed;inset:0;background:#0008;display:none;align-items:center;justify-content:center;
    z-index:9999;padding:16px
}
.modal{
    width:min(720px,96vw);max-height:88vh;overflow:auto;background:#fff;border-radius:16px;
    box-shadow:0 20px 60px #0005;padding:18px
}
.modal-header{display:flex;justify-content:space-between;align-items:start;gap:12px;border-bottom:1px solid var(--line);padding-bottom:10px}
.modal-title{font-size:21px;font-weight:800}.modal-close{background:#eef2f8;color:var(--text);padding:7px 11px}
.detail-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px 16px;margin:15px 0}
.detail-item{display:flex;justify-content:space-between;gap:12px;border-bottom:1px dashed var(--line);padding:7px 0}
.detail-label{color:var(--muted)}.detail-value{font-weight:800}
.reasons-box{background:#f7f9fd;border-radius:11px;padding:12px}
.reasons-box h3{margin:0 0 8px}.reasons-box ul{margin:0;padding-right:20px}.reasons-box li{margin:6px 0}
.source-note{margin-top:10px;font-size:12px;color:var(--muted)}

@media(max-width:1050px){
    .filters{grid-template-columns:repeat(3,1fr)}
}
@media(max-width:900px){
    .wrap{width:100%;padding:14px 5px 25px}
    .grid{grid-template-columns:repeat(2,minmax(130px,1fr))}
    .legend{display:block;margin:7px 0 0}
    th,td{font-size:12px;padding:7px 5px}
    .filters{grid-template-columns:repeat(2,1fr)}
}
@media(max-width:560px){
    .filters{grid-template-columns:1fr}
    .detail-grid{grid-template-columns:1fr}
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

<div class="summary">
    <span id="summaryCount">{{ offers|length }}</span> הצעות ·
    <span id="summaryQualified">{{ qualified_count }}</span> עברו את הסף ·
    ציון ממוצע <span id="summaryAverage">{{ offers_average }}</span> ·
    ציון גבוה <span id="summaryHighest">{{ offers_highest }}</span>
    <span class="legend">
        <span class="dot direct"></span>ישירה
        <span class="dot one-stop"></span>קונקשן אחד
        <span class="dot multi-stop"></span>שניים ומעלה
    </span>
</div>

<div class="filters">
    <div class="filter-group">
        <label for="filterDestination">יעד</label>
        <input id="filterDestination" type="search" placeholder="שם יעד או קוד">
    </div>
    <div class="filter-group">
        <label for="filterDateFrom">יציאה מתאריך</label>
        <input id="filterDateFrom" type="date">
    </div>
    <div class="filter-group">
        <label for="filterDateTo">חזרה עד תאריך</label>
        <input id="filterDateTo" type="date">
    </div>
    <div class="filter-group">
        <label for="filterMaxPrice">מחיר מרבי</label>
        <input id="filterMaxPrice" type="number" min="0" step="1" placeholder="למשל 1500">
    </div>
    <div class="filter-group">
        <label for="filterRoute">מסלול</label>
        <select id="filterRoute">
            <option value="">הכול</option>
            <option value="direct">ישירה</option>
            <option value="one">קונקשן אחד</option>
            <option value="multi">שניים ומעלה</option>
        </select>
    </div>
    <div class="filter-group">
        <label for="filterMinScore">ציון סופי מינימלי</label>
        <input id="filterMinScore" type="number" min="0" max="100" step="1" placeholder="0">
    </div>
    <label class="checkbox-filter">
        <input id="filterQualified" type="checkbox">
        עברו את הסף בלבד
    </label>
    <button class="clear-filter" type="button" onclick="clearFilters()">נקה סינון</button>
</div>

<div class="table-wrap">
<table id="offersTable">
<thead><tr>
    <th class="destination">יעד</th>
    <th class="dates">תאריכים</th>
    <th class="price">מחיר ₪</th>
    <th class="price">ממוצע ₪</th>
    <th class="points">עלות</th>
    <th class="route">מסלול</th>
    <th class="points">כבודה</th>
    <th class="points">שעות</th>
    <th class="points">נדירות</th>
    <th class="points">עונתיות</th>
    <th class="points">אמינות</th>
    <th class="final">ציון סופי</th>
    <th class="reason">סיבת השליחה</th>
</tr></thead>
<tbody>
{% for o in offers %}
<tr class="offer-row"
    data-index="{{ loop.index0 }}"
    data-destination="{{ (o.arrival_code or '')|lower }} {{ (o.destination_name or '')|lower }}"
    data-outbound="{{ o.outbound_date or '' }}"
    data-return="{{ o.return_date or '' }}"
    data-price="{{ o.price_ils or 0 }}"
    data-route="{{ o.route_filter }}"
    data-score="{{ o.score or 0 }}"
    onclick="openDetails({{ loop.index0 }})">
    <td class="destination">
        <span class="destination-code">{{ o.arrival_code or '—' }}</span>
        <span class="destination-name">{{ o.destination_name or o.arrival_code or '—' }}</span>
    </td>
    <td class="dates">
        <span class="date-line">{{ o.outbound_display }}</span>
        <span class="date-line">{{ o.return_display }}</span>
    </td>
    <td class="price">{{ o.price_ils|round|int if o.price_ils is not none else '—' }}</td>
    <td class="price" title="מחיר הייחוס שעליו התבסס ניקוד העלות">
        {{ o.reference_price_ils|round|int if o.reference_price_ils is not none else '—' }}
    </td>
    <td class="points">{{ o.cost_score if o.cost_score is not none else '—' }}</td>
    <td class="route" title="{{ o.route_tooltip }}">
        <span class="route-value {{ o.route_color }}">
            <span class="route-dot"></span>
            <span>{{ o.route_score if o.route_score is not none else '—' }}</span>
        </span>
    </td>
    <td class="points">{{ o.baggage_score if o.baggage_score is not none else '—' }}</td>
    <td class="points">{{ o.hours_score if o.hours_score is not none else '—' }}</td>
    <td class="points">{{ o.rarity_score if o.rarity_score is not none else '—' }}</td>
    <td class="points">{{ o.seasonality_score if o.seasonality_score is not none else '—' }}</td>
    <td class="points">{{ o.reliability_score if o.reliability_score is not none else '—' }}</td>
    <td class="final"><span class="final-score">{{ o.score }}</span></td>
    <td class="reason" title="{{ o.score_reasons|join(' · ') }}">{{ o.send_reason or '—' }}</td>
</tr>
{% else %}
<tr><td class="empty" colspan="13">עדיין אין הצעות. הפעילי סריקה.</td></tr>
{% endfor %}
</tbody>
</table>
<div id="noResults" class="no-results">לא נמצאו הצעות שמתאימות לסינון.</div>
</div>

<h2>סריקות אחרונות</h2>
<div class="table-wrap">
<table class="scans">
<thead><tr><th>מס׳</th><th>סטטוס</th><th>התחלה</th><th>חיפושים</th><th>הצעות</th><th>שגיאות</th></tr></thead>
<tbody>
{% for s in scans %}
<tr><td>{{ s.id }}</td><td>{{ s.status }}</td><td>{{ s.started_at }}</td><td>{{ s.searches_completed }}/{{ s.searches_planned }}</td><td>{{ s.offers_found }}</td><td>{{ s.errors }}</td></tr>
{% else %}
<tr><td class="empty" colspan="6">עדיין אין סריקות.</td></tr>
{% endfor %}
</tbody>
</table>
</div>
</div>

<div id="detailsBackdrop" class="modal-backdrop" onclick="closeDetails(event)">
    <div class="modal" onclick="event.stopPropagation()">
        <div class="modal-header">
            <div>
                <div id="detailTitle" class="modal-title"></div>
                <div id="detailDates" class="muted"></div>
            </div>
            <button class="modal-close" type="button" onclick="closeDetails()">סגירה</button>
        </div>
        <div id="detailGrid" class="detail-grid"></div>
        <div class="reasons-box">
            <h3>איך חושב הציון?</h3>
            <ul id="detailReasons"></ul>
            <div class="source-note">
                הפירוט מוצג ישירות מנתוני מנוע הניקוד. ערך 0 יכול להיות ציון אמיתי,
                או תוצאה של מחסור בנתונים — ההסבר לידו מבהיר מה קרה.
            </div>
        </div>
    </div>
</div>

<script>
const offersData = {{ offers|tojson }};
const minimumScore = {{ minimum_score }};

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

const filterIds = [
    'filterDestination','filterDateFrom','filterDateTo','filterMaxPrice',
    'filterRoute','filterMinScore','filterQualified'
];
filterIds.forEach(id => {
    const element = document.getElementById(id);
    element.addEventListener(element.type === 'checkbox' ? 'change' : 'input', applyFilters);
    if(element.tagName === 'SELECT') element.addEventListener('change', applyFilters);
});

function applyFilters(){
    const destination = document.getElementById('filterDestination').value.trim().toLowerCase();
    const dateFrom = document.getElementById('filterDateFrom').value;
    const dateTo = document.getElementById('filterDateTo').value;
    const maxPrice = Number(document.getElementById('filterMaxPrice').value || 0);
    const route = document.getElementById('filterRoute').value;
    const minScore = Number(document.getElementById('filterMinScore').value || 0);
    const qualifiedOnly = document.getElementById('filterQualified').checked;

    const rows = [...document.querySelectorAll('#offersTable tbody tr.offer-row')];
    const visibleScores = [];

    rows.forEach(row => {
        const rowDestination = row.dataset.destination || '';
        const outbound = row.dataset.outbound || '';
        const returnDate = row.dataset.return || '';
        const price = Number(row.dataset.price || 0);
        const rowRoute = row.dataset.route || '';
        const score = Number(row.dataset.score || 0);

        const visible =
            (!destination || rowDestination.includes(destination)) &&
            (!dateFrom || outbound >= dateFrom) &&
            (!dateTo || returnDate <= dateTo) &&
            (!maxPrice || price <= maxPrice) &&
            (!route || rowRoute === route) &&
            (!minScore || score >= minScore) &&
            (!qualifiedOnly || score >= minimumScore);

        row.style.display = visible ? '' : 'none';
        if(visible) visibleScores.push(score);
    });

    document.getElementById('noResults').style.display =
        visibleScores.length === 0 && rows.length ? 'block' : 'none';

    const qualified = visibleScores.filter(score => score >= minimumScore).length;
    const average = visibleScores.length
        ? (visibleScores.reduce((a,b)=>a+b,0) / visibleScores.length).toFixed(1)
        : '0';
    const highest = visibleScores.length ? Math.max(...visibleScores) : 0;

    document.getElementById('summaryCount').textContent = visibleScores.length;
    document.getElementById('summaryQualified').textContent = qualified;
    document.getElementById('summaryAverage').textContent = average;
    document.getElementById('summaryHighest').textContent = highest;
}

function clearFilters(){
    filterIds.forEach(id => {
        const element = document.getElementById(id);
        if(element.type === 'checkbox') element.checked = false;
        else element.value = '';
    });
    applyFilters();
}

function valueOrDash(value){
    return value === null || value === undefined || value === '' ? '—' : value;
}
function money(value){
    if(value === null || value === undefined || value === '') return '—';
    return Math.round(Number(value)).toLocaleString('he-IL') + ' ₪';
}
function addDetail(label, value){
    return `<div class="detail-item"><span class="detail-label">${label}</span><span class="detail-value">${valueOrDash(value)}</span></div>`;
}

function openDetails(index){
    const offer = offersData[index];
    document.getElementById('detailTitle').textContent =
        `${offer.arrival_code || '—'} · ${offer.destination_name || offer.arrival_code || '—'}`;
    document.getElementById('detailDates').textContent =
        `${offer.outbound_display || '—'}  ←  ${offer.return_display || '—'}`;

    document.getElementById('detailGrid').innerHTML =
        addDetail('מחיר בפועל', money(offer.price_ils)) +
        addDetail('מחיר ממוצע / ייחוס', money(offer.reference_price_ils)) +
        addDetail('עלות', offer.cost_score) +
        addDetail('מסלול', `${valueOrDash(offer.route_score)} · ${offer.route_tooltip || ''}`) +
        addDetail('כבודה', offer.baggage_score) +
        addDetail('שעות', offer.hours_score) +
        addDetail('נדירות', offer.rarity_score) +
        addDetail('עונתיות', offer.seasonality_score) +
        addDetail('אמינות', offer.reliability_score) +
        addDetail('ציון סופי', offer.score);

    const list = document.getElementById('detailReasons');
    list.innerHTML = '';
    const reasons = offer.details_reasons || [];
    if(reasons.length){
        reasons.forEach(reason => {
            const li = document.createElement('li');
            li.textContent = reason;
            list.appendChild(li);
        });
    }else{
        const li = document.createElement('li');
        li.textContent = 'אין פירוט חישוב שמור עבור הדיל הזה.';
        list.appendChild(li);
    }

    document.getElementById('detailsBackdrop').style.display = 'flex';
}
function closeDetails(event){
    if(event && event.target !== document.getElementById('detailsBackdrop')) return;
    document.getElementById('detailsBackdrop').style.display = 'none';
}
document.addEventListener('keydown', event => {
    if(event.key === 'Escape') closeDetails();
});
</script>
</body>
</html>
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
