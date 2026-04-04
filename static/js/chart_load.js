let tickerNameRefreshToken=0;

function syncTickerNameLabel(tickerName){
  document.getElementById('tk-name').textContent=tickerName||'';
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

async function loadChart(){
  const ld=document.getElementById('loading');
  ld.classList.add('on');
  const ticker=document.getElementById('ticker').value.toUpperCase();
  const nameRefreshToken=++tickerNameRefreshToken;
  const interval=document.getElementById('interval').value;
  const start=chartStart,end=chartEnd;
	const period=document.getElementById('period').value,mult=document.getElementById('multiplier').value;
	setBTRangeLabel();
	try{
    let url=`/api/chart?ticker=${ticker}&interval=${interval}&start=${start}&period=${period}&multiplier=${mult}`;
    if(end)url+=`&end=${end}`;
    const mmqs=typeof buildMMQueryString==='function'?buildMMQueryString():'';
    if(mmqs)url+=`&${mmqs}`;
    const res=await fetch(url),data=await res.json();
    if(data.error){alert(data.error);return}
    document.getElementById('tk-sym').textContent=ticker;
    syncTickerNameLabel('');
    document.getElementById('chart-tag').textContent=`${ticker} \u00b7 ${intervalLabel(interval)} \u00b7 ST ${period}/${mult}`;
    candleSeries.setData(data.candles);
    _lastCandles=data.candles;
    const stUpData=(data.supertrend_up||[]).map(d=>d.value==null||Number.isNaN(Number(d.value))?{time:d.time}:d);
    const stDownData=(data.supertrend_down||[]).map(d=>d.value==null||Number.isNaN(Number(d.value))?{time:d.time}:d);
    clearSupertrendSegments();
    stUpSeries=buildSupertrendSegments(stUpData,'#00e68a');
    stDownSeries=buildSupertrendSegments(stDownData,'#ff5274');
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
    // Price display
    if(data.candles.length){
      const l=data.candles[data.candles.length-1],p=data.candles.length>1?data.candles[data.candles.length-2]:l;
      const c=l.close-p.close,cp=c/p.close*100,up=c>=0;
      document.getElementById('tk-price').textContent=formatPriceDisplay(ticker,l.close);
      document.getElementById('tk-price').style.color=up?'var(--green)':'var(--red)';
      const ce=document.getElementById('tk-chg');
      ce.textContent=`${up?'+':''}${c.toFixed(2)} (${up?'+':''}${cp.toFixed(2)}%)`;
      ce.className='tk-chg '+(up?'up':'dn');
    }
    if(data.ticker_name){
      syncTickerNameLabel(data.ticker_name);
    }else{
      queueTickerNameRefresh(ticker,url,nameRefreshToken);
    }
    // Show last 1yr (daily) or 2yr (weekly) by default; all history is loaded so user can scroll left freely
    if(data.candles.length){
      const visStart=defaultVisibleStart(interval);
      const visStartTs=Math.floor(new Date(visStart).getTime()/1000);
      const firstCandle=data.candles[0].time;
      const from=Math.max(visStartTs,firstCandle);
      const to=data.candles[data.candles.length-1].time;
      chart.timeScale().setVisibleRange({from,to});
    }else{
      chart.timeScale().fitContent();
    }
    switchStrategy(document.getElementById('strategy-select').value);
    updateMarkers();
  }catch(e){alert('Error: '+e.message)}
  finally{
    ld.classList.remove('on');
    pushURLParams();
    if(typeof queueWatchlistTrendPreload==='function')queueWatchlistTrendPreload();
  }
}

function switchStrategy(name){
  if(!lastData?.strategies)return;
  const s=lastData.strategies[name];if(!s)return;
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
  renderStats(s.summary);
  renderTrades(s.trades);
}
