(function(root,factory){
  if(typeof module==='object'&&module.exports){
    module.exports=factory();
    return;
  }
  root.strategyPreferenceHelpers=factory();
})(typeof globalThis!=='undefined'?globalThis:this,function(){
  const indexSymbols=new Set(['IXIC','GSPC','DJI','RUT','VIX','NYA','XAX','FTSE','GDAXI','FCHI','N225','HSI','STOXX50E','BVSP','GSPTSE','AXJO','NZ50','KS11','TWII','SSEC','JKSE','KLSE','STI','NSEI','BSESN','TNX','TYX','FVX','IRX','SOX','SPX']);
  const treasurySymbols=new Set(['UST1Y','UST2Y','UST3Y','UST5Y','UST10Y','UST20Y','UST30Y']);
  const semiSymbols=new Set(['ALAB','AMD','ARM','ASML','AVGO','MRVL','MU','NVDA','SNDK','TSM']);
  const softwareSymbols=new Set(['CRM','NOW','PLTR','SNOW']);
  const techSymbols=new Set(['AAPL','AMZN','GOOG','HIMS','HOOD','META','MSFT','RKLB','TSLA']);
  const etfSymbols=new Set(['ARKK','CPER','IAU','IGV','MAGS','SMH','TLT','USO','VGT','XLE']);
  const cryptoAdjacentSymbols=new Set(['COIN','CRCL','GLXY','HUT','MSTR']);

  const categoryLabels={
    indexes:'Index',
    treasuries:'Rates',
    semis:'Semis',
    tech:'Tech',
    software:'Software',
    etfs:'ETF',
    crypto:'Crypto',
    misc:'General',
  };
  const preferredByCategory={
    indexes:{strategyKey:'ema_9_26',strategyLabel:'EMA 9/26 Cross'},
    treasuries:{strategyKey:'trend_sr_macro_v1',strategyLabel:'Trend SR + Macro v1'},
    semis:{strategyKey:'semis_persist_v1',strategyLabel:'Semis Persist v1'},
    tech:{strategyKey:'ema_crossover',strategyLabel:'EMA 5/20 Cross'},
    software:{strategyKey:'trend_sr_macro_v1',strategyLabel:'Trend SR + Macro v1'},
    etfs:{strategyKey:'ribbon',strategyLabel:'Trend-Driven'},
    crypto:{strategyKey:'cci_trend',strategyLabel:'CCI Trend'},
    misc:{strategyKey:'ribbon',strategyLabel:'Trend-Driven'},
  };
  const strategyOverrides={
    SMH:{strategyKey:'semis_persist_v1',strategyLabel:'Semis Persist v1'},
    SOX:{strategyKey:'semis_persist_v1',strategyLabel:'Semis Persist v1'},
  };

  function tickerCategory(ticker){
    const rawTicker=(ticker||'').toUpperCase();
    if(rawTicker.endsWith('-USD'))return 'crypto';
    const raw=rawTicker.replace(/^\^/,'');
    if(treasurySymbols.has(raw))return 'treasuries';
    if(indexSymbols.has(raw)||rawTicker.startsWith('^'))return 'indexes';
    if(semiSymbols.has(raw))return 'semis';
    if(softwareSymbols.has(raw))return 'software';
    if(techSymbols.has(raw))return 'tech';
    if(etfSymbols.has(raw))return 'etfs';
    if(cryptoAdjacentSymbols.has(raw))return 'crypto';
    return 'misc';
  }

  function preferredStrategyMetaForTicker(ticker){
    const rawTicker=(ticker||'').toUpperCase();
    const raw=rawTicker.replace(/^\^/,'');
    const category=tickerCategory(rawTicker);
    const preferred=strategyOverrides[raw]||preferredByCategory[category]||preferredByCategory.misc;
    return{
      category,
      categoryLabel:categoryLabels[category]||'General',
      strategyKey:preferred.strategyKey,
      strategyLabel:preferred.strategyLabel,
    };
  }

  return{tickerCategory,preferredStrategyMetaForTicker,categoryLabels};
});
