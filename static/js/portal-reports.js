/**
 * portal-reports.js - the one chart a worker sees.
 *
 * A single series, so there is no legend: the heading above the chart names
 * what the bars are, and a legend box for one thing is furniture. The colour
 * is the same green used for hours on the admin reports, because the same
 * quantity should not change colour depending on who is looking at it.
 */
(function () {
  'use strict';

  var node = document.getElementById('workerReportData');
  if (!node || typeof Chart === 'undefined') { return; }

  var weeks;
  try { weeks = JSON.parse(node.textContent); } catch (err) { return; }
  if (!weeks || !weeks.length) { return; }

  var canvas = document.getElementById('weeksChart');
  if (!canvas) { return; }

  var HOURS = '#35946a';
  var INK = '#5f6b76';

  new Chart(canvas, {
    type: 'bar',
    data: {
      labels: weeks.map(function (w) { return w.label; }),
      datasets: [{
        label: 'Hours',
        data: weeks.map(function (w) { return w.hours; }),
        backgroundColor: HOURS,
        borderRadius: 4,
        borderSkipped: false,
        maxBarThickness: 34,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      scales: {
        x: { grid: { display: false }, ticks: { color: INK } },
        y: {
          beginAtZero: true,
          grid: { color: 'rgba(95, 107, 118, 0.14)', drawBorder: false },
          ticks: { color: INK },
        },
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: function (item) { return item.raw.toFixed(1) + ' hours'; },
            afterLabel: function (item) {
              var week = weeks[item.dataIndex];
              var parts = [week.days + ' day' + (week.days === 1 ? '' : 's') + ' worked'];
              if (week.overtime) { parts.push(week.overtime.toFixed(1) + ' h overtime'); }
              if (week.late) { parts.push(week.late + ' late'); }
              return parts.join(', ');
            },
          },
        },
      },
    },
  });
})();
