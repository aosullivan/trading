// === URL PARAM SYNC ===
let _urlSignals=[];  // signal chips to restore after chart loads
let _urlChips=null;  // legend chips to restore after chart loads
function readURLParams(){
  const p=new URLSearchParams(window.location.search);
  if(p.get('ticker'))document.getElementById('ticker').value=p.get('ticker').toUpperCase();
  if(p.get('interval'))document.getElementById('interval').value=p.get('interval');
  const interval=document.getElementById('interval').value;
  chartStart=p.get('start')||defaultStart(interval);
  chartEnd=p.get('end')||'';
  if(p.get('period'))document.getElementById('period').value=p.get('period');
  if(p.get('multiplier'))document.getElementById('multiplier').value=p.get('multiplier');
  if(p.get('signals'))_urlSignals=p.get('signals').split(',').filter(Boolean);
  if(p.has('chips'))_urlChips=p.get('chips').split(',').filter(Boolean);
  if(typeof readWatchlistURLState==='function')readWatchlistURLState(p);
}
function pushURLParams(){
  const p=new URLSearchParams();
  const ticker=document.getElementById('ticker').value.toUpperCase();
  const interval=document.getElementById('interval').value;
  const period=document.getElementById('period').value;
  const mult=document.getElementById('multiplier').value;
  if(ticker&&ticker!=='BTC-USD')p.set('ticker',ticker);
  if(interval&&interval!=='1d')p.set('interval',interval);
  if(period&&period!=='10')p.set('period',period);
  if(mult&&mult!=='2.5')p.set('multiplier',mult);
  if(activeSignals.size)p.set('signals',[...activeSignals].join(','));
  // Legend chips (only write if non-default)
  const defaultChips=['vol'];
  const chipsArr=[...activeChips];
  const isDefault=chipsArr.length===defaultChips.length&&defaultChips.every(c=>activeChips.has(c));
  if(!isDefault)p.set('chips',chipsArr.join(','));
  if(typeof writeWatchlistURLState==='function')writeWatchlistURLState(p);
  const qs=p.toString();
  history.replaceState(null,'',qs?'?'+qs:window.location.pathname);
}

function restoreURLState(){
  if(typeof restoreWatchlistURLState==='function')restoreWatchlistURLState();
  // Restore legend items from URL
  if(_urlChips!==null){
    activeChips.clear();
    legendItems.forEach((item,i)=>{
      const shouldBeOn=_urlChips.includes(item.key);
      item.on=shouldBeOn;
      if(shouldBeOn)activeChips.add(item.key);
      // sup, res and volProfile handled after data loads
      if(item.key==='sup'||item.key==='res'||item.key==='volProfile'){/* toggled after data loads */}
      else{(sMap[item.key]?.()||[]).forEach(s=>s.applyOptions({visible:shouldBeOn}))}
      // updateFlipInfo called after data loads
      const row=document.querySelector(`.cl-row[data-li="${i}"]`);
      if(row){
        row.classList.toggle('off',!shouldBeOn);
        row.querySelector('.cl-eye').innerHTML=shouldBeOn?eyeSVG:eyeOffSVG;
      }
    });
  }
  // Restore signal chips from URL
  if(_urlSignals.length){
    document.querySelectorAll('.overlays .chip[onclick^="toggleSignal"]').forEach(el=>{
      const m=el.getAttribute('onclick').match(/toggleSignal\(this,'([\w]+)'\)/);
      if(!m)return;
      const name=m[1];
      if(_urlSignals.includes(name)){
        el.classList.add('on');
        activeSignals.add(name);
      }
    });
  }
}
