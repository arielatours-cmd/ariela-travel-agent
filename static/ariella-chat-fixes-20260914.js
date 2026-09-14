(function(){
'use strict';
function chat(){return document.getElementById('ariellaDesktopChat');}
function summaryRows(){return [...document.querySelectorAll('#ariellaDesktopChat .ac-detail')];}
function flightInfoComplete(){
  const keys=['destination','dates','travelers','budget','flight','baggage'];
  return keys.every(k=>{const row=document.querySelector(`#ariellaDesktopChat [data-summary-key="${k}"]`);return row&&row.classList.contains('is-filled');});
}
function cleanOldUi(){
  const root=chat();if(!root)return;
  root.querySelectorAll('.ariella-new-chat').forEach(x=>x.remove());
  document.querySelectorAll('#vacationTypeGate,.vacation-type-gate').forEach(x=>x.style.setProperty('display','none','important'));
  root.querySelectorAll('.ac-flow-card').forEach(card=>{if(!flightInfoComplete())card.remove();});
}
function isNewVacation(text){return /^(?:מהתחלה|חופשה חדשה|נתחיל מחדש|להתחיל מחדש|בואי נתחיל מחדש|בואי נחפש משהו אחר)\s*[.!?]*$/i.test(String(text||'').trim());}
function resetVisibleVacation(){
  try{localStorage.removeItem('ariellaChatState:v4');localStorage.removeItem('ariellaChatState:v3');sessionStorage.removeItem('ariellaChatState:v4');sessionStorage.removeItem('ariellaChatState:v3');}catch(e){}
  summaryRows().forEach(row=>{row.classList.remove('is-filled');const span=row.querySelector('span');if(span)span.textContent=document.documentElement.lang==='en'?'Not specified yet':'עדיין לא צוין';});
}
function boot(){
  cleanOldUi();
  const root=chat(),send=root?.querySelector('#ariellaChatSend'),input=root?.querySelector('#ariellaChatInput');
  if(send&&input&&!send.dataset.newVacationReset){
    send.dataset.newVacationReset='1';
    send.addEventListener('click',()=>{if(isNewVacation(input.value)){resetVisibleVacation();}},true);
    input.addEventListener('keydown',e=>{if(e.key==='Enter'&&!e.shiftKey&&isNewVacation(input.value)){resetVisibleVacation();}},true);
  }
  new MutationObserver(cleanOldUi).observe(document.body,{childList:true,subtree:true});
}
if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',boot);else boot();
})();