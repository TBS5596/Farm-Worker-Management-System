/**
 * analytics-page.js - the charts on Analytics.
 *
 * Three rules this file follows, and why:
 *
 *  One axis per chart. Two measures on two scales in one frame invite a reader
 *  to compare shapes that are not comparable, which is the commonest way a
 *  chart misleads. Hours and money get separate charts.
 *
 *  Colour carries identity, never rank. The two series colours are fixed:
 *  green is ordinary hours, amber is overtime, on every chart and in every
 *  filter state. Sorting a chart must never repaint it.
 *
 *  The palette is checked rather than chosen by eye. #35946a and #b4690e pass
 *  colour-vision separation, the lightness band, the chroma floor and contrast
 *  against this page's surface. Do not substitute a colour here without
 *  re-checking the pair - "it looks fine to me" is exactly the test that fails
 *  the roughly one reader in twelve with a colour vision deficiency.
 */
(function () {
  'use strict';

  var HOURS = '#35946a';     // ordinary hours, and the single-series colour
  var OVERTIME = '#b4690e';  // overtime, everywhere it appears
  var INK = '#5f6b76';       // axis and label text: ink tokens, never the series colour
  var GRID = 'rgba(95, 107, 118, 0.14)';
  var SURFACE = '#ffffff';

  var node = document.getElementById('reportData');
  if (!node || typeof Chart === 'undefined') { return; }

  var data;
  try { data = JSON.parse(node.textContent); } catch (err) { return; }

  var baseScales = {
    x: { grid: { display: false }, ticks: { color: INK } },
    y: {
      beginAtZero: true,
      grid: { color: GRID, drawBorder: false },
      ticks: { color: INK },
    },
  };

  function money(value) {
    return 'ZMW ' + Number(value).toLocaleString('en', { minimumFractionDigits: 2,
                                                         maximumFractionDigits: 2 });
  }

  // --- Hours by weekday -------------------------------------------------
  // Stacked, because ordinary hours and overtime are parts of one total
  // rather than two independent measures. The 2px surface-coloured border
  // between segments keeps the boundary visible when the two colours meet.
  var weekdayCanvas = document.getElementById('weekdayChart');
  if (weekdayCanvas && data.weekdays && data.weekdays.length) {
    var labels = data.weekdays.map(function (d) { return d.name.slice(0, 3); });
    var regular = data.weekdays.map(function (d) {
      return Math.max(0, Number((d.hours - d.overtime).toFixed(2)));
    });
    var overtime = data.weekdays.map(function (d) { return d.overtime; });

    new Chart(weekdayCanvas, {
      type: 'bar',
      data: {
        labels: labels,
        datasets: [
          { label: 'Ordinary hours', data: regular, backgroundColor: HOURS,
            borderColor: SURFACE, borderWidth: 2, borderRadius: 4,
            borderSkipped: false, maxBarThickness: 46 },
          { label: 'Overtime', data: overtime, backgroundColor: OVERTIME,
            borderColor: SURFACE, borderWidth: 2, borderRadius: 4,
            borderSkipped: false, maxBarThickness: 46 },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: 'index', intersect: false },
        scales: {
          x: { stacked: true, grid: { display: false }, ticks: { color: INK } },
          y: { stacked: true, beginAtZero: true, grid: { color: GRID, drawBorder: false },
               ticks: { color: INK }, title: { display: true, text: 'Hours', color: INK } },
        },
        plugins: {
          // Two series, so a legend is required: identity is never left to
          // colour alone.
          legend: { display: true, position: 'bottom', labels: { color: INK, boxWidth: 12 } },
          tooltip: {
            callbacks: {
              afterBody: function (items) {
                var row = data.weekdays[items[0].dataIndex];
                return row.shifts + ' shifts, averaging ' + row.average.toFixed(1) + ' h';
              },
            },
          },
        },
      },
    });
  }

  // --- Cost by department ----------------------------------------------
  // Horizontal, because department names are words and words read along a
  // horizontal axis without being turned on their side.
  var departmentCanvas = document.getElementById('departmentChart');
  if (departmentCanvas && data.departments && data.departments.length) {
    new Chart(departmentCanvas, {
      type: 'bar',
      data: {
        labels: data.departments.map(function (d) { return d.name; }),
        datasets: [{
          // One series: the chart's own label names it, so no legend box.
          label: 'Gross pay',
          data: data.departments.map(function (d) { return d.gross; }),
          backgroundColor: HOURS,
          borderRadius: 4,
          borderSkipped: false,
          maxBarThickness: 26,
        }],
      },
      options: {
        indexAxis: 'y',
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: { beginAtZero: true, grid: { color: GRID, drawBorder: false }, ticks: { color: INK } },
          y: { grid: { display: false }, ticks: { color: INK } },
        },
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: function (item) { return money(item.raw); },
              afterLabel: function (item) {
                var row = data.departments[item.dataIndex];
                return row.headcount + ' workers, ' + row.share.toFixed(0) + '% of the bill';
              },
            },
          },
        },
      },
    });
  }

  // --- Highest cost workers --------------------------------------------
  // Capped at ten. Beyond that the bars are too thin to compare and the table
  // below is the better way to read the rest.
  var workerCanvas = document.getElementById('workerCostChart');
  if (workerCanvas && data.workers && data.workers.length) {
    var names = data.workerNames.slice(0, 10);
    var values = data.workers.slice(0, 10);
    new Chart(workerCanvas, {
      type: 'bar',
      data: {
        labels: names,
        datasets: [{
          label: 'Gross pay',
          data: values,
          backgroundColor: HOURS,
          borderRadius: 4,
          borderSkipped: false,
          maxBarThickness: 26,
        }],
      },
      options: {
        indexAxis: 'y',
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: { beginAtZero: true, grid: { color: GRID, drawBorder: false }, ticks: { color: INK } },
          y: { grid: { display: false }, ticks: { color: INK } },
        },
        plugins: {
          legend: { display: false },
          tooltip: { callbacks: { label: function (item) { return money(item.raw); } } },
        },
      },
    });
  }
})();
