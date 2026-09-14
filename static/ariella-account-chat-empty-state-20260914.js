(function(){
  'use strict';

  function wireMobileMenu(){
    const b=document.getElementById('mobileNavToggle');
    const m=document.getElementById('mobileNavMenu');
    const a=document.getElementById('mobileMyAriellaToggle');
    const s=document.getElementById('mobileMyAriellaSubmenu');
    if(!b||!m||b.dataset.ariellaMenuFixed==='1') return;
    b.dataset.ariellaMenuFixed='1';
    const closeSub=()=>{if(s){s.hidden=true;s.style.display='none';}if(a)a.setAttribute('aria-expanded','false');};
    const closeAll=()=>{m.hidden=true;m.style.display='none';b.setAttribute('aria-expanded','false');closeSub();};
    b.addEventListener('click',function(e){
      e.preventDefault();
      e.stopImmediatePropagation();
      const opening=m.hidden||getComputedStyle(m).display==='none';
      if(opening){m.hidden=false;m.style.setProperty('display','block','important');b.setAttribute('aria-expanded','true');}
      else closeAll();
    },true);
    if(a&&s){
      a.addEventListener('click',function(e){
        e.preventDefault();
        e.stopImmediatePropagation();
        const opening=s.hidden||getComputedStyle(s).display==='none';
        if(opening){s.hidden=false;s.style.setProperty('display','flex','important');s.style.setProperty('flex-direction','column','important');a.setAttribute('aria-expanded','true');}
        else closeSub();
      },true);
    }
    document.addEventListener('click',function(e){if(!m.contains(e.target)&&e.target!==b)closeAll();});
  }

  function removeDuplicateVacationLinks(empty){
    document.querySelectorAll('a').forEach(a=>{
      const t=(a.textContent||'').trim();
      if((t.includes('תכנון החופשה הראשונה')||t.includes('תכנון החופשה הבאה'))&&!empty.contains(a)) a.remove();
    });
  }

  function buildFirstVacationButton(empty){
    removeDuplicateVacationLinks(empty);
    let btn=empty.querySelector('.ariella-first-vacation-chat');
    if(!btn){
      btn=document.createElement('a');
      btn.className='button primary ariella-first-vacation-chat';
      btn.textContent='תכנון החופשה הראשונה שלי';
      empty.appendChild(btn);
    }
    btn.href='/trip/new?ariella_chat=1';
    btn.onclick=function(){ window.location.assign('/trip/new?ariella_chat=1'); };
    Object.assign(btn.style,{
      display:'flex',alignItems:'center',justifyContent:'center',textAlign:'center',
      width:'fit-content',minHeight:'52px',margin:'30px auto 0',padding:'13px 26px',
      lineHeight:'1.2',background:'#17283f',color:'#ffffff',border:'1px solid #17283f',
      borderRadius:'9px',textDecoration:'none',fontWeight:'700'
    });
  }

  function boot(){
    if(document.documentElement.lang==='en') return;
    wireMobileMenu();

    const intro=document.querySelector('.account-intro');
    const emptySection=document.querySelector('.account-empty-section');
    const empty=document.querySelector('.account-empty-section .empty-state');

    if(intro){
      intro.innerHTML='התחברו לאריאלה והיא תעזור לכם לתכנן<br>את החופשה הבאה שלכם — החל ממציאת טיסות,<br>דרך אטרקציות ומקומות לינה ועד להשכרת רכב.<br>והכול במקום אחד! ✈️';
      Object.assign(intro.style,{
        border:'1px solid #b8914f',borderRadius:'12px',padding:'18px 20px',
        margin:'16px auto 0',maxWidth:'620px',boxSizing:'border-box',lineHeight:'1.65',
        textAlign:'center'
      });
    }

    if(!empty) return;
    empty.querySelector('h3')?.remove();
    empty.querySelector('p')?.remove();
    [...empty.querySelectorAll('a')].forEach(a=>{if(!a.classList.contains('ariella-first-vacation-chat'))a.remove();});
    if(emptySection){emptySection.style.paddingTop='0';emptySection.style.marginTop='0';}
    empty.style.paddingTop='0';
    empty.style.paddingBottom='28px';
    buildFirstVacationButton(empty);
  }

  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',boot);
  else boot();
})();
