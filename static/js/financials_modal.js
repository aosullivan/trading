function closeFinancials(){
  document.getElementById('financials-modal').classList.remove('open');
}

function renderFinancialsPayload(data){
  const overview=data.overview||{};
  const title=overview.ticker_name||overview.ticker||'Financials';
  const subtitle=[overview.ticker,overview.company_line].filter(Boolean).join(' \u2022 ');
  document.getElementById('financials-title').textContent=title;
  document.getElementById('financials-subtitle').textContent=subtitle;

  document.getElementById('financials-status').textContent=data.message||(
    data.available
      ? 'Cached snapshot of valuation, scale, quality, and balance-sheet metrics.'
      : 'Financial metrics are unavailable for this ticker.'
  );

  const metaBits=[];
  if(overview.currency)metaBits.push(`<span class="fin-pill">${escapeHtml(overview.currency)}</span>`);
  if(overview.quote_type)metaBits.push(`<span class="fin-pill">${escapeHtml(String(overview.quote_type).toUpperCase())}</span>`);
  if(overview.website)metaBits.push(`<a class="fin-link" href="${escapeHtml(overview.website)}" target="_blank" rel="noopener noreferrer">Website</a>`);
  document.getElementById('financials-meta').innerHTML=metaBits.join('');

  document.getElementById('financials-grid').innerHTML=(data.sections||[]).map(section=>`<div class="fin-card">
    <h4>${escapeHtml(section.title)}</h4>
    ${(section.metrics||[]).map(metric=>`<div class="fin-metric">
      <div class="fin-label">${escapeHtml(metric.label)}</div>
      <div class="fin-value">${escapeHtml(metric.display)}</div>
    </div>`).join('')}
  </div>`).join('');

  const summary=document.getElementById('financials-summary');
  if(overview.summary){
    summary.style.display='block';
    summary.innerHTML=`<h4>Business Summary</h4><div>${escapeHtml(overview.summary)}</div>`;
  }else{
    summary.style.display='none';
    summary.innerHTML='';
  }
}

async function openFinancials(){
  const ticker=document.getElementById('ticker').value.toUpperCase();
  document.getElementById('financials-modal').classList.add('open');
  document.getElementById('financials-title').textContent=`${ticker} Financials`;
  document.getElementById('financials-subtitle').textContent='';
  document.getElementById('financials-status').textContent='Loading cached financial snapshot...';
  document.getElementById('financials-meta').innerHTML='';
  document.getElementById('financials-grid').innerHTML='';
  document.getElementById('financials-summary').style.display='none';
  document.getElementById('financials-summary').innerHTML='';

  if(financialsClientCache.has(ticker)){
    renderFinancialsPayload(financialsClientCache.get(ticker));
    return;
  }

  try{
    const res=await fetch(`/api/financials?ticker=${encodeURIComponent(ticker)}`);
    const data=await res.json();
    if(!res.ok||data.error) throw new Error(data.error||'Unable to load financials');
    financialsClientCache.set(ticker,data);
    renderFinancialsPayload(data);
  }catch(err){
    renderFinancialsPayload({
      available:false,
      message:`Unable to load financials: ${err.message}`,
      overview:{ticker,ticker_name:`${ticker} Financials`},
      sections:[],
    });
  }
}
