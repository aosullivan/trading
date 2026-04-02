// === SIGNAL TOGGLES ===
const signalColors={
  supertrend:'#5b7fff',ema_crossover:'#ff9800',macd:'#b050ff',
  ma_confirm:'#00d4ff',donchian:'#ffd644',adx_trend:'#00e68a',bb_breakout:'#ff5274',
  keltner:'#e040fb',parabolic_sar:'#76ff03',cci_trend:'#ff6e40',regime_router:'#00fff7'
};
// Add info buttons to chips and handle click-to-show tooltips
let _openTip=null;
document.querySelectorAll('.chip').forEach(chip=>{
  const tip=chip.querySelector('.chip-tip');
  if(!tip)return;
  // Insert info button before the tooltip
  const btn=document.createElement('span');
  btn.className='chip-info';
  btn.textContent='i';
  btn.addEventListener('click',e=>{
    e.stopPropagation();
    if(_openTip===tip){tip.classList.remove('tip-visible');_openTip=null;return}
    if(_openTip)_openTip.classList.remove('tip-visible');
    const r=chip.getBoundingClientRect();
    let left=r.left+r.width/2-220;
    if(left<8)left=8;
    if(left+440>window.innerWidth-8)left=window.innerWidth-448;
    tip.style.left=left+'px';
    tip.style.top=(r.bottom+8)+'px';
    tip.classList.add('tip-visible');
    _openTip=tip;
  });
  chip.insertBefore(btn,tip);
});
// Close tooltip when clicking outside
function closeTrendFlipAggregate(){
  const pop=document.getElementById('trend-flip-aggregate-popover');
  const btn=document.getElementById('trend-flip-aggregate-btn');
  pop.classList.remove('open');
  btn.classList.remove('open');
}
document.addEventListener('click',()=>{
  if(_openTip){_openTip.classList.remove('tip-visible');_openTip=null}
  closeTrendFlipAggregate();
});

const activeSignals=new Set();
const flipOrder=['supertrend','ema_crossover','macd','ma_confirm','donchian','adx_trend','bb_breakout','keltner','parabolic_sar','cci_trend','regime_router','ribbon'];
const flipLabels={supertrend:'ST',ema_crossover:'EMA',macd:'MACD',ma_confirm:'MA',donchian:'Donch',adx_trend:'ADX',bb_breakout:'BB',keltner:'Kelt',parabolic_sar:'SAR',cci_trend:'CCI',regime_router:'RR',ribbon:'Ribbon'};
const flipNames={supertrend:'Supertrend',ema_crossover:'EMA Cross',macd:'MACD',ma_confirm:'MA Confirm',donchian:'Donchian',adx_trend:'ADX',bb_breakout:'BB Breakout',keltner:'Keltner',parabolic_sar:'Parabolic SAR',cci_trend:'CCI',regime_router:'Regime Router',ribbon:'Trend Ribbon'};
function daysSinceNumber(f){
  if(!f?.date)return null;
  return Math.max(0,Math.floor((Date.now()-new Date(f.date+'T00:00:00').getTime())/864e5));
}
function flipDateLabel(f){
  return f?.date||'';
}
function daysSinceHtml(f){
  const diff=daysSinceNumber(f);
  if(diff==null)return'<span style="opacity:0.4">--</span>';
  const c=f.dir==='bullish'?'var(--green)':'var(--red)';
  return`<span style="color:${c}">${diff}d <span style="opacity:0.75">${flipDateLabel(f)}</span></span>`;
}
function flipToneMeta(bullish,bearish){
  const total=bullish+bearish;
  if(!total)return{label:'No data',tone:'mixed',consensusPct:null,score:0};
  const bullPct=Math.round(bullish/total*100);
  const consensusPct=Math.round(Math.max(bullish,bearish)/total*100);
  const score=Math.round(((bullish-bearish)/total)*100);
  if(bullPct>=70)return{label:'Strong Bullish',tone:'bullish',consensusPct,score};
  if(bullPct>=55)return{label:'Bullish Tilt',tone:'bullish',consensusPct,score};
  if(bullPct<=30)return{label:'Strong Bearish',tone:'bearish',consensusPct,score};
  if(bullPct<=45)return{label:'Bearish Tilt',tone:'bearish',consensusPct,score};
  return{label:'Mixed',tone:'mixed',consensusPct,score};
}
function frameSummary(frameFlips,keys){
  const valid=keys.map(k=>frameFlips?.[k]).filter(f=>f?.dir);
  const bullish=valid.filter(f=>f.dir==='bullish').length;
  const bearish=valid.filter(f=>f.dir==='bearish').length;
  const consensusDir=bullish>=bearish?'bullish':'bearish';
  const ages=valid.filter(f=>f.dir===consensusDir).map(daysSinceNumber).filter(d=>d!=null);
  return{
    bullish,
    bearish,
    total:bullish+bearish,
    avgAge:ages.length?Math.round(ages.reduce((sum,d)=>sum+d,0)/ages.length):null,
    meta:flipToneMeta(bullish,bearish),
  };
}
function aggregateRows(flips,keys){
  return keys.map(key=>{
    const daily=flips.daily?.[key]||{};
    const weekly=flips.weekly?.[key]||{};
    const bullScore=(daily.dir==='bullish'?1:daily.dir==='bearish'?-1:0)+(weekly.dir==='bullish'?1:weekly.dir==='bearish'?-1:0);
    const freshness=Math.min(daysSinceNumber(daily)??99999,daysSinceNumber(weekly)??99999);
    return{key,daily,weekly,bullScore,freshness};
  }).sort((a,b)=>{
    if(b.bullScore!==a.bullScore)return b.bullScore-a.bullScore;
    if(a.freshness!==b.freshness)return a.freshness-b.freshness;
    return (flipNames[a.key]||a.key).localeCompare(flipNames[b.key]||b.key);
  });
}
function biasText(row){
  const d=row.daily?.dir,w=row.weekly?.dir;
  if(d&&w&&d===w)return d==='bullish'?{label:'Bull both',cls:'bull'}:{label:'Bear both',cls:'bear'};
  if(d&&w&&d!==w)return{label:'Split',cls:'mixed'};
  if(d==='bullish'||w==='bullish')return{label:'Bull lean',cls:'bull'};
  if(d==='bearish'||w==='bearish')return{label:'Bear lean',cls:'bear'};
  return{label:'No data',cls:'mixed'};
}
function flipCellHtml(f){
  if(!f?.dir)return'<span class="tf-cell tf-cell-empty">--</span>';
  const tone=f.dir==='bullish'?'bull':'bear';
  return`<span class="tf-cell tf-cell-${tone}"><span>${f.dir==='bullish'?'Bull':'Bear'}</span><span>${daysSinceNumber(f)}d</span><span class="tf-flip-date">${flipDateLabel(f)}</span></span>`;
}
function frameCardHtml(title,summary){
  const scoreCls=summary.meta.tone==='bullish'?'bull':summary.meta.tone==='bearish'?'bear':'';
  const bullPct=summary.meta.consensusPct==null?'--':`${summary.meta.consensusPct}%`;
  const score=summary.total?`${summary.meta.score>0?'+':''}${summary.meta.score}`:'--';
  const pillCls=summary.meta.tone==='bullish'?'tf-pill-bull':summary.meta.tone==='bearish'?'tf-pill-bear':'tf-pill-mixed';
  return`<div class="tf-agg-card">
    <div class="tf-agg-card-top">
      <div class="tf-agg-card-title">${title}</div>
      <span class="tf-pill ${pillCls}">${summary.meta.label}</span>
    </div>
    <div class="tf-agg-card-score ${scoreCls}">${bullPct}</div>
    <div class="tf-agg-stats">
      <span><strong>${summary.bullish}</strong> bull</span>
      <span><strong>${summary.bearish}</strong> bear</span>
      <span><strong>${summary.avgAge==null?'--':summary.avgAge+'d'}</strong> avg flip age</span>
    </div>
    <div class="tf-agg-note">Net score ${score} across ${summary.total||0} signals.</div>
  </div>`;
}
function getSelectedFlipKeys(){
  const keys=[...activeSignals];
  if(legendItems.find(i=>i.key==='ribbon')?.on)keys.push('ribbon');
  return[...new Set(keys)];
}
function getAllFlipKeys(flips){
  const found=new Set([...Object.keys(flips?.daily||{}),...Object.keys(flips?.weekly||{})]);
  const ordered=flipOrder.filter(k=>found.has(k));
  return ordered.concat([...found].filter(k=>!ordered.includes(k)).sort());
}
function renderTrendFlipAggregate(){
  const btn=document.getElementById('trend-flip-aggregate-btn');
  const state=document.getElementById('trend-flip-aggregate-state');
  const pop=document.getElementById('trend-flip-aggregate-popover');
  const flips=lastData?.trend_flips;
  const keys=getAllFlipKeys(flips);
  if(!keys.length){
    btn.style.display='none';
    closeTrendFlipAggregate();
    return;
  }
  const daily=frameSummary(flips.daily,keys);
  const weekly=frameSummary(flips.weekly,keys);
  const overall=flipToneMeta(daily.bullish+weekly.bullish,daily.bearish+weekly.bearish);
  const rows=aggregateRows(flips,keys);
  const alignedBull=rows.filter(r=>r.daily?.dir==='bullish'&&r.weekly?.dir==='bullish').length;
  const alignedBear=rows.filter(r=>r.daily?.dir==='bearish'&&r.weekly?.dir==='bearish').length;
  const split=rows.filter(r=>r.daily?.dir&&r.weekly?.dir&&r.daily.dir!==r.weekly.dir).length;
  btn.style.display='inline-flex';
  btn.dataset.tone=overall.tone;
  state.textContent=overall.label;
  btn.title=`${overall.label} • Daily ${daily.bullish}/${daily.total||0} bullish • Weekly ${weekly.bullish}/${weekly.total||0} bullish`;
  pop.innerHTML=`<div class="tf-agg-head">
    <div>
      <h4>Signal Pulse</h4>
      <div class="tf-agg-sub">Daily and weekly flip age across all indicators, sorted from bullish alignment to bearish alignment.</div>
    </div>
    <div class="tf-pills">
      <span class="tf-pill ${overall.tone==='bullish'?'tf-pill-bull':overall.tone==='bearish'?'tf-pill-bear':'tf-pill-mixed'}">${overall.label}</span>
      <span class="tf-pill tf-pill-mixed">${keys.length} indicators</span>
    </div>
  </div>
  <div class="tf-agg-grid">
    ${frameCardHtml('Daily Consensus',daily)}
    ${frameCardHtml('Weekly Consensus',weekly)}
  </div>
  <div class="tf-pills">
    <span class="tf-pill tf-pill-bull">Bull both ${alignedBull}</span>
    <span class="tf-pill tf-pill-bear">Bear both ${alignedBear}</span>
    <span class="tf-pill tf-pill-mixed">Split ${split}</span>
  </div>
  <div class="tf-agg-table">
    <div class="tf-agg-tr th">
      <div>Indicator</div>
      <div>Daily</div>
      <div>Weekly</div>
      <div>Bias</div>
    </div>
    ${rows.map(row=>{
      const bias=biasText(row);
      return`<div class="tf-agg-tr">
        <div class="tf-agg-ind">
          <span class="tf-ind-dot" style="background:${signalColors[row.key]||'#ffd644'}"></span>
          <span class="tf-agg-ind-name">${flipNames[row.key]||row.key}</span>
        </div>
        <div>${flipCellHtml(row.daily)}</div>
        <div>${flipCellHtml(row.weekly)}</div>
        <div><span class="tf-bias tf-bias-${bias.cls}">${bias.label}</span></div>
      </div>`;
    }).join('')}
  </div>`;
}
function toggleTrendFlipAggregate(e){
  e.stopPropagation();
  const pop=document.getElementById('trend-flip-aggregate-popover');
  const btn=document.getElementById('trend-flip-aggregate-btn');
  if(pop.classList.contains('open')){
    closeTrendFlipAggregate();
    return;
  }
  renderTrendFlipAggregate();
  pop.classList.add('open');
  btn.classList.add('open');
}
function updateFlipInfo(){
  const controls=document.getElementById('trend-flip-controls');
  const el=document.getElementById('trend-flip-info');
  if(!lastData?.trend_flips){
    controls.style.display='none';
    closeTrendFlipAggregate();
    return;
  }
  const keys=getSelectedFlipKeys();
  if(!keys.length){
    controls.style.display='none';
    closeTrendFlipAggregate();
    return;
  }
  const flips=lastData.trend_flips;
  let html='';
  keys.forEach(k=>{
    const lbl=flipLabels[k]||k;
    const d=flips.daily?.[k],w=flips.weekly?.[k];
    const clr=signalColors[k]||'#ffd644';
    html+=`<span style="border-left:2px solid ${clr};padding-left:4px;margin-right:2px"><span style="font-weight:600">${lbl}</span> D:${daysSinceHtml(d)} W:${daysSinceHtml(w)}</span>`;
  });
  el.innerHTML=html;
  controls.style.display='inline-flex';
  el.style.display='inline-flex';
  renderTrendFlipAggregate();
}
function toggleSignal(el,name){
  el.classList.toggle('on');
  if(el.classList.contains('on'))activeSignals.add(name);else activeSignals.delete(name);
  updateMarkers();
  updateOverlaysFromSignals();
  updateFlipInfo();
  pushURLParams();
}
let activeBacktestStrat=null;
function updateMarkers(){
  if(!lastData?.strategies){candleSeries.setMarkers([]);return}
  const all=[];
  const shown=new Set(activeSignals);
  // Only include the backtest panel's selected strategy when panel is open
  if(btOpen&&activeBacktestStrat) shown.add(activeBacktestStrat);
  shown.forEach(name=>{
    const s=lastData.strategies[name];if(!s)return;
    const c=signalColors[name]||'#5b7fff';
    s.trades.forEach(t=>{
      all.push({time:Math.floor(new Date(t.entry_date).getTime()/1000),position:'belowBar',color:c,shape:'arrowUp',text:'B',size:2});
      all.push({time:Math.floor(new Date(t.exit_date).getTime()/1000),position:'aboveBar',color:c,shape:'arrowDown',text:'S',size:2});
    });
  });
  all.sort((a,b)=>a.time-b.time);
  candleSeries.setMarkers(all);
}
