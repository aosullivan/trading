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
let wlActiveTab='indexes';
const WL_TAB_ORDER=['indexes','treasuries','semis','tech','software','etfs','crypto','misc'];

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
  document.querySelectorAll('.wl-tab').forEach(b=>b.classList.toggle('active',b.dataset.tab===tab));
  renderWL(wlList);
}
function wlFilteredList(list){return list.filter(t=>wlTickerCategory(t)===wlActiveTab)}

function sortWL(key){
  if(wlSortKey===key){wlSortAsc=!wlSortAsc}else{wlSortKey=key;wlSortAsc=key==='sym'}
  // Update arrows
  ['sym','last','chg','chg_pct'].forEach(k=>{
    const el=document.getElementById('wl-arrow-'+k);
    if(el) el.textContent=k===wlSortKey?(wlSortAsc?' \u25B2':' \u25BC'):'';
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
  }catch(err){
    document.getElementById('wl-count').textContent='0';
    document.getElementById('wl-items').innerHTML='<div style="padding:12px 14px;color:var(--text-3)">Unable to load watchlist.</div>';
  }
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

function renderWL(list){
  const filtered=wlFilteredList(list);
  document.getElementById('wl-count').textContent=filtered.length;
  if(wlSortKey){
    filtered.sort((a,b)=>{
      let va,vb;
      if(wlSortKey==='sym'){va=a;vb=b}
      else{const qa=wlQuotes[a]||{},qb=wlQuotes[b]||{};va=qa[wlSortKey]??-Infinity;vb=qb[wlSortKey]??-Infinity}
      if(typeof va==='string') return wlSortAsc?va.localeCompare(vb):vb.localeCompare(va);
      return wlSortAsc?va-vb:vb-va;
    });
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
function pickTicker(t){
  document.getElementById('ticker').value=t;
  renderWL(wlList);
  loadChart();
}

// === RESIZABLE WATCHLIST ===
(function(){
  const drag=document.getElementById('wl-drag'),panel=document.getElementById('wl-panel');
  let startX,startW;
  drag.addEventListener('mousedown',e=>{
    startX=e.clientX;startW=panel.offsetWidth;
    const move=ev=>{const dx=startX-ev.clientX;panel.style.width=Math.max(200,Math.min(500,startW+dx))+'px'};
    const up=()=>{document.removeEventListener('mousemove',move);document.removeEventListener('mouseup',up)};
    document.addEventListener('mousemove',move);document.addEventListener('mouseup',up);
    e.preventDefault();
  });
})();
