/**
 * dashboard-page.js - the attendance trend chart.
 *
 * The data comes from the server already aggregated, embedded as JSON in data
 * attributes on the <canvas> (see payroll_engine.attendance_trend). No fetch is
 * needed, so the chart is drawn on first paint and works with no network.
 *
 * Example of the four series for a fortnight:
 *   labels:   ["15 Aug", "16 Aug", ...]   one entry per day, oldest first
 *   workers:  [5, 0, 6, 6, ...]           how many people were present
 *   verified: [5, 0, 6, 5, ...]           of those, how many matched a face
 *   hours:    [42.5, 0, 49, 48, ...]      total hours worked
 *
 * Workers and verified are bars side by side, so a gap between them is
 * immediately visible - that gap is attendance recorded without an identity
 * match, which should normally be zero. Hours is a line on its own axis
 * because it is a different unit an order of magnitude larger.
 */
document.addEventListener('DOMContentLoaded', function () {
  var canvas = document.getElementById('attendanceTrendChart');

  // No canvas on this render, or the Chart.js CDN is unreachable: the rest of
  // the dashboard must still work.
  if (!canvas || typeof Chart === 'undefined') {
    return;
  }

  /** Read one JSON series from the canvas's data attributes. */
  function readSeries(name) {
    try {
      return JSON.parse(canvas.dataset[name] || '[]');
    } catch (_) {
      return [];  // a malformed series draws as empty rather than breaking the page
    }
  }

  var labels = readSeries('labels');
  var workers = readSeries('workers');
  var verified = readSeries('verified');
  var hours = readSeries('hours');

  new Chart(canvas, {
    data: {
      labels: labels,
      datasets: [
        {
          type: 'bar',
          label: 'Workers present',
          data: workers,
          backgroundColor: 'rgba(46, 125, 82, 0.75)',  // mid green
          borderRadius: 4,
          order: 2,
        },
        {
          type: 'bar',
          label: 'Face verified',
          data: verified,
          backgroundColor: 'rgba(26, 71, 49, 0.9)',    // deep green, same family
          borderRadius: 4,
          order: 1,
        },
        {
          type: 'line',
          label: 'Hours worked',
          data: hours,
          borderColor: '#fd7e14',
          backgroundColor: 'rgba(253, 126, 20, 0.15)',
          tension: 0.35,
          yAxisID: 'hoursAxis',  // its own scale: hours run far higher than headcount
          order: 0,              // drawn on top of the bars
        },
      ],
    },
    options: {
      responsive: true,
      // Height comes from .chart-shell in dashboard.css. Without that wrapper
      // this setting lets the canvas grow to fill the whole page.
      maintainAspectRatio: false,
      // Hovering anywhere in a day's column shows all three values for that
      // day, which is how the numbers are actually compared.
      interaction: { mode: 'index', intersect: false },
      plugins: {
        legend: { position: 'bottom', labels: { boxWidth: 12, usePointStyle: true } },
      },
      scales: {
        x: { grid: { display: false } },
        y: {
          beginAtZero: true,
          title: { display: true, text: 'Workers' },
          ticks: { precision: 0 },  // headcount is whole people
        },
        hoursAxis: {
          beginAtZero: true,
          position: 'right',
          grid: { drawOnChartArea: false },  // one set of gridlines, not two
          title: { display: true, text: 'Hours' },
        },
      },
    },
  });
});
