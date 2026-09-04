from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
css = ROOT / 'static/site.css'
t = css.read_text(encoding='utf-8')
marker = '/* 2026-09-04 final mobile review */'
if marker in t:
    t = t[:t.index(marker)].rstrip() + '\n'

t += r'''

/* 2026-09-04 final mobile review */
@media(max-width:760px){
  /* Shared header: hamburger visually aligned with the logo. */
  html body .site-header{height:78px!important;min-height:78px!important;padding:0!important}
  html body .site-header .header-inner{width:calc(100% - 22px)!important;height:78px!important;min-height:78px!important;display:grid!important;grid-template-columns:64px minmax(0,1fr) 46px!important;grid-template-areas:'lang brand controls'!important;align-items:center!important;gap:4px!important;direction:ltr!important}
  html body .site-header .language-switch{grid-area:lang!important;position:static!important;transform:none!important;justify-self:start!important;align-self:center!important;margin:0!important;font-size:12px!important}
  html body .site-header .brand{grid-area:brand!important;position:static!important;transform:none!important;justify-self:center!important;align-self:center!important;margin:0!important;gap:7px!important}
  html body .site-header .logo-a{width:40px!important;height:40px!important}
  html body .site-header .brand-name{font-size:17px!important;letter-spacing:3.5px!important}
  html body .site-header .brand-tag{font-size:6.5px!important;letter-spacing:1.8px!important;margin-top:4px!important}
  html body .site-header .main-nav,html body .site-header .desktop-account{display:none!important}
  html body .site-header .mobile-header-controls{grid-area:controls!important;position:static!important;transform:none!important;display:flex!important;width:46px!important;height:46px!important;min-width:46px!important;justify-self:end!important;align-self:center!important;align-items:center!important;justify-content:center!important;margin:0!important}
  html body .site-header .mobile-nav-toggle{position:relative!important;top:6px!important;transform:none!important;display:flex!important;width:42px!important;height:42px!important;min-width:42px!important;flex:0 0 42px!important;padding:0!important;margin:0!important;border:0!important;border-radius:0!important;background:transparent!important;color:#fff!important;font-size:31px!important;line-height:1!important;align-items:center!important;justify-content:center!important}
  html body .site-header .mobile-nav-menu{top:58px!important;right:0!important;left:auto!important;background:#050505!important;color:#fff!important}
  html body .site-header .mobile-myariella-toggle,html body .site-header .mobile-myariella-submenu,html body .site-header .mobile-myariella-submenu a,html body .site-header .mobile-myariella-submenu button{background:#0b0b0b!important;color:#fff!important}

  /* Home: balanced breathing room; the two CTAs stay side by side near viewport bottom. */
  html body .hero{min-height:calc(100svh - 78px)!important;align-items:stretch!important}
  html body .hero .inner{width:92%!important;min-height:calc(100svh - 78px)!important;padding:42px 0 24px!important;margin:0 auto!important;display:flex!important;flex-direction:column!important;justify-content:flex-start!important}
  html body .hero .dark{font-size:44px!important;line-height:1.04!important}
  html body .hero .gold{font-size:41px!important;line-height:1.04!important;margin-top:5px!important}
  html body .hero .subtitle{margin-top:24px!important;font-size:22px!important}
  html body .hero .story{margin-top:34px!important;font-size:17px!important;line-height:1.7!important}
  html body .hero .actions{margin-top:auto!important;padding-top:24px!important;padding-bottom:8px!important;display:flex!important;flex-wrap:nowrap!important;gap:10px!important;width:100%!important}
  html body .hero .actions .btn{width:calc(50% - 5px)!important;min-width:0!important;padding:13px 7px!important;font-size:15px!important;line-height:1.25!important;white-space:normal!important}

  /* Deals filters: mobile controls must not look like desktop-sized fields. */
  html body .deals-page .deal-filters,html body .deals-page .filters-card{padding:16px!important;gap:12px!important}
  html body .deal-filters-main,html body .deal-filters-more{gap:11px!important}
  html body .deal-filters-main label,html body .deal-filters-more label,html body .filter-multi{gap:5px!important;margin:0!important;font-size:14px!important}
  html body .deal-filters-main select,html body .deal-filters-main input,html body .deal-filters-main .filter-multi-button,html body .deal-filters-more select,html body .deal-filters-more input,html body .deal-filters-more .filter-multi-button{min-height:42px!important;height:42px!important;padding:7px 10px!important;font-size:15px!important;border-radius:8px!important}
  html body .deal-filters-more summary{min-height:42px!important;padding:9px 12px!important;font-size:15px!important}

  /* Questionnaire: no repeated upper hero, compact fields/cards on phone. */
  html body .trip-questionnaire-hero{display:none!important}
  html body .trip-wizard{padding-top:12px!important}
  html body .wizard-progress{margin-top:8px!important;margin-bottom:14px!important}
  html body .wizard-step{padding:20px 18px!important}
  html body .wizard-step h2{font-size:29px!important;margin:4px 0 18px!important;line-height:1.2!important}
  html body .wizard-step .conditional-panel{padding:14px!important;margin:12px 0!important}
  html body .wizard-step input:not([type='radio']):not([type='checkbox']),html body .wizard-step select,html body .trip-wizard input[type='date'],html body .trip-wizard input[type='month']{min-height:44px!important;height:44px!important;min-width:0!important;padding:7px 10px!important;font-size:15px!important}
  html body .wizard-step textarea{min-height:76px!important;padding:9px 10px!important;font-size:15px!important}
  html body .wizard-step .choice-button>span{min-height:54px!important;padding:10px 12px!important;font-size:16px!important}
  html body .business-date-panel{gap:12px!important}
  html body .business-time-block{gap:8px!important}
  html body .labeled-inline{display:grid!important;grid-template-columns:62px minmax(0,1fr)!important;align-items:center!important;gap:8px!important}
  html body .labeled-inline>span{text-align:right!important;font-weight:700!important;font-size:14px!important}

  /* Join screen: first phone viewport is compact and immediately actionable. */
  html body .auth-section{padding:22px 0 30px!important}
  html body .auth-grid{gap:18px!important}
  html body .auth-copy h1{font-size:38px!important;line-height:1.08!important;margin:6px 0 12px!important}
  html body .auth-copy p{margin:8px 0!important;font-size:16px!important;line-height:1.45!important}
  html body .auth-copy .trial-note{padding:12px 14px!important;margin-top:12px!important}
  html body .form-card{padding:20px 16px!important}
  html body .form-card h2{font-size:30px!important;margin:0 0 14px!important}
  html body .form-card label{gap:5px!important;margin-bottom:10px!important;font-size:14px!important}
  html body .form-card input,html body .form-card select,html body .form-card .airport-search{min-height:43px!important;height:43px!important;padding:7px 10px!important;font-size:15px!important}
}
'''
css.write_text(t, encoding='utf-8')
print('final mobile review applied')
