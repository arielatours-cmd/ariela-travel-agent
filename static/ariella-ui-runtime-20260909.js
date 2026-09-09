(function(){
  function monthLabel(value, isEn){
    const m=['ינואר','פברואר','מרץ','אפריל','מאי','יוני','יולי','אוגוסט','ספטמבר','אוקטובר','נובמבר','דצמבר'];
    const me=['January','February','March','April','May','June','July','August','September','October','November','December'];
    const parts=String(value||'').split('-');
    const y=Number(parts[0]), idx=Number(parts[1])-1;
    if(!y||idx<0||idx>11)return value;
    return (isEn?me[idx]:m[idx])+' '+y;
  }
  function addMonths(value, offset){
    const p=String(value||'').split('-');
    const y=Number(p[0]), m=Number(p[1]);
    if(!y||!m)return value;
    const d=new Date(y,m-1+offset,1);
    return d.getFullYear()+'-'+String(d.getMonth()+1).padStart(2,'0');
  }
  function replaceMonthInput(input){
    if(!input||input.tagName==='SELECT'||input.dataset.ariellaMonthFixed==='1')return input;
    const isEn=document.documentElement.lang==='en';
    const min=input.min||new Date().toISOString().slice(0,7);
    const current=input.value||'';
    const select=document.createElement('select');
    [...input.attributes].forEach(a=>{if(!['type','min','max','value'].includes(a.name))select.setAttribute(a.name,a.value)});
    select.dataset.ariellaMonthFixed='1';
    const empty=document.createElement('option');empty.value='';empty.textContent=isEn?'Choose month':'בחירת חודש';select.appendChild(empty);
    for(let i=0;i<24;i++){
      const value=addMonths(min,i), opt=document.createElement('option');
      opt.value=value;opt.textContent=monthLabel(value,isEn);if(value===current)opt.selected=true;select.appendChild(opt);
    }
    input.replaceWith(select);
    return select;
  }
  function fixMonthPickers(){
    const ids=['outboundMonth','returnMonth','skiOutboundMonth','skiReturnMonth'];
    const fixed={};ids.forEach(id=>fixed[id]=replaceMonthInput(document.getElementById(id)));
    function wire(outId,retId){
      const out=fixed[outId],ret=fixed[retId];if(!out||!ret)return;
      out.addEventListener('change',()=>{
        const chosen=out.value;if(!chosen)return;
        [...ret.options].forEach(o=>{if(o.value)o.disabled=o.value<chosen});
        if(!ret.value||ret.value<chosen)ret.value=chosen;
        ret.dispatchEvent(new Event('change',{bubbles:true}));
      });
    }
    wire('outboundMonth','returnMonth');wire('skiOutboundMonth','skiReturnMonth');
  }
  function moveSearchStartDate(){
    const isEn=document.documentElement.lang==='en';
    document.querySelectorAll('.trip-main-details').forEach(main=>{
      if(main.querySelector('.trip-search-start-small'))return;
      const rows=[...main.querySelectorAll('.trip-details-list > div')];
      const row=rows.find(r=>{
        const label=(r.querySelector('dt')?.textContent||'').trim();
        return label===(isEn?'Search started':'החיפוש התחיל');
      });
      if(!row)return;
      const value=(row.querySelector('dd')?.textContent||'').trim();
      if(!value)return;
      const line=document.createElement('div');
      line.className='trip-search-start-small';
      line.textContent=(isEn?'Search started: ':'החיפוש התחיל: ')+value;
      line.style.cssText='font-size:11px;line-height:1.2;color:#7a8490;font-weight:600;margin:0 0 3px;direction:rtl;text-align:right;';
      const title=main.querySelector('.trip-title-line');
      if(title)main.insertBefore(line,title);
      row.remove();
    });
  }
  function pollPendingPersonalVacation(){
    const match=location.hash.match(/^#vacation-(\d+)$/);if(!match)return;
    const id=match[1],card=document.getElementById('vacation-'+id),deals=document.getElementById('tripDeals'+id);
    if(!card||!deals)return;
    if(deals.querySelector('.deal-card-v970')){sessionStorage.removeItem('ariellaScanPoll:'+id);return;}
    const title=(card.querySelector('.trip-title-line h3')?.textContent||'').trim();
    if(/אריאלה תמליץ|Ariella recommends/i.test(title))return;
    const key='ariellaScanPoll:'+id,count=Number(sessionStorage.getItem(key)||0);
    if(count>=15){sessionStorage.removeItem(key);return;}
    sessionStorage.setItem(key,String(count+1));
    setTimeout(()=>location.reload(),4000);
  }
  function init(){fixMonthPickers();moveSearchStartDate();pollPendingPersonalVacation();}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init();
})();
