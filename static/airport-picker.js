
(function(){
 const lang=document.documentElement.lang==='en'?'en':'he';
 let data=[];
 fetch('/static/airports.json').then(r=>r.json()).then(x=>data=x).catch(()=>{});
 function label(a){return `${lang==='en'?a.city_en:a.city_he} — ${lang==='en'?a.name_en:a.name_he} (${a.code})`;}
 document.querySelectorAll('[data-airport-picker]').forEach(p=>{
   const search=p.querySelector('.airport-search'), box=p.querySelector('.airport-suggestions'), tags=p.querySelector('.airport-tags'), hidden=p.querySelector('.airport-values');
   let selected=(hidden.value||'').split(',').map(x=>x.trim()).filter(Boolean);
   function render(){
     tags.innerHTML='';
     selected.forEach(code=>{const a=data.find(x=>x.code===code); const t=document.createElement('span');t.className='airport-tag';t.textContent=a?label(a):code;const b=document.createElement('button');b.type='button';b.textContent='×';b.setAttribute('aria-label',lang==='en'?'Remove airport':'הסרת שדה תעופה');b.onclick=()=>{selected=selected.filter(x=>x!==code);render()};t.appendChild(b);tags.appendChild(t)});
     hidden.value=selected.join(',');
   }
   function suggest(){
     const q=search.value.trim().toLowerCase(); if(!q){box.hidden=true;return}
     const hits=data.filter(a=>![...selected].includes(a.code)&&[a.code,a.city_en,a.city_he,a.name_en,a.name_he,a.country].some(v=>(v||'').toLowerCase().includes(q))).slice(0,8);
     box.innerHTML='';hits.forEach(a=>{const b=document.createElement('button');b.type='button';b.textContent=label(a);b.onclick=()=>{selected.push(a.code);search.value='';box.hidden=true;render()};box.appendChild(b)});box.hidden=!hits.length;
   }
   search.addEventListener('input',suggest); search.addEventListener('focus',suggest); document.addEventListener('click',e=>{if(!p.contains(e.target))box.hidden=true}); render();
 });
})();
