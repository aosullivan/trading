// === WATCHLIST ===
const WL_DEFAULT_VIEW='watchlist';
const WL_DEFAULT_TAB='all';
const WL_DEFAULT_TREND_FRAME='daily';
const WL_DEFAULT_TREND_SIDE='all';
const WL_DEFAULT_TREND_SORT_KEY='score';
const WL_SORT_KEYS=['sym','last','chg','chg_pct'];
const WL_TREND_SORT_KEYS=['ticker','flip','strength','score'];
const WL_PANEL_DEFAULT_WIDTH=352;
const WL_PANEL_MIN_WIDTH=320;
const WL_PANEL_MAX_WIDTH=540;
const WL_QUOTES_REFRESH_MS=300000;
const WL_QUOTES_RETRY_MS=4000;
const WL_TRENDS_REFRESH_MS=300000;
const WL_TRENDS_POLL_MS=4000;
const WL_IDLE_PAUSE_MS=300000;
const WL_MOUSEMOVE_ACTIVITY_MS=1000;
const watchlistStrategyPreferenceHelpers=globalThis.strategyPreferenceHelpers;

function toggleWatchlist(){
  wlPanelCollapsed=!wlPanelCollapsed;
  applyWatchlistPanelState({resizeDelay:250});
}

let wlQuotes={};
let wlList=[];
let wlSortKey=null; // 'sym','last','chg','chg_pct'
let wlSortAsc=true;
let wlTrendFrame='daily';
let wlTrendSide='all';
let wlTrendSortKey='score'; // 'ticker','flip','score'
let wlTrendSortAsc=false;
let wlView='watchlist';
let wlActiveTab='all';
let wlTrendRows=[];
let wlTrendsLoading=false;
let wlTrendsStale=false;
let wlPanelCollapsed=false;
let wlPanelWidth=WL_PANEL_DEFAULT_WIDTH;
let wlTrendSelectionSyncPending=false;
const WL_TAB_ORDER=['all','indexes','treasuries','semis','tech','software','etfs','crypto','misc'];
const WL_CATEGORY_LABELS={indexes:'Index',treasuries:'Rates',semis:'Semis',tech:'Tech',software:'Software',etfs:'ETF',crypto:'Crypto',misc:'Misc'};

function wlNormalizeView(view){return view==='trends'?'trends':WL_DEFAULT_VIEW}
function wlNormalizeTab(tab){return WL_TAB_ORDER.includes(tab)?tab:WL_DEFAULT_TAB}
function wlNormalizeTrendFrame(frame){return frame==='weekly'?'weekly':WL_DEFAULT_TREND_FRAME}
function wlNormalizeTrendSide(side){return ['all','bullish','bearish','mixed'].includes(side)?side:WL_DEFAULT_TREND_SIDE}
function wlSortDefaultAsc(key){return key==='sym'}
function wlTrendSortDefaultAsc(key){return key==='ticker'}
function wlNormalizeWidth(width){
  const nextWidth=Number.parseInt(width,10);
  if(!Number.isFinite(nextWidth))return WL_PANEL_DEFAULT_WIDTH;
  return Math.max(WL_PANEL_MIN_WIDTH,Math.min(WL_PANEL_MAX_WIDTH,nextWidth));
}
function syncWatchlistURLState(){
  if(typeof pushURLParams==='function')pushURLParams();
}
function wlCurrentTicker(){
  return document.getElementById('ticker')?.value?.toUpperCase().trim()||'';
}
function syncWLTabButtons(){
  document.querySelectorAll('#wl-tabs .wl-tab').forEach(b=>{
    b.classList.toggle('active',b.dataset.tab===wlActiveTab);
  });
}
function syncWLTrendSideButtons(){
  document.querySelectorAll('.wl-trend-side-tabs .wl-tab').forEach(b=>{
    b.classList.toggle('active',b.dataset.side===wlTrendSide);
  });
}
function resizeWatchlistChart(){
  const container=document.getElementById('chart-container');
  if(!container||typeof chart==='undefined'||!chart?.applyOptions)return;
  chart.applyOptions({width:container.clientWidth,height:container.clientHeight});
}
function applyWatchlistPanelState({syncURL=true,resizeDelay=0}={}){
  const panel=document.getElementById('wl-panel');
  const btn=document.getElementById('wl-toggle');
  if(panel){
    panel.style.width=`${wlPanelWidth}px`;
    panel.classList.toggle('collapsed',wlPanelCollapsed);
  }
  if(btn){
    btn.innerHTML=wlPanelCollapsed?'&#9664;':'&#9654;';
    btn.title=wlPanelCollapsed?'Show Watchlist':'Hide Watchlist';
  }
  if(resizeDelay>0)setTimeout(resizeWatchlistChart,resizeDelay);
  else resizeWatchlistChart();
  if(syncURL)syncWatchlistURLState();
}
function readWatchlistURLState(params){
  wlView=wlNormalizeView(params.get('wlView'));
  wlActiveTab=wlNormalizeTab(params.get('wlTab'));
  wlTrendFrame=wlNormalizeTrendFrame(params.get('wlFrame'));
  wlTrendSide=wlNormalizeTrendSide(params.get('wlSide'));
  const nextSort=params.get('wlSort');
  wlSortKey=WL_SORT_KEYS.includes(nextSort)?nextSort:null;
  if(wlSortKey){
    wlSortAsc=params.has('wlSortAsc')?params.get('wlSortAsc')!=='0':wlSortDefaultAsc(wlSortKey);
  }else{
    wlSortAsc=true;
  }
  const nextTrendSort=params.get('wlTrendSort');
  wlTrendSortKey=WL_TREND_SORT_KEYS.includes(nextTrendSort)?nextTrendSort:WL_DEFAULT_TREND_SORT_KEY;
  wlTrendSortAsc=params.has('wlTrendSortAsc')
    ?params.get('wlTrendSortAsc')!=='0'
    :wlTrendSortDefaultAsc(wlTrendSortKey);
  wlPanelCollapsed=params.get('wlCollapsed')==='1';
  wlPanelWidth=wlNormalizeWidth(params.get('wlWidth')||WL_PANEL_DEFAULT_WIDTH);
}
function writeWatchlistURLState(params){
  if(wlView!==WL_DEFAULT_VIEW)params.set('wlView',wlView);
  if(wlActiveTab!==WL_DEFAULT_TAB)params.set('wlTab',wlActiveTab);
  if(wlTrendFrame!==WL_DEFAULT_TREND_FRAME)params.set('wlFrame',wlTrendFrame);
  if(wlTrendSide!==WL_DEFAULT_TREND_SIDE)params.set('wlSide',wlTrendSide);
  if(wlSortKey){
    params.set('wlSort',wlSortKey);
    if(wlSortAsc!==wlSortDefaultAsc(wlSortKey))params.set('wlSortAsc',wlSortAsc?'1':'0');
  }
  if(wlTrendSortKey!==WL_DEFAULT_TREND_SORT_KEY||wlTrendSortAsc!==wlTrendSortDefaultAsc(wlTrendSortKey)){
    params.set('wlTrendSort',wlTrendSortKey);
    if(wlTrendSortAsc!==wlTrendSortDefaultAsc(wlTrendSortKey)){
      params.set('wlTrendSortAsc',wlTrendSortAsc?'1':'0');
    }
  }
  if(wlPanelCollapsed)params.set('wlCollapsed','1');
  if(wlPanelWidth!==WL_PANEL_DEFAULT_WIDTH)params.set('wlWidth',String(wlPanelWidth));
}
function restoreWatchlistURLState(){
  const resizeDelay=(wlPanelCollapsed||wlPanelWidth!==WL_PANEL_DEFAULT_WIDTH)?250:0;
  applyWatchlistPanelState({syncURL:false,resizeDelay});
  switchWLTab(wlActiveTab,{syncURL:false});
  switchWLTrendFrame(wlTrendFrame,{syncURL:false});
  switchWLTrendSide(wlTrendSide,{syncURL:false});
  switchWLView(wlView,{syncURL:false});
}

const _WL_INDEX_SYMS=new Set(['IXIC','GSPC','DJI','RUT','VIX','NYA','XAX','FTSE','GDAXI','FCHI','N225','HSI','STOXX50E','BVSP','GSPTSE','AXJO','NZ50','KS11','TWII','SSEC','JKSE','KLSE','STI','NSEI','BSESN','TNX','TYX','FVX','IRX','SOX','SPX']);
const _WL_TREASURY_SYMS=new Set([...TREASURY_TICKERS]);
const _WL_SEMI_SYMS=new Set(['ALAB','AMD','ARM','ASML','AVGO','MRVL','MU','NVDA','SNDK','TSM']);
const _WL_SOFTWARE_SYMS=new Set(['CRM','CRWD','NOW','PLTR','SNOW','ZS']);
const _WL_TECH_SYMS=new Set(['AAPL','AMZN','GOOG','HIMS','HOOD','META','MSFT','RKLB','TSLA']);
const _WL_ETF_SYMS=new Set(['ARKK','CPER','IAU','IGV','MAGS','SMH','TLT','USO','VGT','XLE']);
const _WL_CRYPTO_ADJ_SYMS=new Set(['COIN','CRCL','GLXY','HUT','MSTR']);
function wlTickerCategory(t){
  if(watchlistStrategyPreferenceHelpers?.tickerCategory)return watchlistStrategyPreferenceHelpers.tickerCategory(t);
  if(t.endsWith('-USD'))return 'crypto';
  const raw=t.replace(/^\^/,'').toUpperCase();
  if(_WL_TREASURY_SYMS.has(raw))return 'treasuries';
  if(_WL_INDEX_SYMS.has(raw)||t.startsWith('^'))return 'indexes';
  if(_WL_SEMI_SYMS.has(raw))return 'semis';
  if(_WL_SOFTWARE_SYMS.has(raw))return 'software';
  if(_WL_TECH_SYMS.has(raw))return 'tech';
  if(_WL_ETF_SYMS.has(raw))return 'etfs';
  if(_WL_CRYPTO_ADJ_SYMS.has(raw))return 'crypto';
  return 'misc';
}
function wlPreferredStrategyMeta(ticker){
  if(watchlistStrategyPreferenceHelpers?.preferredStrategyMetaForTicker){
    return watchlistStrategyPreferenceHelpers.preferredStrategyMetaForTicker(ticker);
  }
  const category=wlTickerCategory(ticker);
  const fallbackByCategory={
    indexes:{strategyKey:'ema_9_26',strategyLabel:'EMA 9/26 Cross'},
    treasuries:{strategyKey:'trend_sr_macro_v1',strategyLabel:'Trend SR + Macro v1'},
    semis:{strategyKey:'semis_persist_v1',strategyLabel:'Semis Persist v1'},
    tech:{strategyKey:'ema_crossover',strategyLabel:'EMA 5/20 Cross'},
    software:{strategyKey:'trend_sr_macro_v1',strategyLabel:'Trend SR + Macro v1'},
    etfs:{strategyKey:'ribbon',strategyLabel:'Trend-Driven'},
    crypto:{strategyKey:'cci_trend',strategyLabel:'CCI Trend'},
    misc:{strategyKey:'ribbon',strategyLabel:'Trend-Driven'},
  };
  const preferred=fallbackByCategory[category]||fallbackByCategory.misc;
  return{
    category,
    categoryLabel:WL_CATEGORY_LABELS[category]||'General',
    strategyKey:preferred.strategyKey,
    strategyLabel:preferred.strategyLabel,
  };
}
function wlNormalizePreferredStrategyMeta(meta,ticker){
  if(meta?.strategyKey)return meta;
  if(meta?.strategy_key){
    return{
      category:meta.category||wlTickerCategory(ticker),
      categoryLabel:meta.categoryLabel||meta.category_label||WL_CATEGORY_LABELS[meta.category]||WL_CATEGORY_LABELS[wlTickerCategory(ticker)]||'General',
      strategyKey:meta.strategy_key,
      strategyLabel:meta.strategyLabel||meta.strategy_label||meta.strategy_key,
    };
  }
  return wlPreferredStrategyMeta(ticker);
}
function wlResolvePreferredStrategyMeta(row,flips){
  const ticker=row?.ticker||'';
  const preferred=wlNormalizePreferredStrategyMeta(row?.trade_setup?.shared?.preferred_strategy,ticker);
  const availableKeys=getAllFlipKeys(flips);
  if(!availableKeys.length)return preferred;
  if(preferred?.strategyKey&&availableKeys.includes(preferred.strategyKey))return preferred;
  if(availableKeys.includes('ribbon')){
    return{
      category:preferred?.category||wlTickerCategory(ticker),
      categoryLabel:preferred?.categoryLabel||WL_CATEGORY_LABELS[wlTickerCategory(ticker)]||'General',
      strategyKey:'ribbon',
      strategyLabel:'Trend-Driven',
    };
  }
  return{
    category:preferred?.category||wlTickerCategory(ticker),
    categoryLabel:preferred?.categoryLabel||WL_CATEGORY_LABELS[wlTickerCategory(ticker)]||'General',
    strategyKey:availableKeys[0],
    strategyLabel:preferred?.strategyLabel||availableKeys[0],
  };
}
function ensureWLCurrentTickerTab(){
  const currentTicker=wlCurrentTicker();
  if(!currentTicker||wlActiveTab==='all'||!wlList.includes(currentTicker))return;
  const nextTab=wlTickerCategory(currentTicker);
  if(nextTab===wlActiveTab)return;
  wlActiveTab=wlNormalizeTab(nextTab);
  syncWLTabButtons();
}
function ensureWLCurrentTickerTrendSide(){
  const currentTicker=wlCurrentTicker();
  if(!currentTicker||!wlList.includes(currentTicker))return true;
  const row=wlTrendRows.find(item=>item?.ticker===currentTicker);
  if(!row)return false;
  const metaRow=wlTrendRowMeta(row);
  const nextSide=wlNormalizeTrendSide(metaRow?.tradeSetup?.[wlTrendFrame]?.side||metaRow?.[wlTrendFrame]?.meta?.tone);
  if(wlTrendSide==='all'||nextSide===wlTrendSide)return true;
  wlTrendSide=nextSide;
  syncWLTrendSideButtons();
  syncWatchlistURLState();
  return true;
}
function switchWLTab(tab,{syncURL=true}={}){
  wlActiveTab=wlNormalizeTab(tab);
  syncWLTabButtons();
  renderWL(wlList);
  if(syncURL)syncWatchlistURLState();
}
function switchWLView(view,{syncURL=true}={}){
  wlView=wlNormalizeView(view);
  document.querySelectorAll('.wl-view-tab').forEach(b=>b.classList.toggle('active',b.dataset.view===wlView));
  document.getElementById('wl-add-row').style.display=wlView==='watchlist'?'flex':'none';
  document.getElementById('wl-tabs').style.display='flex';
  document.getElementById('wl-trend-tabs').style.display=wlView==='trends'?'flex':'none';
  document.getElementById('wl-trend-side-tabs').style.display=wlView==='trends'?'flex':'none';
  document.getElementById('wl-quote-cols').style.display=wlView==='watchlist'?'grid':'none';
  document.getElementById('wl-trend-cols').style.display=wlView==='trends'?'grid':'none';
  if(syncURL)ensureWLCurrentTickerTab();
  if(wlView==='trends'){
    wlTrendSelectionSyncPending=syncURL&&!ensureWLCurrentTickerTrendSide();
    switchWLTrendFrame(wlTrendFrame,{syncURL:false});
    switchWLTrendSide(wlTrendSide,{syncURL:false});
    fetchTrends();
  }else{
    wlTrendSelectionSyncPending=false;
    stopWLTrendTimers();
  }
  syncWLRefreshTimers();
  renderWL(wlList);
  if(syncURL)syncWatchlistURLState();
}
function wlFilteredList(list){
  if(wlActiveTab==='all')return list;
  return list.filter(t=>wlTickerCategory(t)===wlActiveTab);
}

function wlTreasuryDuration(t){
  const match=t.replace(/^\^/,'').toUpperCase().match(/^UST(\d+)Y$/);
  return match?Number(match[1]):Number.POSITIVE_INFINITY;
}

function wlCompareSymbols(a,b){
  if(wlActiveTab==='treasuries'){
    const da=wlTreasuryDuration(a),db=wlTreasuryDuration(b);
    if(da!==db)return da-db;
  }
  return a.localeCompare(b);
}

function syncWLSortArrows(keys,prefix,activeKey,asc){
  keys.forEach(k=>{
    const arrow=document.getElementById(`${prefix}${k}`);
    const header=arrow?.closest('.wl-sort');
    if(arrow)arrow.textContent=k===activeKey?(asc?' ▲':' ▼'):'';
    if(header)header.classList.toggle('active',k===activeKey);
  });
}

function sortWL(key){
  if(wlSortKey===key){wlSortAsc=!wlSortAsc}else{wlSortKey=key;wlSortAsc=wlSortDefaultAsc(key)}
  syncWLSortArrows(['sym','last','chg','chg_pct'],'wl-arrow-',wlSortKey,wlSortAsc);
  renderWL(wlList);
  syncWatchlistURLState();
}

function sortWLTrends(key){
  if(wlTrendSortKey===key){
    wlTrendSortAsc=!wlTrendSortAsc;
  }else{
    wlTrendSortKey=key;
    wlTrendSortAsc=wlTrendSortDefaultAsc(key);
  }
  syncWLSortArrows(['ticker','flip','strength','score'],'wl-trend-arrow-',wlTrendSortKey,wlTrendSortAsc);
  renderWL(wlList);
  syncWatchlistURLState();
}

function switchWLTrendFrame(frame,{syncURL=true}={}){
  wlTrendFrame=wlNormalizeTrendFrame(frame);
  document.querySelectorAll('.wl-trend-tabs .wl-tab').forEach(b=>{
    b.classList.toggle('active',b.dataset.frame===wlTrendFrame);
  });
  renderWL(wlList);
  if(syncURL)syncWatchlistURLState();
}

function switchWLTrendSide(side,{syncURL=true}={}){
  wlTrendSide=wlNormalizeTrendSide(side);
  syncWLTrendSideButtons();
  if(syncURL)wlTrendSelectionSyncPending=false;
  renderWL(wlList);
  if(syncURL)syncWatchlistURLState();
}

function ensureVisibleWLTab(list){
  if(wlActiveTab==='all'||list.some(t=>wlTickerCategory(t)===wlActiveTab))return;
  const currentTickerTab=wlTickerCategory(document.getElementById('ticker').value.toUpperCase());
  const nextTab=WL_TAB_ORDER.find(tab=>list.some(t=>wlTickerCategory(t)===tab))
    || currentTickerTab;
  if(nextTab)switchWLTab(nextTab);
}

let wlRefreshTimer=null;
let wlQuoteRetryTimer=null;
let wlTrendRefreshTimer=null;
let wlTrendPollTimer=null;
let wlTrendPreloadTimer=null;
let wlIdlePauseTimer=null;
let wlLastActivityAt=Date.now();
let wlLastMouseMoveAt=0;
let wlLifecycleBound=false;
let wlRefreshState='live';
let wlQuotesLoading=false;
let wlQuotesReady=false;

function wlRefreshAllowed(){
  return document.visibilityState!=='hidden'&&(Date.now()-wlLastActivityAt)<WL_IDLE_PAUSE_MS;
}

function setWLRefreshState(state){
  if(wlRefreshState===state)return;
  wlRefreshState=state;
  const el=document.getElementById('wl-refresh-state');
  if(!el)return;
  el.textContent=state==='paused'?'PAUSED':state==='syncing'?'SYNCING':'LIVE';
  el.classList.toggle('paused',state==='paused');
  el.classList.toggle('syncing',state==='syncing');
  el.classList.toggle('live',state==='live');
  el.title=state==='paused'
    ?'Watchlist refresh is paused. Move the mouse or press a key to resume.'
    :state==='syncing'
      ?'Watchlist refresh is resuming...'
      :'Watchlist refresh is live';
}

function syncWLRefreshStateBadge(){
  if(!wlRefreshAllowed()){
    setWLRefreshState('paused');
  }else if(wlQuotesLoading||(wlView==='watchlist'&&wlList.length&&!wlQuotesReady)){
    setWLRefreshState('syncing');
  }else if(wlView==='trends'&&(wlTrendsLoading||wlTrendsStale)){
    setWLRefreshState('syncing');
  }else{
    setWLRefreshState('live');
  }
}

function clearWLQuoteRetryTimer(){
  if(wlQuoteRetryTimer)clearTimeout(wlQuoteRetryTimer);
  wlQuoteRetryTimer=null;
}

function scheduleWLQuoteRetry(){
  if(wlQuoteRetryTimer||!wlRefreshAllowed())return;
  wlQuoteRetryTimer=setTimeout(()=>{
    wlQuoteRetryTimer=null;
    fetchQuotes();
  },WL_QUOTES_RETRY_MS);
}

function stopWLTrendTimers(){
  if(wlTrendRefreshTimer)clearInterval(wlTrendRefreshTimer);
  if(wlTrendPollTimer)clearTimeout(wlTrendPollTimer);
  if(wlTrendPreloadTimer)clearTimeout(wlTrendPreloadTimer);
  wlTrendRefreshTimer=null;
  wlTrendPollTimer=null;
  wlTrendPreloadTimer=null;
}

function stopWLRefreshTimers(){
  if(wlRefreshTimer)clearInterval(wlRefreshTimer);
  wlRefreshTimer=null;
  clearWLQuoteRetryTimer();
  stopWLTrendTimers();
  setWLRefreshState('paused');
}

function scheduleWLIdlePause(){
  if(wlIdlePauseTimer)clearTimeout(wlIdlePauseTimer);
  wlIdlePauseTimer=setTimeout(()=>{
    wlIdlePauseTimer=null;
    stopWLRefreshTimers();
  },WL_IDLE_PAUSE_MS);
}

function syncWLRefreshTimers({forceRefresh=false}={}){
  if(!wlRefreshAllowed()){
    stopWLRefreshTimers();
    return;
  }
  scheduleWLIdlePause();
  if(!wlRefreshTimer){
    wlRefreshTimer=setInterval(fetchQuotes,WL_QUOTES_REFRESH_MS);
  }
  if(wlView==='trends'){
    if(!wlTrendRefreshTimer){
      wlTrendRefreshTimer=setInterval(fetchTrends,WL_TRENDS_REFRESH_MS);
    }
    if(forceRefresh)fetchTrends();
  }else if(wlTrendRefreshTimer){
    clearInterval(wlTrendRefreshTimer);
    wlTrendRefreshTimer=null;
  }
  if(forceRefresh)setWLRefreshState('syncing');
  else syncWLRefreshStateBadge();
  if(forceRefresh){
    fetchQuotes();
    if(wlView!=='trends')queueWatchlistTrendPreload();
  }
}

function markWLActivity({forceRefresh=false}={}){
  const shouldRefresh=forceRefresh||!wlRefreshTimer||(wlView==='trends'&&!wlTrendRefreshTimer);
  wlLastActivityAt=Date.now();
  if(document.visibilityState==='hidden'){
    stopWLRefreshTimers();
    return;
  }
  syncWLRefreshTimers({forceRefresh:shouldRefresh});
}

function bindWLLifecycle(){
  if(wlLifecycleBound)return;
  wlLifecycleBound=true;
  ['pointerdown','keydown','wheel','touchstart'].forEach(evt=>{
    document.addEventListener(evt,()=>markWLActivity(),{passive:true});
  });
  document.addEventListener('mousemove',()=>{
    const now=Date.now();
    if((now-wlLastMouseMoveAt)<WL_MOUSEMOVE_ACTIVITY_MS)return;
    wlLastMouseMoveAt=now;
    markWLActivity();
  },{passive:true});
  window.addEventListener('focus',()=>markWLActivity({forceRefresh:true}));
  document.addEventListener('visibilitychange',()=>{
    if(document.visibilityState==='hidden'){
      stopWLRefreshTimers();
    }else{
      markWLActivity({forceRefresh:true});
    }
  });
  scheduleWLIdlePause();
}

async function loadWL(){
  bindWLLifecycle();
  try{
    const r=await fetch('/api/watchlist');
    const list=await r.json();
    wlList=list;
    ensureVisibleWLTab(list);
    renderWL(list);
    markWLActivity({forceRefresh:true});
  }catch(err){
    document.getElementById('wl-count').textContent='0';
    document.getElementById('wl-items').innerHTML='<div class="wl-trend-msg">Unable to load watchlist.</div>';
  }
}

function queueWatchlistTrendPreload(delayMs=1500){
  if(!wlRefreshAllowed()||wlView==='trends'||wlTrendRows.length||wlTrendsLoading)return;
  if(wlTrendPreloadTimer) clearTimeout(wlTrendPreloadTimer);
  wlTrendPreloadTimer=setTimeout(()=>{
    wlTrendPreloadTimer=null;
    if(wlRefreshAllowed()&&wlView!=='trends'&&!wlTrendRows.length&&!wlTrendsLoading){
      fetchTrends();
    }
  },delayMs);
}

// --- Neighbour chart preload ---
// After the current chart has rendered, quietly warm the `/api/chart` cache
// for the watchlist tickers immediately above and below the current one.
// The response is discarded — the backend's memory+disk caches are the whole
// point. This cuts the first-click latency when the user clicks a neighbour.
let wlChartPreloadTimer=null;
let wlChartPreloadController=null;

function queueWatchlistChartPreload(delayMs=3000){
  if(!wlRefreshAllowed())return;
  // Respect data-saver / metered connections.
  if(typeof navigator!=='undefined'&&navigator.connection&&navigator.connection.saveData)return;
  if(!Array.isArray(wlList)||wlList.length<2)return;
  if(wlChartPreloadTimer)clearTimeout(wlChartPreloadTimer);
  // Abort any in-flight preloads from a previous ticker switch.
  if(wlChartPreloadController){
    try{wlChartPreloadController.abort();}catch(_e){}
    wlChartPreloadController=null;
  }
  wlChartPreloadTimer=setTimeout(()=>{
    wlChartPreloadTimer=null;
    if(!wlRefreshAllowed())return;
    const cur=(document.getElementById('ticker')?.value||'').toUpperCase();
    if(!cur)return;
    const idx=wlList.findIndex(t=>String(t).toUpperCase()===cur);
    if(idx<0)return;
    const neighbours=[];
    if(idx-1>=0)neighbours.push(wlList[idx-1]);
    if(idx+1<wlList.length)neighbours.push(wlList[idx+1]);
    if(!neighbours.length)return;
    const interval=document.getElementById('interval')?.value||'1d';
    const period=document.getElementById('period')?.value||'10';
    const mult=document.getElementById('multiplier')?.value||'2.5';
    const start=(typeof chartStart!=='undefined'&&chartStart)||'2015-01-01';
    const end=(typeof chartEnd!=='undefined'&&chartEnd)||'';
    const controller=(typeof AbortController!=='undefined')?new AbortController():null;
    wlChartPreloadController=controller;
    neighbours.forEach(t=>{
      try{
        const url=(typeof buildChartRequestUrl==='function')
          ? buildChartRequestUrl(String(t).toUpperCase(),interval,start,end,period,mult,{candlesOnly:false,includeMM:true})
          : `/api/chart?ticker=${encodeURIComponent(String(t).toUpperCase())}&interval=${encodeURIComponent(interval)}&start=${encodeURIComponent(start)}&period=${encodeURIComponent(period)}&multiplier=${encodeURIComponent(mult)}${end?`&end=${encodeURIComponent(end)}`:''}`;
        fetch(url,controller?{signal:controller.signal}:undefined).catch(()=>{});
      }catch(_e){}
    });
  },delayMs);
}

function fetchQuotes(){
  if(!wlRefreshAllowed()){
    stopWLRefreshTimers();
    return;
  }
  if(wlQuotesLoading)return;
  wlQuotesLoading=true;
  syncWLRefreshStateBadge();
  fetch('/api/watchlist/quotes')
    .then(r=>{
      if(!r.ok)throw new Error(`Watchlist quotes request failed: ${r.status}`);
      return r.json();
    })
    .then(quotes=>{
      if(!Array.isArray(quotes))throw new Error('Watchlist quotes payload was not an array');
      clearWLQuoteRetryTimer();
      let hasAnyQuote=false;
      let hasMissingQuote=false;
      quotes.forEach(q=>{wlQuotes[q.ticker]=q});
      quotes.forEach(q=>{
        if(q?.last!=null)hasAnyQuote=true;
        else hasMissingQuote=true;
      });
      wlQuotesReady=hasAnyQuote||!quotes.length;
      renderWL(wlList);
      if((!quotes.length&&wlList.length)||hasMissingQuote||(!hasAnyQuote&&wlList.length)){
        scheduleWLQuoteRetry();
      }
      syncWLRefreshStateBadge();
    })
    .catch(()=>{
      scheduleWLQuoteRetry();
      syncWLRefreshStateBadge();
    })
    .finally(()=>{
      wlQuotesLoading=false;
      syncWLRefreshStateBadge();
    });
}

function fetchTrends(){
  if(!wlRefreshAllowed()){
    stopWLRefreshTimers();
    return;
  }
  fetch('/api/watchlist/trends')
    .then(r=>r.json())
    .then(payload=>{
      wlTrendRows=Array.isArray(payload.items)?payload.items:[];
      wlTrendsLoading=!!payload.loading;
      wlTrendsStale=!!payload.stale;
      if(wlView==='trends'&&wlTrendSelectionSyncPending){
        wlTrendSelectionSyncPending=!ensureWLCurrentTickerTrendSide();
      }
      renderWL(wlList);
      if(wlTrendPollTimer) clearTimeout(wlTrendPollTimer);
      wlTrendPollTimer=null;
      if(wlView==='trends'&&wlRefreshAllowed()&&(wlTrendsLoading||wlTrendsStale)){
        wlTrendPollTimer=setTimeout(fetchTrends,WL_TRENDS_POLL_MS);
      }
      syncWLRefreshStateBadge();
    })
    .catch(()=>syncWLRefreshStateBadge());
}

function wlTrendFrameFlip(frameFlips,preferredMeta,tradeSetup){
  const strategyKey=preferredMeta?.strategyKey;
  const preferredFlip=(frameFlips?.[strategyKey])||{};
  const dir=preferredFlip.current_dir||preferredFlip.dir||null;
  const date=preferredFlip.regime_start_date||preferredFlip.current_state_date||preferredFlip.date||null;
  const age=date?daysSinceNumber({date}):null;
  const tone=dir==='bullish'?'bullish':dir==='bearish'?'bearish':'mixed';
  const score=tradeSetup?.trend_bias ?? (dir==='bullish'?100:dir==='bearish'?-100:null);
  return{
    key:strategyKey||null,
    label:preferredMeta?.strategyLabel||'Preferred strategy',
    dir,
    date,
    meta:{
      label:dir==='bullish'?'Bullish':dir==='bearish'?'Bearish':'No data',
      tone,
      coveragePct:dir?100:0,
      score:score??0,
    },
    score,
    tradeScore:tradeSetup?.score??null,
    age,
    dateValue:date?Date.parse(`${date}T00:00:00Z`):-Infinity,
  };
}

function wlTradeSetupFrame(row,frame){
  return row?.trade_setup?.[frame]||{};
}

function wlTrendRowMeta(row){
  const flips={daily:row.daily||{},weekly:row.weekly||{}};
  const preferredStrategy=wlResolvePreferredStrategyMeta(row,flips);
  const keys=getAllFlipKeys(flips);
  if(!keys.length){
    return{
      ticker:row.ticker,
      category:wlTickerCategory(row.ticker),
      daily:{key:null,dir:null,date:null,score:null,tradeScore:null,age:null,dateValue:-Infinity,meta:{tone:'mixed'}},
      weekly:{key:null,dir:null,date:null,score:null,tradeScore:null,age:null,dateValue:-Infinity,meta:{tone:'mixed'}},
      flips,
      tradeSetup:row.trade_setup||{},
      preferredStrategy,
      freshness:Number.POSITIVE_INFINITY,
    };
  }
  const dailySetup=wlTradeSetupFrame(row,'daily');
  const weeklySetup=wlTradeSetupFrame(row,'weekly');
  const daily=wlTrendFrameFlip(flips.daily,preferredStrategy,dailySetup);
  const weekly=wlTrendFrameFlip(flips.weekly,preferredStrategy,weeklySetup);
  return{
    ticker:row.ticker,
    category:wlTickerCategory(row.ticker),
    daily,
    weekly,
    flips,
    tradeSetup:row.trade_setup||{},
    preferredStrategy,
  };
}

function renderTrends(){
  const cur=document.getElementById('ticker').value.toUpperCase();
  syncWLSortArrows(['ticker','flip','strength','score'],'wl-trend-arrow-',wlTrendSortKey,wlTrendSortAsc);
  const rows=(wlTrendRows||[])
    .filter(row=>wlActiveTab==='all'||wlTickerCategory(row?.ticker||'')===wlActiveTab)
    .map(wlTrendRowMeta)
    .sort((a,b)=>{
    const aFrame=a[wlTrendFrame]||{};
    const bFrame=b[wlTrendFrame]||{};
    const aStrength=aFrame.score;
    const bStrength=bFrame.score;
    const aScore=aFrame.tradeScore??aFrame.score;
    const bScore=bFrame.tradeScore??bFrame.score;
    let delta=0;
    if(wlTrendSortKey==='ticker'){
      delta=a.ticker.localeCompare(b.ticker);
    }else if(wlTrendSortKey==='flip'){
      delta=(aFrame.dateValue??-Infinity)-(bFrame.dateValue??-Infinity);
      if(delta===0){
        const absA=aScore==null?-1:Math.abs(aScore);
        const absB=bScore==null?-1:Math.abs(bScore);
        delta=absA-absB;
        if(delta===0){
          delta=(aFrame.meta?.coveragePct??-1)-(bFrame.meta?.coveragePct??-1);
        }
      }
    }else if(wlTrendSortKey==='strength'){
      const absA=aStrength==null?-1:Math.abs(aStrength);
      const absB=bStrength==null?-1:Math.abs(bStrength);
      delta=absA-absB;
      if(delta===0)delta=(aStrength??-999)-(bStrength??-999);
      if(delta===0){
        delta=(aFrame.meta?.coveragePct??-1)-(bFrame.meta?.coveragePct??-1);
      }
    }else{
      const absA=aScore==null?-1:Math.abs(aScore);
      const absB=bScore==null?-1:Math.abs(bScore);
      delta=absA-absB;
      if(delta===0)delta=(aScore??-999)-(bScore??-999);
      if(delta===0){
        delta=(aFrame.meta?.coveragePct??-1)-(bFrame.meta?.coveragePct??-1);
      }
    }
    if(delta!==0)return wlTrendSortAsc?delta:-delta;
    if((aFrame.age??Number.POSITIVE_INFINITY)!==(bFrame.age??Number.POSITIVE_INFINITY)){
      return (aFrame.age??Number.POSITIVE_INFINITY)-(bFrame.age??Number.POSITIVE_INFINITY);
    }
    return a.ticker.localeCompare(b.ticker);
  });
  const categoryCount=wlActiveTab==='all'?wlList.length:wlList.filter(t=>wlTickerCategory(t)===wlActiveTab).length;
  document.getElementById('wl-count').textContent=(wlTrendsLoading&&categoryCount)?categoryCount:rows.length;
  if(!rows.length){
    const statusText=wlTrendsLoading?'Loading trend pulse for your watchlist...':'No trend data available yet.';
    document.getElementById('wl-items').innerHTML=`<div class="wl-trend-msg">${statusText}</div>`;
    return;
  }
  const statusRow=wlTrendsLoading||wlTrendsStale
    ?`<div class="wl-trend-msg">${wlTrendsLoading?'Refreshing trend pulse...':'Trend pulse is updating...'}</div>`
    :'';
  const visibleRows=rows.filter(row=>{
    if(wlTrendSide==='all')return true;
    const setupSide=row?.tradeSetup?.[wlTrendFrame]?.side;
    const tone=row[wlTrendFrame]?.meta?.tone||'mixed';
    return (setupSide||tone)===wlTrendSide;
  });
  document.getElementById('wl-count').textContent=visibleRows.length;
  document.getElementById('wl-items').innerHTML=statusRow
    +(visibleRows.length?visibleRows.map(row=>wlTrendRowHtml(row,cur)).join(''):`<div class="wl-trend-msg">No ${wlTrendSide==='all'?'trend pulse':wlTrendSide} symbols in ${wlTrendFrame} trends.</div>`);
}

function wlTrendRowHtml(row,cur){
  const flip=row[wlTrendFrame]||{};
  const setup=row?.tradeSetup?.[wlTrendFrame]||{};
  const strengthValue=flip.score;
  const displayScore=setup.score??flip.tradeScore??flip.score;
  const strength=strengthValue==null?'--':`${strengthValue>0?'+':''}${strengthValue}`;
  const score=displayScore==null?'--':`${displayScore>0?'+':''}${displayScore}`;
  const tone=setup.side||flip.meta?.tone||'mixed';
  const cls=tone==='bullish'?'up':tone==='bearish'?'dn':'';
  return `<div class="wl-trend-row${row.ticker===cur?' active':''}">
    <div class="wl-tk wl-trend-symbol" onclick="event.stopPropagation();pickTicker('${row.ticker}')"><span>${row.ticker}</span></div>
    <div class="wl-trend-cell" onclick="event.stopPropagation();openTrendPulse('${row.ticker}')">${wlTrendCellHtml(flip,row.preferredStrategy)}</div>
    <div class="wl-v wl-trend-score ${cls}" onclick="event.stopPropagation();openTrendPulse('${row.ticker}')">${strength}</div>
    <div class="wl-v wl-trend-score ${cls}" onclick="event.stopPropagation();openWatchlistTradeScore('${row.ticker}')">${score}</div>
  </div>`;
}

function wlTrendCellHtml(f,preferredStrategy){
  if(!f?.dir)return'<span class="wl-trend-flip">--</span>';
  const tone=f.dir==='bullish'?'up':'dn';
  const age=f.age==null?daysSinceNumber(f):f.age;
  const fullDate=flipDateLabel(f);
  const shortDate=fullDate.replace(/\s+\d{4}$/,'');
  const label=preferredStrategy?.strategyLabel||f.label||'Preferred strategy';
  return `<span class="wl-trend-flip ${tone}" title="${label} · ${fullDate}">${age==null?'--':age+'d'} ${shortDate}</span>`;
}

function renderWL(list){
  if(wlView==='trends'){
    renderTrends();
    return;
  }
  syncWLSortArrows(['sym','last','chg','chg_pct'],'wl-arrow-',wlSortKey,wlSortAsc);
  const filtered=wlFilteredList(list);
  document.getElementById('wl-count').textContent=filtered.length;
  if(wlSortKey){
    filtered.sort((a,b)=>{
      let va,vb;
      if(wlSortKey==='sym')return wlSortAsc?wlCompareSymbols(a,b):wlCompareSymbols(b,a);
      else{const qa=wlQuotes[a]||{},qb=wlQuotes[b]||{};va=qa[wlSortKey]??-Infinity;vb=qb[wlSortKey]??-Infinity}
      if(typeof va==='string') return wlSortAsc?va.localeCompare(vb):vb.localeCompare(va);
      return wlSortAsc?va-vb:vb-va;
    });
  }else if(wlActiveTab==='treasuries'){
    filtered.sort(wlCompareSymbols);
  }
  const cur=document.getElementById('ticker').value.toUpperCase();
  document.getElementById('wl-items').innerHTML=filtered.map(t=>{
    const q=wlQuotes[t]||{};
    const up=q.chg>=0;
    const cls=up?'up':'dn';
    return `<div class="wl-swipe-wrap" data-ticker="${t}">
      <div class="wl-del-bg" onclick="event.stopPropagation();rmWL('${t}')">DELETE</div>
      <div class="wl-row${t===cur?' active':''}" onclick="pickTicker('${t}')">
        <div class="wl-tk"><span>${t}</span></div>
        <div class="wl-v last">${formatLastDisplay(t,q.last)}</div>
        <div class="wl-v ${q.chg!=null?cls:''}">${formatChangeDisplay(q.chg)}</div>
        <div class="wl-v ${q.chg_pct!=null?cls:''}">${q.chg_pct!=null?(up?'+':'')+q.chg_pct+'%':'--'}</div>
      </div>
    </div>`;
  }).join('');
  initSwipeHandlers();
}

function initSwipeHandlers(){
  document.querySelectorAll('.wl-swipe-wrap').forEach(wrap=>{
    const row=wrap.querySelector('.wl-row');
    let startX=0,currentX=0,dragging=false;
    const THRESHOLD=60;

    let didSwipe=false;
    function onStart(x){startX=x;currentX=x;dragging=true;didSwipe=false;row.classList.add('swiping')}
    function onMove(x){
      if(!dragging)return;
      currentX=x;
      const dx=Math.min(0,currentX-startX); // only allow left swipe
      if(Math.abs(currentX-startX)>5) didSwipe=true;
      row.style.transform=`translateX(${dx}px)`;
    }
    function onEnd(){
      if(!dragging)return;
      dragging=false;
      row.classList.remove('swiping');
      const dx=currentX-startX;
      if(dx<-THRESHOLD){
        row.style.transform='translateX(-80px)';
        // Close other open rows
        document.querySelectorAll('.wl-swipe-wrap').forEach(other=>{
          if(other!==wrap){
            const r=other.querySelector('.wl-row');
            r.style.transform='';
          }
        });
      }else{
        row.style.transform='';
      }
    }

    // Suppress click if user swiped
    row.addEventListener('click',e=>{if(didSwipe){e.stopImmediatePropagation();e.preventDefault()}},true);

    // Mouse events
    row.addEventListener('mousedown',e=>{onStart(e.clientX)});
    row.addEventListener('mousemove',e=>{if(dragging){e.preventDefault();onMove(e.clientX)}});
    row.addEventListener('mouseup',onEnd);
    row.addEventListener('mouseleave',onEnd);

    // Touch events
    row.addEventListener('touchstart',e=>{onStart(e.touches[0].clientX)},{passive:true});
    row.addEventListener('touchmove',e=>{onMove(e.touches[0].clientX)},{passive:true});
    row.addEventListener('touchend',onEnd);
  });
  // Close all swipes when clicking elsewhere
  document.addEventListener('click',e=>{
    if(!e.target.closest('.wl-swipe-wrap')){
      document.querySelectorAll('.wl-row').forEach(r=>r.style.transform='');
    }
  });
}

async function addWL(){
  const inp=document.getElementById('wl-input'),t=inp.value.trim().toUpperCase();
  if(!t)return;
  await fetch('/api/watchlist',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ticker:t})});
  inp.value='';switchWLTab(wlTickerCategory(t));loadWL();
}
async function rmWL(t){
  await fetch('/api/watchlist',{method:'DELETE',headers:{'Content-Type':'application/json'},body:JSON.stringify({ticker:t})});
  loadWL();
}
async function pickTicker(t){
  document.getElementById('ticker').value=t;
  renderWL(wlList);
  await loadChart();
}

async function openTrendPulse(t){
  const row=wlTrendRows.find(item=>item?.ticker===t);
  if(row?.daily||row?.weekly){
    document.getElementById('ticker').value=t;
    lastData={...(lastData||{}),trend_flips:{daily:row.daily||{},weekly:row.weekly||{}},trade_setup:row.trade_setup||{}};
    updateFlipInfo();
    if(typeof openTrendFlipAggregate==='function')openTrendFlipAggregate();
    renderWL(wlList);
  }
  await pickTicker(t);
  if(row?.trade_setup){
    lastData={...(lastData||{}),trade_setup:row.trade_setup||{}};
    updateFlipInfo();
  }
  if(typeof openTrendFlipAggregate==='function')openTrendFlipAggregate();
}

// === RESIZABLE WATCHLIST ===
(function(){
  const drag=document.getElementById('wl-drag'),panel=document.getElementById('wl-panel');
  let startX,startW;
  drag.addEventListener('mousedown',e=>{
    startX=e.clientX;startW=panel.offsetWidth;
    const move=ev=>{
      const dx=startX-ev.clientX;
      wlPanelWidth=wlNormalizeWidth(startW+dx);
      panel.style.width=`${wlPanelWidth}px`;
      resizeWatchlistChart();
    };
    const up=()=>{
      document.removeEventListener('mousemove',move);
      document.removeEventListener('mouseup',up);
      syncWatchlistURLState();
      setTimeout(resizeWatchlistChart,250);
    };
    document.addEventListener('mousemove',move);document.addEventListener('mouseup',up);
    e.preventDefault();
  });
})();
