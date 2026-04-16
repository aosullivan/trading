let chart,candleSeries,stUpFill,stDownFill,stUpMid,stDownMid,volumeSeries,btEquityChart,btPriceSeries,btEquitySeries,btHoldSeries;
let stUpSeries=[],stDownSeries=[];
let sma50Series,sma100Series,sma180Series,sma200Series,sma50wSeries,sma100wSeries,sma200wSeries,ema9Series,ema21Series;
// Indicator overlay series — price overlays
let donchUpperSeries,donchLowerSeries;
let bbUpperSeries,bbMidSeries,bbLowerSeries;
let keltUpperSeries,keltMidSeries,keltLowerSeries;
let psarBullSeries,psarBearSeries;
// Oscillator overlay series — separate scale
let macdLineSeries,macdSignalSeries,macdHistSeries;
let adxLineSeries,plusDiSeries,minusDiSeries;
let cciLineSeries;
// ORB overlay series
let orbUpperSeries,orbLowerSeries,orbMidSeries;
// Trend ribbon
let ribbonUpperSeries,ribbonLowerSeries,ribbonCenterSeries;
const overlaySeries=[];
// srPriceLines removed — S/R now uses srLineSeries (line series approach)
let lastData=null,btOpen=false;
let chartStart='',chartEnd='';
const TREASURY_TICKERS=new Set(['UST1Y','UST2Y','UST3Y','UST5Y','UST10Y','UST20Y','UST30Y']);
const financialsClientCache=new Map();

const now=new Date(),yearAgo=new Date(now);yearAgo.setFullYear(yearAgo.getFullYear()-1);

function defaultStart(interval){
  // Monthly charts benefit from deeper history for long-term context.
  return interval==='1mo'?'2000-01-01':'2015-01-01';
}
function defaultVisibleStart(interval){
  const d=new Date();
  // Default to a view that's about 69% wider than the original baseline.
  const lookbackDays=interval==='1mo'?Math.round(365*8):interval==='1wk'?Math.round(365*1.69):Math.round(90*1.69);
  d.setDate(d.getDate()-lookbackDays);
  return d.toISOString().split('T')[0];
}

function intervalLabel(interval){
  if(interval==='1mo')return'Monthly';
  if(interval==='1wk')return'Weekly';
  return'Daily';
}

function isTreasuryTicker(ticker){
  return TREASURY_TICKERS.has(String(ticker||'').toUpperCase());
}

function fmtDisplayNumber(value){
  return Number(value).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});
}

function formatLastDisplay(ticker,value){
  if(value==null||Number.isNaN(Number(value)))return'--';
  return fmtDisplayNumber(value);
}

function formatPriceDisplay(ticker,value){
  if(value==null||Number.isNaN(Number(value)))return'--';
  return `$${Number(value).toFixed(2)}`;
}

function formatChangeDisplay(value){
  if(value==null||Number.isNaN(Number(value)))return'--';
  const n=Number(value);
  return `${n>=0?'+':''}${n.toFixed(2)}`;
}

function escapeHtml(value){
  return String(value??'').replace(/[&<>"']/g,ch=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
}

function initChart(){
  const c=document.getElementById('chart-container');
  chart=LightweightCharts.createChart(c,{
    layout:{background:{color:'#08090d'},textColor:'#6a7090',fontFamily:'Inter,sans-serif'},
    grid:{vertLines:{color:'#12141c'},horzLines:{color:'#12141c'}},
    crosshair:{mode:LightweightCharts.CrosshairMode.Normal,vertLine:{color:'#5b7fff30',labelBackgroundColor:'#5b7fff'},horzLine:{color:'#5b7fff30',labelBackgroundColor:'#5b7fff'}},
    rightPriceScale:{borderColor:'#1c1f30',entireTextOnly:true},
    timeScale:{borderColor:'#1c1f30',timeVisible:false,minBarSpacing:0.5,rightOffset:20},
    handleScroll:{vertTouchDrag:true},handleScale:{axisPressedMouseMove:{time:true,price:true}},
	});
	// Trend ribbon (added first so candles render on top)
	ribbonUpperSeries=chart.addAreaSeries({lineWidth:0,lastValueVisible:false,priceLineVisible:false,visible:false,lineColor:'rgba(0,230,138,0.4)',topColor:'rgba(0,230,138,0.18)',bottomColor:'rgba(0,230,138,0.03)',crosshairMarkerVisible:false});
	ribbonLowerSeries=chart.addAreaSeries({lineWidth:0,lastValueVisible:false,priceLineVisible:false,visible:false,lineColor:'rgba(8,9,13,1)',topColor:'rgba(8,9,13,1)',bottomColor:'rgba(8,9,13,1)',crosshairMarkerVisible:false});
	ribbonCenterSeries=chart.addLineSeries({lineWidth:1,lastValueVisible:false,priceLineVisible:false,visible:false,color:'rgba(255,255,255,0.5)',lineStyle:LightweightCharts.LineStyle.Dashed});
	// Supertrend fills (before candles so candles render on top)
	stUpFill=chart.addAreaSeries({lineWidth:0,lastValueVisible:false,priceLineVisible:false,visible:false,topColor:'rgba(0,230,138,0.10)',bottomColor:'rgba(0,230,138,0.10)',lineColor:'transparent',crosshairMarkerVisible:false});
	stDownFill=chart.addAreaSeries({lineWidth:0,lastValueVisible:false,priceLineVisible:false,visible:false,topColor:'rgba(255,82,116,0.10)',bottomColor:'rgba(255,82,116,0.10)',lineColor:'transparent',crosshairMarkerVisible:false});
	stUpMid=chart.addLineSeries({lineWidth:0,lastValueVisible:false,priceLineVisible:false,visible:false,color:'transparent',crosshairMarkerVisible:false});
	stDownMid=chart.addLineSeries({lineWidth:0,lastValueVisible:false,priceLineVisible:false,visible:false,color:'transparent',crosshairMarkerVisible:false});
	candleSeries=chart.addCandlestickSeries({upColor:'#00e68a',downColor:'#ff5274',borderUpColor:'#00e68a',borderDownColor:'#ff5274',wickUpColor:'#00e68a80',wickDownColor:'#ff527480'});
  sma50Series=chart.addLineSeries({color:'#ffa040',lineWidth:1,lastValueVisible:false,priceLineVisible:false,visible:false});
  sma100Series=chart.addLineSeries({color:'#b050ff',lineWidth:1,lastValueVisible:false,priceLineVisible:false,visible:false});
  sma180Series=chart.addLineSeries({color:'#00d4ff',lineWidth:1,lastValueVisible:false,priceLineVisible:false,visible:false});
  sma200Series=chart.addLineSeries({color:'#00d4ff',lineWidth:1,lastValueVisible:false,priceLineVisible:false,visible:false});
  sma50wSeries=chart.addLineSeries({color:'#e8b839',lineWidth:1,lineStyle:2,lastValueVisible:false,priceLineVisible:false,visible:false});
  sma100wSeries=chart.addLineSeries({color:'#f59f00',lineWidth:1,lineStyle:2,lastValueVisible:false,priceLineVisible:false,visible:false});
  sma200wSeries=chart.addLineSeries({color:'#ffd644',lineWidth:2,lineStyle:2,lastValueVisible:false,priceLineVisible:false,visible:false});
  ema9Series=chart.addLineSeries({color:'#ff9800',lineWidth:1,lastValueVisible:false,priceLineVisible:false,visible:false});
  ema21Series=chart.addLineSeries({color:'#ff5722',lineWidth:1,lastValueVisible:false,priceLineVisible:false,visible:false});
  // Donchian channels (blue)
  donchUpperSeries=chart.addLineSeries({color:'#42a5f5',lineWidth:1,lineStyle:LightweightCharts.LineStyle.Dashed,lastValueVisible:false,priceLineVisible:false,visible:false});
  donchLowerSeries=chart.addLineSeries({color:'#42a5f5',lineWidth:1,lineStyle:LightweightCharts.LineStyle.Dashed,lastValueVisible:false,priceLineVisible:false,visible:false});
  // Bollinger Bands (purple)
  bbUpperSeries=chart.addLineSeries({color:'#ab47bc',lineWidth:1,lastValueVisible:false,priceLineVisible:false,visible:false});
  bbMidSeries=chart.addLineSeries({color:'#ab47bc',lineWidth:1,lineStyle:LightweightCharts.LineStyle.Dashed,lastValueVisible:false,priceLineVisible:false,visible:false});
  bbLowerSeries=chart.addLineSeries({color:'#ab47bc',lineWidth:1,lastValueVisible:false,priceLineVisible:false,visible:false});
  // Keltner Channels (teal)
  keltUpperSeries=chart.addLineSeries({color:'#26a69a',lineWidth:1,lastValueVisible:false,priceLineVisible:false,visible:false});
  keltMidSeries=chart.addLineSeries({color:'#26a69a',lineWidth:1,lineStyle:LightweightCharts.LineStyle.Dashed,lastValueVisible:false,priceLineVisible:false,visible:false});
  keltLowerSeries=chart.addLineSeries({color:'#26a69a',lineWidth:1,lastValueVisible:false,priceLineVisible:false,visible:false});
  // Parabolic SAR dots
  psarBullSeries=chart.addLineSeries({color:'#00e68a',lineWidth:0,lastValueVisible:false,priceLineVisible:false,visible:false,pointMarkersVisible:true,pointMarkersRadius:2});
  psarBearSeries=chart.addLineSeries({color:'#ff5274',lineWidth:0,lastValueVisible:false,priceLineVisible:false,visible:false,pointMarkersVisible:true,pointMarkersRadius:2});
  // MACD oscillator (own scale, bottom panel)
  const oscOpts={priceScaleId:'osc',lastValueVisible:false,priceLineVisible:false,visible:false};
  macdLineSeries=chart.addLineSeries({...oscOpts,color:'#42a5f5',lineWidth:1});
  macdSignalSeries=chart.addLineSeries({...oscOpts,color:'#ef5350',lineWidth:1});
  macdHistSeries=chart.addHistogramSeries({...oscOpts,priceFormat:{type:'price',precision:2}});
  // ADX oscillator
  adxLineSeries=chart.addLineSeries({...oscOpts,color:'#ffd644',lineWidth:2});
  plusDiSeries=chart.addLineSeries({...oscOpts,color:'#00e68a',lineWidth:1});
  minusDiSeries=chart.addLineSeries({...oscOpts,color:'#ff5274',lineWidth:1});
  // CCI oscillator
  cciLineSeries=chart.addLineSeries({...oscOpts,color:'#ff6e40',lineWidth:1});
  // ORB range overlay (orange dashed)
  orbUpperSeries=chart.addLineSeries({color:'#ff9800',lineWidth:1,lineStyle:LightweightCharts.LineStyle.Dashed,lastValueVisible:false,priceLineVisible:false,visible:false});
  orbLowerSeries=chart.addLineSeries({color:'#ff9800',lineWidth:1,lineStyle:LightweightCharts.LineStyle.Dashed,lastValueVisible:false,priceLineVisible:false,visible:false});
  orbMidSeries=chart.addLineSeries({color:'#ff9800',lineWidth:1,lineStyle:LightweightCharts.LineStyle.Dotted,lastValueVisible:false,priceLineVisible:false,visible:false});
  chart.priceScale('osc').applyOptions({scaleMargins:{top:0.75,bottom:0},borderVisible:false,drawTicks:false});
  overlaySeries.push(stUpFill,stDownFill,stUpMid,stDownMid,sma50Series,sma100Series,sma180Series,sma200Series,sma50wSeries,sma100wSeries,sma200wSeries,ema9Series,ema21Series,donchUpperSeries,donchLowerSeries,bbUpperSeries,bbMidSeries,bbLowerSeries,keltUpperSeries,keltMidSeries,keltLowerSeries,psarBullSeries,psarBearSeries,macdLineSeries,macdSignalSeries,macdHistSeries,adxLineSeries,plusDiSeries,minusDiSeries,cciLineSeries,orbUpperSeries,orbLowerSeries,orbMidSeries,ribbonUpperSeries,ribbonLowerSeries,ribbonCenterSeries);
  // Prevent overlay series on the main price scale from influencing vertical auto-scale
  [stUpFill,stDownFill,stUpMid,stDownMid,sma50Series,sma100Series,sma180Series,sma200Series,sma50wSeries,sma100wSeries,sma200wSeries,ema9Series,ema21Series,donchUpperSeries,donchLowerSeries,bbUpperSeries,bbMidSeries,bbLowerSeries,keltUpperSeries,keltMidSeries,keltLowerSeries,psarBullSeries,psarBearSeries,orbUpperSeries,orbLowerSeries,orbMidSeries,ribbonUpperSeries,ribbonLowerSeries,ribbonCenterSeries].forEach(s=>s.applyOptions({autoscaleInfoProvider:()=>null}));
	volumeSeries=chart.addHistogramSeries({priceFormat:{type:'volume'},priceScaleId:'volume'});
	chart.priceScale('volume').applyOptions({scaleMargins:{top:.82,bottom:0}});
	new ResizeObserver(()=>chart.applyOptions({width:c.clientWidth,height:c.clientHeight})).observe(c);

  // Crosshair move -> update MA legend values
  chart.subscribeCrosshairMove(param=>updateLegendValues(param));

  // Update bar count label on visible range change
  chart.timeScale().subscribeVisibleLogicalRangeChange(range=>{
    const lbl=document.getElementById('cn-bars-lbl');
    if(range && lbl){
      const bars=Math.round(range.to-range.from);
      lbl.textContent=bars+' bars';
    }
    scheduleSRRedraw();
  });
}

function clearSupertrendSegments(){
  stUpSeries.forEach(s=>chart.removeSeries(s));
  stDownSeries.forEach(s=>chart.removeSeries(s));
  stUpSeries=[];
  stDownSeries=[];
}

function buildSupertrendSegments(points,color){
  const segments=[];
  let segment=[];
  points.forEach(pt=>{
    if(pt.value==null||Number.isNaN(Number(pt.value))){
      if(segment.length){
        segments.push(segment);
        segment=[];
      }
      return;
    }
    segment.push({time:pt.time,value:pt.value});
  });
  if(segment.length)segments.push(segment);
  return segments.map(data=>{
    const series=chart.addLineSeries({
      color,
      lineWidth:2,
      lineStyle:LightweightCharts.LineStyle.Solid,
      lastValueVisible:false,
      priceLineVisible:false,
      visible:false,
      crosshairMarkerVisible:false,
    });
    series.applyOptions({autoscaleInfoProvider:()=>null});
    series.setData(data);
    return series;
  });
}

/* Chart nav toolbar actions */
function chartNavZoom(dir){
  if(!chart) return;
  const ts=chart.timeScale();
  const range=ts.getVisibleLogicalRange();
  if(!range) return;
  const span=range.to-range.from;
  const factor=dir>0?0.3:(-0.4);
  const shrink=span*factor;
  const mid=(range.from+range.to)/2;
  const newFrom=mid-(span-shrink)/2;
  const newTo=mid+(span-shrink)/2;
  if(newTo-newFrom<3) return; // min 3 bars
  ts.setVisibleLogicalRange({from:newFrom,to:newTo});
}
function chartNavScroll(dir){
  if(!chart) return;
  const ts=chart.timeScale();
  const range=ts.getVisibleLogicalRange();
  if(!range) return;
  const shift=(range.to-range.from)*0.2*dir;
  ts.setVisibleLogicalRange({from:range.from+shift,to:range.to+shift});
}
function chartNavReset(){
  if(!chart || !_lastCandles) return;
  const interval=document.getElementById('interval').value;
  const visStart=defaultVisibleStart(interval);
  const visStartTs=Math.floor(new Date(visStart).getTime()/1000);
  const firstCandle=_lastCandles[0].time;
  const from=Math.max(visStartTs,firstCandle);
  const to=_lastCandles[_lastCandles.length-1].time;
  chart.timeScale().setVisibleRange({from,to});
}
function chartRangePresetYears(years){
  if(!chart||!_lastCandles?.length)return;
  const latestTs=_lastCandles[_lastCandles.length-1].time;
  const latestDate=new Date(latestTs*1000);
  const fromDate=new Date(latestDate);
  fromDate.setFullYear(fromDate.getFullYear()-years);
  const firstCandleTs=_lastCandles[0].time;
  const from=Math.max(Math.floor(fromDate.getTime()/1000),firstCandleTs);
  chart.timeScale().setVisibleRange({from,to:latestTs});
}
function chartRangePresetReset(){
  chartNavReset();
}
function chartNavFit(){
  if(!chart) return;
  chart.timeScale().fitContent();
}
let _lastCandles=null;

function ensureBTChart(){
  if(btEquityChart) return;
  const c=document.getElementById('bt-equity-chart');
  btEquityChart=LightweightCharts.createChart(c,{
    layout:{background:{color:'#10131d'},textColor:'#6a7090',fontFamily:'Inter,sans-serif'},
    grid:{vertLines:{color:'#181c28'},horzLines:{color:'#181c28'}},
    crosshair:{mode:LightweightCharts.CrosshairMode.Normal,vertLine:{color:'#5b7fff22',labelBackgroundColor:'#5b7fff'},horzLine:{color:'#5b7fff22',labelBackgroundColor:'#5b7fff'}},
    leftPriceScale:{visible:true,borderColor:'#1c1f30',scaleMargins:{top:.12,bottom:.08},entireTextOnly:true},
    rightPriceScale:{borderColor:'#1c1f30',scaleMargins:{top:.12,bottom:.08},entireTextOnly:true},
    timeScale:{borderColor:'#1c1f30',timeVisible:false,secondsVisible:false},
  });
  btPriceSeries=btEquityChart.addCandlestickSeries({
    priceScaleId:'left',
    upColor:'#00e68a',
    downColor:'#ff5274',
    borderUpColor:'#00e68a',
    borderDownColor:'#ff5274',
    wickUpColor:'#00e68a80',
    wickDownColor:'#ff527480',
    priceLineVisible:false,
    lastValueVisible:false,
  });
  btEquitySeries=btEquityChart.addAreaSeries({
    topColor:'rgba(91,127,255,0.28)',
    bottomColor:'rgba(91,127,255,0.02)',
    lineColor:'#7f98ff',
    lineWidth:2,
    priceLineVisible:false,
    lastValueVisible:false,
  });
  btHoldSeries=btEquityChart.addLineSeries({
    color:'#ffd644',
    lineWidth:2,
    lineStyle:LightweightCharts.LineStyle.Dashed,
    priceLineVisible:false,
    lastValueVisible:false,
    crosshairMarkerVisible:false,
  });
  new ResizeObserver(()=>{
    btEquityChart.applyOptions({width:c.clientWidth,height:c.clientHeight});
  }).observe(c);
}
