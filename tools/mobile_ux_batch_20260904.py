from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]

def read(rel):
    return (ROOT / rel).read_text(encoding='utf-8')

def write(rel, text):
    (ROOT / rel).write_text(text, encoding='utf-8')

# ---------------- Header: mobile language | centered logo | nav + My Ariella ----------------
p = ROOT / 'templates/_site_header.html'
t = p.read_text(encoding='utf-8')
if 'mobile-nav-toggle' not in t:
    old = '''    <nav class="main-nav" aria-label="{{ 'Main navigation' if site_lang == 'en' else 'תפריט ראשי' }}">
      <a class="{% if request.endpoint == 'site.home' %}active{% endif %}" href="{{ url_for('site.home', lang=site_lang) }}">{{ 'Home' if site_lang == 'en' else 'ראשי' }}</a>
      <a class="{% if request.endpoint == 'site.about' %}active{% endif %}" href="{{ url_for('site.about', lang=site_lang) }}">{{ 'About' if site_lang == 'en' else 'קצת עלינו' }}</a>
      <a class="{% if request.endpoint == 'site.deals' %}active{% endif %}" href="{{ url_for('site.deals', lang=site_lang) }}">{{ 'Deals' if site_lang == 'en' else 'דילים' }}</a>
    </nav>
'''
    new = old + '''    <div class="mobile-nav-wrap">
      <button class="mobile-nav-toggle" id="mobileNavToggle" type="button" aria-expanded="false" aria-controls="mobileNavMenu" aria-label="{{ 'Open menu' if site_lang=='en' else 'פתיחת תפריט' }}">☰</button>
      <nav class="mobile-nav-menu" id="mobileNavMenu" hidden aria-label="{{ 'Mobile navigation' if site_lang=='en' else 'תפריט נייד' }}">
        <a href="{{ url_for('site.home', lang=site_lang) }}">{{ 'Home' if site_lang=='en' else 'ראשי' }}</a>
        <a href="{{ url_for('site.about', lang=site_lang) }}">{{ 'About' if site_lang=='en' else 'קצת עלינו' }}</a>
        <a href="{{ url_for('site.deals', lang=site_lang) }}">{{ 'Deals' if site_lang=='en' else 'דילים' }}</a>
      </nav>
    </div>
'''
    if old not in t:
        raise RuntimeError('header nav anchor missing')
    t = t.replace(old, new, 1)
    t += '''\n<script id="mobile-main-nav-script">\n(function(){\n const b=document.getElementById('mobileNavToggle'),m=document.getElementById('mobileNavMenu'); if(!b||!m)return;\n const close=()=>{m.hidden=true;b.setAttribute('aria-expanded','false')};\n b.addEventListener('click',e=>{e.stopPropagation();const opening=m.hidden;m.hidden=!opening;b.setAttribute('aria-expanded',opening?'true':'false')});\n document.addEventListener('click',e=>{if(!m.contains(e.target)&&e.target!==b)close()});\n document.addEventListener('keydown',e=>{if(e.key==='Escape')close()});\n})();\n</script>\n'''
p.write_text(t, encoding='utf-8')

# ---------------- Questionnaire ----------------
p = ROOT / 'templates/trip_form.html'
t = p.read_text(encoding='utf-8')
# remove repeated questionnaire hero globally
hero_re = re.compile(r'\n<section class="page-hero trip-questionnaire-hero">.*?</section>\n', re.S)
t, n = hero_re.subn('\n', t, count=1)

# First question of each route: add explicit back-to-vacation-type button.
for route in ('standard','business','ski'):
    pat = re.compile(r'(<section class="wizard-step(?: business-question| ski-question)?" data-route="'+route+r'" data-step="1" hidden>.*?<div class="wizard-actions">)(.*?)(</div>\s*</section>)', re.S)
    m = pat.search(t)
    if m and 'wizard-type-back' not in m.group(0):
        back = '''<button type="button" class="button secondary wizard-type-back">{{'Back to vacation type' if site_lang=='en' else 'חזרה לבחירת סוג חופשה'}}</button>'''
        t = t[:m.start()] + m.group(1) + back + m.group(2) + m.group(3) + t[m.end():]

# Business B2: explicit yes/no flexibility, contextual lower fields, clear Date/Time labels.
b2 = re.compile(r'<section class="wizard-step business-question" data-route="business" data-step="2" hidden>.*?</section>', re.S)
new_b2 = '''<section class="wizard-step business-question" data-route="business" data-step="2" hidden>
    <span class="step-number">B2</span><h2>{{'When do you need to travel?' if site_lang=='en' else 'מתי צריך לטוס?'}}</h2>
    <div class="conditional-panel two-cols business-date-panel compact-date-panel">
      <label>{{'Departure date' if site_lang=='en' else 'תאריך יציאה'}}<input type="date" name="business_departure_date" id="businessDepartureDate" min="{{today}}" required></label>
      <label>{{'Return date' if site_lang=='en' else 'תאריך חזרה'}}<input type="date" name="business_return_date" id="businessReturnDate" min="{{today}}" required></label>
    </div>
    <div class="business-flex-choice">
      <h3>{{'Do you have flexibility in the dates?' if site_lang=='en' else 'האם יש לך גמישות בתאריכים?'}}</h3>
      <div class="choice-row compact-options">
        <label class="choice-button small"><input type="radio" name="business_flexible_dates" value="1" required><span>{{'Yes' if site_lang=='en' else 'כן'}}</span></label>
        <label class="choice-button small"><input type="radio" name="business_flexible_dates" value="0" required><span>{{'No' if site_lang=='en' else 'לא'}}</span></label>
      </div>
    </div>
    <div class="conditional-panel" id="businessFlexPanel" hidden>
      <label class="inline-compact-field"><span>{{'How many days can the dates move?' if site_lang=='en' else 'כמה ימים אפשר להזיז?'}}</span>
        <select name="business_flex_days" id="businessFlexDays"><option value="1">± 1</option><option value="2">± 2</option><option value="3">± 3</option></select>
      </label>
    </div>
    <div class="conditional-panel" id="businessTimePanel" hidden>
      <h3>{{'Are there times you need to meet?' if site_lang=='en' else 'יש זמנים שחשוב לעמוד בהם?'}}</h3>
      <div class="business-time-rows">
        <div class="business-time-block"><strong>{{'I need to arrive by' if site_lang=='en' else 'אני צריך/ה להגיע ליעד עד'}}</strong>
          <label class="labeled-inline"><span>{{'Date' if site_lang=='en' else 'תאריך'}}</span><input type="date" name="business_arrive_by_date" id="businessArriveByDate" min="{{today}}"></label>
          <label class="labeled-inline"><span>{{'Time' if site_lang=='en' else 'שעה'}}</span><input type="time" name="business_arrive_by_time"></label>
        </div>
        <div class="business-time-block"><strong>{{'I can leave the destination from' if site_lang=='en' else 'אני יכול/ה לצאת מהיעד החל מ'}}</strong>
          <label class="labeled-inline"><span>{{'Date' if site_lang=='en' else 'תאריך'}}</span><input type="date" name="business_return_after_date" id="businessReturnAfterDate" min="{{today}}"></label>
          <label class="labeled-inline"><span>{{'Time' if site_lang=='en' else 'שעה'}}</span><input type="time" name="business_return_after_time"></label>
        </div>
      </div>
      <p class="helper">{{'If an early arrival is required, Ariella may also consider departure the previous day.' if site_lang=='en' else 'אם נדרשת הגעה מוקדמת, אריאלה יכולה לבדוק גם יציאה ביום הקודם כדי לעמוד בזמן.'}}</p>
    </div>
    <div class="wizard-actions"><button type="button" class="button secondary wizard-back">{{'Back' if site_lang=='en' else 'חזרה'}}</button><button type="button" class="button primary wizard-next">{{'Continue' if site_lang=='en' else 'המשך'}}</button></div>
  </section>'''
t, n_b2 = b2.subn(new_b2, t, count=1)
if n_b2 != 1:
    raise RuntimeError('B2 patch failed')

# First-step back action.
anchor = "  form.querySelectorAll('.wizard-next').forEach(b=>b.addEventListener('click',()=>{const s=routeSteps()[current]; if(validateStep(s))showStep(current+1)}));\n"
if anchor in t and "wizard-type-back').forEach" not in t:
    t = t.replace(anchor, anchor + "  form.querySelectorAll('.wizard-type-back').forEach(b=>b.addEventListener('click',backToGate));\n", 1)

# Business flexibility sync uses explicit yes/no.
old_sync = '''    const bflex=document.getElementById('businessFlexibleDates')?.checked===true;
    document.getElementById('businessFlexPanel').hidden=!bflex;
    document.getElementById('businessTimePanel').hidden=bflex;
'''
new_sync = '''    const bflex=form.querySelector('input[name="business_flexible_dates"]:checked')?.value;
    document.getElementById('businessFlexPanel').hidden=bflex!=='1';
    document.getElementById('businessTimePanel').hidden=bflex!=='0';
'''
if old_sync in t:
    t = t.replace(old_sync, new_sync, 1)

# Strong visual state sync + gentle reveal of new conditional fields.
old_listener = "  form.addEventListener('change',syncAll);\n"
new_listener = '''  function syncSelectedStates(){
    form.querySelectorAll('.choice-button input,.vacation-type-card input').forEach(i=>{
      i.closest('.choice-button,.vacation-type-card')?.classList.toggle('selected',!!i.checked);
    });
  }
  function revealNewFields(){
    if(!window.matchMedia('(max-width: 760px)').matches)return;
    const step=routeSteps()[current]; if(!step)return;
    const visible=Array.from(step.querySelectorAll('.conditional-panel:not([hidden]),.ski-season-warning:not([hidden])')).filter(el=>el.offsetParent!==null);
    const target=visible[visible.length-1]; if(!target)return;
    const r=target.getBoundingClientRect();
    if(r.bottom>window.innerHeight-80){setTimeout(()=>target.scrollIntoView({behavior:'smooth',block:'center'}),60);}
  }
  form.addEventListener('change',()=>{syncAll();syncSelectedStates();setTimeout(revealNewFields,80);});
'''
if old_listener in t:
    t = t.replace(old_listener, new_listener, 1)

p.write_text(t, encoding='utf-8')

# ---------------- Base: centered login error ----------------
p = ROOT / 'templates/base.html'
t = p.read_text(encoding='utf-8')
if 'login-error-modal-runtime' not in t:
    t = t.replace('</body></html>', '''<script id="login-error-modal-runtime">
document.addEventListener('DOMContentLoaded',function(){
  const login=document.querySelector('.auth-section .form-card');
  const stack=document.querySelector('.flash-stack');
  if(!login||!stack)return;
  const err=stack.querySelector('.flash.error,.flash.danger'); if(!err)return;
  err.textContent=document.documentElement.lang==='en'?'The email address or password is incorrect.':'כתובת המייל או הסיסמה אינם נכונים';
  stack.classList.add('login-error-modal');
  const b=document.createElement('button'); b.type='button'; b.className='login-error-close'; b.textContent=document.documentElement.lang==='en'?'OK':'אישור';
  b.addEventListener('click',()=>{stack.remove();login.scrollIntoView({behavior:'smooth',block:'center'});login.querySelector('input[name="email"]')?.focus();});
  err.appendChild(b);
});
</script>
</body></html>''', 1)
p.write_text(t, encoding='utf-8')

# ---------------- Booking: remove customer-facing technical warning; preserve party + cabin ----------------
p = ROOT / 'public_site.py'
t = p.read_text(encoding='utf-8')
t = t.replace('''    target = resolve_booking_target(offer, adults=adults, children=children)''', '''    cabin_class = ((personal_trip.get("answers") or {}).get("business_cabin_class") if personal_trip else None)
    target = resolve_booking_target(offer, adults=adults, children=children, cabin_class=cabin_class)''')
t = t.replace('''        flash("לא ניתן לפתוח כרגע הזמנה מדויקת אצל הספק לדיל הזה. לא העברנו אותך להזמנה כללית או עם מספר נוסעים שגוי.", "warning")
        return redirect(url_for("site.account") + f"#vacation-{trip_id}")''', '''        return redirect(url_for("site.account") + f"#vacation-{trip_id}")''')
p.write_text(t, encoding='utf-8')

p = ROOT / 'booker.py'
t = p.read_text(encoding='utf-8')
t = t.replace('def resolve_booking_target(offer: dict, *, adults: int | None = None, children: int | None = None) -> BookerTarget:', 'def resolve_booking_target(offer: dict, *, adults: int | None = None, children: int | None = None, cabin_class: str | None = None) -> BookerTarget:')
needle = '    pax_children = max(0, int(children or 0))\n'
if needle in t and 'cabin_map' not in t[t.find('def resolve_booking_target('):t.find('def resolve_booking_target(')+2500]:
    t = t.replace(needle, needle + '''    cabin_map = {"economy":"1", "premium":"2", "business":"3", "first":"4"}
    travel_class = cabin_map.get(str(cabin_class or "").lower(), "1")
''', 1)
t = t.replace('"travel_class":"1", "adults":str(pax_adults)', '"travel_class":travel_class, "adults":str(pax_adults)')
p.write_text(t, encoding='utf-8')

# ---------------- Responsive CSS overrides ----------------
p = ROOT / 'static/site.css'
t = p.read_text(encoding='utf-8')
marker = '/* 2026-09-04 mobile UX batch */'
if marker not in t:
    t += r'''

/* 2026-09-04 mobile UX batch */
.trip-questionnaire-hero{display:none!important}
.mobile-nav-wrap,.mobile-nav-toggle,.mobile-nav-menu{display:none}
.login-error-modal{position:fixed!important;inset:0!important;z-index:99999!important;width:100%!important;max-width:none!important;margin:0!important;background:rgba(0,0,0,.42)!important;display:flex!important;align-items:center!important;justify-content:center!important;padding:22px!important}
.login-error-modal .flash{width:min(440px,92vw)!important;background:#fff!important;color:#181818!important;border:1px solid #c99a3f!important;border-radius:16px!important;padding:28px 24px!important;text-align:center!important;font-size:20px!important;box-shadow:0 18px 60px rgba(0,0,0,.25)!important}
.login-error-close{display:block;margin:22px auto 0;padding:11px 34px;border:0;background:#17283f;color:#fff;font-weight:700;cursor:pointer}
.business-time-rows{display:grid;grid-template-columns:1fr 1fr;gap:18px}.business-time-block{display:grid;gap:10px}.labeled-inline{display:grid!important;grid-template-columns:auto 1fr;align-items:center;gap:10px}.labeled-inline span{font-weight:700;min-width:48px}.inline-compact-field{display:flex!important;align-items:center;justify-content:center;gap:14px}.inline-compact-field select{width:auto!important;min-width:90px!important}

@media(max-width:760px){
  .site-header{min-height:92px!important;padding:8px 0!important}.site-header .header-inner{width:96%!important;display:grid!important;grid-template-columns:minmax(72px,1fr) auto minmax(128px,1fr)!important;grid-template-areas:'lang brand controls'!important;gap:6px!important;direction:ltr!important;position:relative!important}
  .site-header .language-switch{grid-area:lang!important;justify-self:start!important;grid-column:auto!important;grid-row:auto!important;font-size:14px!important}
  .site-header .brand{grid-area:brand!important;justify-self:center!important;gap:7px!important}.site-header .logo-a{width:48px!important;height:48px!important}.site-header .brand-name{font-size:19px!important;letter-spacing:5px!important}.site-header .brand-tag{font-size:8px!important;letter-spacing:2.5px!important;margin-top:6px!important}
  .site-header .main-nav{display:none!important}.site-header .account-menu-wrap{grid-area:controls!important;justify-self:end!important;display:flex!important;gap:5px!important;align-items:center!important}
  .site-header .account-menu-button.account{min-width:0!important;width:auto!important;height:42px!important;line-height:40px!important;padding:0 10px!important;font-size:13px!important}.site-header .myariella-star{display:none!important}
  .mobile-nav-wrap{display:block!important;grid-area:controls!important;justify-self:start!important;z-index:1001!important;margin-right:92px!important}.mobile-nav-toggle{display:inline-flex!important;width:42px;height:42px;align-items:center;justify-content:center;border:1px solid #c99a3f;border-radius:10px;background:transparent;color:#fff;font-size:24px;line-height:1}.mobile-nav-menu{position:absolute;top:calc(100% + 8px);right:0;min-width:190px;background:#080808;border:1px solid #c99a3f;border-radius:12px;padding:7px;box-shadow:0 12px 32px rgba(0,0,0,.28);z-index:2000}.mobile-nav-menu:not([hidden]){display:grid!important}.mobile-nav-menu a{color:#fff;text-decoration:none;padding:12px 14px;border-bottom:1px solid rgba(201,154,63,.2);font-weight:700}.mobile-nav-menu a:last-child{border-bottom:0}

  .trip-back-bar{padding-top:10px!important;padding-bottom:6px!important}.back-to-vacations{padding:10px 14px!important;font-size:14px!important}
  .trip-wizard{padding-top:4px!important}.trip-origin-defaults{margin:8px auto 12px!important;padding:10px 12px!important;max-width:96%!important;background:rgba(255,255,255,.55)!important}.origin-default-heading{font-size:15px!important;margin-bottom:6px!important;color:#586473!important}.origin-airport-picker{padding:7px!important}.origin-airport-picker .airport-tag{font-size:13px!important;padding:6px 9px!important}.origin-airport-picker .airport-search{min-height:42px!important;font-size:14px!important;padding:8px 10px!important}
  .wizard-progress{margin:10px 3.5% 4px!important}.wizard-counter{margin:5px 0 8px!important;font-size:14px!important}.wizard-step{width:94%!important;margin:0 auto 10px!important;padding:18px 16px 16px!important;min-height:0!important}.wizard-step .step-number{font-size:30px!important;margin-bottom:2px!important}.wizard-step h2{font-size:clamp(27px,7vw,36px)!important;line-height:1.12!important;margin:2px 0 14px!important}.wizard-step h3{font-size:18px!important;margin:8px 0!important}.wizard-step .helper{font-size:14px!important;line-height:1.45!important;margin:7px 0 10px!important}
  .choice-row,.choice-grid{gap:8px!important}.choice-button{min-height:58px!important;padding:10px 8px!important;font-size:16px!important}.choice-button.small{min-height:52px!important}.choice-button span{line-height:1.25!important}.choice-button small{font-size:12px!important;line-height:1.3!important;margin-top:4px!important}
  .conditional-panel{padding:12px!important;margin:10px 0!important}.conditional-panel.two-cols{gap:9px!important}.conditional-panel label{font-size:15px!important;gap:5px!important}.conditional-panel input,.conditional-panel select,.conditional-panel textarea,.notes-label textarea{min-height:44px!important;padding:8px 10px!important;font-size:16px!important}.conditional-panel textarea,.notes-label textarea{min-height:72px!important;height:72px!important}.compact-date-panel input{min-height:44px!important}
  .wizard-actions{margin-top:14px!important;gap:9px!important}.wizard-actions .button{min-height:48px!important;padding:10px 9px!important;font-size:16px!important}.wizard-actions .wizard-type-back{font-size:13px!important}
  .business-time-rows{grid-template-columns:1fr!important;gap:10px!important}.business-time-block{gap:7px!important}.labeled-inline{grid-template-columns:58px 1fr!important;gap:7px!important}.business-flex-choice{margin-top:8px!important}.inline-compact-field{justify-content:space-between!important}
  .ski-season-warning{padding:10px 12px!important;margin:8px 0!important;font-size:14px!important;line-height:1.4!important}
  .notes-label{font-size:15px!important}.notes-label textarea{margin-top:6px!important}

  .vacation-type-gate{padding:12px 8px!important}.vacation-type-gate h2{font-size:25px!important;margin:8px 0 14px!important}.vacation-type-grid{display:grid!important;grid-template-columns:repeat(3,minmax(0,1fr))!important;gap:8px!important}.vacation-type-card{min-height:150px!important;padding:12px 6px!important;border-radius:14px!important}.vacation-type-card .vacation-type-visual{font-size:34px!important;margin-bottom:5px!important}.vacation-type-card strong{font-size:16px!important;line-height:1.15!important}.vacation-type-card small{font-size:11px!important;line-height:1.25!important;margin-top:5px!important}

  .auth-section{padding:24px 0!important}.auth-grid{gap:18px!important}.auth-copy h1{font-size:42px!important;line-height:1.05!important}.auth-copy p{font-size:17px!important}.form-card{padding:24px 20px!important}.form-card h2{font-size:34px!important;margin-bottom:18px!important}.form-card label{margin-bottom:12px!important}.form-card input,.form-card select{min-height:48px!important;padding:10px 12px!important}.form-card .button{min-height:50px!important}.form-footer{margin-top:16px!important}

  .account-trip-deals .deal-card-v970{overflow:hidden!important}.account-trip-deals .deal-main-grid{display:flex!important;flex-direction:column!important}.account-trip-deals .deal-flight,.account-trip-deals .deal-baggage,.account-trip-deals .deal-commerce{width:100%!important;padding:14px!important}.account-trip-deals .deal-flight *{max-width:100%!important}.account-trip-deals .deal-commerce{border-top:1px solid #e7dfd2!important}.account-trip-deals .deal-why,.account-trip-deals .deal-reasons{font-size:14px!important;line-height:1.5!important;white-space:normal!important}.account-trip-deals .deal-card-v970{font-size:15px!important}
}
'''
p.write_text(t, encoding='utf-8')

print('2026-09-04 mobile UX batch applied successfully')
