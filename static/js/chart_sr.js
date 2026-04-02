// === S/R LINE SERIES (single center line + shaded zone) ===
const SR_AUTOSCALE_BUFFER_RATIO=0.12;
const SR_MAX_VISIBLE_PER_TYPE=2;
const srHelpers=window.ChartSupportResistance;
let srLineSeries=[];  // [{series:[], priceLine, type}]
let srRedrawFrame=0;
function clearSRLines(){
  srLineSeries.forEach(s=>{
    (s.series||[]).forEach(series=>chart.removeSeries(series));
    if(s.priceLine) candleSeries.removePriceLine(s.priceLine);
  });
  srLineSeries=[];
}
function getVisibleCandleRange(){
  if(!chart||!lastData?.candles?.length)return null;
  return srHelpers.getVisibleCandleRange(lastData.candles,chart.timeScale().getVisibleLogicalRange());
}
function srLevelAffectsAutoscale(level){
  return srHelpers.levelAffectsAutoscale(level,getVisibleCandleRange(),SR_AUTOSCALE_BUFFER_RATIO);
}
function redrawActiveSRLines(){
  if(activeChips.has('sup'))drawSRLines('support');
  if(activeChips.has('res'))drawSRLines('resistance');
}
function srLevelIsOnExpectedSide(level,type){
  const current=lastData?.candles?.[lastData.candles.length-1]?.close;
  return srHelpers.levelIsOnExpectedSide(level,type,current);
}
function getVisibleTimeBounds(){
  if(!chart||!lastData?.candles?.length)return null;
  return srHelpers.getVisibleTimeBounds(lastData.candles,chart.timeScale().getVisibleLogicalRange());
}
function srRecencyBeforeVisible(level){
  return srHelpers.recencyBeforeVisible(level,getVisibleTimeBounds());
}
function scheduleSRRedraw(){
  if(srRedrawFrame||!lastData?.candles?.length)return;
  srRedrawFrame=requestAnimationFrame(()=>{
    srRedrawFrame=0;
    redrawActiveSRLines();
  });
}
function drawSRLines(type){
  // Remove existing lines of this type
  srLineSeries=srLineSeries.filter(s=>{
    if(s.type===type){
      (s.series||[]).forEach(series=>chart.removeSeries(series));
      if(s.priceLine) candleSeries.removePriceLine(s.priceLine);
      return false;
    }
    return true;
  });
  if(!lastData?.sr_levels||!lastData.candles?.length)return;
  const candles=lastData.candles;
  const currentClose=candles[candles.length-1]?.close;
  const visibleBounds=getVisibleTimeBounds();
  const filtered=srHelpers.selectVisibleLevels(
    lastData.sr_levels,
    type,
    candles,
    chart.timeScale().getVisibleLogicalRange(),
    currentClose,
    {bufferRatio:SR_AUTOSCALE_BUFFER_RATIO,maxVisible:SR_MAX_VISIBLE_PER_TYPE},
  );
  // Draw only nearby levels for the current viewport.
  // The most recent visible level gets full brightness; others are dimmed.
  const baseColor=type==='support'?'#ffb14d':'#73adff';
  const dimColor=type==='support'?'rgba(255,177,77,0.62)':'rgba(115,173,255,0.62)';
  const priceLabelTextColor='#0d1117';
  const bandFill=type==='support'?'rgba(255,177,77,0.10)':'rgba(115,173,255,0.09)';

  filtered.forEach((lv,rank)=>{
    const isPrimary=rank===0;
    const showBand=isPrimary;
    const solidColor=isPrimary?baseColor:dimColor;
    const solidWidth=isPrimary?3:1;
    const zoneLow=Number.isFinite(lv.zone_low)?lv.zone_low:lv.price;
    const zoneHigh=Number.isFinite(lv.zone_high)?lv.zone_high:lv.price;
    const zoneFloor=Math.min(zoneLow,zoneHigh);
    const zoneCeiling=Math.max(zoneLow,zoneHigh);
    const renderStartTime=srHelpers.getLevelRenderStartTime(lv,visibleBounds);
    let renderStartIdx=0;
    if(Number.isFinite(renderStartTime)){
      let bestDist=Infinity;
      candles.forEach((c,i)=>{
        const d=Math.abs(c.time-renderStartTime);
        if(d<bestDist){
          bestDist=d;
          renderStartIdx=i;
        }
      });
    }
    const centerLineData=[];
    const bandData=[];
    for(let i=renderStartIdx;i<candles.length;i++){
      centerLineData.push({time:candles[i].time,value:lv.price});
      bandData.push({time:candles[i].time,value:zoneCeiling});
    }
    const affectsAutoscale=srLevelAffectsAutoscale(lv);
    const centerLineOpts={color:solidColor,lineWidth:solidWidth,lineStyle:isPrimary?LightweightCharts.LineStyle.Solid:LightweightCharts.LineStyle.Dashed,lastValueVisible:false,priceLineVisible:false,crosshairMarkerVisible:false};
    const bandOpts={
      baseValue:{type:'price',price:zoneFloor},
      topFillColor1:bandFill,
      topFillColor2:bandFill,
      topLineColor:'rgba(0,0,0,0)',
      bottomFillColor1:'rgba(0,0,0,0)',
      bottomFillColor2:'rgba(0,0,0,0)',
      bottomLineColor:'rgba(0,0,0,0)',
      lastValueVisible:false,
      priceLineVisible:false,
      crosshairMarkerVisible:false
    };
    if(!affectsAutoscale){
      centerLineOpts.autoscaleInfoProvider=()=>null;
      if(showBand){
        bandOpts.autoscaleInfoProvider=()=>null;
      }
    }
    const band=showBand&&zoneCeiling>zoneFloor&&typeof chart.addBaselineSeries==='function'
      ? chart.addBaselineSeries(bandOpts)
      : null;
    if(band)band.setData(bandData);
    const centerLine=chart.addLineSeries(centerLineOpts);
    centerLine.setData(centerLineData);
    const priceLine=isPrimary?candleSeries.createPriceLine({
      price:lv.price,
      color:solidColor,
      lineWidth:1,
      lineStyle:LightweightCharts.LineStyle.Dashed,
      lineVisible:false,
      axisLabelVisible:true,
      axisLabelColor:solidColor,
      axisLabelTextColor:priceLabelTextColor,
      title:type==='support'?'SUP':'RES',
    }):null;
    srLineSeries.push({series:[band,centerLine].filter(Boolean),priceLine,type});
  });
}
function toggleSRType(type,on){
  if(on)drawSRLines(type);
  else{
    srLineSeries=srLineSeries.filter(s=>{
      if(s.type===type){
        (s.series||[]).forEach(series=>chart.removeSeries(series));
        if(s.priceLine) candleSeries.removePriceLine(s.priceLine);
        return false;
      }
      return true;
    });
  }
}
