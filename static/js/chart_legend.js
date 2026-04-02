const sMap={vol:()=>[volumeSeries],maAuto:()=>[],sma50:()=>[sma50Series],sma100:()=>[sma100Series],sma200:()=>[sma200Series],sma50w:()=>[sma50wSeries],sma100w:()=>[sma100wSeries],sma200w:()=>[sma200wSeries],emaCross:()=>[ema9Series,ema21Series],ribbon:()=>[ribbonUpperSeries,ribbonLowerSeries,ribbonCenterSeries],volProfile:()=>[],sup:()=>[],res:()=>[]};
const activeChips=new Set(['vol']); // track which legend items are on
const MA_AUTO_KEY='maAuto';
const MA_AUTO_KEYS_BY_INTERVAL={
  '1d':['sma50','sma100','sma200'],
  '1wk':['sma50w','sma100w','sma200w'],
  '1mo':['sma50w','sma100w','sma200w'],
};

// === UNIFIED CHART LEGEND (TradingView-style left panel) ===
const eyeSVG=`<svg width="14" height="14" viewBox="0 0 16 16" fill="none"><path d="M8 3C3 3 1 8 1 8s2 5 7 5 7-5 7-5-2-5-7-5Z" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/><circle cx="8" cy="8" r="2" stroke="currentColor" stroke-width="1.3"/></svg>`;
const eyeOffSVG=`<svg width="14" height="14" viewBox="0 0 16 16" fill="none"><path d="M8 3C3 3 1 8 1 8s2 5 7 5 7-5 7-5-2-5-7-5Z" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/><line x1="2" y1="14" x2="14" y2="2" stroke="currentColor" stroke-width="1.3"/></svg>`;

const legendItems=[
  // Overlays
  {key:'vol',label:'Volume',color:'#5b7fff',on:true},
  {key:'volProfile',label:'Vol Profile',color:'#7c8db5',on:false},
  {key:'res',label:'Resistance',color:'#5b9fff',on:false},
  {key:'sup',label:'Support',color:'#ffa040',on:false},
  // Moving Averages
  {key:MA_AUTO_KEY,label:'Auto',color:'#7f98ff',on:false,section:'ma'},
  {key:'sma50',label:'SMA 50',color:'#ffa040',on:false,dataKey:'sma_50',section:'ma'},
  {key:'sma100',label:'SMA 100',color:'#b050ff',on:false,dataKey:'sma_100',section:'ma'},
  {key:'sma200',label:'SMA 200',color:'#00d4ff',on:false,dataKey:'sma_200',section:'ma'},
  {key:'sma50w',label:'50W MA',color:'#e8b839',on:false,dataKey:'sma_50w',section:'ma'},
  {key:'sma100w',label:'100W MA',color:'#f59f00',on:false,dataKey:'sma_100w',section:'ma'},
  {key:'sma200w',label:'200W MA',color:'#ffd644',on:false,dataKey:'sma_200w',section:'ma'},
  {key:'emaCross',label:'EMA 9/21',color:'#ff9800',on:false,dataKey:'ema9',section:'ma'},
];

function latestDataValue(dataKey){
  const dataArr=lastData?.[dataKey];
  if(!dataArr?.length)return null;
  for(let i=dataArr.length-1;i>=0;i--){
    const value=Number(dataArr[i]?.value);
    if(Number.isFinite(value))return value;
  }
  return null;
}

function setLegendItemState(idx,on){
  const item=legendItems[idx];
  if(!item)return;
  item.on=on;
  const row=document.querySelector(`.cl-row[data-li="${idx}"]`);
  if(row){
    row.classList.toggle('off',!on);
    const eye=row.querySelector('.cl-eye');
    if(eye)eye.innerHTML=on?eyeSVG:eyeOffSVG;
  }
  if(on)activeChips.add(item.key);else activeChips.delete(item.key);
  if(item.key==='sup'){toggleSRType('support',on)}
  else if(item.key==='res'){toggleSRType('resistance',on)}
  else if(item.key==='volProfile'){const vp=document.getElementById('vol-profile');if(vp)vp.style.display=on?'':'none'}
  else{(sMap[item.key]?.()||[]).forEach(s=>s.applyOptions({visible:on}))}
  if(item.key==='ribbon')updateFlipInfo();
}

function syncAutoMovingAverages(){
  const autoIdx=legendItems.findIndex(item=>item.key===MA_AUTO_KEY);
  const autoItem=autoIdx>=0?legendItems[autoIdx]:null;
  if(!autoItem?.on||!lastData?.candles?.length)return;
  const interval=document.getElementById('interval')?.value||'1d';
  const autoKeys=new Set(MA_AUTO_KEYS_BY_INTERVAL[interval]||MA_AUTO_KEYS_BY_INTERVAL['1d']);
  const currentPrice=Number(lastData.candles[lastData.candles.length-1]?.close);
  if(!Number.isFinite(currentPrice))return;
  const candidates=legendItems
    .map((item,idx)=>({item,idx,value:autoKeys.has(item.key)&&item.dataKey?latestDataValue(item.dataKey):null}))
    .filter(entry=>entry.value!=null);
  const sortedAbove=candidates.filter(entry=>entry.value>=currentPrice).sort((a,b)=>(a.value-currentPrice)-(b.value-currentPrice)||a.idx-b.idx);
  const sortedBelow=candidates.filter(entry=>entry.value<currentPrice).sort((a,b)=>(currentPrice-a.value)-(currentPrice-b.value)||a.idx-b.idx);
  const selected=new Set();
  if(sortedAbove.length)selected.add(sortedAbove[0].idx);
  if(sortedBelow.length)selected.add(sortedBelow[0].idx);
  if(selected.size<2){
    // Fallback keeps two closest averages visible when all available lines sit on one side.
    [...candidates]
      .sort((a,b)=>Math.abs(a.value-currentPrice)-Math.abs(b.value-currentPrice)||a.idx-b.idx)
      .forEach(entry=>{if(selected.size<2)selected.add(entry.idx)});
  }
  legendItems.forEach((item,idx)=>{
    if(item.section==='ma'&&item.key!==MA_AUTO_KEY)setLegendItemState(idx,selected.has(idx));
  });
}

function clearMovingAverages(){
  legendItems.forEach((item,idx)=>{
    if(item.section==='ma'&&item.key!==MA_AUTO_KEY)setLegendItemState(idx,false);
  });
}

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
  const nextOn=!item.on;
  if(item.section==='ma'&&item.key!==MA_AUTO_KEY){
    const autoIdx=legendItems.findIndex(entry=>entry.key===MA_AUTO_KEY);
    if(autoIdx>=0&&legendItems[autoIdx].on)setLegendItemState(autoIdx,false);
  }
  setLegendItemState(idx,nextOn);
  if(item.key===MA_AUTO_KEY&&nextOn)syncAutoMovingAverages();
  if(item.key===MA_AUTO_KEY&&!nextOn)clearMovingAverages();
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
