/* Portfolio backtest page */

let pfEquityChart=null, pfEquitySeries=null, pfHoldSeries=null;
let pfHeatChart=null, pfHeatSeries=null;
let pfData=null;

const PF_TICKER_COLORS=[
  '#5b7fff','#00e68a','#ff5274','#ffa040','#b050ff',
  '#00d4ff','#ffd644','#ff7eb3','#76ff7a','#ff6b6b',
  '#4ecdc4','#ffe66d','#a8e6cf','#ff8b94','#95e1d3',
];

function _fmtCurrency(v){
  const n=Number(v||0);
  return `${n>=0?'+':'-'}$${Math.abs(n).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})}`;
}
function _fmtPlain(v){
  return `$${Number(v||0).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2})}`;
}
function _fmtPct(v){
  const n=Number(v||0);
  return `${n>=0?'+':''}${n.toFixed(2)}%`;
}

function _initEquityChart(){
  const el=document.getElementById('pf-equity-chart');
  if(pfEquityChart){pfEquityChart.remove();pfEquityChart=null;}
  pfEquityChart=LightweightCharts.createChart(el,{
    layout:{background:{type:'solid',color:'#10131d'},textColor:'#9da3b8',fontFamily:'Inter'},
    grid:{vertLines:{color:'#1c1f30'},horzLines:{color:'#1c1f30'}},
    crosshair:{mode:0},
    rightPriceScale:{borderColor:'#1c1f30'},
    timeScale:{borderColor:'#1c1f30',timeVisible:false},
    handleScale:{axisPressedMouseMove:true},
    handleScroll:{pressedMouseMove:true},
  });
  pfEquitySeries=pfEquityChart.addLineSeries({color:'#5b7fff',lineWidth:2,title:'Portfolio'});
  pfHoldSeries=pfEquityChart.addLineSeries({color:'#6a7090',lineWidth:1,lineStyle:2,title:'Buy & Hold'});
  return pfEquityChart;
}

function _initHeatChart(){
  const el=document.getElementById('pf-heat-chart');
  if(pfHeatChart){pfHeatChart.remove();pfHeatChart=null;}
  pfHeatChart=LightweightCharts.createChart(el,{
    layout:{background:{type:'solid',color:'#10131d'},textColor:'#9da3b8',fontFamily:'Inter'},
    grid:{vertLines:{color:'#1c1f30'},horzLines:{color:'#1c1f30'}},
    crosshair:{mode:0},
    rightPriceScale:{borderColor:'#1c1f30'},
    timeScale:{borderColor:'#1c1f30',timeVisible:false},
    handleScale:{axisPressedMouseMove:true},
    handleScroll:{pressedMouseMove:true},
  });
  pfHeatSeries=pfHeatChart.addAreaSeries({
    topColor:'rgba(255,160,64,0.3)',
    bottomColor:'rgba(255,160,64,0.02)',
    lineColor:'#ffa040',
    lineWidth:1,
    title:'Heat %',
  });
  return pfHeatChart;
}

function _renderPfStats(s){
  const pf=s.profit_factor==null?'N/A':s.profit_factor;
  const totalPnl=Number(s.total_pnl||0);
  const realizedPnl=Number(s.realized_pnl||0);
  const openPnl=Number(s.open_pnl||0);
  document.getElementById('pf-stats').innerHTML=`
    <div class="sc">
      <div class="sc-l">Net Profit</div>
      <div class="sc-v ${totalPnl>=0?'vg':'vr'}">${_fmtCurrency(totalPnl)}</div>
      <div class="sc-sub">${_fmtPct(s.net_profit_pct)} · ${_fmtCurrency(realizedPnl)} realized / ${_fmtCurrency(openPnl)} open</div>
    </div>
    <div class="sc">
      <div class="sc-l">Max Drawdown</div>
      <div class="sc-v vr">${(s.max_drawdown_pct||0).toFixed(2)}%</div>
      <div class="sc-sub">${_fmtPlain(s.max_drawdown)}</div>
    </div>
    <div class="sc">
      <div class="sc-l">Win Rate</div>
      <div class="sc-v">${(s.win_rate||0).toFixed(1)}%</div>
      <div class="sc-sub">${s.winners||0}/${s.total_trades||0} closed</div>
    </div>
    <div class="sc">
      <div class="sc-l">Profit Factor</div>
      <div class="sc-v">${pf}</div>
      <div class="sc-sub">${_fmtPlain(s.gross_profit)} / ${_fmtPlain(s.gross_loss)}</div>
    </div>
    <div class="sc">
      <div class="sc-l">Total Trades</div>
      <div class="sc-v">${s.total_trades||0}</div>
      <div class="sc-sub">${s.open_trades||0} open · avg P&L ${_fmtCurrency(s.avg_pnl)}</div>
    </div>
    <div class="sc">
      <div class="sc-l">Ending Equity</div>
      <div class="sc-v">${_fmtPlain(s.ending_equity)}</div>
      <div class="sc-sub">Initial ${_fmtPlain(s.initial_capital)}</div>
    </div>
    <div class="sc">
      <div class="sc-l">Sharpe</div>
      <div class="sc-v ${(s.sharpe_ratio||0)>=1?'vg':(s.sharpe_ratio||0)>=0?'':'vr'}">${s.sharpe_ratio==null?'N/A':s.sharpe_ratio.toFixed(2)}</div>
      <div class="sc-sub">Annualized</div>
    </div>
    <div class="sc">
      <div class="sc-l">Sortino</div>
      <div class="sc-v ${(s.sortino_ratio||0)>=1?'vg':(s.sortino_ratio||0)>=0?'':'vr'}">${s.sortino_ratio==null?'N/A':s.sortino_ratio.toFixed(2)}</div>
      <div class="sc-sub">Downside risk</div>
    </div>
    <div class="sc">
      <div class="sc-l">Ret / DD</div>
      <div class="sc-v ${(s.return_over_max_dd||0)>=1?'vg':(s.return_over_max_dd||0)>=0?'':'vr'}">${s.return_over_max_dd==null?'N/A':s.return_over_max_dd.toFixed(2)}</div>
      <div class="sc-sub">Net % ÷ max DD %</div>
    </div>
  `;
}

function _renderTickerBreakdown(perTicker,tickers){
  const rows=tickers.map(t=>{
    const d=perTicker[t];
    if(!d)return '';
    const s=d.summary||{};
    const pnl=Number(s.total_pnl||0);
    const pf=s.profit_factor==null?'N/A':s.profit_factor;
    return `<tr>
      <td style="font-weight:700">${t}</td>
      <td>${s.total_trades||0}</td>
      <td>${(s.win_rate||0).toFixed(1)}%</td>
      <td style="color:${pnl>=0?'var(--green)':'var(--red)'}">${_fmtCurrency(pnl)}</td>
      <td style="color:${pnl>=0?'var(--green)':'var(--red)'}">${_fmtPct(s.net_profit_pct)}</td>
      <td style="color:var(--red)">${(s.max_drawdown_pct||0).toFixed(2)}%</td>
      <td>${pf}</td>
    </tr>`;
  }).join('');
  document.getElementById('pf-ticker-body').innerHTML=rows;
}

function _renderConfig(cfg){
  if(!cfg)return;
  const parts=[
    `Sizing: ${cfg.sizing_method||'all-in'}`,
    `Risk/trade: ${((cfg.risk_fraction||0)*100).toFixed(1)}%`,
    `Stop: ${cfg.stop_type||'none'}`,
    `Heat limit: ${((cfg.heat_limit||0)*100).toFixed(0)}%`,
    `Capital: ${_fmtPlain(cfg.initial_capital)}`,
  ];
  document.getElementById('pf-config-info').innerHTML=parts.map(p=>`<span class="pf-cfg-tag">${p}</span>`).join('');
}

function _setProgress(msg,pct){
  const bar=document.getElementById('pf-progress-bar');
  const txt=document.getElementById('pf-progress-text');
  const wrap=document.getElementById('pf-progress');
  if(wrap)wrap.style.display='flex';
  if(bar)bar.style.width=pct+'%';
  if(txt)txt.textContent=msg;
}

function _hideProgress(){
  const wrap=document.getElementById('pf-progress');
  if(wrap)wrap.style.display='none';
}

function _applyResult(data){
  pfData=data;
  _initEquityChart();
  pfEquitySeries.setData(data.portfolio_equity_curve||[]);
  pfHoldSeries.setData(data.portfolio_buy_hold_curve||[]);
  pfEquityChart.timeScale().fitContent();

  _initHeatChart();
  pfHeatSeries.setData(data.heat_series||[]);
  pfHeatChart.timeScale().fitContent();

  _renderPfStats(data.portfolio_summary||{});
  _renderTickerBreakdown(data.per_ticker||{},data.tickers||[]);
  _renderConfig(data.config);
}

function runPortfolio(){
  const start=document.getElementById('pf-start').value;
  const end=document.getElementById('pf-end').value;
  const strategy=document.getElementById('pf-strategy').value;
  const heatLimit=Number(document.getElementById('pf-heat-limit').value||20)/100;
  const btn=document.getElementById('pf-run');
  const loading=document.getElementById('pf-loading');

  btn.disabled=true;
  loading.classList.add('on');
  _setProgress('Starting…',0);

  const params=new URLSearchParams({start,strategy,heat_limit:heatLimit,stream:'1'});
  if(end)params.set('end',end);

  const es=new EventSource(`/api/portfolio/backtest?${params}`);

  es.addEventListener('progress',function(e){
    const d=JSON.parse(e.data);
    _setProgress(d.message||'',d.pct||0);
  });

  es.addEventListener('result',function(e){
    es.close();
    const data=JSON.parse(e.data);
    if(data.error){alert(data.error);return;}
    _applyResult(data);
    btn.disabled=false;
    loading.classList.remove('on');
    _setProgress('Complete',100);
    setTimeout(_hideProgress,2000);
  });

  es.addEventListener('error_event',function(e){
    es.close();
    const d=JSON.parse(e.data);
    alert(d.message||'Portfolio backtest failed');
    btn.disabled=false;
    loading.classList.remove('on');
    _hideProgress();
  });

  es.onerror=function(){
    es.close();
    btn.disabled=false;
    loading.classList.remove('on');
    _hideProgress();
  };
}

document.addEventListener('DOMContentLoaded',()=>{
  const today=new Date().toISOString().slice(0,10);
  document.getElementById('pf-end').value=today;
});
