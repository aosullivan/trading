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
  const start=document.getElementById('bt-start').value;
  const end=document.getElementById('bt-end').value;
  document.getElementById('bt-equity-range').textContent=`${start||'Start'} -> ${end||'Now'}`;
}

function toggleBT(){
  btOpen=!btOpen;
  const p=document.getElementById('bt-panel-wrap'),b=document.getElementById('bt-btn');
  p.classList.toggle('open',btOpen);
  b.classList.toggle('active',btOpen);
  if(!p.style.height) p.style.height='380px';
  document.getElementById('bt-lbl').textContent=btOpen?'Hide Backtest':'Backtest';
  if(btOpen&&lastData){
    initBTSlider();
  }
  else{updateMarkers()}
  setTimeout(()=>{
    chart.applyOptions({width:document.getElementById('chart-container').clientWidth,height:document.getElementById('chart-container').clientHeight});
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
  loadChart();
}

function renderEquityCurve(points){
  if(!btEquityChart||!btEquitySeries) return;
  btEquitySeries.setData(points);
  btEquityChart.timeScale().fitContent();
}

function renderStats(s){
  const profitFactor=s.profit_factor==null?'Inf':s.profit_factor;
  const profitableLabel=s.total_trades?`${s.winners}/${s.total_trades}`:'0/0';
  document.getElementById('stats').innerHTML=`
    <div class="sc">
      <div class="sc-l">Net Profit</div>
      <div class="sc-v ${s.total_pnl>=0?'vg':'vr'}">${fmtCurrency(s.total_pnl)}</div>
      <div class="sc-sub">${fmtPct(s.net_profit_pct)} on ${fmtCurrencyPlain(s.initial_capital)}</div>
    </div>
    <div class="sc">
      <div class="sc-l">Max Drawdown</div>
      <div class="sc-v vr">${s.max_drawdown_pct.toFixed(2)}%</div>
      <div class="sc-sub">${fmtCurrencyPlain(s.max_drawdown)}</div>
    </div>
    <div class="sc">
      <div class="sc-l">Profitable Trades</div>
      <div class="sc-v">${s.win_rate.toFixed(1)}%</div>
      <div class="sc-sub">${profitableLabel}</div>
    </div>
    <div class="sc">
      <div class="sc-l">Profit Factor</div>
      <div class="sc-v">${profitFactor}</div>
      <div class="sc-sub">${fmtCurrencyPlain(s.gross_profit)} / ${fmtCurrencyPlain(s.gross_loss)}</div>
    </div>
    <div class="sc">
      <div class="sc-l">Total Trades</div>
      <div class="sc-v">${s.total_trades}</div>
      <div class="sc-sub">Long-only next-bar execution</div>
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

function initBTSlider(){
  if(!_lastCandles||!_lastCandles.length)return;
  _btSliderDates=_lastCandles.map(c=>{
    const d=new Date(c.time*1000);
    return d.toISOString().split('T')[0];
  });
  // Default: match chart visible range
  const visRange=chart.timeScale().getVisibleRange();
  if(visRange){
    const loIdx=_btSliderDates.findIndex(d=>new Date(d).getTime()/1000>=visRange.from);
    const hiIdx=_btSliderDates.length-1-[..._btSliderDates].reverse().findIndex(d=>new Date(d).getTime()/1000<=visRange.to);
    _btSliderLo=Math.max(0,loIdx)/_btSliderDates.length;
    _btSliderHi=Math.min(_btSliderDates.length-1,hiIdx>=0?hiIdx:_btSliderDates.length-1)/_btSliderDates.length;
  }else{
    _btSliderLo=0;_btSliderHi=1;
  }
  updateBTSliderUI();
  applyBTFromSlider();
}

function updateBTSliderUI(){
  const track=document.getElementById('bt-range-track');
  if(!track)return;
  const fill=document.getElementById('bt-range-fill');
  const lo=document.getElementById('bt-range-lo');
  const hi=document.getElementById('bt-range-hi');
  const loLabel=document.getElementById('bt-range-start');
  const hiLabel=document.getElementById('bt-range-end');
  fill.style.left=(_btSliderLo*100)+'%';
  fill.style.width=((_btSliderHi-_btSliderLo)*100)+'%';
  lo.style.left=(_btSliderLo*100)+'%';
  hi.style.left=(_btSliderHi*100)+'%';
  const n=_btSliderDates.length;
  if(n){
    const loDate=_btSliderDates[Math.min(Math.round(_btSliderLo*(n-1)),n-1)];
    const hiDate=_btSliderDates[Math.min(Math.round(_btSliderHi*(n-1)),n-1)];
    loLabel.textContent=loDate;
    hiLabel.textContent=hiDate;
    document.getElementById('bt-start').value=loDate;
    document.getElementById('bt-end').value=hiDate;
    document.getElementById('bt-equity-range').textContent=`${loDate} → ${hiDate}`;
  }
}

function applyBTFromSlider(){
  const n=_btSliderDates.length;
  if(!n)return;
  const loDate=_btSliderDates[Math.min(Math.round(_btSliderLo*(n-1)),n-1)];
  const hiDate=_btSliderDates[Math.min(Math.round(_btSliderHi*(n-1)),n-1)];
  document.getElementById('bt-start').value=loDate;
  document.getElementById('bt-end').value=hiDate;
  chartStart=loDate;
  chartEnd=hiDate;
  setBTRangeLabel();
  loadChart();
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
    if(dragging==='bt-range-lo'){_btSliderLo=Math.min(pct,_btSliderHi-0.01)}
    else{_btSliderHi=Math.max(pct,_btSliderLo+0.01)}
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
    if(Math.abs(pct-_btSliderLo)<Math.abs(pct-_btSliderHi)){_btSliderLo=Math.min(pct,_btSliderHi-0.01)}
    else{_btSliderHi=Math.max(pct,_btSliderLo+0.01)}
    updateBTSliderUI();
    applyBTFromSlider();
  });
})();

// === RESIZABLE BACKTEST PANEL ===
(function(){
  const drag=document.getElementById('bt-drag'),panel=document.getElementById('bt-panel-wrap');
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
