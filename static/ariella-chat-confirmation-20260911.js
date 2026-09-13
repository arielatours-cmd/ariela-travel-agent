(function(){
  function boot(){
    const wizard=document.getElementById('tripWizard');
    let chat=document.getElementById('ariellaDesktopChat');
    if(!chat&&wizard){
      const u=new URL(location.href);
      if(u.searchParams.get('ariella_chat')!=='1'){
        u.searchParams.set('ariella_chat','1');
        location.replace(u.toString());
      }
      return;
    }
    if(!chat)return;
    const input=chat.querySelector('#ariellaChatInput'),send=chat.querySelector('#ariellaChatSend'),messages=chat.querySelector('#ariellaChatMessages');
    if(!input||!send||!messages)return;
    const title=chat.querySelector('.ac-head-copy strong');
    if(title)title.textContent='אריאלה — סוכנת הנסיעות הראשית שלך';
    chat.querySelectorAll('.ac-avatar,.ac-mini-avatar').forEach(x=>x.textContent='A');
    const note=chat.querySelector('.ac-note');if(note)note.textContent='אריאלה מתשאלת ומנהלת את החופשה • טינקרבל מחפשת טיסות • Travel מתאים אטרקציות';
    let profile={},history=[],busy=false,lastAttractions='';
    const labels={destination:'יעד',dates:'תאריכים',travelers:'נוסעים',budget:'תקציב',flight:'טיסה',baggage:'כבודה'};
    function add(who,text){const row=document.createElement('div');row.className='ac-row '+who;if(who==='bot'){const a=document.createElement('div');a.className='ac-mini-avatar';a.textContent='A';row.appendChild(a)}const b=document.createElement('div');b.className='ac-bubble';b.textContent=text;row.appendChild(b);messages.appendChild(row);messages.scrollTop=messages.scrollHeight;}
    function valueText(k){const p=profile;if(k==='destination')return (p.destinations||[]).join(', ');if(k==='dates')return p.departure_date&&p.return_date?`${p.departure_date} – ${p.return_date}`:(p.outbound_month||p.return_month||'');if(k==='travelers'){const a=p.adults||0,c=p.children||0,i=p.infants||0;return a||c||i?`${a} מבוגרים${c?`, ${c} ילדים`:''}${i?`, ${i} תינוקות`:''}`:''}if(k==='budget')return p.budget_mode==='unlimited'?'ללא הגבלת תקציב':(p.budget_amount?`${p.budget_amount} ₪ לאדם`:'');if(k==='flight')return p.flight_preference||'';if(k==='baggage')return p.baggage||'';return ''}
    function summary(){Object.keys(labels).forEach(k=>{const row=chat.querySelector(`[data-summary-key="${k}"]`),span=row?.querySelector('span'),v=valueText(k);if(span)span.textContent=v||'עדיין לא צוין';row?.classList.toggle('is-filled',!!v)})}
    function attractionsText(items){if(!items||!items.length)return '';const sig=items.map(x=>x.name).join('|');if(sig===lastAttractions)return '';lastAttractions=sig;return 'Travel כבר מצא ב-DB כמה אטרקציות שמתאימות למה שסיפרת:\n'+items.slice(0,5).map(x=>`• ${x.name}${x.city?' — '+x.city:''}${x.reasons?.length?' ('+x.reasons.join(', ')+')':''}`).join('\n')+'\n\nנמשיך לדייק את החופשה לפני שנבנה את המסלול.'}
    async function submit(){const raw=input.value.trim();if(!raw||busy)return;busy=true;input.value='';send.disabled=true;add('user',raw);history.push({role:'user',content:raw});try{const res=await fetch('/api/ariella/chat',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'same-origin',body:JSON.stringify({message:raw,history:history.slice(-12),profile})});const data=await res.json();if(!res.ok||data.status!=='success')throw new Error(data.message||'chat error');profile=data.profile||profile;summary();const reply=data.reply||'ספרו לי עוד קצת על החופשה שאתם מחפשים.';add('bot',reply);history.push({role:'assistant',content:reply});const travelMsg=attractionsText(data.travel_agent?.attractions||[]);if(travelMsg)add('bot',travelMsg);chat.dataset.tinkerbellHandoff=JSON.stringify(data.tinkerbell_handoff||{});chat.dataset.readyForFlights=data.ready_for_flights?'1':'0';}catch(e){add('bot','יש כרגע תקלה זמנית בחיבור לאריאלה. אפשר לנסות שוב בעוד רגע.');}finally{busy=false;send.disabled=false;input.focus()}}
    send.addEventListener('click',function(e){e.preventDefault();e.stopImmediatePropagation();submit()},true);
    input.addEventListener('keydown',function(e){if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();e.stopImmediatePropagation();submit()}},true);
    const first=messages.querySelector('.ac-row.bot .ac-bubble');
    if(first)first.textContent='היי, אני אריאלה, סוכנת הנסיעות הראשית שלך. ספרו לי חופשי איזו חופשה אתם מחפשים — גם אם עדיין אין לכם יעד. אני אשאל רק מה שחסר, וברקע אעביר לטינקרבל את פרטי הטיסה ול-Travel את ההעדפות למסלול ולאטרקציות.';
    input.placeholder='למשל: אנחנו משפחה עם 3 ילדים ורוצים טבע באוקטובר...';
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot);else boot();
})();