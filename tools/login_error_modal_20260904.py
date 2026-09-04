from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
p = ROOT / 'templates' / 'base.html'
t = p.read_text(encoding='utf-8')
old = '''{% with messages = get_flashed_messages(with_categories=true) %}{% if messages %}<div class="shell flash-stack">{% for category, message in messages %}<div class="flash {{ category }}">{{ message }}</div>{% endfor %}</div>{% endif %}{% endwith %}'''
new = '''{% with messages = get_flashed_messages(with_categories=true) %}
{% if messages %}
  {% if request.endpoint == 'site.login' %}
    <div id="loginFlashModal" class="login-flash-modal" role="dialog" aria-modal="true" aria-labelledby="loginFlashText">
      <div class="login-flash-backdrop"></div>
      <div class="login-flash-card">
        <div id="loginFlashText" class="login-flash-text">{% for category, message in messages %}{{ message }}{% if not loop.last %}<br>{% endif %}{% endfor %}</div>
        <button id="loginFlashOk" type="button" class="login-flash-ok">{{ 'OK' if site_lang == 'en' else 'אישור' }}</button>
      </div>
    </div>
    <style>
      .login-flash-modal{position:fixed;inset:0;z-index:10000;display:flex;align-items:center;justify-content:center;padding:20px}
      .login-flash-backdrop{position:absolute;inset:0;background:rgba(0,0,0,.48)}
      .login-flash-card{position:relative;width:min(420px,92vw);background:#fffaf2;border:1px solid #c99a3f;border-radius:14px;padding:26px 22px 20px;box-shadow:0 18px 55px rgba(0,0,0,.28);text-align:center}
      .login-flash-text{font-size:18px;line-height:1.5;color:#111;margin-bottom:18px}
      .login-flash-ok{min-width:120px;border:0;border-radius:9px;background:#17283f;color:#fff;font-weight:700;font-size:16px;padding:11px 22px;cursor:pointer}
      @media(max-width:760px){.login-flash-card{padding:22px 18px 18px}.login-flash-text{font-size:16px}.login-flash-ok{font-size:15px;padding:10px 20px}}
    </style>
    <script>
      document.addEventListener('DOMContentLoaded',function(){
        const ok=document.getElementById('loginFlashOk');
        if(!ok)return;
        ok.focus();
        ok.addEventListener('click',function(){
          const cleanUrl={{ url_for('site.login', lang=site_lang)|tojson }};
          window.location.replace(cleanUrl);
        });
        document.addEventListener('keydown',function(e){if(e.key==='Escape')ok.click();});
      });
    </script>
  {% else %}
    <div class="shell flash-stack">{% for category, message in messages %}<div class="flash {{ category }}">{{ message }}</div>{% endfor %}</div>
  {% endif %}
{% endif %}
{% endwith %}'''
if old not in t:
    raise SystemExit('flash block not found')
t = t.replace(old, new, 1)
p.write_text(t, encoding='utf-8')
print('login error modal applied')
