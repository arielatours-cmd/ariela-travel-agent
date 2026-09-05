
  const AIRPORT_ALIASES = {
    TBS: ['georgia','georgian','tiflis','גאורגיה','גיאורגיה','טביליסי','תביליסי'],
    BUS: ['georgia','georgian','גאורגיה','גיאורגיה','בטומי','באטומי'],
    RMO: ['chisinau','kishinev','קישינב','קישינאו'],
    EVN: ['yerevan','erevan','ירוואן','ירבן'],
    SKG: ['thessaloniki','saloniki','סלוניקי'],
    ATH: ['athens','אתונה'],
    OTP: ['bucharest','בוקרשט']
  };
(function(){
  const lang=document.documentElement.lang==='en'?'en':'he';
  let data=[];

  function city(a){ return lang==='en' ? a.city_en : a.city_he; }
  function airport(a){ return lang==='en' ? a.name_en : a.name_he; }
  function country(a){ return lang==='en' ? (a.country_en||a.country) : (a.country_he||a.country); }

  /* Selected/default display: IATA — City, Country */
  function compactLabel(a){
    return `${a.code} — ${city(a)}, ${country(a)}`;
  }

  /* Search result display: City — localized airport name — Country (IATA) */
  function fullLabel(a){
    return `${city(a)} — ${airport(a)} — ${country(a)} (${a.code})`;
  }

  function codesFrom(value){
    return (value||'').split(',').map(x=>x.trim()).filter(Boolean);
  }

  function airportByCode(code){
    return data.find(x=>x.code===code);
  }

  function renderDefaultSummaries(){
    document.querySelectorAll('[data-default-airports-display]').forEach(el=>{
      const codes=codesFrom(el.dataset.defaultAirportsDisplay);
      const labels=codes.map(code=>{
        const a=airportByCode(code);
        return a ? compactLabel(a) : code;
      });
      if(labels.length) el.textContent=labels.join(' · ');
    });
  }

  function initializePickers(){
    document.querySelectorAll('[data-airport-picker]').forEach(p=>{
      const search=p.querySelector('.airport-search');
      const box=p.querySelector('.airport-suggestions');
      const tags=p.querySelector('.airport-tags');
      const hidden=p.querySelector('.airport-values');
      const modeInput=p.querySelector('.origin-selection-mode');
      const isOrigin=p.hasAttribute('data-origin-picker');
      const isDestination=p.hasAttribute('data-destination-picker');
      const isBusinessDestination=p.hasAttribute('data-business-destination-picker');
      const defaultCodes=isOrigin ? codesFrom(p.dataset.defaultAirports) : [];
      let selected=codesFrom(hidden.value);
      let usingDefaults=isOrigin && selected.length===0 && defaultCodes.length>0;
      let replacedDefaults=false;

      if(usingDefaults){
        selected=[...defaultCodes];
      }

      function render(){
        tags.innerHTML='';
        selected.forEach(code=>{
          const a=airportByCode(code);
          const tag=document.createElement('span');
          tag.className='airport-tag';
          tag.textContent=a ? compactLabel(a) : code;

          const remove=document.createElement('button');
          remove.type='button';
          remove.textContent='×';
          remove.setAttribute('aria-label',lang==='en'?'Remove airport':'הסרת שדה תעופה');
          remove.onclick=()=>{
            const removingReplacement = isOrigin && replacedDefaults && !defaultCodes.includes(code);
            selected=selected.filter(x=>x!==code);
            usingDefaults=false;
            /* If a manually selected replacement (e.g. Milan) is removed and nothing
               remains, return to the customer's country defaults. Removing TLV/HFA
               themselves is still treated as an intentional edit and is not undone. */
            if(removingReplacement && selected.length===0 && defaultCodes.length){
              selected=[...defaultCodes];
              usingDefaults=true;
              replacedDefaults=false;
            }
            render();
          };
          tag.appendChild(remove);
          tags.appendChild(tag);
        });
        hidden.value=selected.join(',');
        if(isOrigin && modeInput) modeInput.value = replacedDefaults ? 'custom' : 'default';
      }

      function suggest(){
        const q=search.value.trim().toLowerCase();
        if(!q){ box.hidden=true; return; }

        const hits=data.filter(a=>
          !selected.includes(a.code) &&
          [a.code,a.city_en,a.city_he,a.name_en,a.name_he,a.country,a.country_en,a.country_he,...(AIRPORT_ALIASES[a.code]||[])]
            .some(v=>(v||'').toLowerCase().includes(q))
        ).slice(0,10);

        box.innerHTML='';
        hits.forEach(a=>{
          const b=document.createElement('button');
          b.type='button';
          b.textContent=fullLabel(a);
          b.onclick=()=>{
            /*
             * First manually selected departure airport REPLACES account defaults.
             * Further selections are added to the user's own list.
             */
            if(isOrigin && usingDefaults){
              selected=[];
              usingDefaults=false;
              replacedDefaults=true;
            }
            // "Specific destination" means exactly one destination. "Several"
            // keeps multi-select behavior.
            if(isDestination || isBusinessDestination){
              const mode = isBusinessDestination
                ? document.querySelector('input[name="business_destination_mode"]:checked')?.value
                : document.querySelector('input[name="destination_mode"]:checked')?.value;
              if(mode==='specific') selected=[];
            }
            if(!selected.includes(a.code)) selected.push(a.code);
            search.value='';
            box.hidden=true;
            render();
          };
          box.appendChild(b);
        });
        box.hidden=!hits.length;
      }

      search.addEventListener('input',suggest);
      search.addEventListener('focus',suggest);
      document.addEventListener('click',e=>{ if(!p.contains(e.target)) box.hidden=true; });
      if(isDestination || isBusinessDestination){
        p.addEventListener('ariella-clear-destinations',()=>{
          selected=[];
          search.value='';
          box.hidden=true;
          render();
        });
      }
      render();
    });
  }

  fetch('/static/airports.json')
    .then(r=>r.json())
    .then(x=>{
      data=x;
      renderDefaultSummaries();
      initializePickers();
    })
    .catch(()=>{
      initializePickers();
    });
})();

/* Mobile questionnaire: place the “Back to My Vacations” button centered below
   the vacation-type cards instead of above the questionnaire. */
document.addEventListener('DOMContentLoaded',()=>{
  if(!window.matchMedia('(max-width:760px)').matches) return;
  const gate=document.getElementById('vacationTypeGate');
  const backBar=document.querySelector('.trip-back-bar');
  const backButton=backBar?.querySelector('.back-to-vacations');
  if(!gate || !backBar || !backButton) return;
  gate.insertAdjacentElement('afterend',backBar);
  backBar.style.width='100%';
  backBar.style.maxWidth='100%';
  backBar.style.display='flex';
  backBar.style.justifyContent='center';
  backBar.style.padding='8px 16px 28px';
  backBar.style.margin='0 auto';
  backButton.style.width='min(300px,82vw)';
  backButton.style.minHeight='50px';
  backButton.style.display='inline-flex';
  backButton.style.alignItems='center';
  backButton.style.justifyContent='center';
  backButton.style.margin='0 auto';
});
