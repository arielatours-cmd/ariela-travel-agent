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
  function initDesktopChatPreview(){
    const wizard=document.getElementById('tripWizard');
    if(!wizard||window.innerWidth<900)return;
    const params=new URLSearchParams(location.search);
    if(params.get('ariella_chat')!=='1')return;
    if(document.getElementById('ariellaDesktopChat'))return;

    const isEn=document.documentElement.lang==='en';
    const style=document.createElement('style');
    style.id='ariella-desktop-chat-preview-style';
    style.textContent=`
      body.ariella-chat-preview-active #tripWizard{display:none!important}
      #ariellaDesktopChat{width:min(1280px,92%);margin:28px auto 54px;direction:${isEn?'ltr':'rtl'};font-family:Arial,"Segoe UI",sans-serif}
      #ariellaDesktopChat .ac-shell{display:grid;grid-template-columns:minmax(0,2fr) minmax(300px,.85fr);gap:22px;align-items:stretch}
      #ariellaDesktopChat .ac-chat,#ariellaDesktopChat .ac-summary{background:#fffaf2;border:1px solid rgba(201,154,63,.38);border-radius:22px;box-shadow:0 14px 38px rgba(23,40,63,.08);overflow:hidden}
      #ariellaDesktopChat .ac-chat{min-height:650px;display:flex;flex-direction:column}
      #ariellaDesktopChat .ac-head{display:flex;align-items:center;gap:14px;padding:20px 24px;background:linear-gradient(135deg,#102b30,#18373a);color:#fff;border-bottom:1px solid #c99a3f}
      #ariellaDesktopChat .ac-avatar{width:58px;height:58px;border-radius:50%;display:grid;place-items:center;flex:0 0 auto;background:linear-gradient(145deg,#f6d98b,#c99a3f);border:2px solid #fff3cf;color:#17283f;font:700 28px Georgia,serif;box-shadow:0 5px 18px rgba(0,0,0,.18)}
      #ariellaDesktopChat .ac-head-copy strong{display:block;font-size:21px;margin-bottom:3px}.ac-head-copy small{color:#d8e7e5;font-size:13px}
      #ariellaDesktopChat .ac-online{margin-inline-start:auto;display:flex;align-items:center;gap:7px;color:#d8e7e5;font-size:13px}.ac-online::before{content:"";width:8px;height:8px;border-radius:50%;background:#56c596;box-shadow:0 0 0 3px rgba(86,197,150,.16)}
      #ariellaDesktopChat .ac-messages{flex:1;padding:28px 30px;display:flex;flex-direction:column;gap:14px;background:linear-gradient(180deg,#fffdf8,#fbf5e9)}
      #ariellaDesktopChat .ac-row{display:flex;gap:10px;align-items:flex-end}#ariellaDesktopChat .ac-row.user{justify-content:flex-start}
      #ariellaDesktopChat .ac-bubble{max-width:74%;padding:13px 16px;border-radius:17px;font-size:16px;line-height:1.55;white-space:pre-wrap}
      #ariellaDesktopChat .ac-row.bot .ac-bubble{background:#fff;border:1px solid #eadfc8;border-bottom-${isEn?'left':'right'}-radius:5px;color:#17283f}
      #ariellaDesktopChat .ac-row.user .ac-bubble{background:#0b8f9c;color:#fff;border-bottom-${isEn?'right':'left'}-radius:5px}
      #ariellaDesktopChat .ac-mini-avatar{width:31px;height:31px;border-radius:50%;display:grid;place-items:center;background:#17283f;color:#e7c778;font-weight:800;font-size:14px;flex:0 0 auto}
      #ariellaDesktopChat .ac-compose{padding:17px 20px;border-top:1px solid #eadfc8;background:#fff;display:flex;gap:10px;align-items:center}
      #ariellaDesktopChat .ac-compose textarea{flex:1;min-height:52px;max-height:125px;resize:none;border:1px solid #d9cdb8;border-radius:14px;padding:14px 15px;font:inherit;outline:none;background:#fffdf9;color:#17283f}
      #ariellaDesktopChat .ac-compose textarea:focus{border-color:#0b8f9c;box-shadow:0 0 0 3px rgba(11,143,156,.1)}
      #ariellaDesktopChat .ac-send{height:52px;min-width:92px;border:0;border-radius:13px;background:#0b8f9c;color:#fff;font-weight:800;font-size:15px;cursor:pointer}.ac-send:hover{background:#087a86}
      #ariellaDesktopChat .ac-summary{padding:0 22px 22px;align-self:start;position:sticky;top:18px}
      #ariellaDesktopChat .ac-summary-head{margin:0 -22px 18px;padding:20px 22px 16px;border-bottom:1px solid #eadfc8;background:#fffdf9}
      #ariellaDesktopChat .ac-summary-head strong{display:block;font-size:22px;color:#17283f}.ac-summary-head small{display:block;margin-top:5px;color:#75808b;line-height:1.4}
      #ariellaDesktopChat .ac-detail{display:grid;grid-template-columns:34px 1fr;gap:10px;padding:11px 0;border-bottom:1px solid #eee5d5}.ac-detail:last-of-type{border-bottom:0}
      #ariellaDesktopChat .ac-detail-icon{font-size:20px;text-align:center}.ac-detail b{display:block;color:#17283f;font-size:14px;margin-bottom:3px}.ac-detail span{display:block;color:#8a8173;font-size:14px}
      #ariellaDesktopChat .ac-questionnaire{width:100%;margin-top:18px;border:1px solid #c99a3f;background:transparent;color:#17283f;border-radius:12px;padding:12px 14px;font-weight:700;cursor:pointer}.ac-questionnaire:hover{background:#f7edda}
      #ariellaDesktopChat .ac-note{margin-top:12px;font-size:12px;line-height:1.45;color:#8a8173;text-align:center}
      @media(max-width:1050px){#ariellaDesktopChat .ac-shell{grid-template-columns:minmax(0,1.55fr) minmax(280px,.8fr)}}
    `;
    document.head.appendChild(style);

    const wrap=document.createElement('section');
    wrap.id='ariellaDesktopChat';
    wrap.setAttribute('aria-label',isEn?'Chat with Ariella':'שיחה עם אריאלה');
    wrap.innerHTML=`
      <div class="ac-shell">
        <div class="ac-chat">
          <div class="ac-head">
            <div class="ac-avatar" aria-hidden="true">A</div>
            <div class="ac-head-copy"><strong>${isEn?'Ariella — your personal travel agent':'אריאלה — סוכנת הנסיעות האישית שלך'}</strong><small>${isEn?'Tell me naturally what kind of vacation you want':'ספרו לי חופשי איזו חופשה אתם מחפשים'}</small></div>
            <div class="ac-online">${isEn?'Available':'זמינה עכשיו'}</div>
          </div>
          <div class="ac-messages" id="ariellaChatMessages">
            <div class="ac-row bot"><div class="ac-mini-avatar">A</div><div class="ac-bubble">${isEn?'Hi 👋 I’m Ariella. Tell me about the vacation you have in mind — destination, dates, who is traveling, or anything else that matters to you. You can write it all in your own words.':'היי 👋 אני אריאלה. ספרו לי על החופשה שאתם מחפשים — יעד, תאריכים, מי נוסע או כל דבר שחשוב לכם. אפשר פשוט לכתוב לי חופשי, במילים שלכם.'}</div></div>
          </div>
          <div class="ac-compose">
            <textarea id="ariellaChatInput" rows="1" placeholder="${isEn?'For example: We are a couple looking for Thailand in December for about two weeks…':'לדוגמה: אנחנו זוג, מחפשים תאילנד בדצמבר בערך לשבועיים…'}"></textarea>
            <button type="button" class="ac-send" id="ariellaChatSend">${isEn?'Send':'שליחה'}</button>
          </div>
        </div>
        <aside class="ac-summary">
          <div class="ac-summary-head"><strong>${isEn?'My vacation':'החופשה שלי'}</strong><small>${isEn?'The details Ariella understands from the conversation will appear here.':'הפרטים שאריאלה תבין מהשיחה יתעדכנו כאן.'}</small></div>
          ${[
            ['🌍',isEn?'Destination':'יעד'],['📅',isEn?'Dates':'תאריכים'],['👥',isEn?'Travelers':'נוסעים'],['💰',isEn?'Budget':'תקציב'],['✈️',isEn?'Flight':'טיסה'],['🧳',isEn?'Baggage':'כבודה']
          ].map(x=>`<div class="ac-detail"><div class="ac-detail-icon">${x[0]}</div><div><b>${x[1]}</b><span>${isEn?'Not specified yet':'עדיין לא צוין'}</span></div></div>`).join('')}
          <button type="button" class="ac-questionnaire" id="ariellaUseQuestionnaire">${isEn?'Prefer the questionnaire?':'מעדיפים למלא שאלון?'}</button>
          <div class="ac-note">${isEn?'Preview mode — the conversational AI connection comes in the next stage.':'מצב תצוגה מקדימה — חיבור ה-AI לשדות ולמנוע החיפוש יבוצע בשלב הבא.'}</div>
        </aside>
      </div>`;
    wizard.parentNode.insertBefore(wrap,wizard);
    document.body.classList.add('ariella-chat-preview-active');

    const messages=wrap.querySelector('#ariellaChatMessages');
    const input=wrap.querySelector('#ariellaChatInput');
    const send=wrap.querySelector('#ariellaChatSend');
    function addMessage(text,who){
      const row=document.createElement('div');row.className='ac-row '+who;
      if(who==='bot'){const av=document.createElement('div');av.className='ac-mini-avatar';av.textContent='A';row.appendChild(av);}
      const bubble=document.createElement('div');bubble.className='ac-bubble';bubble.textContent=text;row.appendChild(bubble);messages.appendChild(row);messages.scrollTop=messages.scrollHeight;
    }
    function submitPreviewMessage(){
      const text=input.value.trim();if(!text)return;
      addMessage(text,'user');input.value='';
      setTimeout(()=>addMessage(isEn?'Got it. I’ll collect the important details from what you tell me and only ask about what is still missing.':'קיבלתי. אני אאסוף מהשיחה את הפרטים החשובים ואשאל רק על מה שעדיין חסר.','bot'),350);
    }
    send.addEventListener('click',submitPreviewMessage);
    input.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();submitPreviewMessage();}});
    wrap.querySelector('#ariellaUseQuestionnaire').addEventListener('click',()=>{
      document.body.classList.remove('ariella-chat-preview-active');wrap.hidden=true;wizard.scrollIntoView({behavior:'smooth',block:'start'});
    });
  }
  function init(){fixMonthPickers();moveSearchStartDate();pollPendingPersonalVacation();initDesktopChatPreview();}
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init);else init();
})();
