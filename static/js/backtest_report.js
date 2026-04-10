let activeBacktestStrat=BT_DEFAULT_STRATEGY;

const btReportState={
  ticker:'BTC-USD',
  interval:'1d',
  period:'10',
  multiplier:'2.5',
  domainStart:'',
  domainEnd:'',
};

function syncBacktestReportURL(){
  const p=new URLSearchParams();
  p.set('ticker',btReportState.ticker);
  p.set('interval',btReportState.interval);
  p.set('start',chartStart||defaultStart(btReportState.interval));
  if(chartEnd)p.set('end',chartEnd);
  if(btReportState.domainStart)p.set('domain_start',btReportState.domainStart);
  if(btReportState.domainEnd)p.set('domain_end',btReportState.domainEnd);
  p.set('period',btReportState.period);
  p.set('multiplier',btReportState.multiplier);
  p.set('strategy',activeBacktestStrat||BT_DEFAULT_STRATEGY);
  const mm=typeof getMMParams==='function'?getMMParams():null;
  if(mm?.sizing)p.set('mm_sizing',mm.sizing);
  if(mm?.stop){
    p.set('mm_stop',mm.stop);
    p.set('mm_stop_val',mm.stopVal);
  }
  if(mm?.riskCap)p.set('mm_risk_cap',mm.riskCap);
  if(mm?.compound&&mm.compound!=='trade')p.set('mm_compound',mm.compound);
  history.replaceState(null,'',`?${p.toString()}`);
}

function updateBacktestReportTitle(){
  const tickerEl=document.getElementById('bt-symbol-ticker');
  const metaEl=document.getElementById('bt-symbol-meta');
  const metaParts=[];
  if(lastData?.ticker_name)metaParts.push(lastData.ticker_name);
  metaParts.push(intervalLabel(btReportState.interval));
  tickerEl.textContent=btReportState.ticker;
  metaEl.textContent=metaParts.join(' · ');
  document.title=`${btReportState.ticker} Backtest Report`;
}

function readBacktestReportParams(){
  const p=new URLSearchParams(window.location.search);
  btReportState.ticker=(p.get('ticker')||'BTC-USD').toUpperCase();
  btReportState.interval=p.get('interval')||'1d';
  btReportState.period=p.get('period')||'10';
  btReportState.multiplier=p.get('multiplier')||'2.5';
  chartStart=p.get('start')||defaultStart(btReportState.interval);
  chartEnd=p.get('end')||'';
  btReportState.domainStart=p.get('domain_start')||chartStart;
  btReportState.domainEnd=p.get('domain_end')||chartEnd;
  activeBacktestStrat=p.get('strategy')||BT_DEFAULT_STRATEGY;
  if(typeof applyMMParams==='function'){
    applyMMParams({
      sizing:p.get('mm_sizing')||'',
      stop:p.get('mm_stop')||'',
      stopVal:p.get('mm_stop_val')||'',
      riskCap:p.get('mm_risk_cap')||'',
      compound:p.get('mm_compound')||'trade',
    });
  }
  const select=document.getElementById('strategy-select');
  if(select.querySelector(`option[value="${CSS.escape(activeBacktestStrat)}"]`)){
    select.value=activeBacktestStrat;
  }else{
    activeBacktestStrat=BT_DEFAULT_STRATEGY;
    select.value=BT_DEFAULT_STRATEGY;
  }
  document.getElementById('bt-start').value=chartStart;
  document.getElementById('bt-end').value=chartEnd||now.toISOString().split('T')[0];
  setBTRangeLabel();
}

function sameBTDateRange(startA,endA,startB,endB){
  return String(startA||'')===String(startB||'')&&String(endA||'')===String(endB||'');
}

async function fetchBacktestPayload(start,end,opts={}){
  let url=`/api/chart?ticker=${encodeURIComponent(btReportState.ticker)}&interval=${encodeURIComponent(btReportState.interval)}&start=${encodeURIComponent(start)}&period=${encodeURIComponent(btReportState.period)}&multiplier=${encodeURIComponent(btReportState.multiplier)}`;
  if(end)url+=`&end=${encodeURIComponent(end)}`;
  if(opts.candlesOnly)url+='&candles_only=1';
  const mmqs=typeof buildMMQueryString==='function'?buildMMQueryString():'';
  if(mmqs&&!opts.candlesOnly)url+=`&${mmqs}`;
  const res=await fetch(url);
  return res.json();
}

async function loadBacktestReport(){
  if(typeof setBacktestLoading==='function')setBacktestLoading(true);
  try{
    ensureBTChart();
    if(
      !_btSliderInitialized&&
      !sameBTDateRange(chartStart,chartEnd,btReportState.domainStart,btReportState.domainEnd)
    ){
      const domainData=await fetchBacktestPayload(btReportState.domainStart,btReportState.domainEnd,{candlesOnly:true});
      if(domainData.error){
        alert(domainData.error);
        return;
      }
      // Slider dates span the full domain; price underlay must use the backtest window (second fetch).
      initBTSlider(domainData.candles||[]);
    }

    const data=await fetchBacktestPayload(chartStart,chartEnd);
    if(data.error){
      alert(data.error);
      return;
    }
    btOpen=true;
    lastData=data;
    _lastCandles=data.candles||[];
    if(!_btSliderInitialized){
      initBTSlider();
    }else{
      updateBTSliderUI();
    }
    updateBacktestReportTitle();
    switchStrategy(activeBacktestStrat);
  }catch(e){
    alert('Error: '+(e?.message||String(e)));
  }finally{
    if(typeof setBacktestLoading==='function')setBacktestLoading(false);
  }
}

function switchStrategy(name){
  if(!lastData?.strategies)return;
  const resolved=lastData.strategies[name]?name:BT_DEFAULT_STRATEGY;
  const s=lastData.strategies[resolved];
  if(!s)return;
  activeBacktestStrat=resolved;
  document.getElementById('strategy-select').value=resolved;
  renderEquityCurve(
    s.equity_curve||[],
    s.buy_hold_equity_curve||lastData.buy_hold_equity_curve||[],
    s.trades||[]
  );
  renderStats(s.summary||{},s.buy_hold_equity_curve||lastData.buy_hold_equity_curve||[]);
  renderTrades(s.trades||[]);
  if(typeof updateRibbonStrategyHint==='function')updateRibbonStrategyHint(resolved);
  syncBacktestReportURL();
}

readBacktestReportParams();
loadBacktestReport();
