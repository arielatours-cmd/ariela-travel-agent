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
  html body .deals-page .deal-filters,
  html body .deals-page .filters-card{
    padding:10px!important;
    gap:8px!important;
  }
  html body .deal-filters-main,
  html body .deal-filters-more{
    gap:8px!important;
  }
  html body .deal-filters-main label,
  html body .deal-filters-more label,
  html body .filter-multi{
    gap:3px!important;
    margin:0!important;
    font-size:12px!important;
    line-height:1.2!important;
  }
  html body .deal-filters-main select,
  html body .deal-filters-main input,
  html body .deal-filters-main .filter-multi-button,
  html body .deal-filters-more select,
  html body .deal-filters-more input,
  html body .deal-filters-more .filter-multi-button{
    min-height:36px!important;
    height:36px!important;
    padding:5px 8px!important;
    font-size:13px!important;
    line-height:1.15!important;
    border-radius:7px!important;
  }
  html body .deal-filters-more summary{
    min-height:36px!important;
    padding:7px 9px!important;
    font-size:13px!important;
    line-height:1.15!important;
  }
  html body .deal-filters-main button,
  html body .deal-filters-more button{
    min-height:36px!important;
    padding:6px 9px!important;
    font-size:13px!important;
  }
}
'''

css.write_text(t, encoding='utf-8')
print('compact mobile deals filters applied')
