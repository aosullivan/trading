// === SIGNAL TOGGLES ===
const signalColors={
  supertrend:'#5b7fff',ema_crossover:'#ff9800',macd:'#b050ff',
  ma_confirm:'#00d4ff',donchian:'#ffd644',adx_trend:'#00e68a',bb_breakout:'#ff5274',
  keltner:'#e040fb',parabolic_sar:'#76ff03',cci_trend:'#ff6e40',regime_router:'#00fff7',
  ribbon:'#7f98ff'
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
function openTrendFlipAggregate(){
  renderTrendFlipAggregate();
  const pop=document.getElementById('trend-flip-aggregate-popover');
  const btn=document.getElementById('trend-flip-aggregate-btn');
  if(btn.style.display==='none')return;
  pop.classList.add('open');
  btn.classList.add('open');
}
document.addEventListener('click',()=>{
  if(_openTip){_openTip.classList.remove('tip-visible');_openTip=null}
  closeTrendFlipAggregate();
});

const activeSignals=new Set();
const flipOrder=['ribbon','ma_confirm','supertrend','ema_crossover','macd','donchian','adx_trend','bb_breakout','keltner','parabolic_sar','cci_trend','regime_router'];
const flipOrderRank=Object.fromEntries(flipOrder.map((key,idx)=>[key,idx]));
const flipLabels={pulse:'Pulse',supertrend:'ST',ema_crossover:'EMA',macd:'MACD',ma_confirm:'MA',donchian:'Donch',adx_trend:'ADX',bb_breakout:'BB',keltner:'Kelt',parabolic_sar:'SAR',cci_trend:'CCI',regime_router:'RR',ribbon:'Trend'};
const flipNames={supertrend:'Supertrend',ema_crossover:'EMA Cross',macd:'MACD',ma_confirm:'MA Confirm',donchian:'Donchian',adx_trend:'ADX',bb_breakout:'BB Breakout',keltner:'Keltner',parabolic_sar:'Parabolic SAR',cci_trend:'CCI',regime_router:'Regime Router',ribbon:'Trend-Driven'};
const flipDateFormatter=new Intl.DateTimeFormat('en-GB',{day:'numeric',month:'short',year:'numeric',timeZone:'UTC'});
let trendPulseMode='equal';
const trendPulseProfiles={
  default:{
    ribbon:24,ma_confirm:16,supertrend:12,ema_crossover:12,macd:10,donchian:8,
    adx_trend:7,bb_breakout:5,keltner:4,parabolic_sar:3,cci_trend:2,regime_router:1
  },
  tech:{
    ribbon:24,ma_confirm:15,supertrend:12,ema_crossover:13,macd:12,donchian:8,
    adx_trend:7,bb_breakout:4,keltner:3,parabolic_sar:3,cci_trend:1,regime_router:1
  },
  semis:{
    ribbon:25,ma_confirm:14,supertrend:12,ema_crossover:12,macd:12,donchian:10,
    adx_trend:8,bb_breakout:3,keltner:2,parabolic_sar:3,cci_trend:1,regime_router:1
  },
  software:{
    ribbon:24,ma_confirm:15,supertrend:11,ema_crossover:13,macd:12,donchian:7,
    adx_trend:7,bb_breakout:5,keltner:3,parabolic_sar:3,cci_trend:2,regime_router:1
  },
  crypto:{
    ribbon:26,ma_confirm:15,supertrend:13,ema_crossover:12,macd:10,donchian:10,
    adx_trend:8,bb_breakout:4,keltner:3,parabolic_sar:2,cci_trend:1,regime_router:1
  },
  indexes:{
    ribbon:22,ma_confirm:18,supertrend:10,ema_crossover:10,macd:8,donchian:6,
    adx_trend:7,bb_breakout:8,keltner:4,parabolic_sar:2,cci_trend:3,regime_router:3
  },
  etfs:{
    ribbon:22,ma_confirm:18,supertrend:10,ema_crossover:10,macd:8,donchian:6,
    adx_trend:7,bb_breakout:8,keltner:4,parabolic_sar:2,cci_trend:3,regime_router:3
  },
  treasuries:{
    ribbon:24,ma_confirm:20,supertrend:9,ema_crossover:8,macd:7,donchian:5,
    adx_trend:9,bb_breakout:7,keltner:4,parabolic_sar:2,cci_trend:2,regime_router:4
  },
  misc:{
    ribbon:24,ma_confirm:15,supertrend:11,ema_crossover:11,macd:10,donchian:8,
    adx_trend:7,bb_breakout:5,keltner:4,parabolic_sar:3,cci_trend:2,regime_router:2
  }
};
const trendPulseCategoryLabels={
  indexes:'Index',treasuries:'Rates',semis:'Semis',tech:'Tech',software:'Software',
  etfs:'ETF',crypto:'Crypto',misc:'General',default:'General'
};
function daysSinceNumber(f){
  if(!f?.date)return null;
  return Math.max(0,Math.floor((Date.now()-new Date(f.date+'T00:00:00').getTime())/864e5));
}
function flipDateLabel(f){
  if(!f?.date)return'';
  const [year,month,day]=f.date.split('-').map(Number);
  if(!year||!month||!day)return f.date;
  return flipDateFormatter.format(new Date(Date.UTC(year,month-1,day)));
}
function daysSinceHtml(f){
  const diff=daysSinceNumber(f);
  if(diff==null)return'<span class="trend-flip-empty">--</span>';
  const tone=f.dir==='bullish'?'bull':'bear';
  return`<span class="trend-flip-value trend-flip-value-${tone}"><span class="trend-flip-age">${diff}d</span><span class="trend-flip-date">${flipDateLabel(f)}</span></span>`;
}
function flipInfoRowHtml(frame,f){
  return`<span class="trend-flip-row"><span class="trend-flip-frame">${frame}</span>${daysSinceHtml(f)}</span>`;
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
function trendPulseCategory(){
  const ticker=document.getElementById('ticker')?.value?.toUpperCase()||'';
  if(typeof wlTickerCategory==='function'&&ticker)return wlTickerCategory(ticker);
  return 'default';
}
function trendPulseWeights(keys,mode,category){
  if(mode!=='weighted')return Object.fromEntries(keys.map(key=>[key,1]));
  const profile=trendPulseProfiles[category||trendPulseCategory()]||trendPulseProfiles.default;
  const rawTotal=keys.reduce((sum,key)=>sum+(profile[key]||trendPulseProfiles.default[key]||1),0)||1;
  return Object.fromEntries(keys.map(key=>[
    key,
    (profile[key]||trendPulseProfiles.default[key]||1)/rawTotal
  ]));
}
function formatPulseMetric(value,mode,total){
  if(mode==='weighted')return `${Math.round((total?value/total:0)*100)}%`;
  return `${Math.round(value)}`;
}
function formatPulseWeight(weight){
  return `${(weight*100).toFixed(1)}%`;
}
function frameSummary(frameFlips,keys,weights){
  const valid=keys
    .map(k=>({flip:frameFlips?.[k],weight:weights[k]||1}))
    .filter(item=>item.flip?.dir);
  const bullish=valid
    .filter(item=>item.flip.dir==='bullish')
    .reduce((sum,item)=>sum+item.weight,0);
  const bearish=valid
    .filter(item=>item.flip.dir==='bearish')
    .reduce((sum,item)=>sum+item.weight,0);
  const consensusDir=bullish>=bearish?'bullish':'bearish';
  const ages=valid
    .filter(item=>item.flip.dir===consensusDir)
    .map(item=>({age:daysSinceNumber(item.flip),weight:item.weight}))
    .filter(item=>item.age!=null);
  const ageWeight=ages.reduce((sum,item)=>sum+item.weight,0);
  const avgAge=ages.length?Math.round(ages.reduce((sum,item)=>sum+item.age*item.weight,0)/(ageWeight||1)):null;
  const avgDate=avgAge==null?null:new Date(Date.now()-avgAge*864e5).toISOString().slice(0,10);
  return{
    bullish,
    bearish,
    total:bullish+bearish,
    avgAge,
    avgDate,
    meta:flipToneMeta(bullish,bearish),
  };
}
function aggregateRows(flips,keys,weights){
  return keys.map(key=>{
    const daily=flips.daily?.[key]||{};
    const weekly=flips.weekly?.[key]||{};
    const weight=weights[key]||1;
    const bullScore=weight*((daily.dir==='bullish'?1:daily.dir==='bearish'?-1:0)+(weekly.dir==='bullish'?1:weekly.dir==='bearish'?-1:0));
    const freshness=Math.min(daysSinceNumber(daily)??99999,daysSinceNumber(weekly)??99999);
    return{key,daily,weekly,bullScore,freshness,weight};
  }).sort((a,b)=>{
    if(a.key==='ribbon'&&b.key!=='ribbon')return-1;
    if(b.key==='ribbon'&&a.key!=='ribbon')return 1;
    if(b.bullScore!==a.bullScore)return b.bullScore-a.bullScore;
    if(a.freshness!==b.freshness)return a.freshness-b.freshness;
    const orderDelta=(flipOrderRank[a.key]??999)-(flipOrderRank[b.key]??999);
    if(orderDelta!==0)return orderDelta;
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
function frameCardHtml(title,summary,mode){
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
      <span><strong>${formatPulseMetric(summary.bullish,mode,summary.total)}</strong> bull</span>
      <span><strong>${formatPulseMetric(summary.bearish,mode,summary.total)}</strong> bear</span>
      <span><strong>${summary.avgAge==null?'--':summary.avgAge+'d'}</strong> avg flip age</span>
    </div>
    <div class="tf-agg-note">Net score ${score} ${mode==='weighted'?'from weighted signal share.':`across ${summary.total||0} signals.`}</div>
  </div>`;
}
function getSelectedFlipKeys(){
  const keys=[...activeSignals];
  if(legendItems.find(i=>i.key==='ribbon')?.on)keys.push('ribbon');
  const found=new Set(keys);
  const ordered=flipOrder.filter(key=>found.has(key));
  return ordered.concat([...found].filter(key=>!ordered.includes(key)).sort());
}
function getAllFlipKeys(flips){
  const found=new Set([...Object.keys(flips?.daily||{}),...Object.keys(flips?.weekly||{})]);
  const ordered=flipOrder.filter(k=>found.has(k));
  return ordered.concat([...found].filter(k=>!ordered.includes(k)).sort());
}
function trendPulseModeTitle(mode){
  return mode==='weighted'?'Weighted Avg':'Equal-Weighted';
}
function trendPulseDescription(mode,category){
  if(mode==='weighted'){
    return `Trend-Driven is pinned first and carries the largest weight. Remaining weights reflect ${trendPulseCategoryLabels[category]||'General'} popularity, then rows sort by weighted bullish/bearish alignment and flip freshness.`;
  }
  return 'Trend-Driven is pinned first. Every indicator contributes one vote, then rows sort by bullish/bearish alignment and flip freshness.';
}
function setTrendPulseMode(e,mode){
  e.stopPropagation();
  trendPulseMode=mode==='weighted'?'weighted':'equal';
  renderTrendFlipAggregate();
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
  const mode=trendPulseMode==='weighted'?'weighted':'equal';
  const category=trendPulseCategory();
  const weights=trendPulseWeights(keys,mode);
  const daily=frameSummary(flips.daily,keys,weights);
  const weekly=frameSummary(flips.weekly,keys,weights);
  const overall=flipToneMeta(daily.bullish+weekly.bullish,daily.bearish+weekly.bearish);
  const rows=aggregateRows(flips,keys,weights);
  const alignedBull=rows.filter(r=>r.daily?.dir==='bullish'&&r.weekly?.dir==='bullish').length;
  const alignedBear=rows.filter(r=>r.daily?.dir==='bearish'&&r.weekly?.dir==='bearish').length;
  const split=rows.filter(r=>r.daily?.dir&&r.weekly?.dir&&r.daily.dir!==r.weekly.dir).length;
  btn.style.display='inline-flex';
  btn.dataset.tone=overall.tone;
  state.textContent=`${overall.label} · ${trendPulseModeTitle(mode)}`;
  btn.title=`${overall.label} • Daily ${formatPulseMetric(daily.bullish,mode,daily.total)} bullish • Weekly ${formatPulseMetric(weekly.bullish,mode,weekly.total)} bullish`;
  pop.innerHTML=`<div class="tf-agg-head">
    <div>
      <h4>Signal Pulse</h4>
      <div class="tf-agg-sub">${trendPulseDescription(mode,category)}</div>
    </div>
    <div class="tf-pills">
      <span class="tf-pill ${overall.tone==='bullish'?'tf-pill-bull':overall.tone==='bearish'?'tf-pill-bear':'tf-pill-mixed'}">${overall.label}</span>
      <span class="tf-pill tf-pill-mixed">${keys.length} indicators</span>
      <span class="tf-pill tf-pill-accent">${trendPulseCategoryLabels[category]||'General'}</span>
    </div>
  </div>
  <div class="tf-agg-tabs">
    <button type="button" class="tf-agg-tab ${mode==='equal'?'active':''}" onclick="setTrendPulseMode(event,'equal')">Equal-Weighted</button>
    <button type="button" class="tf-agg-tab ${mode==='weighted'?'active':''}" onclick="setTrendPulseMode(event,'weighted')">Weighted Avg</button>
  </div>
  <div class="tf-agg-grid">
    ${frameCardHtml('Daily Consensus',daily,mode)}
    ${frameCardHtml('Weekly Consensus',weekly,mode)}
  </div>
  <div class="tf-pills">
    <span class="tf-pill tf-pill-bull">Bull both ${alignedBull}</span>
    <span class="tf-pill tf-pill-bear">Bear both ${alignedBear}</span>
    <span class="tf-pill tf-pill-mixed">Split ${split}</span>
  </div>
  <div class="tf-agg-table">
    <div class="tf-agg-tr tf-agg-tr-${mode} th">
      <div>Indicator</div>
      <div>Daily</div>
      <div>Weekly</div>
      <div>Bias</div>
      ${mode==='weighted'?'<div>Weight</div>':''}
    </div>
    ${rows.map(row=>{
      const bias=biasText(row);
      return`<div class="tf-agg-tr tf-agg-tr-${mode}">
        <div class="tf-agg-ind">
          <span class="tf-ind-dot" style="background:${signalColors[row.key]||'#ffd644'}"></span>
          <span class="tf-agg-ind-name">${flipNames[row.key]||row.key}</span>
        </div>
        <div>${flipCellHtml(row.daily)}</div>
        <div>${flipCellHtml(row.weekly)}</div>
        <div><span class="tf-bias tf-bias-${bias.cls}">${bias.label}</span></div>
        ${mode==='weighted'?`<div><span class="tf-weight">${formatPulseWeight(row.weight)}</span></div>`:''}
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
  openTrendFlipAggregate();
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
    html+=`<span class="trend-flip-item" style="border-left-color:${clr}"><span class="trend-flip-label">${lbl}</span><span class="trend-flip-lines">${flipInfoRowHtml('D',d)}${flipInfoRowHtml('W',w)}</span></span>`;
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
      if(!t.open){
        all.push({time:Math.floor(new Date(t.exit_date).getTime()/1000),position:'aboveBar',color:c,shape:'arrowDown',text:'S',size:2});
      }
    });
  });
  all.sort((a,b)=>a.time-b.time);
  candleSeries.setMarkers(all);
}
