from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
p = ROOT / 'static/site.css'
t = p.read_text(encoding='utf-8')
marker = '/* 2026-09-04 mobile header overlap hotfix */'
if marker not in t:
    t += r'''

/* 2026-09-04 mobile header overlap hotfix */
@media(max-width:760px){
  html body .site-header{min-height:104px!important;padding:10px 0!important}
  html body .site-header .header-inner{
    width:96%!important;
    display:grid!important;
    grid-template-columns:78px minmax(0,1fr) 122px!important;
    grid-template-areas:'lang brand account'!important;
    align-items:center!important;
    gap:4px!important;
    direction:ltr!important;
  }
  html body .site-header .language-switch{grid-area:lang!important;justify-self:start!important;margin:0!important}
  html body .site-header .brand{grid-area:brand!important;justify-self:center!important;min-width:0!important;gap:6px!important}
  html body .site-header .logo-a{width:44px!important;height:44px!important}
  html body .site-header .brand-name{font-size:18px!important;letter-spacing:4px!important}
  html body .site-header .brand-tag{font-size:7px!important;letter-spacing:2px!important;margin-top:5px!important}
  html body .site-header .account-menu-wrap{grid-area:account!important;justify-self:end!important;width:118px!important;min-width:0!important;margin:0!important}
  html body .site-header .account-menu-button.account{
    width:118px!important;min-width:118px!important;max-width:118px!important;height:42px!important;
    padding:0 7px!important;font-size:13px!important;overflow:hidden!important
  }
  html body .site-header .myariella-label{gap:0!important;max-width:100%!important}
  html body .site-header .myariella-star{display:none!important}
  html body .site-header .mobile-nav-wrap{
    display:block!important;position:absolute!important;right:0!important;bottom:-45px!important;
    margin:0!important;z-index:1001!important
  }
  html body .site-header .mobile-nav-toggle{display:inline-flex!important}
}
'''
p.write_text(t, encoding='utf-8')
print('mobile header overlap hotfix applied')
