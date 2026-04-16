(function(root,factory){
  if(typeof module==='object'&&module.exports){
    module.exports=factory();
    return;
  }
  root.trendPulseHelpers=factory();
})(typeof globalThis!=='undefined'?globalThis:this,function(){
  function flipToneMeta(bullish,bearish,possibleTotal){
    const total=bullish+bearish;
    const possible=possibleTotal||total;
    if(!total||!possible){
      return{label:'No data',tone:'mixed',consensusPct:null,coveragePct:0,score:0};
    }
    const bullPct=Math.round(bullish/total*100);
    const consensusPct=Math.round(Math.max(bullish,bearish)/total*100);
    const coveragePct=Math.round(total/possible*100);
    const score=Math.round(((bullish-bearish)/possible)*100);
    if(bullPct>=70)return{label:'Strong Bullish',tone:'bullish',consensusPct,coveragePct,score};
    if(bullPct>=55)return{label:'Bullish Tilt',tone:'bullish',consensusPct,coveragePct,score};
    if(bullPct<=30)return{label:'Strong Bearish',tone:'bearish',consensusPct,coveragePct,score};
    if(bullPct<=45)return{label:'Bearish Tilt',tone:'bearish',consensusPct,coveragePct,score};
    return{label:'Mixed',tone:'mixed',consensusPct,coveragePct,score};
  }

  function frameSummary(frameFlips,keys,weights,ageForFlip){
    const valid=keys
      .map(k=>({flip:frameFlips?.[k],weight:weights[k]||1}))
      .filter(item=>item.flip?.dir);
    const bullish=valid
      .filter(item=>item.flip.dir==='bullish')
      .reduce((sum,item)=>sum+item.weight,0);
    const bearish=valid
      .filter(item=>item.flip.dir==='bearish')
      .reduce((sum,item)=>sum+item.weight,0);
    const possibleTotal=keys.reduce((sum,key)=>sum+(weights[key]||1),0);
    const consensusDir=bullish>=bearish?'bullish':'bearish';
    const ages=valid
      .filter(item=>item.flip.dir===consensusDir)
      .map(item=>({age:ageForFlip(item.flip),weight:item.weight}))
      .filter(item=>item.age!=null);
    const ageWeight=ages.reduce((sum,item)=>sum+item.weight,0);
    const avgAge=ages.length?Math.round(ages.reduce((sum,item)=>sum+item.age*item.weight,0)/(ageWeight||1)):null;
    const avgDate=avgAge==null?null:new Date(Date.now()-avgAge*864e5).toISOString().slice(0,10);
    return{
      bullish,
      bearish,
      total:bullish+bearish,
      possibleTotal,
      avgAge,
      avgDate,
      meta:flipToneMeta(bullish,bearish,possibleTotal),
    };
  }

  return{flipToneMeta,frameSummary};
});
