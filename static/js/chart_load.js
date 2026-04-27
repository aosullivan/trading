let tickerNameRefreshToken=0;
let chartLoadRequestToken=0;

function syncTickerNameLabel(tickerName){
  document.getElementById('tk-name').textContent=tickerName||'';
}

function buildChartRequestUrl(ticker,interval,start,end,period,mult,{candlesOnly=false,includeMM=true,strategyOnly=false,strategy='',includeShared=false}={}){
  let url=`/api/chart?ticker=${encodeURIComponent(ticker)}&interval=${encodeURIComponent(interval)}&start=${encodeURIComponent(start)}&period=${encodeURIComponent(period)}&multiplier=${encodeURIComponent(mult)}`;
  if(end)url+=`&end=${encodeURIComponent(end)}`;
  if(candlesOnly)url+='&candles_only=1';
  if(strategyOnly)url+='&strategy_only=1';
  if(includeShared)url+='&include_shared=1';
  if(strategy)url+=`&strategy=${encodeURIComponent(strategy)}`;
  if(includeMM){
    const mmqs=typeof buildMMQueryString==='function'?buildMMQueryString():'';
    if(mmqs)url+=`&${mmqs}`;
  }
  return url;
}

function syncChartHeader(ticker,interval,period,mult,tickerName=''){
  document.getElementById('tk-sym').textContent=ticker;
  syncTickerNameLabel(tickerName);
  document.getElementById('chart-tag').textContent=`${ticker} \u00b7 ${intervalLabel(interval)} \u00b7 ST ${period}/${mult}`;
}

function updateChartPriceDisplay(ticker,candles){
  const priceEl=document.getElementById('tk-price');
  const changeEl=document.getElementById('tk-chg');
  if(!candles?.length){
    priceEl.textContent='--';
    priceEl.style.color='';
    changeEl.textContent='--';
    changeEl.className='tk-chg';
    return;
  }
  const last=candles[candles.length-1];
  const prev=candles.length>1?candles[candles.length-2]:last;
  const change=last.close-prev.close;
  const changePct=prev.close?change/prev.close*100:0;
  const up=change>=0;
  priceEl.textContent=formatPriceDisplay(ticker,last.close);
  priceEl.style.color=up?'var(--green)':'var(--red)';
  changeEl.textContent=`${up?'+':''}${change.toFixed(2)} (${up?'+':''}${changePct.toFixed(2)}%)`;
  changeEl.className='tk-chg '+(up?'up':'dn');
}

function applyDefaultVisibleRange(interval,candles){
  if(candles?.length){
    const visStart=defaultVisibleStart(interval);
    const visStartTs=Math.floor(new Date(visStart).getTime()/1000);
    const firstCandle=candles[0].time;
    const from=Math.max(visStartTs,firstCandle);
    const to=candles[candles.length-1].time;
    chart.timeScale().setVisibleRange({from,to});
    return;
  }
  chart.timeScale().fitContent();
}

function clearChartDerivedSeries(){
  clearSupertrendSegments();
  stUpFill.setData([]);stDownFill.setData([]);
  stUpMid.setData([]);stDownMid.setData([]);
  volumeSeries.setData([]);
  sma50Series.setData([]);sma100Series.setData([]);
  sma180Series.setData([]);sma200Series.setData([]);
  sma50wSeries.setData([]);sma100wSeries.setData([]);sma200wSeries.setData([]);
  ema9Series.setData([]);ema21Series.setData([]);
  donchUpperSeries.setData([]);donchLowerSeries.setData([]);
  bbUpperSeries.setData([]);bbMidSeries.setData([]);bbLowerSeries.setData([]);
  keltUpperSeries.setData([]);keltMidSeries.setData([]);keltLowerSeries.setData([]);
  psarBullSeries.setData([]);psarBearSeries.setData([]);
  macdLineSeries.setData([]);macdSignalSeries.setData([]);macdHistSeries.setData([]);
  adxLineSeries.setData([]);plusDiSeries.setData([]);minusDiSeries.setData([]);
  cciLineSeries.setData([]);
  orbUpperSeries.setData([]);orbLowerSeries.setData([]);orbMidSeries.setData([]);
  ribbonUpperSeries.setData([]);ribbonLowerSeries.setData([]);ribbonCenterSeries.setData([]);
  candleSeries.setMarkers([]);
  renderVolProfile([]);
  clearSRLines();
  if(typeof updateOverlaysFromSignals==='function')updateOverlaysFromSignals();
}

function applyCandlesPayload(ticker,interval,period,mult,data){
  const candles=data.candles||[];
  candleSeries.setData(candles);
  _lastCandles=candles;
  lastData={ticker_name:data.ticker_name||'',candles};
  syncChartHeader(ticker,interval,period,mult,data.ticker_name||'');
  updateChartPriceDisplay(ticker,candles);
  applyDefaultVisibleRange(interval,candles);
  clearChartDerivedSeries();
  updateLegendValues(null);
  updateFlipInfo();
}

function applySelectedStrategyPayload(data,requestedStrategy){
  const strategies=data?.strategies||{};
  const strategyKey=data?.strategy||requestedStrategy;
  const strategyPayload=strategies[strategyKey];
  if(!strategyKey||!strategyPayload)return false;
  if(!lastData)lastData={};
  lastData={
    ...lastData,
    buy_hold_equity_curve:data.buy_hold_equity_curve||lastData.buy_hold_equity_curve||[],
    strategies:{
      ...(lastData.strategies||{}),
      [strategyKey]:strategyPayload,
    },
  };
  return true;
}

function queueTickerNameRefresh(ticker,url,token,attempt=1){
  if(attempt>4)return;
  window.setTimeout(async()=>{
    if(token!==tickerNameRefreshToken)return;
    if(document.getElementById('ticker').value.toUpperCase()!==ticker)return;
    try{
      const res=await fetch(url),data=await res.json();
      if(token!==tickerNameRefreshToken)return;
      if(document.getElementById('ticker').value.toUpperCase()!==ticker)return;
      if(data.ticker_name){
        syncTickerNameLabel(data.ticker_name);
      }else{
        queueTickerNameRefresh(ticker,url,token,attempt+1);
      }
    }catch(_e){}
  },attempt*700);
}

async function loadStrategyPayload(name){
  const ticker=document.getElementById('ticker').value.toUpperCase();
  const interval=document.getElementById('interval').value;
  const start=chartStart,end=chartEnd;
  const period=document.getElementById('period').value,mult=document.getElementById('multiplier').value;
  const url=buildChartRequestUrl(ticker,interval,start,end,period,mult,{strategyOnly:true,strategy:name,includeMM:true});
  if(typeof setBacktestLoading==='function')setBacktestLoading(true);
  try{
    const data=await fetch(url).then(r=>r.json());
    if(data?.error)throw new Error(data.error);
    applySelectedStrategyPayload(data,name);
    return true;
  }catch(e){
    alert('Error: '+e.message);
    return false;
  }finally{
    if(typeof setBacktestLoading==='function')setBacktestLoading(false);
  }
}

function applySharedChartPayload(ticker,interval,period,mult,data,selectedStrategy,{resetRange=false}={}){
  const candles=data.candles||[];
  candleSeries.setData(candles);
  _lastCandles=candles;
  syncChartHeader(ticker,interval,period,mult,data.ticker_name||'');
  updateChartPriceDisplay(ticker,candles);
  clearChartDerivedSeries();
  applySelectedStrategyPayload(data,selectedStrategy);
  const stUpData=(data.supertrend_up||[]).map(d=>d.value==null||Number.isNaN(Number(d.value))?{time:d.time}:d);
  const stDownData=(data.supertrend_down||[]).map(d=>d.value==null||Number.isNaN(Number(d.value))?{time:d.time}:d);
  const stIUpData=(data.supertrend_i_up||[]).map(d=>d.value==null||Number.isNaN(Number(d.value))?{time:d.time}:d);
  const stIDownData=(data.supertrend_i_down||[]).map(d=>d.value==null||Number.isNaN(Number(d.value))?{time:d.time}:d);
  clearSupertrendSegments();
  clearSupertrendISegments();
  stUpSeries=buildSupertrendSegments(stUpData,'#00e68a');
  stDownSeries=buildSupertrendSegments(stDownData,'#ff5274');
  stIUpSeries=buildSupertrendSegments(stIUpData,'#00d084');
  stIDownSeries=buildSupertrendSegments(stIDownData,'#ff3d71');
  // Supertrend fills: area from body middle to supertrend line
  stUpFill.setData(stUpData.map(d=>d.value==null?{time:d.time}:{time:d.time,value:d.mid??d.value}));
  stDownFill.setData(stDownData.map(d=>d.value==null?{time:d.time}:{time:d.time,value:d.mid??d.value}));
  stUpMid.setData(stUpData);
  stDownMid.setData(stDownData);
  volumeSeries.setData(data.volumes);
  sma50Series.setData(data.sma_50||[]);sma100Series.setData(data.sma_100||[]);
  sma180Series.setData(data.sma_180||[]);sma200Series.setData(data.sma_200||[]);
  sma50wSeries.setData(data.sma_50w||[]);sma100wSeries.setData(data.sma_100w||[]);sma200wSeries.setData(data.sma_200w||[]);
  ema9Series.setData(data.ema9||[]);ema21Series.setData(data.ema21||[]);
  // Indicator overlays
  const ov=data.overlays||{};
  donchUpperSeries.setData(ov.donchian?.upper||[]);donchLowerSeries.setData(ov.donchian?.lower||[]);
  bbUpperSeries.setData(ov.bb?.upper||[]);bbMidSeries.setData(ov.bb?.mid||[]);bbLowerSeries.setData(ov.bb?.lower||[]);
  keltUpperSeries.setData(ov.keltner?.upper||[]);keltMidSeries.setData(ov.keltner?.mid||[]);keltLowerSeries.setData(ov.keltner?.lower||[]);
  psarBullSeries.setData(ov.psar?.bull||[]);psarBearSeries.setData(ov.psar?.bear||[]);
  // Oscillators
  macdLineSeries.setData(data.macd_line||[]);macdSignalSeries.setData(data.signal_line||[]);macdHistSeries.setData(data.macd_hist||[]);
  adxLineSeries.setData(ov.adx?.adx||[]);plusDiSeries.setData(ov.adx?.plus_di||[]);minusDiSeries.setData(ov.adx?.minus_di||[]);
  cciLineSeries.setData(ov.cci?.cci||[]);
  orbUpperSeries.setData(ov.orb?.upper||[]);orbLowerSeries.setData(ov.orb?.lower||[]);orbMidSeries.setData(ov.orb?.mid||[]);
  // Trend ribbon with per-bar colors (area series)
  const rUpper=ov.ribbon?.upper||[],rLower=ov.ribbon?.lower||[];
  ribbonUpperSeries.setData(rUpper.map(d=>{
    const a=parseFloat(d.color?.match(/[\d.]+(?=\)$)/)?.[0]||'0.25');
    return{time:d.time,value:d.value,lineColor:d.lineColor||d.color,topColor:d.color,bottomColor:d.color?.replace(/[\d.]+\)$/,Math.max(0.03,a*0.2).toFixed(2)+')')};
  }));
  ribbonLowerSeries.setData(rLower.map(d=>({time:d.time,value:d.value})));
  ribbonCenterSeries.setData(ov.ribbon?.center||[]);
  lastData=data;
  syncAutoMovingAverages();
  // Trend flip dates
  updateFlipInfo();
  // Volume profile
  renderVolProfile(data.vol_profile||[]);
  // Redraw S/R lines if chip is active
  clearSRLines();
  redrawActiveSRLines();
  updateLegendValues(null);
  updateChartPriceDisplay(ticker,data.candles);
  if(resetRange)applyDefaultVisibleRange(interval,data.candles);
  switchStrategy(document.getElementById('strategy-select').value);
  updateMarkers();
}

async function loadChart(){
  const ld=document.getElementById('loading');
  const loadingLabel=document.getElementById('loading-label');
  if(typeof cancelWatchlistChartPreload==='function')cancelWatchlistChartPreload();
  ld.classList.add('on');
  if(loadingLabel)loadingLabel.textContent='Loading chart…';
  if(typeof setBacktestLoading==='function')setBacktestLoading(true);
  const ticker=document.getElementById('ticker').value.toUpperCase();
  const nameRefreshToken=++tickerNameRefreshToken;
  const requestToken=++chartLoadRequestToken;
  const interval=document.getElementById('interval').value;
  const start=chartStart,end=chartEnd;
  const period=document.getElementById('period').value,mult=document.getElementById('multiplier').value;
  setBTRangeLabel();
  const selectedStrategy=document.getElementById('strategy-select')?.value||activeBacktestStrat||'ribbon';
  const candlesUrl=buildChartRequestUrl(ticker,interval,start,end,period,mult,{candlesOnly:true,includeMM:false});
  const nameRefreshUrl=candlesUrl;
  const selectedStrategyUrl=buildChartRequestUrl(ticker,interval,start,end,period,mult,{strategyOnly:true,strategy:selectedStrategy,includeMM:true,includeShared:true});
  let candlesLoaded=false;
  try{
    syncChartHeader(ticker,interval,period,mult,'');
    const candleData=await fetch(candlesUrl).then(r=>r.json());
    if(requestToken!==chartLoadRequestToken)return;
    if(candleData.error)throw new Error(candleData.error);
    applyCandlesPayload(ticker,interval,period,mult,candleData);
    if(candleData.ticker_name){
      syncTickerNameLabel(candleData.ticker_name);
    }else{
      queueTickerNameRefresh(ticker,nameRefreshUrl,nameRefreshToken);
    }
    candlesLoaded=true;
    ld.classList.remove('on');
    pushURLParams();
  }catch(e){alert('Error: '+e.message)}
  if(!candlesLoaded||requestToken!==chartLoadRequestToken){
    if(typeof setBacktestLoading==='function')setBacktestLoading(false);
    if(requestToken===chartLoadRequestToken){
      ld.classList.remove('on');
    }
    return;
  }
  if(loadingLabel)loadingLabel.textContent='Loading strategy…';
  try{
    const data=await fetch(selectedStrategyUrl).then(r=>r.json());
    if(requestToken!==chartLoadRequestToken)return;
    if(data.error)throw new Error(data.error);
    applySharedChartPayload(ticker,interval,period,mult,data,selectedStrategy);
    if(data.ticker_name)syncTickerNameLabel(data.ticker_name);
  }catch(e){alert('Error: '+e.message)}
  finally{
    if(typeof setBacktestLoading==='function')setBacktestLoading(false);
    if(requestToken===chartLoadRequestToken){
      ld.classList.remove('on');
      pushURLParams();
      if(typeof queueWatchlistTrendPreload==='function')queueWatchlistTrendPreload();
      if(typeof queueWatchlistChartPreload==='function')queueWatchlistChartPreload();
    }
  }
}

async function switchStrategy(name){
  if(!lastData?.strategies)lastData={...(lastData||{}),strategies:{}};
  let s=lastData.strategies[name];
  if(!s){
    const loaded=await loadStrategyPayload(name);
    if(!loaded)return;
    s=lastData?.strategies?.[name];
    if(!s)return;
  }
  activeBacktestStrat=name;
  updateMarkers();
  showOverlaysForStrategy(name);
  if(btOpen){
    ensureBTChart();
  }
  renderEquityCurve(
    s.equity_curve||[],
    s.buy_hold_equity_curve||lastData.buy_hold_equity_curve||[],
    s.trades||[]
  );
  renderStats(s.summary,s.buy_hold_equity_curve||lastData.buy_hold_equity_curve||[]);
  renderTrades(s.trades);
  if(typeof updateRibbonStrategyHint==='function')updateRibbonStrategyHint(name);
}
