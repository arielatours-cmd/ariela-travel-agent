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

    // Business dates: replace the ambiguous checkbox presentation with an
    // explicit Yes/No choice. Keep the original checkbox as the submitted value.
    const flex=document.getElementById('businessFlexibleDates');
    if(flex&&!document.querySelector('.business-flex-choice')){
      const oldLabel=flex.closest('.business-flex-toggle');
      if(oldLabel)oldLabel.style.display='none';
      const box=document.createElement('div');box.className='business-flex-choice';
      const title=document.createElement('div');title.className='business-flex-question';
      title.textContent=document.documentElement.lang==='en'?'Do you have flexibility with the dates?':'האם יש גמישות בתאריכים?';
      title.style.gridColumn='1/-1';title.style.fontWeight='700';title.style.textAlign='center';
      const yes=document.createElement('button');yes.type='button';yes.textContent=document.documentElement.lang==='en'?'Yes':'כן';
      const no=document.createElement('button');no.type='button';no.textContent=document.documentElement.lang==='en'?'No':'לא';
      box.append(title,yes,no);oldLabel?.insertAdjacentElement('afterend',box);
      function choose(value){
        flex.checked=value;flex.dispatchEvent(new Event('change',{bubbles:true}));
        yes.classList.toggle('selected',value);no.classList.toggle('selected',!value);
      }
      yes.addEventListener('click',()=>choose(true));
      no.addEventListener('click',()=>choose(false));
      // No selection initially: hide both follow-up sections until the user answers.
      const time=document.getElementById('businessTimePanel');
      const days=document.getElementById('businessFlexPanel');
      if(time)time.hidden=true;if(days)days.hidden=true;
      box.addEventListener('click',()=>{
        if(flex.checked){if(days)days.hidden=false;if(time)time.hidden=true;}
        else{if(days)days.hidden=true;if(time)time.hidden=false;}
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
