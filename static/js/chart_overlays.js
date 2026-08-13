// Map strategy names to their overlay series
const overlayMap={
  ribbon:[()=>ribbonUpperSeries,()=>ribbonLowerSeries,()=>ribbonCenterSeries],
  supertrend_i:[()=>stIUpSeries,()=>stIDownSeries],
  ema_crossover:[()=>ema9Series,()=>ema21Series],
  bb_breakout:[()=>bbUpperSeries,()=>bbMidSeries,()=>bbLowerSeries],
  cci_trend:[()=>cciLineSeries],
};

// Server-side overlay families (the `overlays=` request param). Each toggle
// maps to the family whose data it needs; sup/res draw from sr_levels, which
// always rides along with the strategy payload.
const FAMILY_BY_SIGNAL={ribbon:'ribbon',supertrend_i:'supertrend_i',ema_crossover:'ema',bb_breakout:'bb',cci_trend:'cci'};
const FAMILY_BY_LEGEND={vol:'volumes',volProfile:'vol_profile',maAuto:'sma',sma50:'sma',sma100:'sma',sma200:'sma',sma50w:'sma',sma100w:'sma',sma200w:'sma',emaCross:'ema'};
const FAMILY_DATA_PRESENT={
  ribbon:d=>d?.overlays?.ribbon!==undefined,
  bb:d=>d?.overlays?.bb!==undefined,
  cci:d=>d?.overlays?.cci!==undefined,
  supertrend_i:d=>d?.supertrend_i_up!==undefined,
  supertrend:d=>d?.supertrend_up!==undefined,
  ema:d=>d?.ema9!==undefined,
  sma:d=>d?.sma_50!==undefined,
  volumes:d=>d?.volumes!==undefined,
  vol_profile:d=>d?.vol_profile!==undefined,
};

function currentOverlayFamilies(){
  const fams=new Set();
  if(typeof activeSignals!=='undefined')activeSignals.forEach(sig=>{const f=FAMILY_BY_SIGNAL[sig];if(f)fams.add(f)});
  if(typeof btOpen!=='undefined'&&btOpen&&typeof activeBacktestStrat!=='undefined'&&activeBacktestStrat){
    const f=FAMILY_BY_SIGNAL[activeBacktestStrat];
    if(f)fams.add(f);
  }
  if(typeof activeChips!=='undefined')activeChips.forEach(k=>{const f=FAMILY_BY_LEGEND[k];if(f)fams.add(f)});
  return fams;
}

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
  stIUpSeries.forEach(s=>{if(!chipProtected.has(s))s.applyOptions({visible:false})});
  stIDownSeries.forEach(s=>{if(!chipProtected.has(s))s.applyOptions({visible:false})});
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
