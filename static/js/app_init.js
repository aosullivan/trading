readURLParams();
document.addEventListener('DOMContentLoaded',()=>{
  document.getElementById('bt-start').value=chartStart||yearAgo.toISOString().split('T')[0];
  document.getElementById('bt-end').value=chartEnd||now.toISOString().split('T')[0];
  setBTRangeLabel();
});

// Keyboard shortcuts
document.addEventListener('keydown',e=>{
  if(e.key==='Escape')closeFinancials();
  if(e.key==='Enter'&&document.activeElement.id==='ticker')loadChart();
});

initChart();buildChartLegend();restoreURLState();syncInitialSignalChipState();loadWL();loadChart();
