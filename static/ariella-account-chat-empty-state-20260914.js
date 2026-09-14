(function(){
  function toChatHref(href){
    try{
      const u=new URL(href,location.origin);
      u.searchParams.set('ariella_chat','1');
      return u.pathname+u.search+u.hash;
    }catch(e){return href;}
  }

  function wireDirectChatLinks(){
    [...document.querySelectorAll('a')].forEach(a=>{
      const t=(a.textContent||'').trim();
      if(t.includes('תכנון החופשה הראשונה')||t.includes('תכנון החופשה הבאה')){
        const target=toChatHref(a.href);
        a.href=target;
        if(!a.dataset.ariellaDirectChat){
          a.dataset.ariellaDirectChat='1';
          a.addEventListener('click',function(e){
            e.preventDefault();
            e.stopImmediatePropagation();
            location.assign(toChatHref(this.href));
          },true);
        }
      }
    });
  }

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
      e.preventDefault();e.stopImmediatePropagation();
      const opening=m.hidden||getComputedStyle(m).display==='none';
      if(opening){m.hidden=false;m.style.setProperty('display','block','important');b.setAttribute('aria-expanded','true');}
      else closeAll();
    },true);

    if(a&&s){
      a.addEventListener('click',function(e){
        e.preventDefault();e.stopImmediatePropagation();
        const opening=s.hidden||getComputedStyle(s).display==='none';
        if(opening){s.hidden=false;s.style.setProperty('display','flex','important');s.style.setProperty('flex-direction','column','important');a.setAttribute('aria-expanded','true');}
        else closeSub();
      },true);
    }

    document.addEventListener('click',function(e){if(!m.contains(e.target)&&e.target!==b)closeAll();});
  }

  function boot(){
    if(document.documentElement.lang==='en') return;

    wireDirectChatLinks();
    wireMobileMenu();

    const first=[...document.querySelectorAll('a')].find(a=>(a.textContent||'').includes('תכנון החופשה הראשונה'));
    const intro=document.querySelector('.account-intro');
    const emptySection=document.querySelector('.account-empty-section');
    const empty=document.querySelector('.account-empty-section .empty-state');

    if(!first || !empty) return;

    if(intro){
      intro.textContent='התחברו לאריאלה והיא תעזור לכם לתכנן את החופשה הבאה שלכם — החל ממציאת טיסות, דרך אטרקציות ומקומות לינה ועד להשכרת רכב. והכול במקום אחד! ✈️';
    }

    empty.querySelector('h3')?.remove();
    empty.querySelector('p')?.remove();

    if(emptySection){emptySection.style.paddingTop='12px';emptySection.style.marginTop='0';}
    empty.style.paddingTop='18px';
    empty.style.paddingBottom='18px';

    first.textContent='תכנון החופשה הראשונה שלי';
    first.href=toChatHref(first.href);
    empty.appendChild(first);
    first.style.display='flex';
    first.style.alignItems='center';
    first.style.justifyContent='center';
    first.style.textAlign='center';
    first.style.width='fit-content';
    first.style.minHeight='48px';
    first.style.margin='0 auto';
    first.style.padding='12px 24px';
    first.style.lineHeight='1.2';
  }

  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',boot); else boot();
})();
