// === SIGNAL TOGGLES ===
const signalColors={
  cb50:'#00d4ff',cb150:'#26c6da',sma_10_100:'#66bb6a',sma_10_200:'#42a5f5',
  ema_trend:'#ab47bc',yearly_ma:'#ef5350',
  supertrend:'#5b7fff',ema_crossover:'#ff9800',macd:'#b050ff',
  donchian:'#ffd644',bb_breakout:'#ff5274',
  keltner:'#e040fb',parabolic_sar:'#76ff03',cci_trend:'#ff6e40',orb_breakout:'#ffab40',
  ribbon:'#7f98ff',
  corpus_trend:'#4dd0e1',
  corpus_trend_layered:'#26c6da',
  weekly_core_overlay_v1:'#ffd644',
  ema_9_26:'#ffb74d',
  semis_persist_v1:'#81c784',
  cci_hysteresis:'#ff8a65',
  polymarket:'#8bc34a'
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
const flipOrder=['ribbon','corpus_trend','corpus_trend_layered','weekly_core_overlay_v1','ema_9_26','semis_persist_v1','cci_hysteresis','bb_breakout','ema_crossover','cci_trend','polymarket'];
const flipOrderRank=Object.fromEntries(flipOrder.map((key,idx)=>[key,idx]));
const flipLabels={pulse:'Pulse',ribbon:'Trend',corpus_trend:'Corpus',corpus_trend_layered:'Corpus L',weekly_core_overlay_v1:'Core+Ov',ema_9_26:'EMA9',semis_persist_v1:'Semis',cci_hysteresis:'CCI H',bb_breakout:'BB',ema_crossover:'EMA5',cci_trend:'CCI',polymarket:'Poly'};
const flipNames={ribbon:'Trend-Driven',corpus_trend:'Corpus Trend',corpus_trend_layered:'Corpus Trend Layered',weekly_core_overlay_v1:'Weekly Core + Daily Overlay',ema_9_26:'EMA 9/26 Cross',semis_persist_v1:'Semis Persist v1',cci_hysteresis:'CCI Hysteresis',bb_breakout:'BB Breakout',ema_crossover:'EMA 5/20 Cross',cci_trend:'CCI Trend',polymarket:'Polymarket Skew'};
const flipDateFormatter=new Intl.DateTimeFormat('en-GB',{day:'numeric',month:'short',year:'numeric',timeZone:'UTC'});
let trendPulseMode='equal';
const trendPulseProfiles={
  default:{
    ribbon:24,corpus_trend:18,corpus_trend_layered:14,weekly_core_overlay_v1:12,
    ema_9_26:8,semis_persist_v1:10,cci_hysteresis:14,bb_breakout:8,ema_crossover:7,cci_trend:5,polymarket:0
  },
  crypto:{
    ribbon:22,corpus_trend:16,corpus_trend_layered:12,weekly_core_overlay_v1:14,
    ema_9_26:6,semis_persist_v1:5,cci_hysteresis:12,bb_breakout:7,ema_crossover:7,cci_trend:5,polymarket:12
  },
  semis:{
    ribbon:20,corpus_trend:16,corpus_trend_layered:12,weekly_core_overlay_v1:10,
    ema_9_26:8,semis_persist_v1:18,cci_hysteresis:10,bb_breakout:8,ema_crossover:7,cci_trend:5,polymarket:0
  }
};
const trendPulseCategoryLabels={
  indexes:'Index',treasuries:'Rates',semis:'Semis',tech:'Tech',software:'Software',
  etfs:'ETF',crypto:'Crypto',misc:'General',default:'General'
};
const trendPulseMath=globalThis.trendPulseHelpers;
const chartSignalStrategyPreferenceHelpers=globalThis.strategyPreferenceHelpers;
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
function flipToneMeta(bullish,bearish,possibleTotal){
  return trendPulseMath.flipToneMeta(bullish,bearish,possibleTotal);
}
function trendPulseCategory(){
  const ticker=document.getElementById('ticker')?.value?.toUpperCase()||'';
  if(chartSignalStrategyPreferenceHelpers?.tickerCategory&&ticker)return chartSignalStrategyPreferenceHelpers.tickerCategory(ticker);
  if(typeof wlTickerCategory==='function'&&ticker)return wlTickerCategory(ticker);
  return 'default';
}
function preferredStrategyMeta(ticker,tradeSetup){
  const sharedPreferred=tradeSetup?.shared?.preferred_strategy;
  if(sharedPreferred?.strategy_key){
    return{
      category:sharedPreferred.category,
      categoryLabel:sharedPreferred.category_label,
      strategyKey:sharedPreferred.strategy_key,
      strategyLabel:sharedPreferred.strategy_label,
    };
  }
  if(chartSignalStrategyPreferenceHelpers?.preferredStrategyMetaForTicker){
    return chartSignalStrategyPreferenceHelpers.preferredStrategyMetaForTicker(ticker);
  }
  return{
    category:trendPulseCategory(),
    categoryLabel:trendPulseCategoryLabels[trendPulseCategory()]||'General',
    strategyKey:'ribbon',
    strategyLabel:'Trend-Driven',
  };
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
  return trendPulseMath.frameSummary(frameFlips,keys,weights,daysSinceNumber);
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
  const coverage=summary.meta.coveragePct==null?'--':`${summary.meta.coveragePct}%`;
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
      <span><strong>${coverage}</strong> coverage</span>
      <span><strong>${summary.avgAge==null?'--':summary.avgAge+'d'}</strong> avg regime age</span>
    </div>
    <div class="tf-agg-note">Net score ${score} ${mode==='weighted'?'after coverage-adjusted weighting.':`after coverage adjustment across ${summary.possibleTotal||0} tracked signals.`}</div>
  </div>`;
}
function getSelectedFlipKeys(){
  const available=getAllFlipKeys(lastData?.trend_flips);
  const availableSet=new Set(available);
  const keys=[...activeSignals].filter(key=>availableSet.has(key));
  if(legendItems.find(i=>i.key==='ribbon')?.on)keys.push('ribbon');
  const found=new Set(keys.filter(key=>availableSet.has(key)));
  const ordered=flipOrder.filter(key=>found.has(key));
  const selected=ordered.concat([...found].filter(key=>!ordered.includes(key)).sort());
  return selected.length?selected:available;
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
    return `Trend-Driven is pinned first and carries the largest weight. Remaining weights reflect the active ${trendPulseCategoryLabels[category]||'General'} strategy mix, then rows sort by weighted bullish/bearish alignment and regime age.`;
  }
  return 'Trend-Driven is pinned first. Every tracked strategy contributes one vote, then rows sort by bullish/bearish alignment and regime age.';
}
function setTrendPulseMode(e,mode){
  e.stopPropagation();
  trendPulseMode=mode==='weighted'?'weighted':'equal';
  renderTrendFlipAggregate();
}
function tradeSetupScoreCardHtml(title,frame,setup){
  if(!setup||setup.score==null)return '';
  const scoreCls=setup.side==='bullish'?'bull':setup.side==='bearish'?'bear':'';
  const pillCls=setup.side==='bullish'?'tf-pill-bull':setup.side==='bearish'?'tf-pill-bear':'tf-pill-mixed';
  const score=`${setup.score>0?'+':''}${setup.score}`;
  return `<div class="tf-agg-card tf-agg-card-clickable" onclick="event.stopPropagation();openTradeScoreDetails('${frame}')">
    <div class="tf-agg-card-top">
      <div class="tf-agg-card-title">${title}</div>
      <span class="tf-pill ${pillCls}">${setup.side||'mixed'}</span>
    </div>
    <div class="tf-agg-card-score ${scoreCls}">${score}</div>
    <div class="tf-agg-stats">
      <span><strong>${setup.trend_bias>0?'+':''}${setup.trend_bias??'--'}</strong> trend bias</span>
      <span><strong>${Math.round(setup.level_component??0)}</strong> level</span>
      <span><strong>${Math.round(setup.ma_component??0)}</strong> MA</span>
      <span><strong>${Math.round(setup.room_component??0)}</strong> room</span>
    </div>
    <div class="tf-agg-note">Trade Score combines trend bias with support/resistance, nearest moving average, and upside/downside room.</div>
  </div>`;
}
function tradeSetupDistanceHtml(label,entry){
  if(!entry)return `<span class="tf-pill tf-pill-mixed">${label} --</span>`;
  const pct=entry.distance_pct==null?'--':`${entry.distance_pct}%`;
  const atr=entry.distance_atr==null?'--':`${entry.distance_atr} ATR`;
  const pos=entry.position||'at';
  const price=entry.price==null?'--':entry.price;
  return `<span class="tf-pill tf-pill-mixed">${label} ${price} · ${pct} ${pos} · ${atr}</span>`;
}
function tradeSetupSharedHtml(tradeSetup){
  const shared=tradeSetup?.shared;
  if(!shared||(!shared.nearest_support&&!shared.nearest_resistance&&!shared.nearest_ma))return '';
  const nearestMa=shared.nearest_ma;
  const maLabel=nearestMa
    ?`Nearest MA ${nearestMa.label} ${nearestMa.price} · ${nearestMa.distance_pct}% ${nearestMa.position} · ${nearestMa.distance_atr==null?'--':nearestMa.distance_atr+' ATR'}`
    :'Nearest MA --';
  const upside=shared.upside_room_pct==null?'--':`${shared.upside_room_pct}% / ${shared.upside_room_atr==null?'--':shared.upside_room_atr+' ATR'}`;
  const downside=shared.downside_room_pct==null?'--':`${shared.downside_room_pct}% / ${shared.downside_room_atr==null?'--':shared.downside_room_atr+' ATR'}`;
  const confluence=[shared.confluence?.bullish,shared.confluence?.bearish].filter(Boolean);
  return `<div class="tf-agg-card tf-setup-card">
    <div class="tf-agg-card-top">
      <div class="tf-agg-card-title">Structure</div>
      <span class="tf-pill tf-pill-accent">Price ${shared.price??'--'}</span>
    </div>
    <div class="tf-pills tf-setup-pills">
      ${tradeSetupDistanceHtml('Support',shared.nearest_support)}
      ${tradeSetupDistanceHtml('Resistance',shared.nearest_resistance)}
      <span class="tf-pill tf-pill-mixed">${maLabel}</span>
      <span class="tf-pill tf-pill-mixed">Upside room ${upside}</span>
      <span class="tf-pill tf-pill-mixed">Downside room ${downside}</span>
      ${confluence.map(label=>`<span class="tf-pill tf-pill-accent">${label}</span>`).join('')}
    </div>
  </div>`;
}
function fallbackFlipKey(frameFlips){
  const found=new Set(Object.keys(frameFlips||{}));
  return flipOrder.find(key=>found.has(key))||[...found].sort()[0]||null;
}
function preferredFlipForFrame(frameFlips,preferred){
  const preferredKey=preferred?.strategyKey||null;
  const preferredFlip=preferredKey?(frameFlips?.[preferredKey]||null):null;
  const preferredDir=preferredFlip?.dir||preferredFlip?.current_dir||null;
  if(preferredDir){
    return{
      flip:preferredFlip,
      strategyKey:preferredKey,
      strategyLabel:preferred.strategyLabel,
      usingFallback:false,
    };
  }
  const fallbackKey=fallbackFlipKey(frameFlips);
  if(!fallbackKey){
    return{
      flip:{},
      strategyKey:preferredKey,
      strategyLabel:preferred?.strategyLabel||'Preferred strategy',
      usingFallback:false,
    };
  }
  return{
    flip:frameFlips?.[fallbackKey]||{},
    strategyKey:fallbackKey,
    strategyLabel:flipNames[fallbackKey]||flipLabels[fallbackKey]||fallbackKey,
    usingFallback:true,
  };
}
function preferredPulseTone(dailyFlip,weeklyFlip){
  const dailyDir=dailyFlip?.flip?.dir||dailyFlip?.flip?.current_dir||null;
  const weeklyDir=weeklyFlip?.flip?.dir||weeklyFlip?.flip?.current_dir||null;
  const bullish=(dailyDir==='bullish'?1:0)+(weeklyDir==='bullish'?1:0);
  const bearish=(dailyDir==='bearish'?1:0)+(weeklyDir==='bearish'?1:0);
  if(!bullish&&!bearish)return{label:'No data',tone:'mixed'};
  if(bullish===2)return{label:'Bullish',tone:'bullish'};
  if(bearish===2)return{label:'Bearish',tone:'bearish'};
  if(bullish>bearish)return{label:'Bullish Tilt',tone:'bullish'};
  if(bearish>bullish)return{label:'Bearish Tilt',tone:'bearish'};
  return{label:'Split',tone:'mixed'};
}
function preferredStrategyCardHtml(title,flip,setup,preferred){
  const resolvedFlip=flip?.flip||{};
  const dir=resolvedFlip?.dir||resolvedFlip?.current_dir||null;
  const tone=dir==='bullish'?'bullish':dir==='bearish'?'bearish':'mixed';
  const pillCls=tone==='bullish'?'tf-pill-bull':tone==='bearish'?'tf-pill-bear':'tf-pill-mixed';
  const score=setup?.score==null?'--':`${setup.score>0?'+':''}${setup.score}`;
  const age=daysSinceNumber(resolvedFlip);
  const startDate=flipDateLabel(resolvedFlip)||'--';
  const sourceLabel=flip?.strategyLabel||preferred.strategyLabel;
  const sourcePrefix=flip?.usingFallback?`${sourceLabel} fallback`:`${sourceLabel}`;
  const source=setup?.trend_source_label||`Preferred strategy bias (${preferred.strategyLabel})`;
  return `<div class="tf-agg-card">
    <div class="tf-agg-card-top">
      <div class="tf-agg-card-title">${title}</div>
      <span class="tf-pill ${pillCls}">${dir?dir.charAt(0).toUpperCase()+dir.slice(1):'No data'}</span>
    </div>
    <div class="tf-agg-card-score ${tone==='bullish'?'bull':tone==='bearish'?'bear':''}">${score}</div>
    <div class="tf-agg-stats">
      <span><strong>${sourcePrefix}</strong> source</span>
      <span><strong>${age==null?'--':age+'d'}</strong> regime age</span>
      <span><strong>${startDate}</strong> since</span>
      <span><strong>${setup?.trend_bias??'--'}</strong> bias</span>
    </div>
    <div class="tf-agg-note">${source} sets the direction first, then the trade score layers in structure, moving averages, and room.</div>
  </div>`;
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
  const tradeSetup=lastData?.trade_setup||{};
  const ticker=document.getElementById('ticker')?.value?.toUpperCase()||'';
  const preferred=preferredStrategyMeta(ticker,tradeSetup);
  const dailyFlip=preferredFlipForFrame(flips.daily,preferred);
  const weeklyFlip=preferredFlipForFrame(flips.weekly,preferred);
  const overall=preferredPulseTone(dailyFlip,weeklyFlip);
  btn.style.display='inline-flex';
  btn.dataset.tone=overall.tone;
  state.textContent=`${preferred.strategyLabel} · ${overall.label}`;
  btn.title=`${preferred.strategyLabel} • Daily ${dailyFlip?.flip?.dir||dailyFlip?.flip?.current_dir||'no data'} • Weekly ${weeklyFlip?.flip?.dir||weeklyFlip?.flip?.current_dir||'no data'}`;
  pop.innerHTML=`<div class="tf-agg-head">
    <div>
      <h4>Signal Pulse</h4>
      <div class="tf-agg-sub">Class-aware pulse for this symbol. ${preferred.categoryLabel} names default to ${preferred.strategyLabel}, and the daily/weekly cards below are driven from that preferred strategy first.</div>
    </div>
    <div class="tf-pills">
      <span class="tf-pill ${overall.tone==='bullish'?'tf-pill-bull':overall.tone==='bearish'?'tf-pill-bear':'tf-pill-mixed'}">${overall.label}</span>
      <span class="tf-pill tf-pill-accent">${preferred.categoryLabel||trendPulseCategoryLabels[preferred.category]||'General'}</span>
      <span class="tf-pill tf-pill-mixed">${preferred.strategyLabel}</span>
    </div>
  </div>
  <div class="tf-agg-grid">
    ${preferredStrategyCardHtml('Daily Preferred Signal',dailyFlip,tradeSetup.daily,preferred)}
    ${preferredStrategyCardHtml('Weekly Preferred Signal',weeklyFlip,tradeSetup.weekly,preferred)}
  </div>
  ${tradeSetupSharedHtml(tradeSetup)}`;
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
function syncInitialSignalChipState(){
  document.querySelectorAll('.overlays .chip[onclick^="toggleSignal"]').forEach(el=>{
    const onclick=el.getAttribute('onclick')||'';
    const match=onclick.match(/toggleSignal\(this,'([^']+)'\)/);
    if(!match)return;
    if(el.classList.contains('on'))activeSignals.add(match[1]);
  });
}
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
