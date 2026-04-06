/* Signal bar: fetches per-ticker signal after chart load. */
(function(){
  const bar = document.getElementById('signal-bar');
  if(!bar) return;

  const badge = document.getElementById('sb-badge');
  const elShares = document.getElementById('sb-shares');
  const elNotional = document.getElementById('sb-notional');
  const elStop = document.getElementById('sb-stop');
  const elRisk = document.getElementById('sb-risk');
  const elWeight = document.getElementById('sb-weight');

  function fmt(n, dec){
    if(n == null || isNaN(n)) return '—';
    return Number(n).toLocaleString('en-US',{minimumFractionDigits:dec||0, maximumFractionDigits:dec||0});
  }
  function pct(n){
    if(n == null || isNaN(n)) return '—';
    return (n*100).toFixed(1)+'%';
  }

  let _lastTicker = null;

  window.refreshSignalBar = function(ticker){
    if(!ticker){ bar.style.display='none'; return; }
    ticker = ticker.toUpperCase();
    _lastTicker = ticker;
    fetch('/api/signals/'+encodeURIComponent(ticker))
      .then(r=>r.json())
      .then(s=>{
        if(s.ticker !== _lastTicker) return;
        if(s.direction === 'NO_DATA'){
          bar.style.display='none';
          return;
        }
        bar.style.display='flex';
        const isLong = s.direction === 'LONG';
        badge.textContent = s.direction;
        badge.className = 'sb-badge ' + (isLong ? 'long' : 'flat');
        elShares.textContent = s.shares || '—';
        elNotional.textContent = s.notional ? '$'+fmt(s.notional) : '—';
        elStop.textContent = s.stop_level != null ? fmt(s.stop_level,2) : '—';
        elRisk.textContent = s.position_risk ? '$'+fmt(s.position_risk) : '—';
        elWeight.textContent = s.weight ? pct(s.weight) : '—';
      })
      .catch(()=>{ bar.style.display='none'; });
  };

  const _origLoadChart = window.loadChart;
  if(typeof _origLoadChart === 'function'){
    window.loadChart = async function(){
      await _origLoadChart.apply(this, arguments);
      const t = document.getElementById('ticker');
      if(t) refreshSignalBar(t.value);
    };
  }
})();
