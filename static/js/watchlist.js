// === WATCHLIST ===
function toggleWatchlist(){
  const panel=document.getElementById('wl-panel');
  const btn=document.getElementById('wl-toggle');
  const collapsed=!panel.classList.contains('collapsed');
  panel.classList.toggle('collapsed',collapsed);
  btn.innerHTML=collapsed?'&#9664;':'&#9654;';
  btn.title=collapsed?'Show Watchlist':'Hide Watchlist';
  setTimeout(()=>{
    chart.applyOptions({width:document.getElementById('chart-container').clientWidth,height:document.getElementById('chart-container').clientHeight});
  },250);
}

let wlQuotes={};
let wlList=[];
let wlSortKey=null; // 'sym','last','chg','chg_pct'
let wlSortAsc=true;
let wlTrendFrame='daily';
let wlTrendSortKey='score'; // 'ticker','flip','score'
let wlTrendSortAsc=false;
let wlView='watchlist';
let wlActiveTab='indexes';
let wlTrendRows=[];
let wlTrendsLoading=false;
let wlTrendsStale=false;
const WL_TAB_ORDER=['indexes','treasuries','semis','tech','software','etfs','crypto','misc'];
const WL_CATEGORY_LABELS={indexes:'Index',treasuries:'Rates',semis:'Semis',tech:'Tech',software:'Software',etfs:'ETF',crypto:'Crypto',misc:'Misc'};

const _WL_INDEX_SYMS=new Set(['IXIC','GSPC','DJI','RUT','VIX','NYA','XAX','FTSE','GDAXI','FCHI','N225','HSI','STOXX50E','BVSP','GSPTSE','AXJO','NZ50','KS11','TWII','SSEC','JKSE','KLSE','STI','NSEI','BSESN','TNX','TYX','FVX','IRX','SOX','SPX']);
const _WL_TREASURY_SYMS=new Set([...TREASURY_TICKERS]);
const _WL_SEMI_SYMS=new Set(['ALAB','AMD','ARM','ASML','AVGO','MRVL','MU','NVDA','SNDK','TSM']);
const _WL_SOFTWARE_SYMS=new Set(['CRM','NOW','PLTR','SNOW']);
const _WL_TECH_SYMS=new Set(['AAPL','AMZN','GOOG','HIMS','HOOD','META','MSFT','RKLB','TSLA']);
const _WL_ETF_SYMS=new Set(['ARKK','CPER','IAU','IGV','MAGS','SMH','TLT','USO','VGT','XLE']);
const _WL_CRYPTO_ADJ_SYMS=new Set(['COIN','CRCL','GLXY','HUT','MSTR']);
function wlTickerCategory(t){
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
function switchWLTab(tab){
  wlActiveTab=tab;
  document.querySelectorAll('#wl-tabs .wl-tab').forEach(b=>b.classList.toggle('active',b.dataset.tab===tab));
  renderWL(wlList);
}
function switchWLView(view){
  wlView=view==='trends'?'trends':'watchlist';
  document.querySelectorAll('.wl-view-tab').forEach(b=>b.classList.toggle('active',b.dataset.view===wlView));
  document.getElementById('wl-add-row').style.display=wlView==='watchlist'?'flex':'none';
  document.getElementById('wl-tabs').style.display=wlView==='watchlist'?'flex':'none';
  document.getElementById('wl-trend-tabs').style.display=wlView==='trends'?'flex':'none';
  document.getElementById('wl-quote-cols').style.display=wlView==='watchlist'?'grid':'none';
  document.getElementById('wl-trend-cols').style.display=wlView==='trends'?'grid':'none';
  if(wlView==='trends'){
    switchWLTrendFrame(wlTrendFrame);
    fetchTrends();
  }
  renderWL(wlList);
}
function wlFilteredList(list){return list.filter(t=>wlTickerCategory(t)===wlActiveTab)}

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
  if(wlSortKey===key){wlSortAsc=!wlSortAsc}else{wlSortKey=key;wlSortAsc=key==='sym'}
  syncWLSortArrows(['sym','last','chg','chg_pct'],'wl-arrow-',wlSortKey,wlSortAsc);
  renderWL(wlList);
}

function sortWLTrends(key){
  if(wlTrendSortKey===key){
    wlTrendSortAsc=!wlTrendSortAsc;
  }else{
    wlTrendSortKey=key;
    wlTrendSortAsc=key==='ticker';
  }
  syncWLSortArrows(['ticker','flip','score'],'wl-trend-arrow-',wlTrendSortKey,wlTrendSortAsc);
  renderWL(wlList);
}

function switchWLTrendFrame(frame){
  wlTrendFrame=frame==='weekly'?'weekly':'daily';
  document.querySelectorAll('.wl-trend-tabs .wl-tab').forEach(b=>{
    b.classList.toggle('active',b.dataset.frame===wlTrendFrame);
  });
  renderWL(wlList);
}

function ensureVisibleWLTab(list){
  if(list.some(t=>wlTickerCategory(t)===wlActiveTab))return;
  const currentTickerTab=wlTickerCategory(document.getElementById('ticker').value.toUpperCase());
  const nextTab=WL_TAB_ORDER.find(tab=>list.some(t=>wlTickerCategory(t)===tab))
    || currentTickerTab;
  if(nextTab)switchWLTab(nextTab);
}

let wlRefreshTimer=null;
let wlTrendRefreshTimer=null;
let wlTrendPollTimer=null;
let wlTrendPreloadTimer=null;
async function loadWL(){
  try{
    const r=await fetch('/api/watchlist');
    const list=await r.json();
    wlList=list;
    ensureVisibleWLTab(list);
    renderWL(list);
    fetchQuotes();
    if(wlRefreshTimer) clearInterval(wlRefreshTimer);
    wlRefreshTimer=setInterval(fetchQuotes,300000);
    if(wlTrendRefreshTimer) clearInterval(wlTrendRefreshTimer);
    wlTrendRefreshTimer=setInterval(fetchTrends,300000);
  }catch(err){
    document.getElementById('wl-count').textContent='0';
    document.getElementById('wl-items').innerHTML='<div class="wl-trend-msg">Unable to load watchlist.</div>';
  }
}

function queueWatchlistTrendPreload(delayMs=1500){
  if(wlView==='trends'||wlTrendRows.length||wlTrendsLoading)return;
  if(wlTrendPreloadTimer) clearTimeout(wlTrendPreloadTimer);
  wlTrendPreloadTimer=setTimeout(()=>{
    wlTrendPreloadTimer=null;
    if(wlView!=='trends'&&!wlTrendRows.length&&!wlTrendsLoading){
      fetchTrends();
    }
  },delayMs);
}

function fetchQuotes(){
  fetch('/api/watchlist/quotes')
    .then(r=>r.json())
    .then(quotes=>{
      quotes.forEach(q=>{wlQuotes[q.ticker]=q});
      renderWL(wlList);
    })
    .catch(()=>{});
}

function fetchTrends(){
  fetch('/api/watchlist/trends')
    .then(r=>r.json())
    .then(payload=>{
      wlTrendRows=Array.isArray(payload.items)?payload.items:[];
      wlTrendsLoading=!!payload.loading;
      wlTrendsStale=!!payload.stale;
      renderWL(wlList);
      if(wlTrendPollTimer) clearTimeout(wlTrendPollTimer);
      if(wlTrendsLoading||wlTrendsStale){
        wlTrendPollTimer=setTimeout(fetchTrends,4000);
      }
    })
    .catch(()=>{});
}

function wlTrendFrameFlip(frameFlips,keys,weights,summary){
  summary=summary||frameSummary(frameFlips,keys,weights);
  if(!summary.total)return{dir:null,date:null,meta:summary.meta,score:null,age:null,dateValue:-Infinity};
  const dir=summary.bullish>=summary.bearish?'bullish':'bearish';
  let bestFlip={dir:null,date:null};
  let bestAge=Number.POSITIVE_INFINITY;
  keys.forEach(key=>{
    const flip=frameFlips?.[key];
    const age=daysSinceNumber(flip);
    if(flip?.dir===dir&&flip?.date&&age!=null&&age<bestAge){
      bestFlip={dir:flip.dir,date:flip.date};
      bestAge=age;
    }
  });
  return{
    ...bestFlip,
    meta:summary.meta,
    score:summary.meta.score,
    age:bestAge===Number.POSITIVE_INFINITY?null:bestAge,
    dateValue:bestFlip.date?Date.parse(`${bestFlip.date}T00:00:00Z`):-Infinity,
  };
}

function wlTrendRowMeta(row){
  const flips={daily:row.daily||{},weekly:row.weekly||{}};
  const keys=getAllFlipKeys(flips);
  if(!keys.length){
    return{
      ticker:row.ticker,
      category:wlTickerCategory(row.ticker),
      daily:{dir:null,date:null,score:null,age:null,dateValue:-Infinity,meta:{tone:'mixed'}},
      weekly:{dir:null,date:null,score:null,age:null,dateValue:-Infinity,meta:{tone:'mixed'}},
      freshness:Number.POSITIVE_INFINITY,
    };
  }
  const weights=trendPulseWeights(keys,'weighted',wlTickerCategory(row.ticker));
  const dailySummary=frameSummary(flips.daily,keys,weights);
  const weeklySummary=frameSummary(flips.weekly,keys,weights);
  const daily=wlTrendFrameFlip(flips.daily,keys,weights,dailySummary);
  const weekly=wlTrendFrameFlip(flips.weekly,keys,weights,weeklySummary);
  return{
    ticker:row.ticker,
    category:wlTickerCategory(row.ticker),
    daily,
    weekly,
  };
}

function renderTrends(){
  const cur=document.getElementById('ticker').value.toUpperCase();
  syncWLSortArrows(['ticker','flip','score'],'wl-trend-arrow-',wlTrendSortKey,wlTrendSortAsc);
  const rows=(wlTrendRows||[]).map(wlTrendRowMeta).sort((a,b)=>{
    const aFrame=a[wlTrendFrame]||{};
    const bFrame=b[wlTrendFrame]||{};
    let delta=0;
    if(wlTrendSortKey==='ticker'){
      delta=a.ticker.localeCompare(b.ticker);
    }else if(wlTrendSortKey==='flip'){
      delta=(aFrame.dateValue??-Infinity)-(bFrame.dateValue??-Infinity);
      if(delta===0){
        const absA=aFrame.score==null?-1:Math.abs(aFrame.score);
        const absB=bFrame.score==null?-1:Math.abs(bFrame.score);
        delta=absA-absB;
      }
    }else{
      const absA=aFrame.score==null?-1:Math.abs(aFrame.score);
      const absB=bFrame.score==null?-1:Math.abs(bFrame.score);
      delta=absA-absB;
      if(delta===0)delta=(aFrame.score??-999)-(bFrame.score??-999);
    }
    if(delta!==0)return wlTrendSortAsc?delta:-delta;
    if((aFrame.age??Number.POSITIVE_INFINITY)!==(bFrame.age??Number.POSITIVE_INFINITY)){
      return (aFrame.age??Number.POSITIVE_INFINITY)-(bFrame.age??Number.POSITIVE_INFINITY);
    }
    return a.ticker.localeCompare(b.ticker);
  });
  document.getElementById('wl-count').textContent=(wlTrendsLoading&&wlList.length)?wlList.length:rows.length;
  if(!rows.length){
    const statusText=wlTrendsLoading?'Loading trend pulse for your watchlist...':'No trend data available yet.';
    document.getElementById('wl-items').innerHTML=`<div class="wl-trend-msg">${statusText}</div>`;
    return;
  }
  const statusRow=wlTrendsLoading||wlTrendsStale
    ?`<div class="wl-trend-msg">${wlTrendsLoading?'Refreshing trend pulse...':'Trend pulse is updating...'}</div>`
    :'';
  document.getElementById('wl-items').innerHTML=statusRow+rows.map(row=>{
    const flip=row[wlTrendFrame]||{};
    const score=flip.score==null?'--':`${flip.score>0?'+':''}${flip.score}`;
    const tone=flip.meta?.tone||'mixed';
    const scoreCls=tone==='bullish'?'bull':tone==='bearish'?'bear':'';
    return `<div class="wl-trend-row${row.ticker===cur?' active':''}">
      <div class="wl-trend-symbol" onclick="event.stopPropagation();pickTicker('${row.ticker}')">
        <strong>${row.ticker}</strong>
        <span class="wl-trend-cat">${WL_CATEGORY_LABELS[row.category]||row.category}</span>
      </div>
      <div class="wl-trend-cell" onclick="event.stopPropagation();openTrendPulse('${row.ticker}')">${wlTrendCellHtml(flip)}</div>
      <div class="wl-trend-score ${scoreCls}" onclick="event.stopPropagation();openTrendPulse('${row.ticker}')">
        <span class="wl-trend-score-val">${score}</span>
        <span class="wl-trend-score-track"><span class="wl-trend-score-fill" style="width:${Math.min(100,Math.abs(flip.score||0))}%"></span></span>
      </div>
    </div>`;
  }).join('');
}

function wlTrendCellHtml(f){
  if(!f?.dir)return'<span class="tf-cell wl-trend-pill wl-trend-pill-empty"><span class="wl-trend-age">--</span><span class="tf-flip-date">No flip</span></span>';
  const tone=f.dir==='bullish'?'bull':'bear';
  const age=f.age==null?daysSinceNumber(f):f.age;
  const fullDate=flipDateLabel(f);
  const shortDate=fullDate.replace(/\s+\d{4}$/,'');
  return `<span class="tf-cell tf-cell-${tone} wl-trend-pill">
    <span class="wl-trend-pill-top">
      <span class="wl-trend-age">${age==null?'--':age+'d'}</span>
      <span class="wl-trend-dir">${f.dir==='bullish'?'Bull':'Bear'}</span>
    </span>
    <span class="tf-flip-date" title="${fullDate}">${shortDate}</span>
  </span>`;
}

function renderWL(list){
  if(wlView==='trends'){
    renderTrends();
    return;
  }
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
  await pickTicker(t);
  if(typeof openTrendFlipAggregate==='function')openTrendFlipAggregate();
}

// === RESIZABLE WATCHLIST ===
(function(){
  const drag=document.getElementById('wl-drag'),panel=document.getElementById('wl-panel');
  let startX,startW;
  drag.addEventListener('mousedown',e=>{
    startX=e.clientX;startW=panel.offsetWidth;
    const move=ev=>{const dx=startX-ev.clientX;panel.style.width=Math.max(320,Math.min(540,startW+dx))+'px'};
    const up=()=>{document.removeEventListener('mousemove',move);document.removeEventListener('mouseup',up)};
    document.addEventListener('mousemove',move);document.addEventListener('mouseup',up);
    e.preventDefault();
  });
})();
