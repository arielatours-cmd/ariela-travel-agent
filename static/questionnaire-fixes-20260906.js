(function(){
  function init(){
    const form=document.getElementById('tripWizard');
    if(!form)return;

    // Move the back button to its final mobile position before revealing it.
    const bar=document.querySelector('.trip-back-bar');
    const gate=document.getElementById('vacationTypeGate');
    if(bar&&gate&&window.matchMedia('(max-width:760px)').matches){
      gate.insertAdjacentElement('afterend',bar);
      bar.classList.add('mobile-ready');
    }else if(bar){bar.classList.add('mobile-ready');}

    // Keep budget wording identical across regular, business and ski flows.
    const isEn=document.documentElement.lang==='en';
    function setChoiceText(name,value,textHe,textEn){
      const input=form.querySelector(`input[name="${name}"][value="${value}"]`);
      const span=input?.closest('.choice-button')?.querySelector('span');
      if(span)span.textContent=isEn?textEn:textHe;
    }
    setChoiceText('business_budget_mode','per_person','תקציב לאדם','Budget per person');
    setChoiceText('business_budget_mode','unlimited','ללא הגבלת תקציב','No budget limit');
    setChoiceText('ski_budget_mode','per_person','תקציב לאדם','Budget per person');
    setChoiceText('ski_budget_mode','unlimited','ללא הגבלת תקציב','No budget limit');

    const skiBudgetStep=form.querySelector('.ski-question[data-step="7"]');
    const skiBudgetHeading=skiBudgetStep?.querySelector('h2');
    if(skiBudgetHeading)skiBudgetHeading.textContent=isEn?'Would you like to set a budget?':'האם תרצו להגביל את התקציב?';

    // Business: the free-text notes field was removed by product decision.
    const businessNotes=form.querySelector('textarea[name="business_notes"]')?.closest('.notes-label');
    if(businessNotes)businessNotes.remove();

    // "Up to one connection" is not a useful preference here; remove it in both languages/views.
    const oneConnection=form.querySelector('input[name="business_priorities"][value="max_one_connection"]')?.closest('.choice-button');
    if(oneConnection)oneConnection.remove();

    // Business dates: explicit Yes/No flexibility choice.
    // Yes -> show number of flexible days. No -> show arrival/departure time constraints.
    const flex=document.getElementById('businessFlexibleDates');
    if(flex&&!document.querySelector('.business-flex-choice')){
      const oldLabel=flex.closest('.business-flex-toggle');
      if(oldLabel)oldLabel.style.display='none';
      const box=document.createElement('div');box.className='business-flex-choice';
      const title=document.createElement('div');title.className='business-flex-question';
      title.textContent=isEn?'Do you have flexibility with the dates?':'האם יש גמישות בתאריכים?';
      const yes=document.createElement('button');yes.type='button';yes.textContent=isEn?'Yes':'כן';
      const no=document.createElement('button');no.type='button';no.textContent=isEn?'No':'לא';
      box.append(title,yes,no);oldLabel?.insertAdjacentElement('afterend',box);

      const time=document.getElementById('businessTimePanel');
      const days=document.getElementById('businessFlexPanel');
      let answered=false;
      function choose(value){
        answered=true;
        flex.checked=value;
        yes.classList.toggle('selected',value);
        no.classList.toggle('selected',!value);
        flex.dispatchEvent(new Event('change',{bubbles:true}));
        if(value){if(days)days.hidden=false;if(time)time.hidden=true;}
        else{if(days)days.hidden=true;if(time)time.hidden=false;}
      }
      yes.addEventListener('click',()=>choose(true));
      no.addEventListener('click',()=>choose(false));
      if(time)time.hidden=true;
      if(days)days.hidden=true;
      form.addEventListener('change',function(e){
        if(e.target===flex&&answered){
          if(flex.checked){if(days)days.hidden=false;if(time)time.hidden=true;}
          else{if(days)days.hidden=true;if(time)time.hidden=false;}
        }
      });
    }

    // Business time constraints: make it explicit which box is Date and which is Time.
    const timePanel=document.getElementById('businessTimePanel');
    if(timePanel&&!timePanel.querySelector('.business-time-field-headings')){
      timePanel.querySelectorAll('.two-cols > label').forEach(function(label){
        const inputs=label.querySelectorAll('input[type="date"],input[type="time"]');
        if(inputs.length!==2)return;
        const headings=document.createElement('div');
        headings.className='business-time-field-headings';
        const dateLabel=document.createElement('span');
        dateLabel.textContent=isEn?'Date':'תאריך';
        const timeLabel=document.createElement('span');
        timeLabel.textContent=isEn?'Time':'שעה';
        headings.append(dateLabel,timeLabel);
        inputs[0].insertAdjacentElement('beforebegin',headings);
        inputs[0].classList.add('business-time-date');
        inputs[1].classList.add('business-time-clock');
      });
    }

    // Keep mixed ski levels unavailable for solo travelers even for browsers
    // without :has() support, and clear a stale mixed selection if party changes.
    function syncSoloSki(){
      const solo=form.querySelector('input[name="ski_travel_party"][value="solo"]')?.checked;
      const mixed=form.querySelector('input[name="ski_skill_level"][value="mixed"]');
      const label=mixed?.closest('.choice-button');
      if(label)label.hidden=!!solo;
      if(solo&&mixed?.checked){mixed.checked=false;mixed.dispatchEvent(new Event('change',{bubbles:true}));}
    }
    form.querySelectorAll('input[name="ski_travel_party"]').forEach(x=>x.addEventListener('change',syncSoloSki));
    syncSoloSki();
  }
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',init,{once:true});else init();
})();
