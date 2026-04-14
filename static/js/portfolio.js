/* Portfolio backtest page */

let pfEquityChart=null, pfEquitySeries=null, pfHoldSeries=null;
let pfHeatChart=null, pfHeatSeries=null;
let pfData=null;
let pfCampaigns=[];
let pfSelectedCampaignId=null;
let pfCampaignPollTimer=null;

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
  document.getElementById('pf-comparison').innerHTML=`
    <div class="sc">
      <div class="sc-l">Winner</div>
      <div class="sc-v ${c.winner==='strategy'?'vg':c.winner==='buy_hold'?'vr':''}">${c.winner==='buy_hold'?'Buy & Hold':c.winner==='strategy'?'Strategy':'Tie'}</div>
      <div class="sc-sub">Same basket, same date range</div>
    </div>
    <div class="sc">
      <div class="sc-l">Equity Gap</div>
      <div class="sc-v ${equityGap>=0?'vg':'vr'}">${_fmtCurrency(equityGap)}</div>
      <div class="sc-sub">${_fmtPlain(c.strategy_ending_equity)} vs ${_fmtPlain(c.buy_hold_ending_equity)}</div>
    </div>
    <div class="sc">
      <div class="sc-l">Return Gap</div>
      <div class="sc-v ${returnGap>=0?'vg':'vr'}">${_fmtPct(returnGap)}</div>
      <div class="sc-sub">${_fmtPct(c.strategy_return_pct)} vs ${_fmtPct(c.buy_hold_return_pct)}</div>
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
  const cadenceSelect=document.getElementById('pf-schedule-cadence');
  if(cadenceSelect){
    cadenceSelect.addEventListener('change',_syncScheduleControls);
  }
  document.addEventListener('click',function(e){
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
});
