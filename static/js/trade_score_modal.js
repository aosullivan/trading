const TRADE_SCORE_FORMULA_TEXT='Trade Score = 50% trend bias + 20% nearest support/resistance proximity + 15% nearest moving average proximity + 15% upside/downside room, plus a 10-point confluence bonus when the anchor level and nearest moving average cluster within about 1 ATR.';

function closeTradeScoreModal(){
  document.getElementById('trade-score-modal')?.classList.remove('open');
}

function tradeScoreFrameLabel(frame){
  return frame==='weekly'?'Weekly':'Daily';
}

function tradeScoreToneClass(side){
  return side==='bullish'?'bull':side==='bearish'?'bear':'mixed';
}

function tradeScoreSigned(value,digits=0){
  if(value==null||Number.isNaN(Number(value)))return'--';
  const number=Number(value);
  const text=digits>0?number.toFixed(digits):String(Math.round(number));
  return number>0?`+${text}`:text;
}

function tradeScorePlain(value,digits=0){
  if(value==null||Number.isNaN(Number(value)))return'--';
  const number=Number(value);
  const text=digits>0?number.toFixed(digits):String(Math.round(number));
  return text.replace(/\.0$/,'');
}

function tradeScorePercent(value){
  if(value==null||Number.isNaN(Number(value)))return'--';
  return `${Number(value).toFixed(2).replace(/\.00$/,'')}%`;
}

function tradeScoreAtr(value){
  if(value==null||Number.isNaN(Number(value)))return'--';
  return `${Number(value).toFixed(2).replace(/\.00$/,'')} ATR`;
}

function tradeScorePrice(value){
  if(value==null||Number.isNaN(Number(value)))return'--';
  return Number(value).toFixed(2);
}

function tradeScoreLevelRow(label,entry){
  if(!entry){
    return `<div class="trade-score-structure-row"><span>${escapeHtml(label)}</span><strong>--</strong></div>`;
  }
  return `<div class="trade-score-structure-row">
    <span>${escapeHtml(label)}</span>
    <strong>${tradeScorePrice(entry.price)}</strong>
    <em>${tradeScorePercent(entry.distance_pct)} · ${tradeScoreAtr(entry.distance_atr)} · ${escapeHtml(entry.position||'at')}</em>
  </div>`;
}

function tradeScoreSideLabel(side){
  return side==='bearish'?'bearish':side==='bullish'?'bullish':'mixed';
}

function tradeScoreConfluenceBonus(setup,shared){
  const side=setup?.side;
  if(!side||side==='mixed')return 0;
  return shared?.confluence?.[side]?10:0;
}

function tradeScoreRawSetup(setup,shared){
  if(!setup)return null;
  const trend=Math.abs(Number(setup.trend_bias??0));
  const level=Number(setup.level_component??0);
  const ma=Number(setup.ma_component??0);
  const room=Number(setup.room_component??50);
  const raw=(0.50*trend)+(0.20*level)+(0.15*ma)+(0.15*room)+tradeScoreConfluenceBonus(setup,shared);
  if(Number.isNaN(raw))return Math.abs(Number(setup.score??0))||null;
  return Math.min(100,raw);
}

function tradeScoreComponent(label,componentScore,weightPct,detail){
  const score=Number(componentScore??0);
  return{
    label,
    component_score:Number.isNaN(score)?0:score,
    weight_pct:weightPct,
    weighted_contribution:((Number.isNaN(score)?0:score)*weightPct)/100,
    detail,
  };
}

function tradeScoreFallbackComponents(setup,shared){
  const side=setup?.side||'mixed';
  const anchor=side==='bearish'?shared?.nearest_resistance:shared?.nearest_support;
  const anchorLabel=side==='bearish'?'resistance':'support';
  const ma=shared?.nearest_ma;
  const trendDetail=`Weighted signal bias is ${tradeScoreSigned(setup?.trend_bias)}. That sets the setup direction to ${tradeScoreSideLabel(side)}.`;
  const levelDetail=anchor
    ?`Price is ${tradeScorePercent(anchor.distance_pct)} from nearby ${anchorLabel} at ${tradeScorePrice(anchor.price)} (${tradeScoreAtr(anchor.distance_atr)}).`
    :`No nearby ${anchorLabel} was found, so this factor stays muted.`;
  const maDetail=ma
    ?`Nearest moving average is ${ma.label} at ${tradeScorePrice(ma.price)}, sitting ${tradeScorePercent(ma.distance_pct)} away (${tradeScoreAtr(ma.distance_atr)}) ${ma.position||'at'} price.`
    :'No moving average was available for this factor.';
  const roomDetail=`Upside room is ${tradeScorePercent(shared?.upside_room_pct)} (${tradeScoreAtr(shared?.upside_room_atr)}) versus downside room ${tradeScorePercent(shared?.downside_room_pct)} (${tradeScoreAtr(shared?.downside_room_atr)}).`;
  return[
    tradeScoreComponent('Trend bias',setup?.trend_bias==null?0:Math.abs(setup.trend_bias),50,trendDetail),
    tradeScoreComponent('Support / resistance',setup?.level_component??0,20,levelDetail),
    tradeScoreComponent('Nearest moving average',setup?.ma_component??0,15,maDetail),
    tradeScoreComponent('Room to target',setup?.room_component??50,15,roomDetail),
  ];
}

function tradeScoreFallbackSummary(setup,shared){
  if(!setup)return'Trade Score combines trend bias, structure, moving averages, and room.';
  const side=tradeScoreSideLabel(setup.side);
  if(setup.side==='mixed'){
    return `Trend bias is ${tradeScoreSigned(setup.trend_bias)}, so the setup stays mixed and the score remains muted.`;
  }
  const anchor=setup.side==='bearish'?shared?.nearest_resistance:shared?.nearest_support;
  const anchorText=anchor?` Price is ${tradeScorePercent(anchor.distance_pct)} from ${setup.side==='bearish'?'resistance':'support'} at ${tradeScorePrice(anchor.price)}.`:'';
  return `This is a ${side} setup led by a ${tradeScoreSigned(setup.trend_bias)} trend bias.${anchorText}`;
}

function tradeScoreFallbackHighlights(setup,shared){
  if(!setup)return[];
  const highlights=[];
  if(setup.side==='mixed'){
    highlights.push(`Trend bias is ${tradeScoreSigned(setup.trend_bias)}, which is too close to neutral for a strong directional score.`);
    return highlights;
  }
  const anchor=setup.side==='bearish'?shared?.nearest_resistance:shared?.nearest_support;
  if(anchor?.distance_atr!=null){
    if(Number(setup.level_component??0)>=60){
      highlights.push(`Price is sitting fairly close to ${setup.side==='bearish'?'resistance':'support'}, which helps the score.`);
    }else if(Number(setup.level_component??0)<=30){
      highlights.push(`Price is not especially close to ${setup.side==='bearish'?'resistance':'support'}, so that factor contributes less.`);
    }
  }
  const ma=shared?.nearest_ma;
  if(ma){
    const aligned=(setup.side==='bullish'&&['below','at'].includes(ma.position))||(setup.side==='bearish'&&['above','at'].includes(ma.position));
    if(aligned){
      highlights.push(`${ma.label} is positioned on the supportive side of price for this ${setup.side} setup.`);
    }else{
      highlights.push(`${ma.label} is on the wrong side of price for this setup, so MA confirmation is weaker.`);
    }
  }
  if(Number(setup.room_component??50)>=55){
    highlights.push(`The risk/reward room is favorable for the ${setup.side} side.`);
  }else if(Number(setup.room_component??50)<=45){
    highlights.push('The room to target is not especially favorable here.');
  }
  if(tradeScoreConfluenceBonus(setup,shared)){
    highlights.push(`A confluence bonus was added because ${shared.confluence?.[setup.side]} are clustered together.`);
  }
  return highlights;
}

function tradeScoreBreakdown(setup,shared){
  const source=setup?.breakdown||{};
  const components=(source.components&&source.components.length)?source.components:tradeScoreFallbackComponents(setup,shared);
  const bonus=source.bonus||(
    tradeScoreConfluenceBonus(setup,shared)
      ?{
        label:'Confluence bonus',
        points:tradeScoreConfluenceBonus(setup,shared),
        detail:`${shared.confluence?.[setup.side]} are clustered together.`,
      }
      :null
  );
  return{
    formula:source.formula||TRADE_SCORE_FORMULA_TEXT,
    strength_label:source.strength_label||'Trade setup',
    summary:source.summary||tradeScoreFallbackSummary(setup,shared),
    components,
    bonus,
    highlights:(source.highlights&&source.highlights.length)?source.highlights:tradeScoreFallbackHighlights(setup,shared),
    raw_score:source.raw_score??tradeScoreRawSetup(setup,shared),
  };
}

function tradeScoreActionStrength(setup,shared){
  const source=setup?.action_strength;
  if(source?.items?.length)return source;
  if(!setup)return{label:'Action Strength',items:[]};
  const level=Number(setup.level_component??0);
  const ma=Number(setup.ma_component??0);
  const location=setup.side==='mixed'?0:((level*0.20)+(ma*0.15))/0.35;
  return{
    label:'Action Strength',
    items:[
      {
        key:'direction_confidence',
        label:'Direction',
        score:Math.abs(Number(setup.trend_bias??0)),
        detail:`Net directional pressure is ${tradeScoreSigned(setup.trend_bias)} after bullish and bearish signals offset each other.`,
      },
      {
        key:'entry_location_quality',
        label:'Location',
        score:location,
        detail:setup.side==='mixed'
          ?'Location is held at zero while the setup is mixed.'
          :'Blends the nearest support/resistance and moving-average components.',
      },
      {
        key:'risk_reward_room',
        label:'Room',
        score:Number(setup.room_component??50),
        detail:'Compares available room in the setup direction against room on the adverse side.',
      },
      {
        key:'strategy_agreement',
        label:'Agreement',
        score:Math.abs(Number(setup.trend_bias??0)),
        detail:'Estimates signal consensus from the net trend bias when detailed agreement is unavailable.',
      },
    ],
  };
}

function tradeScoreActionCaption(item){
  if(item?.key==='direction_confidence')return'Regime';
  if(item?.key==='entry_location_quality')return'Support + MA';
  if(item?.key==='risk_reward_room')return'Room';
  if(item?.key==='strategy_agreement')return'Consensus';
  return'';
}

function tradeScoreActionStrengthHtml(actionStrength,toneCls,compact=false){
  const items=actionStrength?.items||[];
  if(!items.length)return'';
  const heading=compact?'':`<h4>${escapeHtml(actionStrength.label||'Action Strength')}</h4>`;
  return `${heading}
    <div class="trade-score-action-grid">
      ${items.map(item=>`<div class="trade-score-action-card trade-score-action-card-${toneCls}">
        <div class="trade-score-action-head">
          <span>${escapeHtml(item.label||'Signal')}</span>
          <strong>${tradeScorePlain(item.score)} / 100</strong>
        </div>
        <div class="trade-score-action-meter"><span style="width:${Math.max(0,Math.min(100,Number(item.score??0)))}%"></span></div>
        <p>${escapeHtml(compact?tradeScoreActionCaption(item):(item.detail||''))}</p>
      </div>`).join('')}
    </div>`;
}

function renderTradeScorePayload(ticker,frame,tradeSetup,options={}){
  const scopedFrame=frame==='weekly'?'weekly':'daily';
  const setup=tradeSetup?.[scopedFrame];
  const shared=tradeSetup?.shared||{};
  const isActionFocus=options?.focus==='action_strength';
  const focus=isActionFocus?'Action Strength':'Trade Score';
  document.querySelector('#trade-score-modal .trade-score-modal')?.classList.toggle('trade-score-modal-compact',isActionFocus);
  if(!setup||setup.score==null){
    document.getElementById('trade-score-title').textContent=`${ticker||'Ticker'} ${tradeScoreFrameLabel(scopedFrame)} ${focus}`;
    document.getElementById('trade-score-subtitle').textContent='No trade score is available yet.';
    document.getElementById('trade-score-status').textContent='The app does not have enough setup data for this frame yet.';
    document.getElementById('trade-score-topline').innerHTML='';
    document.getElementById('trade-score-action-strength').innerHTML='';
    document.getElementById('trade-score-grid').innerHTML='';
    document.getElementById('trade-score-formula').innerHTML='';
    document.getElementById('trade-score-highlights').innerHTML='';
    document.getElementById('trade-score-structure').innerHTML='';
    return;
  }
  const breakdown=tradeScoreBreakdown(setup,shared);
  const toneCls=tradeScoreToneClass(setup.side);
  const actionStrength=tradeScoreActionStrength(setup,shared);
  const components=(breakdown.components||[]).map(component=>`<div class="trade-score-factor trade-score-factor-${toneCls}">
    <div class="trade-score-factor-head">
      <span>${escapeHtml(component.label||'Factor')}</span>
      <span>${escapeHtml(String(component.weight_pct??'--'))}% weight</span>
    </div>
    <div class="trade-score-factor-score ${toneCls}">${tradeScoreSigned(component.weighted_contribution,1)} pts</div>
    <div class="trade-score-factor-meta">${tradeScoreSigned(component.component_score)} / 100 factor score</div>
  </div>`).join('');
  document.getElementById('trade-score-title').textContent=`${ticker||'Ticker'} ${tradeScoreFrameLabel(scopedFrame)} ${focus}`;
  document.getElementById('trade-score-subtitle').textContent=isActionFocus
    ?`${tradeScoreSigned(setup.score)} trade score · ${setup.side||'mixed'}`
    :`${breakdown.strength_label||'Trade setup'} · ${setup.side||'mixed'}`;
  document.getElementById('trade-score-status').textContent='';
  document.getElementById('trade-score-topline').innerHTML=isActionFocus
    ?''
    :`<div class="trade-score-pill trade-score-pill-${toneCls}">
      <span>Final score</span>
      <strong>${tradeScoreSigned(setup.score)}</strong>
    </div>
    <div class="trade-score-pill">
      <span>Trend bias</span>
      <strong>${tradeScoreSigned(setup.trend_bias)}</strong>
    </div>
    <div class="trade-score-pill">
      <span>Raw setup</span>
      <strong>${tradeScoreSigned(breakdown.raw_score,1)}</strong>
    </div>`;
  document.getElementById('trade-score-action-strength').innerHTML=isActionFocus?tradeScoreActionStrengthHtml(actionStrength,toneCls,true):'';
  document.getElementById('trade-score-grid').innerHTML=isActionFocus?'':components;
  document.getElementById('trade-score-formula').innerHTML='';
  document.getElementById('trade-score-highlights').innerHTML='';
  document.getElementById('trade-score-structure').innerHTML='';
}

function openTradeScoreDetails(frame='daily',ticker=null,tradeSetup=null,options={}){
  const resolvedTicker=(ticker||document.getElementById('ticker')?.value||'').toUpperCase();
  renderTradeScorePayload(resolvedTicker,frame,tradeSetup||lastData?.trade_setup||{},options);
  document.getElementById('trade-score-modal')?.classList.add('open');
}

function openWatchlistTradeScore(ticker){
  const row=wlTrendRows.find(item=>item?.ticker===ticker);
  if(!row?.trade_setup)return;
  openTradeScoreDetails(wlTrendFrame,ticker,row.trade_setup);
}

function openWatchlistActionStrength(ticker){
  const row=wlTrendRows.find(item=>item?.ticker===ticker);
  if(!row?.trade_setup)return;
  openTradeScoreDetails(wlTrendFrame,ticker,row.trade_setup,{focus:'action_strength'});
}

document.addEventListener('keydown',event=>{
  if(event.key==='Escape')closeTradeScoreModal();
});
