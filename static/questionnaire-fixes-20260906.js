(function(){
  function init(){
    if(!document.getElementById('ariella-corrections-20260908')){const link=document.createElement('link');link.id='ariella-corrections-20260908';link.rel='stylesheet';link.href='/static/ariella-corrections-20260908.css?v=20260908k';document.head.appendChild(link);}
    const form=document.getElementById('tripWizard');const isEn=document.documentElement.lang==='en';
    if(form){
      const bar=document.querySelector('.trip-back-bar'),gate=document.getElementById('vacationTypeGate');if(bar&&gate&&window.matchMedia('(max-width:760px)').matches){gate.insertAdjacentElement('afterend',bar);bar.classList.add('mobile-ready');}else if(bar){bar.classList.add('mobile-ready');}
      function setChoiceText(name,value,textHe,textEn){const input=form.querySelector(`input[name="${name}"][value="${value}"]`),span=input?.closest('.choice-button')?.querySelector('span');if(span)span.textContent=isEn?textEn:textHe;}
      setChoiceText('budget_mode','per_person','תקציב לאדם','Budget per person');setChoiceText('budget_mode','unlimited','ללא הגבלת תקציב','No budget limit');setChoiceText('business_budget_mode','per_person','תקציב לאדם','Budget per person');setChoiceText('business_budget_mode','unlimited','ללא הגבלת תקציב','No budget limit');setChoiceText('ski_budget_mode','per_person','תקציב לאדם','Budget per person');setChoiceText('ski_budget_mode','unlimited','ללא הגבלת תקציב','No budget limit');
      [form.querySelector('.wizard-step[data-route="standard"][data-step="5"]'),form.querySelector('.business-question[data-step="6"]'),form.querySelector('.ski-question[data-step="7"]')].forEach(step=>{const h=step?.querySelector('h2');if(h)h.textContent=isEn?'Would you like to set a budget?':'האם תרצו להגביל את התקציב?';});
      form.querySelectorAll('.choice-icon,.party-people-icon,.budget-choice-icon,.direct-flight-icon,.answer-visual-icon').forEach(icon=>icon.remove());
      function addVisual(name,value,symbol,className=''){const label=form.querySelector(`input[name="${name}"][value="${value}"]`)?.closest('.choice-button'),span=label?.querySelector(':scope > span');if(!label||!span)return;label.classList.add('has-answer-visual');const i=document.createElement('i');i.className='answer-visual-icon '+className;i.setAttribute('aria-hidden','true');i.textContent=symbol;span.prepend(i);}
      addVisual('destination_mode','specific','📍','destination-pin-icon');addVisual('destination_mode','open','🌍','destination-globe-icon');
      addVisual('date_mode','exact','📅','date-choice-icon');addVisual('date_mode','month','🗓️','date-choice-icon');
      const party={solo:['👤'],couple:['👤','👤'],friends:['👤','👤','👤'],family:['👤','👤','👤','👤','👤']};Object.entries(party).forEach(([value,people])=>{const span=form.querySelector(`input[name="travel_party"][value="${value}"]`)?.closest('.choice-button')?.querySelector(':scope > span');if(!span)return;const wrap=document.createElement('i');wrap.className='party-people-icon '+(value==='family'?'family-people-icon':'');wrap.setAttribute('aria-hidden','true');people.forEach((person,index)=>{const p=document.createElement('b');p.textContent=person;if(value==='family'&&index>=2)p.className='child-person';wrap.appendChild(p);});span.prepend(wrap);});
      addVisual('deal_priorities','baggage','🧳','priority-choice-icon');addVisual('deal_priorities','direct','✈️','priority-choice-icon');addVisual('deal_priorities','maximize','⏰','priority-choice-icon');
      addVisual('budget_mode','per_person','💵','budget-choice-icon');addVisual('budget_mode','unlimited','💵💵💵','budget-choice-icon budget-many-bills');
      form.querySelectorAll('.wizard-type-back').forEach(button=>button.addEventListener('click',()=>{form.querySelectorAll('input[name="vacation_type"]').forEach(input=>{input.checked=false;input.closest('.vacation-type-card')?.classList.remove('selected');});},true));
      const businessNotes=form.querySelector('textarea[name="business_notes"]')?.closest('.notes-label');if(businessNotes)businessNotes.remove();const oneConnection=form.querySelector('input[name="business_priorities"][value="max_one_connection"]')?.closest('.choice-button');if(oneConnection)oneConnection.remove();
      function syncSoloSki(){const solo=form.querySelector('input[name="ski_travel_party"][value="solo"]')?.checked,mixed=form.querySelector('input[name="ski_skill_level"][value="mixed"]'),label=mixed?.closest('.choice-button');if(label)label.hidden=!!solo;if(solo&&mixed?.checked){mixed.checked=false;mixed.dispatchEvent(new Event('change',{bubbles:true}));}}form.querySelectorAll('input[name="ski_travel_party"]').forEach(x=>x.addEventListener('change',syncSoloSki));syncSoloSki();
    }
    document.querySelectorAll('.search-status').forEach(el=>{const t=(el.textContent||'').trim().toLowerCase();if(t==='סריקה ראשונית'||t==='initial scan')el.remove();});
    document.querySelectorAll('.notification-toggle').forEach(button=>{if(button.querySelector('.whatsapp-one-time-price'))return;const text=button.querySelector(':scope > span:not(.toggle-track)');if(!text)return;const note=document.createElement('small');note.className='whatsapp-one-time-price';note.textContent=isEn?'One-time payment of ₪9':'בתשלום חד פעמי של 9 ש״ח';text.appendChild(note);});
    document.querySelectorAll('.deal-alert-copy').forEach(copy=>{if(copy.querySelector('.deal-alert-price'))return;const note=document.createElement('small');note.className='deal-alert-price';note.textContent=isEn?'One-time payment of ₪9':'בתשלום חד פעמי של 9 ש״ח';copy.appendChild(note);});
    document.querySelectorAll('.important-terms dd.check').forEach(el=>{el.textContent=isEn?'Check on supplier website':'יש לבדוק באתר הספק';});
    document.querySelectorAll('.important-terms dd').forEach(el=>{const t=(el.textContent||'').trim();if(t==='בכפוף לתנאי הספק'||t==='יש לבדוק מול הספק'||t==='Subject to supplier terms')el.textContent=isEn?'Check on supplier website':'יש לבדוק באתר הספק';});
    if(window.matchMedia('(max-width:760px)').matches){
      const wrap=document.getElementById('dealFiltersWrap'),main=wrap?.querySelector('.deal-filters-main'),more=document.getElementById('dealFiltersMore'),button=document.getElementById('moreFiltersToggle'),clear=document.getElementById('clearDealFilters');
      const stops=document.getElementById('filterStops');
      if(stops){stops.style.setProperty('width','72%','important');stops.style.setProperty('align-self','flex-start','important');}
      function addPopupClose(wrapId,labelHe,labelEn){const popupWrap=document.getElementById(wrapId),menu=popupWrap?.querySelector('.filter-multi-menu');if(!menu||menu.querySelector('.mobile-filter-popup-close'))return;const close=document.createElement('button');close.type='button';close.className='mobile-filter-popup-close';close.setAttribute('aria-label',isEn?labelEn:labelHe);close.textContent='×';close.style.cssText='position:sticky;top:0;float:left;z-index:3;width:32px;height:32px;min-height:32px;padding:0;margin:0 0 6px 0;border:0;border-radius:50%;background:#17283f;color:#fff;font-size:24px;line-height:30px;font-weight:700;cursor:pointer;box-shadow:0 2px 8px rgba(0,0,0,.18)';close.addEventListener('click',e=>{e.preventDefault();e.stopPropagation();menu.hidden=true;});menu.prepend(close);}
      addPopupClose('filterAirlineWrap','סגירת חברות תעופה','Close airlines');
      addPopupClose('filterDestinationWrap','סגירת יעדים','Close destinations');
      if(wrap&&clear){
        wrap.appendChild(clear);
        clear.style.cssText='display:none;width:100%;min-height:40px;margin:8px 0 0;padding:8px 12px;border:0;border-radius:9px;background:#0b8f9c;color:#fff;font-size:13px;font-weight:800;align-items:center;justify-content:center;cursor:pointer';
      }
      if(wrap&&main&&more&&button){
        const children=[...main.children].filter(el=>el!==button);
        const setOpen=open=>{
          wrap.classList.toggle('filters-open',open);
          button.setAttribute('aria-expanded',open?'true':'false');
          button.textContent=isEn?(open?'Close filters ▴':'Filter deals ▾'):(open?'סגור סינון ▴':'סינון דילים ▾');
          button.style.setProperty('display','flex','important');
          button.style.setProperty('width','100%','important');
          main.style.setProperty('display','grid','important');
          main.style.setProperty('grid-template-columns',open?'repeat(2,minmax(0,1fr))':'1fr','important');
          main.style.setProperty('gap',open?'7px 8px':'0','important');
          children.forEach(el=>el.style.setProperty('display',open?'flex':'none','important'));
          if(open){more.hidden=false;more.setAttribute('aria-hidden','false');more.style.setProperty('display','grid','important');more.style.setProperty('grid-template-columns','repeat(2,minmax(0,1fr))','important');if(clear)clear.style.setProperty('display','flex','important');}
          else{more.hidden=true;more.setAttribute('aria-hidden','true');more.style.setProperty('display','none','important');if(clear)clear.style.setProperty('display','none','important');}
        };
        setOpen(false);
        button.addEventListener('click',e=>{e.preventDefault();e.stopImmediatePropagation();setOpen(button.getAttribute('aria-expanded')!=='true');},true);
      }
    }
    document.querySelectorAll('.plan-options').forEach(box=>{if(box.dataset.twoPlans==='1')return;const firstForm=box.querySelector('form');if(!firstForm)return;const action=firstForm.getAttribute('action')||'',plans=isEn?[{key:'daily',name:'Database search',desc:'Smart search using Ariella’s shared deal database',price:'₪19'},{key:'intensive',name:'Intensive search',desc:'Includes external scans when needed',price:'₪39'}]:[{key:'daily',name:'חיפוש במאגר',desc:'חיפוש חכם במאגר הדילים המשותף של אריאלה',price:'19 ₪'},{key:'intensive',name:'חיפוש אינטנסיבי',desc:'כולל סריקות חיצוניות לפי הצורך',price:'39 ₪'}];box.innerHTML='';box.dataset.twoPlans='1';plans.forEach((p,idx)=>{const f=document.createElement('form');f.method='post';f.action=action;const input=document.createElement('input');input.type='hidden';input.name='plan';input.value=p.key;const b=document.createElement('button');b.type='submit';b.className='plan-choice'+(idx===0?' recommended':'');if(idx===0){const em=document.createElement('em');em.textContent=isEn?'Recommended':'מומלץ';b.appendChild(em);}const strong=document.createElement('strong');strong.textContent=p.name,span=document.createElement('span');span.textContent=p.desc;const price=document.createElement('b');price.textContent=p.price+' · '+(isEn?'per month':'לחודש');b.append(strong,span,price);f.append(input,b);box.appendChild(f);});});
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
})();