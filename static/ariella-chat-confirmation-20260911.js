(function(){
  function boot(){
    const wizard=document.getElementById('tripWizard');
    let chat=document.getElementById('ariellaDesktopChat');
    if(!chat&&wizard){
      const u=new URL(location.href);
      if(u.searchParams.get('ariella_chat')!=='1'){u.searchParams.set('ariella_chat','1');location.replace(u.toString());}
      return;
    }
    if(!chat||chat.dataset.ariellaChatBooted==='1')return;
    chat.dataset.ariellaChatBooted='1';
    const input=chat.querySelector('#ariellaChatInput'),send=chat.querySelector('#ariellaChatSend'),messages=chat.querySelector('#ariellaChatMessages');
    if(!input||!send||!messages)return;
    const style=document.createElement('style');
    style.textContent=`#ariellaDesktopChat .ac-row.bot{align-items:flex-start!important}#ariellaDesktopChat .ac-row.bot .ac-mini-avatar{margin-top:4px!important;align-self:flex-start!important}.ac-service-card{max-width:88%;margin:4px 42px 12px 0;background:#fff;border:1px solid #e2d4b8;border-radius:16px;padding:15px;color:#17283f}.ac-service-card strong{display:block;margin-bottom:10px;font-size:16px}.ac-service-options{display:grid;grid-template-columns:1fr 1fr;gap:8px}.ac-service-option{display:flex;align-items:center;gap:7px;border:1px solid #dccb9f;border-radius:11px;padding:10px 11px;background:#fffaf2;cursor:pointer}.ac-service-option input{accent-color:#0b8f9c}.ac-service-go{margin-top:12px;border:0;border-radius:10px;background:#0b8f9c;color:#fff;font-weight:800;padding:11px 16px;cursor:pointer}.ac-service-error{display:block;margin-top:8px;color:#9b3b31;font-size:13px}@media(max-width:600px){.ac-service-options{grid-template-columns:1fr}.ac-service-card{margin-right:0;max-width:100%}}`;
    document.head.appendChild(style);
    const title=chat.querySelector('.ac-head-copy strong');if(title)title.textContent='אריאלה — סוכנת הנסיעות הראשית שלך';
    chat.querySelectorAll('.ac-avatar,.ac-mini-avatar').forEach(x=>x.textContent='A');
    const note=chat.querySelector('.ac-note');if(note)note.style.display='none';

    const STORAGE_KEY='ariellaChatState:v3';
    let profile={},history=[],busy=false,lastAttractions=[];
    try{
      const saved=JSON.parse(localStorage.getItem(STORAGE_KEY)||'null');
      if(saved&&typeof saved==='object'){
        if(saved.profile&&typeof saved.profile==='object')profile=saved.profile;
        if(Array.isArray(saved.history))history=saved.history.slice(-80);
      }
    }catch(e){}
    // Clean the legacy preview greeting that used to arrive asynchronously after the real welcome.
    let greetingSeen=false;
    history=history.filter((item,index)=>{
      const text=String(item?.content||'').trim();
      const greeting=item?.role==='assistant'&&index<4&&/^היי[ ,].*(?:אריאלה|איך אפשר לעזור|איזו חופשה)/.test(text);
      if(!greeting)return true;
      if(greetingSeen)return false;
      greetingSeen=true;return true;
    });

    const labels={destination:'יעד',dates:'תאריכים',travelers:'נוסעים',budget:'תקציב',flight:'טיסה',baggage:'כבודה'};
    function saveState(){try{localStorage.setItem(STORAGE_KEY,JSON.stringify({profile,history:history.slice(-80),saved_at:new Date().toISOString()}));}catch(e){}}
    function add(who,text){if(!String(text||'').trim())return;const row=document.createElement('div');row.className='ac-row '+who;if(who==='bot'){const a=document.createElement('div');a.className='ac-mini-avatar';a.textContent='A';row.appendChild(a)}const b=document.createElement('div');b.className='ac-bubble';b.textContent=text;row.appendChild(b);messages.appendChild(row);messages.scrollTop=messages.scrollHeight;}
    function valueText(k){const p=profile;if(k==='destination')return Array.isArray(p.destinations)?p.destinations.join(', '):(p.destinations||'');if(k==='dates')return p.departure_date&&p.return_date?`${p.departure_date} – ${p.return_date}`:(p.outbound_month||p.return_month||'');if(k==='travelers'){const a=p.adults||0,c=p.children||0,i=p.infants||0;return a||c||i?`${a} מבוגרים${c?`, ${c} ילדים`:''}${i?`, ${i} תינוקות`:''}`:''}if(k==='budget')return p.budget_mode==='unlimited'?'ללא הגבלת תקציב':(p.budget_amount?`${p.budget_amount} ₪ לאדם`:'');if(k==='flight')return p.flight_preference||'';if(k==='baggage')return p.baggage||'';return ''}
    function summary(){Object.keys(labels).forEach(k=>{const row=chat.querySelector(`[data-summary-key="${k}"]`),span=row?.querySelector('span'),v=valueText(k);if(span)span.textContent=v||'עדיין לא צוין';row?.classList.toggle('is-filled',!!v)})}
    function aiErrorMessage(data){const d=String(data?.detail||'');if(/429/.test(d))return 'אין כרגע מכסת API זמינה.';if(/401|403/.test(d))return 'החיבור לשרת לא הושלם.';if(/400/.test(d))return 'הבקשה לא התקבלה. נסי שוב.';return 'יש כרגע תקלה זמנית. נסי שוב בעוד רגע.'}

    function renderServicePicker(){
      if(document.getElementById('ariellaServiceCard')||(Array.isArray(profile.services)&&profile.services.length))return;
      const card=document.createElement('div');card.id='ariellaServiceCard';card.className='ac-service-card';
      card.innerHTML=`<strong>מה תרצו שאריאלה תמצא או תתכנן עבורכם?</strong><div class="ac-service-options">
        <label class="ac-service-option"><input type="checkbox" value="flight"> ✈️ טיסות</label>
        <label class="ac-service-option"><input type="checkbox" value="lodging"> 🏨 לינה</label>
        <label class="ac-service-option"><input type="checkbox" value="attractions"> 🎟️ אטרקציות</label>
        <label class="ac-service-option"><input type="checkbox" value="route"> 🗺️ בניית מסלול</label>
        <label class="ac-service-option"><input type="checkbox" value="car"> 🚗 השכרת רכב</label>
      </div><button type="button" class="ac-service-go">המשך</button><span class="ac-service-error" hidden>בחרו לפחות אפשרות אחת.</span>`;
      messages.appendChild(card);messages.scrollTop=messages.scrollHeight;
      card.querySelector('.ac-service-go').addEventListener('click',async()=>{
        const selected=[...card.querySelectorAll('input:checked')].map(x=>x.value);
        if(!selected.length){card.querySelector('.ac-service-error').hidden=false;return;}
        profile.services=selected;saveState();card.remove();
        const names={flight:'טיסות',lodging:'לינה',attractions:'אטרקציות',route:'בניית מסלול',car:'השכרת רכב'};
        await sendMessage('אני מחפש/ת: '+selected.map(x=>names[x]).join(', '),true);
      });
    }

    async function sendMessage(raw,displayUser){
      raw=String(raw||'').trim();if(!raw||busy)return;
      busy=true;send.disabled=true;if(displayUser)add('user',raw);
      const priorHistory=history.slice(-12);history.push({role:'user',content:raw});saveState();
      try{
        const res=await fetch('/api/ariella/chat',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'same-origin',body:JSON.stringify({message:raw,history:priorHistory,profile})});
        const data=await res.json();
        if(!res.ok||data.status!=='success'){const err=aiErrorMessage(data);add('bot',err);history.push({role:'assistant',content:err});saveState();return;}
        profile=data.profile||profile;lastAttractions=data.travel_agent?.attractions||[];summary();
        const reply=String(data.reply||'').trim();if(reply){add('bot',reply);history.push({role:'assistant',content:reply});}
        chat.dataset.tinkerbellHandoff=JSON.stringify(data.tinkerbell_handoff||{});chat.dataset.readyForFlights=data.ready_for_flights?'1':'0';chat.dataset.flightSearchStarted=data.flight_search_started?'1':'0';
        if(data.show_service_picker)renderServicePicker();
        if(data.intake_complete&&lastAttractions.length&&(profile.services||[]).some(x=>x==='attractions'||x==='route')){
          const lines=lastAttractions.slice(0,5).map(x=>`• ${x.name}${x.city?' — '+x.city:''}`).join('\n');
          const text='מצאתי התאמות ראשונות לאטרקציות:\n'+lines;add('bot',text);history.push({role:'assistant',content:text});
        }
        saveState();
      }catch(e){const err='יש כרגע תקלה זמנית. נסי שוב בעוד רגע.';add('bot',err);history.push({role:'assistant',content:err});saveState();}
      finally{busy=false;send.disabled=false;input.value='';input.focus()}
    }
    async function submit(){const raw=input.value.trim();input.value='';await sendMessage(raw,true)}
    send.addEventListener('click',function(e){e.preventDefault();e.stopImmediatePropagation();submit()},true);
    input.addEventListener('keydown',function(e){if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();e.stopImmediatePropagation();submit()}},true);

    messages.innerHTML='';
    if(history.length){history.forEach(item=>add(item.role==='assistant'?'bot':'user',String(item.content||'')));}
    else {const welcome='היי, אני אריאלה. מה תרצו לתכנן לחופשה?';add('bot',welcome);history=[{role:'assistant',content:welcome}];saveState();}
    summary();renderServicePicker();input.placeholder='';

    // Legacy preview code may finish an async name lookup after this script. Remove only that obsolete second greeting.
    const guard=new MutationObserver(muts=>{for(const m of muts){for(const n of m.addedNodes){if(n.nodeType!==1||!n.matches?.('.ac-row.bot'))continue;const text=(n.querySelector('.ac-bubble')?.textContent||'').trim();if(/^היי[ ,].*איך אפשר לעזור\??$/.test(text)){n.remove();}}}});
    guard.observe(messages,{childList:true});setTimeout(()=>guard.disconnect(),6000);
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot);else boot();
})();