// Map strategy names to their overlay series
const overlayMap={
  ribbon:[()=>ribbonUpperSeries,()=>ribbonLowerSeries,()=>ribbonCenterSeries],
  supertrend:[()=>stUpSeries,()=>stDownSeries],
  ema_crossover:[()=>ema9Series,()=>ema21Series],
  macd:[()=>macdLineSeries,()=>macdSignalSeries,()=>macdHistSeries],
  donchian:[()=>donchUpperSeries,()=>donchLowerSeries],
  bb_breakout:[()=>bbUpperSeries,()=>bbMidSeries,()=>bbLowerSeries],
  keltner:[()=>keltUpperSeries,()=>keltMidSeries,()=>keltLowerSeries],
  parabolic_sar:[()=>psarBullSeries,()=>psarBearSeries],
  cci_trend:[()=>cciLineSeries],
};

function forEachSeriesRef(seriesRef,cb){
  if(Array.isArray(seriesRef))seriesRef.forEach(s=>s&&cb(s));
  else if(seriesRef)cb(seriesRef);
}

function updateOverlaysFromSignals(){
  // Combine active signal chips + backtest panel strategy
  const active=new Set(activeSignals);
  if(btOpen&&activeBacktestStrat) active.add(activeBacktestStrat);
  // Collect series that legend chips are keeping visible
  const chipProtected=new Set();
  activeChips.forEach(n=>{(sMap[n]?.()||[]).forEach(ref=>forEachSeriesRef(ref,s=>chipProtected.add(s)))});
  // Hide overlay series (unless protected by a legend chip), then show active ones
  overlaySeries.forEach(s=>{if(!chipProtected.has(s))s.applyOptions({visible:false})});
  stUpSeries.forEach(s=>{if(!chipProtected.has(s))s.applyOptions({visible:false})});
  stDownSeries.forEach(s=>{if(!chipProtected.has(s))s.applyOptions({visible:false})});
  active.forEach(name=>{
    const fns=overlayMap[name];
    if(fns)fns.forEach(fn=>forEachSeriesRef(fn(),s=>s.applyOptions({visible:true})));
  });
}

function showOverlaysForStrategy(name){
  updateOverlaysFromSignals();
}

// === VOL PROFILE RENDERER ===
function renderVolProfile(data){
  const el=document.getElementById('vol-profile');
  if(!data||!data.length){el.innerHTML='';return}
  const maxVol=Math.max(...data.map(d=>d.total));
  // Render bottom-to-top (lowest price at bottom)
  el.innerHTML=data.map(d=>{
    const pct=maxVol>0?(d.total/maxVol*100):0;
    const bPct=d.total>0?(d.buy/d.total*100):50;
    const sPct=100-bPct;
    return `<div class="vp-bar"><div class="vp-fill" style="width:${pct}%"><div class="vp-buy" style="width:${bPct}%"></div><div class="vp-sell" style="width:${sPct}%"></div></div></div>`;
  }).reverse().join('');
}
