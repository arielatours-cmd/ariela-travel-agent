from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
p = ROOT / 'static/site.css'
t = p.read_text(encoding='utf-8')
marker = '/* 2026-09-04 mobile header overlap hotfix */'
# Always replace the previous hotfix block so deploys are deterministic.
if marker in t:
    t = t[:t.index(marker)].rstrip() + '\n'

t += r'''

/* 2026-09-04 mobile header overlap hotfix */
@media(max-width:760px){
  html body .site-header{
    min-height:94px!important;
    padding:8px 0!important;
  }
  html body .site-header .header-inner{
    width:96%!important;
    display:grid!important;
    grid-template-columns:78px minmax(150px,1fr) 168px!important;
    grid-template-areas:'lang brand controls'!important;
    align-items:center!important;
    gap:4px!important;
    direction:ltr!important;
  }
  html body .site-header .language-switch{
    grid-area:lang!important;
    justify-self:start!important;
    align-self:center!important;
    margin:0!important;
    font-size:14px!important;
  }
  html body .site-header .brand{
    grid-area:brand!important;
    justify-self:center!important;
    align-self:center!important;
    min-width:0!important;
    gap:6px!important;
    margin:0!important;
  }
  html body .site-header .logo-a{width:44px!important;height:44px!important}
  html body .site-header .brand-name{font-size:18px!important;letter-spacing:4px!important}
  html body .site-header .brand-tag{font-size:7px!important;letter-spacing:2px!important;margin-top:5px!important}

  html body .site-header .mobile-header-controls{
    grid-area:controls!important;
    justify-self:end!important;
    align-self:center!important;
    display:flex!important;
    flex-direction:row-reverse!important;
    align-items:center!important;
    justify-content:flex-start!important;
    gap:6px!important;
    width:168px!important;
    min-width:168px!important;
    margin:0!important;
    position:relative!important;
    direction:ltr!important;
  }
  html body .site-header .account-menu-wrap{
    display:flex!important;
    align-items:center!important;
    width:120px!important;
    min-width:120px!important;
    margin:0!important;
    position:relative!important;
  }
  html body .site-header .account-menu-button.account{
    width:120px!important;
    min-width:120px!important;
    max-width:120px!important;
    height:40px!important;
    min-height:40px!important;
    padding:0 8px!important;
    font-size:13px!important;
    line-height:38px!important;
    overflow:hidden!important;
    border-radius:999px!important;
  }
  html body .site-header .myariella-label{gap:0!important;max-width:100%!important}
  html body .site-header .myariella-star{display:none!important}
  html body .site-header .mobile-nav-toggle{
    display:inline-flex!important;
    position:static!important;
    flex:0 0 40px!important;
    width:40px!important;
    height:40px!important;
    margin:0!important;
    align-items:center!important;
    justify-content:center!important;
    border:1px solid #c99a3f!important;
    border-radius:10px!important;
    background:transparent!important;
    color:#fff!important;
    font-size:22px!important;
    line-height:1!important;
    padding:0!important;
  }
  html body .site-header .mobile-nav-menu{
    top:calc(100% + 8px)!important;
    right:0!important;
    left:auto!important;
  }
}
'''
p.write_text(t, encoding='utf-8')
print('mobile header overlap hotfix applied')
