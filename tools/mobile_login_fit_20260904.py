from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
css = ROOT / 'static/site.css'
t = css.read_text(encoding='utf-8')
marker = '/* 2026-09-04 mobile login fit */'
if marker in t:
    t = t[:t.index(marker)].rstrip() + '\n'

t += r'''

/* 2026-09-04 mobile login fit */
@media(max-width:760px){
  /* Login/auth page only: fit the complete form in the first phone viewport. */
  html body .auth-section{padding:14px 0 18px!important;min-height:calc(100svh - 78px)!important}
  html body .auth-grid{gap:12px!important}
  html body .auth-copy{margin:0!important;padding:0!important}
  html body .auth-copy h1{font-size:34px!important;line-height:1.03!important;margin:0 0 8px!important}
  html body .auth-copy p{font-size:15px!important;line-height:1.35!important;margin:4px 0!important}
  html body .auth-copy .trial-note{padding:8px 10px!important;margin-top:8px!important}
  html body .form-card{padding:15px 14px!important;margin-top:4px!important}
  html body .form-card h2{font-size:27px!important;line-height:1.1!important;margin:0 0 10px!important}
  html body .form-card label{gap:4px!important;margin-bottom:7px!important;font-size:13px!important}
  html body .form-card input,html body .form-card select,html body .form-card .airport-search{min-height:39px!important;height:39px!important;padding:5px 9px!important;font-size:14px!important}
  html body .form-card .password-wrap{margin:0!important}
  html body .form-card .forgot-password,html body .form-card .forgot-link{margin:3px 0 7px!important;font-size:13px!important}
  html body .form-card button[type='submit'],html body .form-card .btn{min-height:41px!important;padding:8px 12px!important;font-size:15px!important}
  html body .form-card .auth-switch,html body .form-card .form-footer{margin-top:9px!important;font-size:14px!important;line-height:1.25!important}
}
'''
css.write_text(t, encoding='utf-8')
print('mobile login fit applied')
