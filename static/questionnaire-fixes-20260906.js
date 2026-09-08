(function(){
  function init(){
    if(!document.getElementById('ariella-corrections-20260908')){
      const link=document.createElement('link');link.id='ariella-corrections-20260908';link.rel='stylesheet';link.href='/static/ariella-corrections-20260908.css';document.head.appendChild(link);
    }
    const form=document.getElementById('tripWizard');
    const isEn=document.documentElement.lang==='en';

    if(form){
      const bar=document.querySelector('.trip-back-bar');
      const gate=document.getElementById('vacationTypeGate');
      if(bar&&gate&&window.matchMedia('(max-width:760px)').matches){gate.insertAdjacentElement('afterend',bar);bar.classList.add('mobile-ready');}else if(bar){bar.classList.add('mobile-ready');}

      function setChoiceText(name,value,textHe,textEn){
        const input=form.querySelector(`input[name="${name}"][value="${value}"]`);
        const span=input?.closest('.choice-button')?.querySelector('span');
        if(span)span.textContent=isEn?textEn:textHe;
      }
      setChoiceText('budget_mode','per_person','תקציב לאדם','Budget per person');
      setChoiceText('budget_mode','unlimited','ללא הגבלת תקציב','No budget limit');
      setChoiceText('business_budget_mode','per_person','תקציב לאדם','Budget per person');
      setChoiceText('business_budget_mode','unlimited','ללא הגבלת תקציב','No budget limit');
      setChoiceText('ski_budget_mode','per_person','תקציב לאדם','Budget per person');
      setChoiceText('ski_budget_mode','unlimited','ללא הגבלת תקציב','No budget limit');
      [form.querySelector('.wizard-step[data-route="standard"][data-step="5"]'),form.querySelector('.business-question[data-step="6"]'),form.querySelector('.ski-question[data-step="7"]')].forEach(step=>{const h=step?.querySelector('h2');if(h)h.textContent=isEn?'Would you like to set a budget?':'האם תרצו להגביל את התקציב?';});

      const icons={destination_mode:{specific:'📍',open:'✦'},date_mode:{exact:'▣',month:'▦',anytime:'↔'},budget_mode:{per_person:'₪',unlimited:'▤'},business_budget_mode:{per_person:'₪',unlimited:'▤'},ski_budget_mode:{per_person:'₪',unlimited:'▤'},deal_priorities:{direct:'✈',baggage:'▣',dates:'▦',maximize:'↗'},ski_date_mode:{exact:'▣',month:'▦',ski_flexible:'↔'}};
      Object.entries(icons).forEach(([name,values])=>Object.entries(values).forEach(([value,icon])=>{form.querySelectorAll(`input[name="${name}"][value="${value}"]`).forEach(input=>{const label=input.closest('.choice-button');if(!label||label.querySelector('.choice-icon'))return;const span=label.querySelector(':scope > span');if(!span)return;const i=document.createElement('i');i.className='choice-icon';i.setAttribute('aria-hidden','true');i.textContent=icon;span.prepend(i);});}));

      form.querySelectorAll('.wizard-type-back').forEach(button=>button.addEventListener('click',()=>{form.querySelectorAll('input[name="vacation_type"]').forEach(input=>{input.checked=false;input.closest('.vacation-type-card')?.classList.remove('selected');});},true));

      const businessNotes=form.querySelector('textarea[name="business_notes"]')?.closest('.notes-label');if(businessNotes)businessNotes.remove();
      const oneConnection=form.querySelector('input[name="business_priorities"][value="max_one_connection"]')?.closest('.choice-button');if(oneConnection)oneConnection.remove();

      const flex=document.getElementById('businessFlexibleDates');
      if(flex&&!document.querySelector('.business-flex-choice')){
        const oldLabel=flex.closest('.business-flex-toggle');if(oldLabel)oldLabel.style.display='none';
        const box=document.createElement('div');box.className='business-flex-choice';const title=document.createElement('div');title.className='business-flex-question';title.textContent=isEn?'Do you have flexibility with the dates?':'האם יש גמישות בתאריכים?';const yes=document.createElement('button');yes.type='button';yes.textContent=isEn?'Yes':'כן';const no=document.createElement('button');no.type='button';no.textContent=isEn?'No':'לא';box.append(title,yes,no);oldLabel?.insertAdjacentElement('afterend',box);
        const time=document.getElementById('businessTimePanel'),days=document.getElementById('businessFlexPanel');let answered=false;
        function choose(value){answered=true;flex.checked=value;yes.classList.toggle('selected',value);no.classList.toggle('selected',!value);flex.dispatchEvent(new Event('change',{bubbles:true}));if(value){if(days)days.hidden=false;if(time)time.hidden=true;}else{if(days)days.hidden=true;if(time)time.hidden=false;}}
        yes.addEventListener('click',()=>choose(true));no.addEventListener('click',()=>choose(false));if(time)time.hidden=true;if(days)days.hidden=true;
        form.addEventListener('change',function(e){if(e.target===flex&&answered){if(flex.checked){if(days)days.hidden=false;if(time)time.hidden=true;}else{if(days)days.hidden=true;if(time)time.hidden=false;}}});
      }

      const timePanel=document.getElementById('businessTimePanel');
      if(timePanel&&!timePanel.querySelector('.business-time-field-headings')){timePanel.querySelectorAll('.two-cols > label').forEach(function(label){const inputs=label.querySelectorAll('input[type="date"],input[type="time"]');if(inputs.length!==2)return;const headings=document.createElement('div');headings.className='business-time-field-headings';const dateLabel=document.createElement('span');dateLabel.textContent=isEn?'Date':'תאריך';const timeLabel=document.createElement('span');timeLabel.textContent=isEn?'Time':'שעה';headings.append(dateLabel,timeLabel);inputs[0].insertAdjacentElement('beforebegin',headings);inputs[0].classList.add('business-time-date');inputs[1].classList.add('business-time-clock');});}

      function syncSoloSki(){const solo=form.querySelector('input[name="ski_travel_party"][value="solo"]')?.checked;const mixed=form.querySelector('input[name="ski_skill_level"][value="mixed"]');const label=mixed?.closest('.choice-button');if(label)label.hidden=!!solo;if(solo&&mixed?.checked){mixed.checked=false;mixed.dispatchEvent(new Event('change',{bubbles:true}));}}
      form.querySelectorAll('input[name="ski_travel_party"]').forEach(x=>x.addEventListener('change',syncSoloSki));syncSoloSki();
    }

    document.querySelectorAll('.search-status').forEach(el=>{const t=(el.textContent||'').trim().toLowerCase();if(t==='סריקה ראשונית'||t==='initial scan')el.remove();});

    document.querySelectorAll('.notification-toggle').forEach(button=>{if(button.querySelector('.whatsapp-one-time-price'))return;const text=button.querySelector(':scope > span:not(.toggle-track)');if(!text)return;const note=document.createElement('small');note.className='whatsapp-one-time-price';note.textContent=isEn?'One-time payment · ₪9':'תשלום חד־פעמי · 9 ₪';text.appendChild(note);});

    document.querySelectorAll('.plan-options').forEach(box=>{
      if(box.dataset.twoPlans==='1')return;const firstForm=box.querySelector('form');if(!firstForm)return;const action=firstForm.getAttribute('action')||'';
      const plans=isEn?[{key:'daily',name:'Database search',desc:'Smart search using Ariella’s shared deal database',price:'₪19'},{key:'intensive',name:'Intensive search',desc:'Includes external scans when needed',price:'₪39'}]:[{key:'daily',name:'חיפוש במאגר',desc:'חיפוש חכם במאגר הדילים המשותף של אריאלה',price:'19 ₪'},{key:'intensive',name:'חיפוש אינטנסיבי',desc:'כולל סריקות חיצוניות לפי הצורך',price:'39 ₪'}];
      box.innerHTML='';box.dataset.twoPlans='1';plans.forEach((p,idx)=>{const f=document.createElement('form');f.method='post';f.action=action;const input=document.createElement('input');input.type='hidden';input.name='plan';input.value=p.key;const b=document.createElement('button');b.type='submit';b.className='plan-choice'+(idx===0?' recommended':'');if(idx===0){const em=document.createElement('em');em.textContent=isEn?'Recommended':'מומלץ';b.appendChild(em);}const strong=document.createElement('strong');strong.textContent=p.name;const span=document.createElement('span');span.textContent=p.desc;const price=document.createElement('b');price.textContent=p.price+' · '+(isEn?'one-time payment':'תשלום חד־פעמי');b.append(strong,span,price);f.append(input,b);box.appendChild(f);});
    });
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
})();
