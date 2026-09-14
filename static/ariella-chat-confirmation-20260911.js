(function(){
  function boot(){
    const wizard=document.getElementById('tripWizard');
    let chat=document.getElementById('ariellaDesktopChat');
    if(!chat&&wizard){const u=new URL(location.href);if(u.searchParams.get('ariella_chat')!=='1'){u.searchParams.set('ariella_chat','1');location.replace(u.toString());}return;}
    if(!chat||chat.dataset.ariellaChatBooted==='1')return;chat.dataset.ariellaChatBooted='1';
    const input=chat.querySelector('#ariellaChatInput'),send=chat.querySelector('#ariellaChatSend'),messages=chat.querySelector('#ariellaChatMessages');if(!input||!send||!messages)return;
    const style=document.createElement('style');
    style.textContent=`#ariellaDesktopChat .ac-row.bot{align-items:flex-start!important}#ariellaDesktopChat .ac-row.bot .ac-mini-avatar{margin-top:4px!important;align-self:flex-start!important}.ac-flow-card{max-width:90%;margin:4px 42px 12px 0;background:#fff;border:1px solid #e2d4b8;border-radius:16px;padding:15px;color:#17283f}.ac-flow-card strong{display:block;margin-bottom:10px;font-size:16px}.ac-flow-options{display:grid;grid-template-columns:1fr 1fr;gap:8px}.ac-flow-option{display:flex;align-items:center;gap:7px;border:1px solid #dccb9f;border-radius:11px;padding:10px 11px;background:#fffaf2;cursor:pointer}.ac-flow-option input{accent-color:#0b8f9c}.ac-flow-go{margin-top:12px;border:0;border-radius:10px;background:#0b8f9c;color:#fff;font-weight:800;padding:11px 16px;cursor:pointer}.ac-flow-secondary{margin-top:12px;margin-inline-start:8px;border:1px solid #0b8f9c;border-radius:10px;background:#fff;color:#0b8f9c;font-weight:800;padding:10px 14px;cursor:pointer}.ac-flow-error{display:block;margin-top:8px;color:#9b3b31;font-size:13px}.ac-result-list{margin:8px 0 0;padding-right:20px;line-height:1.55}.ac-result-list a{color:#0b8f9c;font-weight:700}@media(max-width:600px){.ac-flow-options{grid-template-columns:1fr 1fr}.ac-flow-card{margin-right:0;max-width:100%}}`;
    document.head.appendChild(style);
    const title=chat.querySelector('.ac-head-copy strong');if(title)title.textContent='אריאלה — סוכנת הנסיעות הראשית שלך';
    chat.querySelectorAll('.ac-avatar,.ac-mini-avatar').forEach(x=>x.textContent='A');const note=chat.querySelector('.ac-note');if(note)note.style.display='none';

    const STORAGE_KEY='ariellaChatState:v4';
    let profile={},history=[],busy=false,lastResponse=null;
    try{
      const saved=JSON.parse(localStorage.getItem(STORAGE_KEY)||localStorage.getItem('ariellaChatState:v3')||'null');
      if(saved&&typeof saved==='object'){if(saved.profile&&typeof saved.profile==='object')profile=saved.profile;if(Array.isArray(saved.history))history=saved.history.slice(-120);}
      const regGender=localStorage.getItem('ariellaRegistrationGender');if(regGender&&!profile.customer_gender)profile.customer_gender=regGender;
    }catch(e){}
    let greetingSeen=false;history=history.filter((item,index)=>{const text=String(item?.content||'').trim();const greeting=item?.role==='assistant'&&index<4&&/^היי[ ,].*(?:אריאלה|איך אפשר לעזור|איזו חופשה|כיף לראות)/.test(text);if(!greeting)return true;if(greetingSeen)return false;greetingSeen=true;return true;});

    const labels={destination:'יעד',dates:'תאריכים',travelers:'נוסעים',budget:'תקציב',flight:'טיסה',baggage:'כבודה'};
    function saveState(){try{localStorage.setItem(STORAGE_KEY,JSON.stringify({profile,history:history.slice(-120),saved_at:new Date().toISOString()}));}catch(e){}}
    function add(who,text){if(!String(text||'').trim())return;const row=document.createElement('div');row.className='ac-row '+who;if(who==='bot'){const a=document.createElement('div');a.className='ac-mini-avatar';a.textContent='A';row.appendChild(a)}const b=document.createElement('div');b.className='ac-bubble';b.textContent=text;row.appendChild(b);messages.appendChild(row);messages.scrollTop=messages.scrollHeight;}
    function valueText(k){const p=profile;if(k==='destination')return Array.isArray(p.destinations)?p.destinations.join(', '):(p.destinations||'');if(k==='dates')return p.departure_date&&p.return_date?`${p.departure_date} – ${p.return_date}`:(p.outbound_month||p.return_month||'');if(k==='travelers'){const a=p.adults||0,c=p.children||0,i=p.infants||0;return a||c||i?`${a} מבוגרים${c?`, ${c} ילדים`:''}${i?`, ${i} תינוקות`:''}`:''}if(k==='budget')return p.budget_mode==='unlimited'?'ללא הגבלת תקציב':(p.budget_amount?`${p.budget_amount} ₪ לאדם`:'');if(k==='flight')return p.flight_preference||'';if(k==='baggage')return p.baggage||'';return ''}
    function summary(){Object.keys(labels).forEach(k=>{const row=chat.querySelector(`[data-summary-key="${k}"]`),span=row?.querySelector('span'),v=valueText(k);if(span)span.textContent=v||'עדיין לא צוין';row?.classList.toggle('is-filled',!!v)})}
    function clearCards(){messages.querySelectorAll('.ac-flow-card').forEach(x=>x.remove())}
    function aiErrorMessage(data){const d=String(data?.detail||'');if(/429/.test(d))return 'אין כרגע מכסת API זמינה.';if(/401|403/.test(d))return 'החיבור לשרת לא הושלם.';if(/400/.test(d))return data?.message||'הבקשה לא התקבלה. נסי שוב.';return data?.message||'יש כרגע תקלה זמנית. נסי שוב בעוד רגע.'}
    async function getMemberFirstName(){try{const cached=localStorage.getItem('ariellaMemberFirstName');if(cached)return cached;const links=[...document.querySelectorAll('a')],detailsLink=links.find(a=>/פרטי החשבון|Account Details/i.test((a.textContent||'').trim()));if(!detailsLink)return '';const res=await fetch(detailsLink.href,{credentials:'same-origin'});if(!res.ok)return '';const html=await res.text(),doc=new DOMParser().parseFromString(html,'text/html'),full=(doc.querySelector('input[name="full_name"]')?.value||'').trim(),first=full.split(/\s+/)[0]||'';if(first)localStorage.setItem('ariellaMemberFirstName',first);return first;}catch(e){return '';}}

    function renderPurposePicker(){
      clearCards();const card=document.createElement('div');card.className='ac-flow-card';card.id='ariellaPurposeCard';
      card.innerHTML=`<strong>מה מטרת הנסיעה?</strong><div class="ac-flow-options"><label class="ac-flow-option"><input type="radio" name="ariellaPurpose" value="business"> 💼 נסיעת עסקים</label><label class="ac-flow-option"><input type="radio" name="ariellaPurpose" value="ski"> 🎿 חופשת סקי</label><label class="ac-flow-option"><input type="radio" name="ariellaPurpose" value="standard"> 🌍 טיול בחו״ל</label></div><button type="button" class="ac-flow-go">המשך</button><span class="ac-flow-error" hidden>בחרו אפשרות אחת.</span>`;
      messages.appendChild(card);messages.scrollTop=messages.scrollHeight;
      card.querySelector('.ac-flow-go').onclick=()=>{const el=card.querySelector('input:checked');if(!el){card.querySelector('.ac-flow-error').hidden=false;return;}profile.vacation_type=el.value;profile.services=[];saveState();card.remove();renderServicePicker();};
    }

    function renderServicePicker(){
      clearCards();const type=profile.vacation_type||'standard';const card=document.createElement('div');card.className='ac-flow-card';card.id='ariellaServiceCard';
      let extras=[];
      if(type==='business')extras=[['lodging','🏨 לינה'],['car','🚗 רכב']];
      else if(type==='ski')extras=[['lodging','🏨 לינה'],['car','🚗 רכב'],['attractions','🎿 אתר סקי']];
      else extras=[['lodging','🏨 לינה'],['car','🚗 רכב'],['attractions','🎟️ אטרקציות'],['route','🗺️ תכנון מסלול']];
      card.innerHTML=`<strong>טיסה כלולה בחיפוש. מה עוד תרצו שאחפש או אתכנן?</strong><div class="ac-flow-options">${extras.map(([v,l])=>`<label class="ac-flow-option"><input type="checkbox" value="${v}"> ${l}</label>`).join('')}</div><button type="button" class="ac-flow-go">המשך</button>`;
      messages.appendChild(card);messages.scrollTop=messages.scrollHeight;
      card.querySelector('.ac-flow-go').onclick=async()=>{const selected=['flight',...[...card.querySelectorAll('input:checked')].map(x=>x.value)];profile.services=selected;saveState();card.remove();await sendMessage('בחרתי את שירותי החופשה',false);};
    }

    function renderChoice(choice){
      clearCards();const card=document.createElement('div');card.className='ac-flow-card';card.id='ariellaChoiceCard';const multi=choice.type==='multi';
      card.innerHTML=`<strong>${choice.title||''}</strong><div class="ac-flow-options">${(choice.options||[]).map((o,i)=>`<label class="ac-flow-option"><input type="${multi?'checkbox':'radio'}" name="ariellaChoice${multi?'_'+i:''}" value="${String(o.value).replace(/"/g,'&quot;')}"> ${o.label}</label>`).join('')}</div>${choice.allow_none?'<label class="ac-flow-option" style="margin-top:8px"><input type="checkbox" data-none-choice> לא נדרש משהו מיוחד</label>':''}<button type="button" class="ac-flow-go">המשך</button><span class="ac-flow-error" hidden>בחרו לפחות אפשרות אחת.</span>`;
      messages.appendChild(card);messages.scrollTop=messages.scrollHeight;
      card.querySelector('.ac-flow-go').onclick=async()=>{const none=card.querySelector('[data-none-choice]')?.checked;let vals=none?['none']:[...card.querySelectorAll('.ac-flow-options input:checked')].map(x=>x.value);if(!vals.length){card.querySelector('.ac-flow-error').hidden=false;return;}let value=multi?vals:vals[0];if(choice.field==='save_traveler_names')value=String(value)==='true';if(choice.field==='travel_party_type'){if(value==='solo'){profile.adults=1;profile.children=0;profile.infants=0;}else if(value==='couple'){profile.adults=2;profile.children=0;profile.infants=0;}}profile[choice.field]=value;saveState();card.remove();await sendMessage(Array.isArray(value)?value.join(', '):String(value),true);};
    }

    function travelerChoiceForReply(reply){
      if(profile.travel_party_type)return null;
      if(!/כמה נוסעים יהיו|כמה נוסעים|מי נוסע/.test(String(reply||'')))return null;
      return {field:'travel_party_type',type:'single',title:'מי נוסע לחופשה?',options:[{value:'solo',label:'אני לבד'},{value:'couple',label:'עם בן/בת זוג'},{value:'family',label:'משפחה עם ילדים'},{value:'friends',label:'עם חברים'}]};
    }
    function personalizeTravelerNamesQuestion(reply){
      if(profile.save_traveler_names!==true||!/כתבו את השמות הפרטיים|השמות הפרטיים של הנוסעים/.test(String(reply||'')))return reply;
      const party=String(profile.travel_party_type||'').toLowerCase();
      if(party==='family'||party==='משפחה')return 'איך קוראים לבן/בת הזוג ולילדים? כתבו את השמות הפרטיים שתרצו שאזכור לחיפושים הבאים.';
      if(party==='friends'||party==='חברים')return 'מה השמות הפרטיים של החברים שנוסעים איתכם?';
      if(party==='couple'||party==='זוג')return 'איך קוראים לבן/בת הזוג שנוסע/ת איתכם?';
      return reply;
    }

    function renderConfirmation(data){
      clearCards();const card=document.createElement('div');card.className='ac-flow-card';card.id='ariellaConfirmCard';
      card.innerHTML=`<strong>הפרטים הושלמו.</strong><div>${data.confirmation_text||"עברו על כל הפרטים ב'החופשה שלי'. אם הכול נכון, אשרו יציאה לחיפוש."}</div><button type="button" class="ac-flow-go">מאשר לצאת לחיפוש</button>`;
      messages.appendChild(card);messages.scrollTop=messages.scrollHeight;card.querySelector('.ac-flow-go').onclick=confirmSearch;
    }

    function renderSearchResults(data){
      if(Array.isArray(data.itinerary)&&data.itinerary.length){const card=document.createElement('div');card.className='ac-flow-card';card.innerHTML='<strong>מסלול מומלץ</strong><ol class="ac-result-list">'+data.itinerary.map(x=>`<li>יום ${x.day}: ${x.activity||''}${x.base?' — '+x.base:''}${x.price?' · '+x.price:''}${x.booking_url?` · <a href="${x.booking_url}" target="_blank" rel="noopener">הזמנה</a>`:''}</li>`).join('')+'</ol>';messages.appendChild(card);}
      if(Array.isArray(data.attractions)&&data.attractions.length){const card=document.createElement('div');card.className='ac-flow-card';card.innerHTML='<strong>אטרקציות מתאימות</strong><ul class="ac-result-list">'+data.attractions.slice(0,8).map(x=>`<li>${x.name||''}${x.city?' — '+x.city:''}${x.price?' · '+x.price:''}${(x.booking_url||x.official_url)?` · <a href="${x.booking_url||x.official_url}" target="_blank" rel="noopener">הזמנה</a>`:''}</li>`).join('')+'</ul>';messages.appendChild(card);}
      if(data.monitoring_offer?.available){const card=document.createElement('div');card.className='ac-flow-card';card.innerHTML=`<strong>${data.monitoring_offer.title}</strong><div>${(data.monitoring_offer.plans||[]).map(x=>`${x.price_ils} ₪ — ${x.label}`).join('<br>')}</div>`;messages.appendChild(card);}
      messages.scrollTop=messages.scrollHeight;
    }

    async function confirmSearch(){
      if(busy)return;busy=true;send.disabled=true;const card=document.getElementById('ariellaConfirmCard');if(card)card.querySelector('.ac-flow-go').disabled=true;
      try{
        const res=await fetch('/api/ariella/confirm-search',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'same-origin',body:JSON.stringify({profile,history})});const data=await res.json();
        if(!res.ok||data.status!=='success'){const err=aiErrorMessage(data);add('bot',err);history.push({role:'assistant',content:err});saveState();return;}
        clearCards();add('bot',data.message);history.push({role:'assistant',content:data.message});renderSearchResults(data);
        const gender=profile.customer_gender;profile=gender?{customer_gender:gender}:{};saveState();summary();renderPurposePicker();
      }catch(e){const err='יש כרגע תקלה זמנית. נסי שוב בעוד רגע.';add('bot',err);history.push({role:'assistant',content:err});saveState();}
      finally{busy=false;send.disabled=false;input.focus();}
    }

    async function sendMessage(raw,displayUser){
      raw=String(raw||'').trim();if(!raw||busy)return;busy=true;send.disabled=true;if(displayUser)add('user',raw);const priorHistory=history.slice(-12);history.push({role:'user',content:raw});saveState();
      try{
        const res=await fetch('/api/ariella/chat',{method:'POST',headers:{'Content-Type':'application/json'},credentials:'same-origin',body:JSON.stringify({message:raw,history:priorHistory,profile})});const data=await res.json();
        if(!res.ok||data.status!=='success'){const err=aiErrorMessage(data);add('bot',err);history.push({role:'assistant',content:err});saveState();return;}
        lastResponse=data;profile=data.profile||profile;summary();let reply=personalizeTravelerNamesQuestion(String(data.reply||'').trim());let choice=data.ui_choice||travelerChoiceForReply(reply);
        if(choice){renderChoice(choice);}else if(reply){add('bot',reply);history.push({role:'assistant',content:reply});}
        if(data.show_purpose_picker)renderPurposePicker();else if(data.show_service_picker)renderServicePicker();else if(data.requires_confirmation)renderConfirmation(data);
        saveState();
      }catch(e){const err='יש כרגע תקלה זמנית. נסי שוב בעוד רגע.';add('bot',err);history.push({role:'assistant',content:err});saveState();}
      finally{busy=false;send.disabled=false;input.value='';input.focus();}
    }

    async function submit(){const raw=input.value.trim();input.value='';await sendMessage(raw,true)}
    send.addEventListener('click',function(e){e.preventDefault();e.stopImmediatePropagation();submit()},true);
    input.addEventListener('keydown',function(e){if(e.key==='Enter'&&!e.shiftKey){e.preventDefault();e.stopImmediatePropagation();submit()}},true);

    async function initializeConversation(){
      messages.innerHTML='';
      if(history.length){history.forEach(item=>add(item.role==='assistant'?'bot':'user',String(item.content||'')));}
      else{
        const firstName=await getMemberFirstName();
        const female=String(profile.customer_gender||'').toLowerCase()==='female';
        let welcome='היי, אני אריאלה. איך אני יכולה לעזור לך הפעם?';
        if(firstName)welcome=female?`היי ${firstName}, שמחה שחזרת, כמה כיף שאת כאן. איך אני יכולה לעזור לך הפעם?`:`היי ${firstName}, שמחה שחזרת, כמה כיף שאתה כאן. איך אני יכולה לעזור לך הפעם?`;
        add('bot',welcome);history=[{role:'assistant',content:welcome}];saveState();
      }
      summary();if(!profile.vacation_type)renderPurposePicker();else if(!Array.isArray(profile.services)||!profile.services.length)renderServicePicker();input.placeholder='';
    }
    initializeConversation();
    const guard=new MutationObserver(muts=>{for(const m of muts){for(const n of m.addedNodes){if(n.nodeType!==1||!n.matches?.('.ac-row.bot'))continue;const text=(n.querySelector('.ac-bubble')?.textContent||'').trim();if(/^היי[ ,].*איך אפשר לעזור\??$/.test(text))n.remove();}}});guard.observe(messages,{childList:true});setTimeout(()=>guard.disconnect(),6000);
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot);else boot();
})();