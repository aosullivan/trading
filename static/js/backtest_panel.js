const BT_DEFAULT_STRATEGY='ribbon';
const BT_IS_STANDALONE=document.body?.dataset?.backtestMode==='standalone';
let _btSliderInitialized=false;
let _lastMMParams='';

function getMMParams(){
  const sizing=document.getElementById('mm-sizing')?.value||'';
  const stop=document.getElementById('mm-stop')?.value||'';
  const stopVal=document.getElementById('mm-stop-val')?.value||'3';
  const riskCap=document.getElementById('mm-risk-cap')?.value||'';
  const compound=document.getElementById('mm-compound')?.value||'trade';
  return{sizing,stop,stopVal,riskCap,compound};
}

function buildMMQueryString(){
  const p=getMMParams();
  const parts=[];
  if(p.sizing)parts.push(`mm_sizing=${p.sizing}`);
  if(p.stop){
    parts.push(`mm_stop=${p.stop}`);
    parts.push(`mm_stop_val=${p.stopVal}`);
  }
  if(p.riskCap)parts.push(`mm_risk_cap=${p.riskCap}`);
  if(p.compound!=='trade')parts.push(`mm_compound=${p.compound}`);
  return parts.join('&');
}

function onMMChange(){
  // Show/hide stop params
  const stopType=document.getElementById('mm-stop')?.value;
  const paramsEl=document.getElementById('mm-stop-params');
  if(paramsEl)paramsEl.style.display=stopType?'flex':'none';
  // Update placeholder based on stop type
  const stopInput=document.getElementById('mm-stop-val');
  if(stopInput){
    if(stopType==='atr'){stopInput.value='3';stopInput.title='ATR multiple';stopInput.step='0.5'}
    else if(stopType==='pct'){stopInput.value='5';stopInput.title='Stop loss %';stopInput.step='1'}
  }
  // Trigger reload if params actually changed
  const newParams=buildMMQueryString();
  if(newParams!==_lastMMParams){
    _lastMMParams=newParams;
    requestBacktestReload();
  }
}

function fmtCurrency(value){
  const n=Number(value||0);
  return `${n>=0?'+':'-'}$${Math.abs(n).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})}`;
}

function fmtCurrencyPlain(value){
  return `$${Number(value||0).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})}`;
}

function fmtPct(value){
  const n=Number(value||0);
  return `${n>=0?'+':''}${n.toFixed(2)}%`;
}

function setBTRangeLabel(){
  const startEl=document.getElementById('bt-start');
  const endEl=document.getElementById('bt-end');
  const label=document.getElementById('bt-equity-range');
  if(!startEl||!endEl||!label)return;
  label.textContent=`${startEl.value||'Start'} -> ${endEl.value||'Now'}`;
}

function candleTimeToBTDate(ts){
  return new Date(ts*1000).toISOString().split('T')[0];
}

function getBTLaunchRanges(){
  const domainStart=chartStart||(_lastCandles?.length?candleTimeToBTDate(_lastCandles[0].time):'');
  const domainEnd=chartEnd||(_lastCandles?.length?candleTimeToBTDate(_lastCandles[_lastCandles.length-1].time):'');
  let start=domainStart;
  let end=domainEnd;
  const visRange=(typeof chart!=='undefined'&&chart?.timeScale)?chart.timeScale().getVisibleRange():null;
  if(visRange&&_lastCandles?.length){
    const loIdx=_lastCandles.findIndex(c=>c.time>=visRange.from);
    const hiIdx=_lastCandles.length-1-[..._lastCandles].reverse().findIndex(c=>c.time<=visRange.to);
    start=candleTimeToBTDate(_lastCandles[Math.max(0,loIdx>=0?loIdx:0)].time);
    end=candleTimeToBTDate(_lastCandles[Math.max(0,Math.min(_lastCandles.length-1,hiIdx>=0?hiIdx:_lastCandles.length-1))].time);
  }
  return{start,end,domainStart,domainEnd};
}

function openBacktestTab(){
  const p=new URLSearchParams();
  const ticker=document.getElementById('ticker')?.value?.toUpperCase()||'TSLA';
  const interval=document.getElementById('interval')?.value||'1d';
  const period=document.getElementById('period')?.value||'10';
  const mult=document.getElementById('multiplier')?.value||'2.5';
  const strategy=document.getElementById('strategy-select')?.value||activeBacktestStrat||BT_DEFAULT_STRATEGY;
  const ranges=getBTLaunchRanges();
  p.set('ticker',ticker);
  p.set('interval',interval);
  if(ranges.start)p.set('start',ranges.start);
  if(ranges.end)p.set('end',ranges.end);
  if(ranges.domainStart)p.set('domain_start',ranges.domainStart);
  if(ranges.domainEnd)p.set('domain_end',ranges.domainEnd);
  p.set('period',period);
  p.set('multiplier',mult);
  p.set('strategy',strategy);
  const mm=getMMParams();
  if(mm.sizing)p.set('mm_sizing',mm.sizing);
  if(mm.stop){p.set('mm_stop',mm.stop);p.set('mm_stop_val',mm.stopVal)}
  if(mm.riskCap)p.set('mm_risk_cap',mm.riskCap);
  if(mm.compound!=='trade')p.set('mm_compound',mm.compound);
  const url=`/backtest?${p.toString()}`;
  const tab=window.open(url,'_blank');
  if(tab){
    tab.opener=null;
    tab.focus();
  }
}

function closeBacktestView(){
  if(BT_IS_STANDALONE){
    window.close();
    window.setTimeout(()=>{
      if(!window.closed)window.location.href=`/${window.location.search}`;
    },120);
    return;
  }
  toggleBT();
}

function toggleBT(){
  if(BT_IS_STANDALONE){
    closeBacktestView();
    return;
  }
  btOpen=!btOpen;
  const p=document.getElementById('bt-panel-wrap'),b=document.getElementById('bt-btn');
  p.classList.toggle('open',btOpen);
  b.classList.toggle('active',btOpen);
  if(!p.style.height) p.style.height='380px';
  document.getElementById('bt-lbl').textContent=btOpen?'Hide Backtest':'Backtest';
  if(btOpen&&lastData){
    initBTSlider();
  }
  else{
    if(typeof updateMarkers==='function')updateMarkers();
    if(typeof updateOverlaysFromSignals==='function')updateOverlaysFromSignals();
  }
  setTimeout(()=>{
    if(typeof chart!=='undefined'&&chart){
      chart.applyOptions({width:document.getElementById('chart-container').clientWidth,height:document.getElementById('chart-container').clientHeight});
    }
    if(btEquityChart){
      const c=document.getElementById('bt-equity-chart');
      btEquityChart.applyOptions({width:c.clientWidth,height:c.clientHeight});
      btEquityChart.timeScale().fitContent();
    }
  },50);
}

function applyBT(){
  chartStart=document.getElementById('bt-start').value;
  chartEnd=document.getElementById('bt-end').value;
  setBTRangeLabel();
  requestBacktestReload();
}

function requestBacktestReload(){
  if(typeof loadChart==='function'){
    loadChart();
    return;
  }
  if(typeof loadBacktestReport==='function'){
    loadBacktestReport();
  }
}

function buildBTTradeMarkers(trades){
  return (trades||[]).flatMap(t=>{
    const markers=[{
      time:Math.floor(new Date(`${t.entry_date}T00:00:00Z`).getTime()/1000),
      position:'belowBar',
      color:'#00e68a',
      shape:'arrowUp',
      text:'BUY',
    }];
    if(!t.open){
      markers.push({
        time:Math.floor(new Date(`${t.exit_date}T00:00:00Z`).getTime()/1000),
        position:'aboveBar',
        color:'#ff5274',
        shape:'arrowDown',
        text:'SELL',
      });
    }
    return markers;
  }).sort((a,b)=>a.time-b.time);
}

function renderEquityCurve(points,holdPoints,trades){
  if(!btEquityChart||!btEquitySeries) return;
  if(btPriceSeries){
    btPriceSeries.setData(_lastCandles&&_lastCandles.length?_lastCandles:[]);
  }
  btEquitySeries.setData(points);
  btEquitySeries.setMarkers(buildBTTradeMarkers(trades));
  if(btHoldSeries)btHoldSeries.setData(holdPoints||[]);
  btEquityChart.timeScale().fitContent();
}

function renderStats(s){
  const profitFactor=s.profit_factor==null?'N/A':s.profit_factor;
  const profitableLabel=s.total_trades?`${s.winners}/${s.total_trades}`:'0/0';
  const openTrades=Number(s.open_trades||0);
  const totalPnl=Number(s.total_pnl||0);
  const realizedPnl=Number(s.realized_pnl||0);
  const openPnl=Number(s.open_pnl||0);
  document.getElementById('stats').innerHTML=`
    <div class="sc">
      <div class="sc-l">Net Profit</div>
      <div class="sc-v ${totalPnl>=0?'vg':'vr'}">${fmtCurrency(totalPnl)}</div>
      <div class="sc-sub">${fmtPct(s.net_profit_pct)} · ${fmtCurrency(realizedPnl)} realized / ${fmtCurrency(openPnl)} open</div>
    </div>
    <div class="sc">
      <div class="sc-l">Max Drawdown</div>
      <div class="sc-v vr">${s.max_drawdown_pct.toFixed(2)}%</div>
      <div class="sc-sub">${fmtCurrencyPlain(s.max_drawdown)}</div>
    </div>
    <div class="sc">
      <div class="sc-l">Profitable Trades</div>
      <div class="sc-v">${s.win_rate.toFixed(1)}%</div>
      <div class="sc-sub">${profitableLabel} closed trades</div>
    </div>
    <div class="sc">
      <div class="sc-l">Profit Factor</div>
      <div class="sc-v">${profitFactor}</div>
      <div class="sc-sub">${fmtCurrencyPlain(s.gross_profit)} / ${fmtCurrencyPlain(s.gross_loss)}</div>
    </div>
    <div class="sc">
      <div class="sc-l">Closed Trades</div>
      <div class="sc-v">${s.total_trades}</div>
      <div class="sc-sub">${openTrades} open positions</div>
    </div>
    <div class="sc">
      <div class="sc-l">Open P&amp;L</div>
      <div class="sc-v ${openPnl>=0?'vg':'vr'}">${fmtCurrency(openPnl)}</div>
      <div class="sc-sub">Marked to last close</div>
    </div>
    <div class="sc">
      <div class="sc-l">Avg Trade</div>
      <div class="sc-v ${s.avg_pnl>=0?'vg':'vr'}">${fmtCurrency(s.avg_pnl)}</div>
      <div class="sc-sub">Per closed position</div>
    </div>
    <div class="sc">
      <div class="sc-l">Avg Winner</div>
      <div class="sc-v vg">${fmtCurrency(s.avg_winner)}</div>
      <div class="sc-sub">${s.winners} winning trades</div>
    </div>
    <div class="sc">
      <div class="sc-l">Avg Loser</div>
      <div class="sc-v vr">${fmtCurrency(-Math.abs(s.avg_loser))}</div>
      <div class="sc-sub">${s.losers} losing trades</div>
    </div>
    <div class="sc">
      <div class="sc-l">Best Trade</div>
      <div class="sc-v vg">${fmtCurrency(s.best_trade)}</div>
      <div class="sc-sub">Largest gain</div>
    </div>
    <div class="sc">
      <div class="sc-l">Worst Trade</div>
      <div class="sc-v vr">${fmtCurrency(s.worst_trade)}</div>
      <div class="sc-sub">Largest loss</div>
    </div>
    <div class="sc">
      <div class="sc-l">Ending Equity</div>
      <div class="sc-v">${fmtCurrencyPlain(s.ending_equity)}</div>
      <div class="sc-sub">From ${fmtCurrencyPlain(s.initial_capital)}</div>
    </div>
    <div class="sc">
      <div class="sc-l">Sharpe Ratio</div>
      <div class="sc-v ${(s.sharpe_ratio||0)>=1?'vg':(s.sharpe_ratio||0)>=0?'':'vr'}">${s.sharpe_ratio==null?'N/A':s.sharpe_ratio.toFixed(2)}</div>
      <div class="sc-sub">Annualized (√252)</div>
    </div>
    <div class="sc">
      <div class="sc-l">Sortino Ratio</div>
      <div class="sc-v ${(s.sortino_ratio||0)>=1?'vg':(s.sortino_ratio||0)>=0?'':'vr'}">${s.sortino_ratio==null?'N/A':s.sortino_ratio.toFixed(2)}</div>
      <div class="sc-sub">Downside risk only</div>
    </div>
    <div class="sc">
      <div class="sc-l">Return / Max DD</div>
      <div class="sc-v ${(s.return_over_max_dd||0)>=1?'vg':(s.return_over_max_dd||0)>=0?'':'vr'}">${s.return_over_max_dd==null?'N/A':s.return_over_max_dd.toFixed(2)}</div>
      <div class="sc-sub">Net profit % ÷ max drawdown %</div>
    </div>
  `;
}

function renderTrades(trades){
  document.getElementById('trades-body').innerHTML=trades.map((t,i)=>`<tr>
    <td style="color:var(--text-4)">${i+1}</td><td><span class="badge-l">LONG</span></td>
    <td>${t.entry_date}</td><td>$${t.entry_price}</td>
    <td>${t.exit_date}${t.open?'<span style="color:var(--text-4)"> (open)</span>':''}</td><td>$${t.exit_price}</td>
    <td style="color:${t.pnl>=0?'var(--green)':'var(--red)'}">${t.pnl>=0?'+':''}$${t.pnl}</td>
    <td style="color:${t.pnl_pct>=0?'var(--green)':'var(--red)'}">${t.pnl_pct>=0?'+':''}${t.pnl_pct}%</td>
  </tr>`).join('');
}

// === BACKTEST RANGE SLIDER ===
let _btSliderDates=[];  // all available dates from chart data
let _btSliderLo=0, _btSliderHi=1;  // 0-1 normalized positions

function _btSliderIndexToPct(idx){
  const n=_btSliderDates.length;
  return n<=1?0:idx/(n-1);
}

function _btSliderPctToIndex(pct){
  const n=_btSliderDates.length;
  if(!n)return 0;
  return Math.max(0,Math.min(n-1,Math.round(pct*(n-1))));
}

function _btSliderMinGap(){
  const n=_btSliderDates.length;
  return n<=1?0:1/(n-1);
}

function initBTSlider(){
  if(!_lastCandles||!_lastCandles.length)return;
  _btSliderDates=_lastCandles.map(c=>{
    const d=new Date(c.time*1000);
    return d.toISOString().split('T')[0];
  });
  const startVal=chartStart||_btSliderDates[0];
  const endVal=chartEnd||_btSliderDates[_btSliderDates.length-1];
  const loIdxByDate=_btSliderDates.findIndex(d=>d>=startVal);
  const hiIdxByDate=_btSliderDates.length-1-[..._btSliderDates].reverse().findIndex(d=>d<=endVal);
  const hasMainChart=typeof chart!=='undefined'&&chart&&chart.timeScale;
  const visRange=hasMainChart&&!BT_IS_STANDALONE?chart.timeScale().getVisibleRange():null;
  if(visRange){
    const loIdx=_btSliderDates.findIndex(d=>new Date(d).getTime()/1000>=visRange.from);
    const hiIdx=_btSliderDates.length-1-[..._btSliderDates].reverse().findIndex(d=>new Date(d).getTime()/1000<=visRange.to);
    _btSliderLo=_btSliderIndexToPct(Math.max(0,loIdx));
    _btSliderHi=_btSliderIndexToPct(Math.min(_btSliderDates.length-1,hiIdx>=0?hiIdx:_btSliderDates.length-1));
  }else{
    _btSliderLo=_btSliderIndexToPct(Math.max(0,loIdxByDate>=0?loIdxByDate:0));
    _btSliderHi=_btSliderIndexToPct(Math.max(0,Math.min(_btSliderDates.length-1,hiIdxByDate>=0?hiIdxByDate:_btSliderDates.length-1)));
  }
  if(_btSliderHi<_btSliderLo)_btSliderHi=_btSliderLo;
  _btSliderInitialized=true;
  updateBTSliderUI();
  if(!BT_IS_STANDALONE)applyBTFromSlider();
}

function updateBTSliderUI(){
  const track=document.getElementById('bt-range-track');
  if(!track)return;
  const fill=document.getElementById('bt-range-fill');
  const lo=document.getElementById('bt-range-lo');
  const hi=document.getElementById('bt-range-hi');
  const loLabel=document.getElementById('bt-range-start');
  const hiLabel=document.getElementById('bt-range-end');
  const loBubble=document.getElementById('bt-range-lo-bubble');
  const hiBubble=document.getElementById('bt-range-hi-bubble');
  fill.style.left=(_btSliderLo*100)+'%';
  fill.style.width=((_btSliderHi-_btSliderLo)*100)+'%';
  lo.style.left=(_btSliderLo*100)+'%';
  hi.style.left=(_btSliderHi*100)+'%';
  const n=_btSliderDates.length;
  if(n){
    const loDate=_btSliderDates[_btSliderPctToIndex(_btSliderLo)];
    const hiDate=_btSliderDates[_btSliderPctToIndex(_btSliderHi)];
    loLabel.textContent=loDate;
    hiLabel.textContent=hiDate;
    if(loBubble)loBubble.textContent=loDate;
    if(hiBubble)hiBubble.textContent=hiDate;
    document.getElementById('bt-start').value=loDate;
    document.getElementById('bt-end').value=hiDate;
    document.getElementById('bt-equity-range').textContent=`${loDate} → ${hiDate}`;
  }
}

function applyBTFromSlider(){
  const n=_btSliderDates.length;
  if(!n)return;
  const loDate=_btSliderDates[_btSliderPctToIndex(_btSliderLo)];
  const hiDate=_btSliderDates[_btSliderPctToIndex(_btSliderHi)];
  document.getElementById('bt-start').value=loDate;
  document.getElementById('bt-end').value=hiDate;
  chartStart=loDate;
  chartEnd=hiDate;
  setBTRangeLabel();
  requestBacktestReload();
}

(function(){
  const track=document.getElementById('bt-range-track');
  if(!track)return;
  let dragging=null, startX=0;
  function pctFromX(x){const r=track.getBoundingClientRect();return Math.max(0,Math.min(1,(x-r.left)/r.width))}

  ['bt-range-lo','bt-range-hi'].forEach(id=>{
    const el=document.getElementById(id);
    el.addEventListener('mousedown',e=>{e.preventDefault();dragging=id;el.classList.add('active');startX=e.clientX});
  });

  document.addEventListener('mousemove',e=>{
    if(!dragging)return;
    const pct=pctFromX(e.clientX);
    const minGap=_btSliderMinGap();
    if(dragging==='bt-range-lo'){_btSliderLo=Math.min(pct,_btSliderHi-minGap)}
    else{_btSliderHi=Math.max(pct,_btSliderLo+minGap)}
    updateBTSliderUI();
  });

  document.addEventListener('mouseup',()=>{
    if(!dragging)return;
    document.getElementById(dragging).classList.remove('active');
    dragging=null;
    applyBTFromSlider();
  });

  // Click on track to move nearest handle
  track.addEventListener('click',e=>{
    if(e.target.classList.contains('bt-range-handle'))return;
    const pct=pctFromX(e.clientX);
    const minGap=_btSliderMinGap();
    if(Math.abs(pct-_btSliderLo)<Math.abs(pct-_btSliderHi)){_btSliderLo=Math.min(pct,_btSliderHi-minGap)}
    else{_btSliderHi=Math.max(pct,_btSliderLo+minGap)}
    updateBTSliderUI();
    applyBTFromSlider();
  });
})();

// === RESIZABLE BACKTEST PANEL ===
(function(){
  const drag=document.getElementById('bt-drag'),panel=document.getElementById('bt-panel-wrap');
  if(!drag||!panel||BT_IS_STANDALONE)return;
  let startY,startH;
  drag.addEventListener('mousedown',e=>{
    startY=e.clientY;startH=panel.offsetHeight;
    const maxH=document.querySelector('.center').offsetHeight-120;
    const move=ev=>{
      const dy=startY-ev.clientY;
      panel.style.height=Math.max(120,Math.min(maxH,startH+dy))+'px';
    };
    const up=()=>{
      document.removeEventListener('mousemove',move);document.removeEventListener('mouseup',up);
      chart.applyOptions({width:document.getElementById('chart-container').clientWidth,height:document.getElementById('chart-container').clientHeight});
    };
    document.addEventListener('mousemove',move);document.addEventListener('mouseup',up);
    e.preventDefault();
  });
})();
