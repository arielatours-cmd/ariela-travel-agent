/* Deals-only first-paint stabilizer.
   Deal cards historically rendered several background URLs at once. Browsers can
   briefly paint a fallback image and then replace it when the top layer finishes.
   Normalize each deal visual to one deterministic URL as the HTML is parsed. */
(function(){
  function normalize(el){
    if(!el || !el.matches || !el.matches('.deal-visual')) return;
    var raw = el.style.backgroundImage || '';
    var urls = [];
    raw.replace(/url\(["']?([^"')]+)["']?\)/g,function(_,url){ urls.push(url); return _; });
    if(urls.length <= 1) return;
    var chosen = urls[0];
    el.style.backgroundImage = "linear-gradient(180deg,rgba(255,255,255,.01),rgba(0,0,0,.18)),url('" + chosen.replace(/'/g,"%27") + "')";
  }
  function scan(node){
    if(!node || node.nodeType!==1) return;
    normalize(node);
    if(node.querySelectorAll) node.querySelectorAll('.deal-visual').forEach(normalize);
  }
  var observer = new MutationObserver(function(records){
    records.forEach(function(record){ record.addedNodes.forEach(scan); });
  });
  observer.observe(document.documentElement,{childList:true,subtree:true});
  document.addEventListener('DOMContentLoaded',function(){
    document.querySelectorAll('.deal-visual').forEach(normalize);
    observer.disconnect();
  },{once:true});
})();
