from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
css = ROOT / 'static/site.css'
t = css.read_text(encoding='utf-8')
marker = '/* 2026-09-04 compact mobile deals filters */'
if marker in t:
    t = t[:t.index(marker)].rstrip() + '\n'

t += r'''

/* 2026-09-04 compact mobile deals filters */
@media(max-width:760px){
  html body .deals-page .deal-filters-wrap{
    margin:10px 0 14px!important;
    padding:8px!important;
    border-radius:10px!important;
  }

  html body .deals-page .deal-filters-main,
  html body .deals-page .deal-filters-more{
    display:grid!important;
    grid-template-columns:repeat(2,minmax(0,1fr))!important;
    gap:7px!important;
    width:100%!important;
    align-items:end!important;
  }

  /* Keep the last main field full width so the two action buttons sit side by side. */
  html body .deals-page .deal-filters-main > label:nth-of-type(4){grid-column:1/-1!important}

  html body .deals-page .deal-filters-wrap label,
  html body .deals-page .filter-multi{
    min-width:0!important;
    width:100%!important;
    gap:2px!important;
    margin:0!important;
    font-size:11px!important;
    line-height:1.1!important;
  }

  html body .deals-page .deal-filters-wrap select,
  html body .deals-page .deal-filters-wrap input,
  html body .deals-page .filter-multi-button{
    width:100%!important;
    min-height:32px!important;
    height:32px!important;
    padding:3px 7px!important;
    font-size:12px!important;
    line-height:1!important;
    border-radius:6px!important;
  }

  html body .deals-page .deal-more-filters-toggle,
  html body .deals-page .deal-clear-filters{
    min-height:32px!important;
    height:32px!important;
    width:100%!important;
    padding:3px 7px!important;
    font-size:12px!important;
    line-height:1!important;
    border-radius:6px!important;
  }

  html body .deals-page .deal-filters-more{
    margin-top:7px!important;
    padding-top:7px!important;
  }
}
'''

css.write_text(t, encoding='utf-8')
print('compact mobile deals filters applied')
