/* Portfolio backtest page */

let pfEquityChart=null, pfEquitySeries=null, pfHoldSeries=null;
let pfHeatChart=null, pfHeatSeries=null;
let pfData=null;
let pfCampaigns=[];
let pfSelectedCampaignId=null;
let pfCampaignPollTimer=null;
let pfComparisonRows=[];
let pfComparisonSelectedRunIds=[];

const PF_TICKER_COLORS=[
  '#5b7fff','#00e68a','#ff5274','#ffa040','#b050ff',
  '#00d4ff','#ffd644','#ff7eb3','#76ff7a','#ff6b6b',
  '#4ecdc4','#ffe66d','#a8e6cf','#ff8b94','#95e1d3',
];

const PF_COMPARISON_METRIC_META={
  best_gap_vs_buy_hold:{label:'Gap Vs Buy & Hold',field:'gap_vs_buy_hold_pct',type:'pct'},
  best_return_over_drawdown:{label:'Return / Drawdown',field:'return_over_drawdown',type:'ratio'},
  best_return:{label:'Return',field:'strategy_return_pct',type:'pct'},
  lowest_drawdown:{label:'Lowest Drawdown',field:'max_drawdown_pct',type:'drawdown'},
};

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

function _winnerMedal(show,title){
  return show?`<span class="sc-medal" title="${_escapeHtml(title)}">&#129351;</span>`:'';
}

function _escapeHtml(value){
  return String(value??'').replace(/[&<>"']/g,function(ch){
    return ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'})[ch];
  });
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

function _renderPfStats(s,c){
  const pf=s.profit_factor==null?'N/A':s.profit_factor;
  const profitableLabel=s.total_trades?`${s.winners}/${s.total_trades}`:'0/0';
  const initialCapital=Number(s.initial_capital||0);
  const openTrades=Number(s.open_trades||0);
  const totalPnl=Number(s.total_pnl||0);
  const realizedPnl=Number(s.realized_pnl||0);
  const openPnl=Number(s.open_pnl||0);
  const holdEndingEquity=Number(c?.buy_hold_ending_equity||initialCapital);
  const holdTotalPnl=holdEndingEquity-initialCapital;
  const strategyWins=c ? totalPnl>=holdTotalPnl : false;
  const holdWins=c ? holdTotalPnl>=totalPnl : false;
  document.getElementById('pf-stats').innerHTML=`
    <div class="sc sc-net-profit">
      <div class="sc-l">Net Profit</div>
      <div class="sc-compare">
        <div class="sc-compare-row">
          <div class="sc-compare-meta">
            <span class="sc-compare-label">Strategy${_winnerMedal(strategyWins,'Portfolio strategy winner')}</span>
            <span class="sc-compare-note">Ending equity ${_fmtPlain(s.ending_equity)}</span>
          </div>
          <div class="sc-compare-values">
            <span class="sc-compare-value ${totalPnl>=0?'vg':'vr'}">${_fmtCurrency(totalPnl)}</span>
            <span class="sc-compare-pct ${Number(s.net_profit_pct||0)>=0?'vg':'vr'}">${_fmtPct(s.net_profit_pct)}</span>
          </div>
        </div>
        <div class="sc-compare-row">
          <div class="sc-compare-meta">
            <span class="sc-compare-label">Buy &amp; Hold${_winnerMedal(holdWins,'Portfolio buy and hold winner')}</span>
            <span class="sc-compare-note">Ending equity ${_fmtPlain(holdEndingEquity)}</span>
          </div>
          <div class="sc-compare-values">
            <span class="sc-compare-value ${holdTotalPnl>=0?'vg':'vr'}">${_fmtCurrency(holdTotalPnl)}</span>
            <span class="sc-compare-pct ${Number(c?.buy_hold_return_pct||0)>=0?'vg':'vr'}">${c?_fmtPct(c.buy_hold_return_pct):'N/A'}</span>
          </div>
        </div>
      </div>
      <div class="sc-net-profit-foot">
        <div class="sc-sub sc-sub-strong">Overall net increase: ${_fmtPct(s.net_profit_pct)} strategy${c?` · ${_fmtPct(c.buy_hold_return_pct)} buy &amp; hold`:''}</div>
        <div class="sc-sub">${_fmtCurrency(realizedPnl)} realized / ${_fmtCurrency(openPnl)} open</div>
      </div>
    </div>
    <div class="sc">
      <div class="sc-l">Ending Equity</div>
      <div class="sc-v">${_fmtPlain(s.ending_equity)}</div>
      <div class="sc-sub">From ${_fmtPlain(s.initial_capital)}</div>
    </div>
    <div class="sc">
      <div class="sc-l">Return / Max DD</div>
      <div class="sc-v ${(s.return_over_max_dd||0)>=1?'vg':(s.return_over_max_dd||0)>=0?'':'vr'}">${s.return_over_max_dd==null?'N/A':s.return_over_max_dd.toFixed(2)}</div>
      <div class="sc-sub">Net profit % ÷ max drawdown %</div>
    </div>
    <div class="sc">
      <div class="sc-l">Max Drawdown</div>
      <div class="sc-v vr">${(s.max_drawdown_pct||0).toFixed(2)}%</div>
      <div class="sc-sub">${_fmtPlain(s.max_drawdown)}</div>
    </div>
    <div class="sc">
      <div class="sc-l">Profit Factor</div>
      <div class="sc-v">${pf}</div>
      <div class="sc-sub">${_fmtPlain(s.gross_profit)} / ${_fmtPlain(s.gross_loss)}</div>
    </div>
    <div class="sc">
      <div class="sc-l">Profitable Trades</div>
      <div class="sc-v">${(s.win_rate||0).toFixed(1)}%</div>
      <div class="sc-sub">${profitableLabel} closed trades</div>
    </div>
    <div class="sc">
      <div class="sc-l">Closed Trades</div>
      <div class="sc-v">${s.total_trades||0}</div>
      <div class="sc-sub">${openTrades} open positions</div>
    </div>
    <div class="sc">
      <div class="sc-l">Open P&amp;L</div>
      <div class="sc-v ${openPnl>=0?'vg':'vr'}">${_fmtCurrency(openPnl)}</div>
      <div class="sc-sub">Marked to last close</div>
    </div>
    <div class="sc">
      <div class="sc-l">Avg Trade</div>
      <div class="sc-v ${Number(s.avg_pnl||0)>=0?'vg':'vr'}">${_fmtCurrency(s.avg_pnl)}</div>
      <div class="sc-sub">Per closed position</div>
    </div>
    <div class="sc">
      <div class="sc-l">Sharpe</div>
      <div class="sc-v ${(s.sharpe_ratio||0)>=1?'vg':(s.sharpe_ratio||0)>=0?'':'vr'}">${s.sharpe_ratio==null?'N/A':s.sharpe_ratio.toFixed(2)}</div>
      <div class="sc-sub">Annualized from bar spacing</div>
    </div>
    <div class="sc">
      <div class="sc-l">Sortino</div>
      <div class="sc-v ${(s.sortino_ratio||0)>=1?'vg':(s.sortino_ratio||0)>=0?'':'vr'}">${s.sortino_ratio==null?'N/A':s.sortino_ratio.toFixed(2)}</div>
      <div class="sc-sub">Downside risk</div>
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
    const contributionSeries=d.equity_contribution||[];
    const endingContribution=contributionSeries.length ? Number(contributionSeries[contributionSeries.length-1].value||0) : 0;
    const status=(s.open_trades||0)>0?'Active':'Flat';
    return `<tr>
      <td style="font-weight:700">${t}</td>
      <td>${status}</td>
      <td>${s.total_trades||0}</td>
      <td>${(s.win_rate||0).toFixed(1)}%</td>
      <td style="color:${pnl>=0?'var(--green)':'var(--red)'}">${_fmtCurrency(pnl)}</td>
      <td style="color:${pnl>=0?'var(--green)':'var(--red)'}">${_fmtPct(s.net_profit_pct)}</td>
      <td>${_fmtPlain(endingContribution)}</td>
      <td style="color:var(--red)">${(s.max_drawdown_pct||0).toFixed(2)}%</td>
      <td>${pf}</td>
    </tr>`;
  }).join('');
  document.getElementById('pf-ticker-body').innerHTML=rows;
}

function _renderComparison(c){
  if(!c){
    document.getElementById('pf-comparison').innerHTML='';
    return;
  }
  const equityGap=Number(c.equity_gap||0);
  const returnGap=Number(c.return_gap_pct||0);
  const strategyWins=c.winner==='strategy' || c.winner==='tie';
  const holdWins=c.winner==='buy_hold' || c.winner==='tie';
  document.getElementById('pf-comparison').innerHTML=`
    <div class="sc">
      <div class="sc-l">Winner</div>
      <div class="sc-v ${c.winner==='strategy'?'vg':c.winner==='buy_hold'?'vr':''}">${c.winner==='buy_hold'?'Buy & Hold':'Strategy'}${c.winner==='tie'?' / Buy & Hold':''}</div>
      <div class="sc-sub">Same basket, same date range${_winnerMedal(strategyWins,'Strategy benchmark winner')}${_winnerMedal(holdWins,'Buy and hold benchmark winner')}</div>
    </div>
    <div class="sc">
      <div class="sc-l">Strategy Return</div>
      <div class="sc-v ${Number(c.strategy_return_pct||0)>=0?'vg':'vr'}">${_fmtPct(c.strategy_return_pct)}</div>
      <div class="sc-sub">Ending equity ${_fmtPlain(c.strategy_ending_equity)}</div>
    </div>
    <div class="sc">
      <div class="sc-l">Buy &amp; Hold Return</div>
      <div class="sc-v ${Number(c.buy_hold_return_pct||0)>=0?'vg':'vr'}">${_fmtPct(c.buy_hold_return_pct)}</div>
      <div class="sc-sub">Ending equity ${_fmtPlain(c.buy_hold_ending_equity)}</div>
    </div>
    <div class="sc">
      <div class="sc-l">Equity Gap</div>
      <div class="sc-v ${equityGap>=0?'vg':'vr'}">${_fmtCurrency(equityGap)}</div>
      <div class="sc-sub">Strategy minus buy &amp; hold</div>
    </div>
    <div class="sc">
      <div class="sc-l">Return Gap</div>
      <div class="sc-v ${returnGap>=0?'vg':'vr'}">${_fmtPct(returnGap)}</div>
      <div class="sc-sub">Strategy minus buy &amp; hold</div>
    </div>
  `;
}

function _renderBasketDiagnostics(d){
  if(!d){
    document.getElementById('pf-basket-diagnostics').innerHTML='';
    return;
  }
  const parts=[
    `Size: ${d.size_bucket||'n/a'}`,
    `Composition: ${d.composition||'n/a'}`,
    `Tickers: ${d.count||0}`,
    `Traded: ${d.traded_tickers||0}`,
    `Active: ${d.active_tickers||0}`,
    `Crypto: ${d.crypto_count||0}`,
    `Equity: ${d.equity_count||0}`,
  ];
  document.getElementById('pf-basket-diagnostics').innerHTML=parts.map(p=>`<span class="pf-cfg-tag">${p}</span>`).join('');
}

function _renderOrders(orders){
  const rows=(orders||[]).slice(0,20).map(order=>{
    const pnl=Number(order.pnl||0);
    return `<tr>
      <td style="font-weight:700">${order.ticker||''}</td>
      <td>${order.status||''}</td>
      <td>${order.entry_date||''}</td>
      <td>${order.exit_date||''}</td>
      <td>${_fmtPlain(order.entry_price||0)}</td>
      <td>${order.exit_price==null?'':_fmtPlain(order.exit_price)}</td>
      <td>${Number(order.quantity||0).toFixed(4)}</td>
      <td style="color:${pnl>=0?'var(--green)':'var(--red)'}">${_fmtCurrency(pnl)}</td>
      <td style="color:${pnl>=0?'var(--green)':'var(--red)'}">${_fmtPct(order.pnl_pct||0)}</td>
    </tr>`;
  }).join('');
  document.getElementById('pf-orders-body').innerHTML=rows || '<tr><td colspan="9">No orders yet</td></tr>';
}

function _renderConfig(cfg){
  if(!cfg)return;
  const basketBits=[cfg.basket_source||'watchlist'];
  if(cfg.basket_preset)basketBits.push(cfg.basket_preset);
  if(Array.isArray(cfg.requested_tickers) && cfg.requested_tickers.length){
    basketBits.push(`${cfg.requested_tickers.length} requested`);
  }
  const parts=[
    `Strategy: ${cfg.strategy||'ribbon'}`,
    `Basket: ${basketBits.join(' · ')}`,
    `Sizing: ${cfg.sizing_method||'all-in'}`,
    `Risk/trade: ${((cfg.risk_fraction||0)*100).toFixed(1)}%`,
    `Stop: ${cfg.stop_type||'none'}`,
    `Heat limit: ${((cfg.heat_limit||0)*100).toFixed(0)}%`,
    `Capital: ${_fmtPlain(cfg.initial_capital)}`,
  ];
  document.getElementById('pf-config-info').innerHTML=parts.map(p=>`<span class="pf-cfg-tag">${p}</span>`).join('');
}

function _parseTagList(raw){
  return (raw||'').split(',').map(t=>t.trim()).filter(Boolean);
}

function _defaultCampaignSchedule(){
  return {
    enabled:false,
    cadence:'manual',
    interval_hours:24,
    weekdays:['mon'],
    hour:9,
    minute:0,
    next_run_at:null,
    last_queued_at:null,
  };
}

function _formatScheduleSummary(schedule){
  const safe=schedule||_defaultCampaignSchedule();
  if(!safe.enabled || safe.cadence==='manual'){
    return 'manual only';
  }
  if(safe.cadence==='hourly'){
    return `every ${Number(safe.interval_hours||24)}h`;
  }
  const weekdays=(safe.weekdays||[]).join(', ') || 'mon';
  const hour=String(Number(safe.hour||0)).padStart(2,'0');
  const minute=String(Number(safe.minute||0)).padStart(2,'0');
  return `${weekdays} @ ${hour}:${minute}`;
}

function _formatTimestamp(value){
  if(!value)return 'N/A';
  const dt=new Date(value);
  if(Number.isNaN(dt.getTime()))return value;
  return dt.toLocaleString(undefined,{dateStyle:'medium',timeStyle:'short'});
}

function _formatComparisonMetric(type,value){
  if(value==null)return 'N/A';
  if(type==='pct' || type==='drawdown'){
    return `${Number(value).toFixed(2)}%`;
  }
  if(type==='ratio'){
    return Number(value).toFixed(2);
  }
  if(type==='currency'){
    return _fmtPlain(value);
  }
  return String(value);
}

function _comparisonWinnerLabel(row){
  if(row.winner==='strategy')return 'Beat buy & hold';
  if(row.winner==='buy_hold')return 'Buy & hold won';
  return 'Tied benchmark';
}

function _comparisonStatusTone(row){
  if(row.winner==='strategy')return 'vg';
  if(row.winner==='buy_hold')return 'vr';
  return '';
}

function _comparisonSortLabel(sortBy){
  return PF_COMPARISON_METRIC_META[sortBy]?.label || PF_COMPARISON_METRIC_META.best_gap_vs_buy_hold.label;
}

function _comparisonBasketLabel(row){
  return row.basket_definition || row.preset || row.basket_source || 'watchlist';
}

function _comparisonSelectionLimit(){
  return 3;
}

function _applyCampaignScheduleForm(campaign){
  const schedule=campaign?.schedule || _defaultCampaignSchedule();
  document.getElementById('pf-schedule-cadence').value=schedule.enabled ? schedule.cadence : 'manual';
  document.getElementById('pf-schedule-interval-hours').value=Number(schedule.interval_hours||24);
  document.getElementById('pf-schedule-weekdays').value=(schedule.weekdays||[]).join(', ');
  document.getElementById('pf-schedule-hour').value=Number(schedule.hour??9);
  document.getElementById('pf-schedule-minute').value=Number(schedule.minute??0);
  _syncScheduleControls();
}

function _collectScheduleForm(){
  const cadence=document.getElementById('pf-schedule-cadence').value;
  return {
    enabled:cadence!=='manual',
    cadence,
    interval_hours:Number(document.getElementById('pf-schedule-interval-hours').value||24),
    weekdays:_parseTagList(document.getElementById('pf-schedule-weekdays').value).map(v=>v.toLowerCase().slice(0,3)),
    hour:Number(document.getElementById('pf-schedule-hour').value||9),
    minute:Number(document.getElementById('pf-schedule-minute').value||0),
  };
}

function _collectCurrentRunSpec(){
  const strategy=document.getElementById('pf-strategy').value;
  const basketSource=document.getElementById('pf-basket-source').value;
  const manualTickers=document.getElementById('pf-manual-tickers').value.trim();
  const preset=document.getElementById('pf-preset').value;
  const start=document.getElementById('pf-start').value;
  const end=document.getElementById('pf-end').value;
  const heatLimit=Number(document.getElementById('pf-heat-limit').value||20)/100;
  const basketLabel=basketSource==='manual' ? (manualTickers||'manual') : basketSource==='preset' ? preset : 'watchlist';
  const run={
    name:`${strategy} · ${basketLabel}`,
    strategy,
    allocator_policy:'signal_flip_v1',
    basket_source:basketSource,
    start,
    end,
    heat_limit:heatLimit,
    money_management:{
      sizing_method:'fixed_fraction',
      stop_type:'atr',
      stop_atr_period:20,
      stop_atr_multiple:3.0
    }
  };
  if(basketSource==='manual'){
    const tickers=manualTickers.split(/[\s,]+/).map(t=>t.trim().toUpperCase()).filter(Boolean);
    if(!tickers.length) throw new Error('Manual basket requires at least one ticker');
    run.tickers=tickers;
  }
  if(basketSource==='preset'){
    run.preset=preset;
  }
  return run;
}

async function _jsonRequest(url, options){
  const resp=await fetch(url, options);
  const data=await resp.json().catch(()=>({}));
  if(!resp.ok){
    throw new Error(data.error||`Request failed (${resp.status})`);
  }
  return data;
}

function _renderCampaignList(items){
  const el=document.getElementById('pf-campaign-list');
  if(!items.length){
    el.innerHTML='<div class="pf-empty">No campaigns yet. Save the current form as a campaign to start a run plan.</div>';
    return;
  }
  el.innerHTML=items.map(item=>{
    const progress=item.progress||{};
    const queuedOrRunning=(item.status==='queued'||item.status==='running');
    return `<div class="pf-campaign-card ${pfSelectedCampaignId===item.campaign_id?'active':''}">
      <div class="pf-campaign-card-head">
        <div>
          <div class="pf-campaign-name">${_escapeHtml(item.name)}</div>
          <div class="pf-campaign-goal">${_escapeHtml(item.goal||'No goal recorded')}</div>
        </div>
        <span class="pf-status pf-status-${_escapeHtml(item.status||'planned')}">${_escapeHtml(item.status||'planned')}</span>
      </div>
      <div class="pf-campaign-meta">
        <span class="pf-cfg-tag">${progress.completed||0}/${progress.total||0} complete</span>
        <span class="pf-cfg-tag">${progress.remaining||0} remaining</span>
        <span class="pf-cfg-tag">${(progress.percent_completed||0).toFixed ? progress.percent_completed.toFixed(1) : Number(progress.percent_completed||0).toFixed(1)}%</span>
      </div>
      <div class="pf-campaign-actions">
        <button class="tk-action" type="button" data-campaign-action="select" data-campaign-id="${item.campaign_id}">Inspect</button>
        <button class="tk-action" type="button" data-campaign-action="queue" data-campaign-id="${item.campaign_id}" ${queuedOrRunning?'disabled':''}>${queuedOrRunning?'Running':'Queue'}</button>
      </div>
    </div>`;
  }).join('');
}

function _renderCampaignDetail(campaign){
  const el=document.getElementById('pf-campaign-detail');
  if(!campaign){
    el.innerHTML='<div class="pf-empty">Select a campaign to inspect its run statuses and saved summaries.</div>';
    return;
  }
  const progress=campaign.progress||{};
  const schedule=campaign.schedule||_defaultCampaignSchedule();
  const scheduleBits=[
    `<span class="pf-cfg-tag">schedule: ${_escapeHtml(_formatScheduleSummary(schedule))}</span>`,
  ];
  if(schedule.next_run_at){
    scheduleBits.push(`<span class="pf-cfg-tag">next: ${_escapeHtml(schedule.next_run_at)}</span>`);
  }
  if(schedule.last_queued_at){
    scheduleBits.push(`<span class="pf-cfg-tag">last queued: ${_escapeHtml(schedule.last_queued_at)}</span>`);
  }
  const runs=(campaign.runs||[]).map(run=>{
    const summary=run.last_result||{};
    const winner=summary.winner ? `<span class="pf-cfg-tag">winner: ${_escapeHtml(summary.winner)}</span>` : '';
    const gap=summary.return_gap_pct==null ? '' : `<span class="pf-cfg-tag">gap: ${_fmtPct(summary.return_gap_pct)}</span>`;
    const orders=summary.order_count==null ? '' : `<span class="pf-cfg-tag">orders: ${summary.order_count}</span>`;
    const error=run.last_error ? `<span class="pf-cfg-tag">error: ${_escapeHtml(run.last_error)}</span>` : '';
    return `<tr>
      <td style="font-weight:700">${_escapeHtml(run.name||run.run_id)}</td>
      <td><span class="pf-status pf-status-${_escapeHtml(run.status||'planned')}">${_escapeHtml(run.status||'planned')}</span></td>
      <td>${_escapeHtml(run.strategy||'')}</td>
      <td>${_escapeHtml(run.basket_source||'')}</td>
      <td>${_escapeHtml((run.tickers||[]).join(', ') || run.preset || 'watchlist')}</td>
      <td>${_escapeHtml(run.last_run_at||'')}</td>
      <td><div class="pf-inline-tags">${winner}${gap}${orders}${error}</div></td>
    </tr>`;
  }).join('');
  el.innerHTML=`
    <div class="pf-campaign-summary">
      <div class="pf-campaign-summary-head">
        <div>
          <div class="pf-campaign-name">${_escapeHtml(campaign.name)}</div>
          <div class="pf-campaign-goal">${_escapeHtml(campaign.goal||'No goal recorded')}</div>
        </div>
        <span class="pf-status pf-status-${_escapeHtml(campaign.status||'planned')}">${_escapeHtml(campaign.status||'planned')}</span>
      </div>
      <div class="pf-campaign-meta">
        <span class="pf-cfg-tag">${progress.completed||0}/${progress.total||0} complete</span>
        <span class="pf-cfg-tag">${progress.remaining||0} remaining</span>
        <span class="pf-cfg-tag">${progress.queued||0} queued</span>
        <span class="pf-cfg-tag">${progress.running||0} running</span>
        <span class="pf-cfg-tag">${progress.failed||0} failed</span>
      </div>
      <div class="pf-campaign-meta">${scheduleBits.join('')}</div>
    </div>
    <div class="t-scroll">
      <table class="ttbl">
        <thead>
          <tr>
            <th>Run</th>
            <th>Status</th>
            <th>Strategy</th>
            <th>Basket</th>
            <th>Definition</th>
            <th>Last Run</th>
            <th>Latest Summary</th>
          </tr>
        </thead>
        <tbody>${runs || '<tr><td colspan="7">No runs saved for this campaign</td></tr>'}</tbody>
      </table>
    </div>
  `;
}

async function refreshCampaigns(options={}){
  const items=(await _jsonRequest('/api/portfolio/campaigns')).items||[];
  pfCampaigns=items;
  if(!pfSelectedCampaignId && items.length){
    pfSelectedCampaignId=items[0].campaign_id;
  }
  _renderCampaignList(items);
  if(pfSelectedCampaignId){
    try{
      const campaign=await _jsonRequest(`/api/portfolio/campaigns/${pfSelectedCampaignId}`);
      _renderCampaignDetail(campaign);
      _applyCampaignScheduleForm(campaign);
    }catch(_err){
      pfSelectedCampaignId=null;
      _renderCampaignDetail(null);
      _applyCampaignScheduleForm(null);
    }
  }else{
    _renderCampaignDetail(null);
    _applyCampaignScheduleForm(null);
  }
  _syncCampaignPolling(options.force===true);
}

function _syncCampaignPolling(force){
  const shouldPoll=pfCampaigns.some(item=>item.status==='queued'||item.status==='running');
  if(pfCampaignPollTimer){
    clearTimeout(pfCampaignPollTimer);
    pfCampaignPollTimer=null;
  }
  if(shouldPoll || force){
    pfCampaignPollTimer=setTimeout(()=>{ refreshCampaigns().catch(()=>{}); }, shouldPoll ? 2500 : 6000);
  }
}

async function createCampaignFromCurrentForm(){
  const name=document.getElementById('pf-campaign-name').value.trim();
  const goal=document.getElementById('pf-campaign-goal').value.trim();
  const tags=_parseTagList(document.getElementById('pf-campaign-tags').value);
  const feedback=document.getElementById('pf-campaign-feedback');
  if(!name){
    feedback.textContent='Add a campaign name first.';
    return;
  }
  try{
    const run=_collectCurrentRunSpec();
    const campaign=await _jsonRequest('/api/portfolio/campaigns',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({name,goal,tags,runs:[run]})
    });
    pfSelectedCampaignId=campaign.campaign_id;
    feedback.textContent='Campaign saved.';
    await refreshCampaigns({force:true});
  }catch(err){
    feedback.textContent=err.message||'Could not save campaign.';
  }
}

async function createResearchMatrixCampaign(){
  const feedback=document.getElementById('pf-campaign-feedback');
  const name=document.getElementById('pf-campaign-name').value.trim();
  const goal=document.getElementById('pf-campaign-goal').value.trim();
  const tags=_parseTagList(document.getElementById('pf-campaign-tags').value);
  try{
    const payload=await _jsonRequest('/api/portfolio/campaigns/research-matrix',{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify({name,goal,tags})
    });
    pfSelectedCampaignId=payload.campaign.campaign_id;
    const runCount=Number(payload.matrix?.run_count||payload.campaign?.runs?.length||0);
    feedback.textContent=`Research matrix saved with ${runCount} run${runCount===1?'':'s'}.`;
    await refreshCampaigns({force:true});
  }catch(err){
    feedback.textContent=err.message||'Could not create research matrix.';
  }
}

async function queueCampaign(campaignId){
  const feedback=document.getElementById('pf-campaign-feedback');
  try{
    const result=await _jsonRequest(`/api/portfolio/campaigns/${campaignId}/queue`,{
      method:'POST',
      headers:{'Content-Type':'application/json'}
    });
    pfSelectedCampaignId=campaignId;
    feedback.textContent=`Queued ${result.queued} run${result.queued===1?'':'s'}.`;
    await refreshCampaigns({force:true});
  }catch(err){
    feedback.textContent=err.message||'Could not queue campaign.';
  }
}

function _syncScheduleControls(){
  const cadence=(document.getElementById('pf-schedule-cadence')||{}).value || 'manual';
  const hasSelection=Boolean(pfSelectedCampaignId);
  const intervalWrap=document.getElementById('pf-schedule-interval-wrap');
  const weekdaysWrap=document.getElementById('pf-schedule-weekdays-wrap');
  const hourWrap=document.getElementById('pf-schedule-hour-wrap');
  const minuteWrap=document.getElementById('pf-schedule-minute-wrap');
  if(intervalWrap)intervalWrap.style.display=cadence==='hourly' ? 'block' : 'none';
  if(weekdaysWrap)weekdaysWrap.style.display=cadence==='weekly' ? 'block' : 'none';
  if(hourWrap)hourWrap.style.display=cadence==='weekly' ? 'block' : 'none';
  if(minuteWrap)minuteWrap.style.display=cadence==='weekly' ? 'block' : 'none';
  ['pf-schedule-cadence','pf-schedule-interval-hours','pf-schedule-weekdays','pf-schedule-hour','pf-schedule-minute','pf-save-schedule','pf-rerun-campaign']
    .forEach(id=>{
      const el=document.getElementById(id);
      if(el)el.disabled=!hasSelection;
    });
}

async function saveSelectedCampaignSchedule(){
  const feedback=document.getElementById('pf-schedule-feedback');
  if(!pfSelectedCampaignId){
    feedback.textContent='Select a campaign first.';
    return;
  }
  try{
    await _jsonRequest(`/api/portfolio/campaigns/${pfSelectedCampaignId}/schedule`,{
      method:'POST',
      headers:{'Content-Type':'application/json'},
      body:JSON.stringify(_collectScheduleForm()),
    });
    feedback.textContent='Schedule saved.';
    await refreshCampaigns({force:true});
  }catch(err){
    feedback.textContent=err.message||'Could not save schedule.';
  }
}

async function rerunSelectedCampaign(){
  const feedback=document.getElementById('pf-schedule-feedback');
  if(!pfSelectedCampaignId){
    feedback.textContent='Select a campaign first.';
    return;
  }
  try{
    const result=await _jsonRequest(`/api/portfolio/campaigns/${pfSelectedCampaignId}/rerun`,{
      method:'POST',
      headers:{'Content-Type':'application/json'},
    });
    feedback.textContent=`Queued ${result.queued} run${result.queued===1?'':'s'} for rerun.`;
    await refreshCampaigns({force:true});
  }catch(err){
    feedback.textContent=err.message||'Could not rerun campaign.';
  }
}

function _renderComparisonRanking(items,sortBy){
  const el=document.getElementById('pf-comparison-ranking');
  if(!items.length){
    el.innerHTML='<div class="pf-empty">No saved runs match the current filters yet.</div>';
    return;
  }
  el.innerHTML=items.map((row,index)=>{
    const selected=pfComparisonSelectedRunIds.includes(row.run_id);
    const tone=_comparisonStatusTone(row);
    const compareLabel=selected ? 'Selected' : 'Compare';
    return `<div class="pf-compare-card ${selected?'active':''}">
      <div class="pf-compare-card-head">
        <div class="pf-compare-main">
          <div class="pf-compare-rank">#${index+1}</div>
          <div>
            <div class="pf-compare-name">${_escapeHtml(row.run_name)}${row.winner==='strategy'?_winnerMedal(true,'This run beat buy and hold'):''}</div>
            <div class="pf-compare-sub">${_escapeHtml(row.campaign_name)} · ${_escapeHtml(row.strategy)} · ${_escapeHtml(_comparisonBasketLabel(row))}</div>
          </div>
        </div>
        <span class="pf-status pf-status-${_escapeHtml(row.status||'planned')}">${_escapeHtml(row.status||'planned')}</span>
      </div>
      <div class="pf-compare-metrics">
        <span class="pf-cfg-tag ${tone}">${_escapeHtml(_comparisonWinnerLabel(row))}</span>
        <span class="pf-cfg-tag">Return ${row.strategy_return_pct==null?'N/A':_fmtPct(row.strategy_return_pct)}</span>
        <span class="pf-cfg-tag ${Number(row.gap_vs_buy_hold_pct||0)>=0?'vg':'vr'}">Gap ${row.gap_vs_buy_hold_pct==null?'N/A':_fmtPct(row.gap_vs_buy_hold_pct)}</span>
        <span class="pf-cfg-tag">Max DD ${row.max_drawdown_pct==null?'N/A':`${Number(row.max_drawdown_pct).toFixed(2)}%`}</span>
        <span class="pf-cfg-tag">Orders ${row.order_count ?? 'N/A'}</span>
      </div>
      <div class="pf-compare-actions">
        <button class="tk-action pf-compare-toggle ${selected?'active':''}" type="button" data-compare-run-id="${row.run_id}">${compareLabel}</button>
        <span class="pf-section-sub">Completed ${_escapeHtml(_formatTimestamp(row.completed_at || row.last_run_at))}</span>
      </div>
    </div>`;
  }).join('');
  const detail=document.getElementById('pf-comparison-detail');
  if(detail && !detail.innerHTML){
    detail.innerHTML=`<div class="pf-empty">Compare runs ranked by ${_escapeHtml(_comparisonSortLabel(sortBy))}.</div>`;
  }
}

function _renderComparisonDetail(payload){
  const el=document.getElementById('pf-comparison-detail');
  if(!payload || !(payload.items||[]).length){
    el.innerHTML='<div class="pf-empty">Select up to three completed runs to inspect them side by side.</div>';
    return;
  }
  const items=payload.items||[];
  const metricWinners=payload.metric_winners||{};
  const metricCards=Object.entries(PF_COMPARISON_METRIC_META).map(([metricKey,meta])=>{
    const winner=metricWinners[metricKey];
    if(!winner){
      return `<div class="pf-compare-winner-card">
        <div class="pf-compare-winner-label">${_escapeHtml(meta.label)}</div>
        <div class="pf-compare-winner-run">No winner yet</div>
        <div class="pf-section-sub">Missing saved metric on selected runs</div>
      </div>`;
    }
    return `<div class="pf-compare-winner-card">
      <div class="pf-compare-winner-label">${_escapeHtml(meta.label)}</div>
      <div class="pf-compare-winner-run">${_escapeHtml(winner.run_name)}${_winnerMedal(true,`${meta.label} winner`)}</div>
      <div class="pf-section-sub">${_escapeHtml(_formatComparisonMetric(meta.type,winner.value))}</div>
    </div>`;
  }).join('');

  const rows=[
    {label:'Campaign',render:item=>_escapeHtml(item.campaign_name)},
    {label:'Strategy',render:item=>_escapeHtml(item.strategy)},
    {label:'Basket',render:item=>_escapeHtml(_comparisonBasketLabel(item))},
    {label:'Winner',render:item=>`<span class="${_comparisonStatusTone(item)}">${_escapeHtml(_comparisonWinnerLabel(item))}</span>`},
    {label:'Strategy Return',render:item=>item.strategy_return_pct==null?'N/A':_fmtPct(item.strategy_return_pct)},
    {label:'Buy & Hold Return',render:item=>item.buy_hold_return_pct==null?'N/A':_fmtPct(item.buy_hold_return_pct)},
    {label:'Gap Vs Buy & Hold',render:item=>item.gap_vs_buy_hold_pct==null?'N/A':`<span class="${Number(item.gap_vs_buy_hold_pct||0)>=0?'vg':'vr'}">${_fmtPct(item.gap_vs_buy_hold_pct)}</span>`},
    {label:'Max Drawdown',render:item=>item.max_drawdown_pct==null?'N/A':`${Number(item.max_drawdown_pct).toFixed(2)}%`},
    {label:'Return / Drawdown',render:item=>item.return_over_drawdown==null?'N/A':Number(item.return_over_drawdown).toFixed(2)},
    {label:'Ending Equity',render:item=>item.strategy_ending_equity==null?'N/A':_fmtPlain(item.strategy_ending_equity)},
    {label:'Orders',render:item=>item.order_count ?? 'N/A'},
    {label:'Traded Tickers',render:item=>item.traded_tickers ?? 'N/A'},
    {label:'Completed',render:item=>_escapeHtml(_formatTimestamp(item.completed_at || item.last_run_at))},
  ];

  const headerCells=items.map(item=>`<th>${_escapeHtml(item.run_name)}</th>`).join('');
  const bodyRows=rows.map(row=>`<tr><th>${_escapeHtml(row.label)}</th>${items.map(item=>`<td>${row.render(item)}</td>`).join('')}</tr>`).join('');

  el.innerHTML=`
    <div class="pf-compare-detail">
      <div class="pf-compare-winners">${metricCards}</div>
      <div class="t-scroll pf-compare-table">
        <table class="ttbl">
          <thead>
            <tr>
              <th>Metric</th>
              ${headerCells}
            </tr>
          </thead>
          <tbody>${bodyRows}</tbody>
        </table>
      </div>
    </div>
  `;
}

function _syncComparisonSelection(items,options={}){
  const availableIds=new Set(items.map(item=>item.run_id));
  pfComparisonSelectedRunIds=pfComparisonSelectedRunIds.filter(runId=>availableIds.has(runId));
  if(options.reset){
    pfComparisonSelectedRunIds=[];
  }
  const preferred=items.slice(0,_comparisonSelectionLimit()).map(item=>item.run_id);
  for(const runId of preferred){
    if(pfComparisonSelectedRunIds.length >= Math.min(_comparisonSelectionLimit(), items.length))break;
    if(!pfComparisonSelectedRunIds.includes(runId)){
      pfComparisonSelectedRunIds.push(runId);
    }
  }
}

async function refreshComparisonDetail(){
  if(!pfComparisonSelectedRunIds.length){
    _renderComparisonDetail(null);
    return;
  }
  const params=new URLSearchParams({run_ids:pfComparisonSelectedRunIds.join(',')});
  const payload=await _jsonRequest(`/api/portfolio/campaigns/compare?${params.toString()}`);
  _renderComparisonDetail(payload);
}

async function refreshComparisonRanking(options={}){
  const feedback=document.getElementById('pf-comparison-feedback');
  const params=new URLSearchParams();
  const sortBy=(document.getElementById('pf-compare-sort')||{}).value || 'best_gap_vs_buy_hold';
  const strategy=(document.getElementById('pf-compare-strategy-filter')||{}).value || '';
  const basketSource=(document.getElementById('pf-compare-basket-filter')||{}).value || '';
  const status=(document.getElementById('pf-compare-status-filter')||{}).value || '';
  params.set('sort_by',sortBy);
  if(strategy)params.set('strategy',strategy);
  if(basketSource)params.set('basket_source',basketSource);
  if(status)params.set('status',status);

  try{
    const payload=await _jsonRequest(`/api/portfolio/campaigns/completed-runs?${params.toString()}`);
    pfComparisonRows=payload.items||[];
    _syncComparisonSelection(pfComparisonRows,options);
    _renderComparisonRanking(pfComparisonRows,payload.sort_by||sortBy);
    await refreshComparisonDetail();
    if(!pfComparisonRows.length){
      feedback.textContent='No saved runs match the current filters yet.';
    }else{
      feedback.textContent=`Showing ${pfComparisonRows.length} run${pfComparisonRows.length===1?'':'s'} ranked by ${_comparisonSortLabel(payload.sort_by||sortBy)}.`;
    }
  }catch(err){
    pfComparisonRows=[];
    _renderComparisonRanking([],sortBy);
    _renderComparisonDetail(null);
    feedback.textContent=err.message||'Could not load comparison runs.';
  }
}

function toggleComparisonRun(runId){
  if(!runId)return;
  const idx=pfComparisonSelectedRunIds.indexOf(runId);
  if(idx>=0){
    pfComparisonSelectedRunIds.splice(idx,1);
  }else{
    while(pfComparisonSelectedRunIds.length >= _comparisonSelectionLimit()){
      pfComparisonSelectedRunIds.shift();
    }
    pfComparisonSelectedRunIds.push(runId);
  }
  _renderComparisonRanking(pfComparisonRows,(document.getElementById('pf-compare-sort')||{}).value || 'best_gap_vs_buy_hold');
  refreshComparisonDetail().catch(err=>{
    const feedback=document.getElementById('pf-comparison-feedback');
    if(feedback)feedback.textContent=err.message||'Could not compare selected runs.';
  });
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

  _renderPfStats(data.portfolio_summary||{},data.comparison);
  _renderComparison(data.comparison);
  _renderBasketDiagnostics(data.basket_diagnostics);
  _renderOrders(data.orders);
  _renderTickerBreakdown(data.per_ticker||{},data.tickers||[]);
  _renderConfig(data.config);
}

function _syncBasketControls(){
  const source=(document.getElementById('pf-basket-source')||{}).value||'watchlist';
  const manualWrap=document.getElementById('pf-manual-wrap');
  const presetWrap=document.getElementById('pf-preset-wrap');
  if(manualWrap)manualWrap.style.display=source==='manual'?'flex':'none';
  if(presetWrap)presetWrap.style.display=source==='preset'?'flex':'none';
}

function runPortfolio(){
  const start=document.getElementById('pf-start').value;
  const end=document.getElementById('pf-end').value;
  const strategy=document.getElementById('pf-strategy').value;
  const basketSource=document.getElementById('pf-basket-source').value;
  const manualTickers=document.getElementById('pf-manual-tickers').value.trim();
  const preset=document.getElementById('pf-preset').value;
  const heatLimit=Number(document.getElementById('pf-heat-limit').value||20)/100;
  const btn=document.getElementById('pf-run');
  const loading=document.getElementById('pf-loading');

  btn.disabled=true;
  loading.classList.add('on');
  _setProgress('Starting…',0);

  const params=new URLSearchParams({
    start,
    strategy,
    basket_source:basketSource,
    heat_limit:heatLimit,
    stream:'1'
  });
  if(basketSource==='manual' && manualTickers)params.set('tickers',manualTickers);
  if(basketSource==='preset')params.set('preset',preset);
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
  const basketSource=document.getElementById('pf-basket-source');
  if(basketSource){
    basketSource.addEventListener('change',_syncBasketControls);
    _syncBasketControls();
  }
  const saveCampaignBtn=document.getElementById('pf-save-campaign');
  if(saveCampaignBtn){
    saveCampaignBtn.addEventListener('click',()=>{ createCampaignFromCurrentForm().catch(()=>{}); });
  }
  const researchMatrixBtn=document.getElementById('pf-create-research-matrix');
  if(researchMatrixBtn){
    researchMatrixBtn.addEventListener('click',()=>{ createResearchMatrixCampaign().catch(()=>{}); });
  }
  const refreshCampaignsBtn=document.getElementById('pf-refresh-campaigns');
  if(refreshCampaignsBtn){
    refreshCampaignsBtn.addEventListener('click',()=>{ refreshCampaigns({force:true}).catch(()=>{}); });
  }
  const saveScheduleBtn=document.getElementById('pf-save-schedule');
  if(saveScheduleBtn){
    saveScheduleBtn.addEventListener('click',()=>{ saveSelectedCampaignSchedule().catch(()=>{}); });
  }
  const rerunCampaignBtn=document.getElementById('pf-rerun-campaign');
  if(rerunCampaignBtn){
    rerunCampaignBtn.addEventListener('click',()=>{ rerunSelectedCampaign().catch(()=>{}); });
  }
  const refreshComparisonBtn=document.getElementById('pf-refresh-comparison');
  if(refreshComparisonBtn){
    refreshComparisonBtn.addEventListener('click',()=>{ refreshComparisonRanking({reset:true}).catch(()=>{}); });
  }
  ['pf-compare-sort','pf-compare-strategy-filter','pf-compare-basket-filter','pf-compare-status-filter'].forEach(id=>{
    const el=document.getElementById(id);
    if(el){
      el.addEventListener('change',()=>{ refreshComparisonRanking({reset:true}).catch(()=>{}); });
    }
  });
  const cadenceSelect=document.getElementById('pf-schedule-cadence');
  if(cadenceSelect){
    cadenceSelect.addEventListener('change',_syncScheduleControls);
  }
  document.addEventListener('click',function(e){
    const compareBtn=e.target.closest('[data-compare-run-id]');
    if(compareBtn){
      toggleComparisonRun(compareBtn.getAttribute('data-compare-run-id'));
      return;
    }
    const btn=e.target.closest('[data-campaign-action]');
    if(!btn)return;
    const action=btn.getAttribute('data-campaign-action');
    const campaignId=btn.getAttribute('data-campaign-id');
    if(action==='select'){
      pfSelectedCampaignId=campaignId;
      refreshCampaigns({force:true}).catch(()=>{});
    }else if(action==='queue' && !btn.disabled){
      queueCampaign(campaignId).catch(()=>{});
    }
  });
  _applyCampaignScheduleForm(null);
  refreshCampaigns({force:true}).catch(()=>{});
  refreshComparisonRanking({reset:true}).catch(()=>{});
});
