const sMap={vol:()=>[volumeSeries],sma50:()=>[sma50Series],sma100:()=>[sma100Series],sma200:()=>[sma200Series],sma50w:()=>[sma50wSeries],sma200w:()=>[sma200wSeries],emaCross:()=>[ema9Series,ema21Series],ribbon:()=>[ribbonUpperSeries,ribbonLowerSeries,ribbonCenterSeries],volProfile:()=>[],sup:()=>[],res:()=>[]};
const activeChips=new Set(['vol']); // track which legend items are on

// === UNIFIED CHART LEGEND (TradingView-style left panel) ===
const eyeSVG=`<svg width="14" height="14" viewBox="0 0 16 16" fill="none"><path d="M8 3C3 3 1 8 1 8s2 5 7 5 7-5 7-5-2-5-7-5Z" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/><circle cx="8" cy="8" r="2" stroke="currentColor" stroke-width="1.3"/></svg>`;
const eyeOffSVG=`<svg width="14" height="14" viewBox="0 0 16 16" fill="none"><path d="M8 3C3 3 1 8 1 8s2 5 7 5 7-5 7-5-2-5-7-5Z" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/><line x1="2" y1="14" x2="14" y2="2" stroke="currentColor" stroke-width="1.3"/></svg>`;

const legendItems=[
  // Overlays
  {key:'vol',label:'Volume',color:'#5b7fff',on:true},
  {key:'ribbon',label:'Trend Ribbon',color:'#ffd644',on:false},
  {key:'volProfile',label:'Vol Profile',color:'#7c8db5',on:false},
  {key:'res',label:'Resistance',color:'#5b9fff',on:false},
  {key:'sup',label:'Support',color:'#ffa040',on:false},
  // Moving Averages
  {key:'sma50',label:'SMA 50',color:'#ffa040',on:false,dataKey:'sma_50',section:'ma'},
  {key:'sma100',label:'SMA 100',color:'#b050ff',on:false,dataKey:'sma_100',section:'ma'},
  {key:'sma200',label:'SMA 200',color:'#00d4ff',on:false,dataKey:'sma_200',section:'ma'},
  {key:'sma50w',label:'50W MA',color:'#e8b839',on:false,dataKey:'sma_50w',section:'ma'},
  {key:'sma200w',label:'200W MA',color:'#ffd644',on:false,dataKey:'sma_200w',section:'ma'},
  {key:'emaCross',label:'EMA 9/21',color:'#ff9800',on:false,dataKey:'ema9',section:'ma'},
];

function buildChartLegend(){
  const c=document.getElementById('chart-legend');
  let html='';
  let inMA=false;
  legendItems.forEach((item,i)=>{
    if(item.section==='ma'&&!inMA){html+=`<div class="cl-section">Moving Averages</div>`;inMA=true;}
    const cls=item.on?'':'off';
    html+=`<div class="cl-row ${cls}" data-li="${i}" onclick="toggleLegendItem(${i})">
      <span class="cl-eye">${item.on?eyeSVG:eyeOffSVG}</span>
      <span class="cl-dot" style="background:${item.color}"></span>
      <span class="cl-label">${item.label}</span>
      ${item.dataKey?`<span class="cl-val" id="cl-val-${i}">--</span>`:''}
    </div>`;
  });
  c.innerHTML=html;
}

function toggleLegendItem(idx){
  const item=legendItems[idx];
  item.on=!item.on;
  const row=document.querySelector(`.cl-row[data-li="${idx}"]`);
  row.classList.toggle('off',!item.on);
  row.querySelector('.cl-eye').innerHTML=item.on?eyeSVG:eyeOffSVG;
  if(item.on)activeChips.add(item.key);else activeChips.delete(item.key);
  // Special toggles
  if(item.key==='sup'){toggleSRType('support',item.on)}
  else if(item.key==='res'){toggleSRType('resistance',item.on)}
  else if(item.key==='volProfile'){const vp=document.getElementById('vol-profile');if(vp)vp.style.display=item.on?'':'none'}
  else{(sMap[item.key]?.()||[]).forEach(s=>s.applyOptions({visible:item.on}))}
  if(item.key==='ribbon')updateFlipInfo();
  pushURLParams();
}

// Compat shim for URL restore
function toggleChip(el,n){const idx=legendItems.findIndex(i=>i.key===n);if(idx>=0)toggleLegendItem(idx);}

function updateLegendValues(param){
  if(!lastData)return;
  legendItems.forEach((item,i)=>{
    if(!item.dataKey)return;
    const el=document.getElementById('cl-val-'+i);
    if(!el)return;
    const dataArr=lastData[item.dataKey];
    if(!dataArr||!dataArr.length){el.textContent='--';return;}
    let val='--';
    if(param&&param.time){
      const t=typeof param.time==='object'?new Date(param.time.year,param.time.month-1,param.time.day).getTime()/1000:param.time;
      for(let j=dataArr.length-1;j>=0;j--){
        if(dataArr[j].time<=t){val=dataArr[j].value.toFixed(2);break;}
      }
    }else{
      val=dataArr[dataArr.length-1].value.toFixed(2);
    }
    el.textContent=val;
  });
}
