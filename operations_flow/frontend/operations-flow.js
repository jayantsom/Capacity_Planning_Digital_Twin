import { apiJson } from '/shared/static/dashboard.js';
import { SEMANTIC_COLORS } from '/shared/static/chart.js?v=20261027c';
import {
  applyRoleView, bindTabs, chartManager, chartSpec, fillSelect, formatNumber, queryFromForm,
  renderKpis, renderTable, setViewState,
} from '/shared/static/planning.js?v=20261027e';

const form = document.getElementById('filters');
const charts = chartManager();
let activeView = 'production-control';

async function loadFilters() {
  const payload = await apiJson(`/operations-flow/api/filters/${activeView}`);
  fillSelect(form, 'site', payload.options.site, 'All sites');
  fillSelect(form, 'product', payload.options.product, 'All products');
  fillSelect(form, 'operation', payload.options.operation, 'All operations');
  fillSelect(form, 'resource', payload.options.resource, 'All resources');
  document.getElementById('filter-scope').textContent =
    'Filter applicability is dataset-specific: product does not apply to queue/throughput; operation and resource do not apply to cycle time, route adherence, or schedule attainment.';
}

function aggregateByDate(rows, dateKey, valueKey) {
  const values = new Map();
  rows.forEach((row) => values.set(String(row[dateKey]), (values.get(String(row[dateKey])) || 0) + Number(row[valueKey] || 0)));
  return [...values.entries()].sort(([a], [b]) => a.localeCompare(b));
}

async function loadDashboard() {
  charts.dispose();
  setViewState(`Loading ${activeView.replace('-', ' ')} view.`);
  try {
    const payload = await apiJson(`/operations-flow/api/dashboard/${activeView}?${queryFromForm(form)}`);
    const release = document.getElementById('release-status');
    release.textContent = `Release ${payload.release.release_id || 'unknown'}`;
    release.dataset.state = payload.status === 'empty' ? 'warning' : 'ready';
    setViewState(payload.message || `${activeView.replace('-', ' ')} view at daily grain.`, payload.status);
    const kpi = payload.kpis;
    renderKpis('flow-kpis', [
      ['WIP', kpi.wip_quantity_ea, 'EA'],
      ['Maximum queue age', kpi.maximum_queue_age_minutes, 'minutes', 1],
      ['Throughput', kpi.throughput_quantity_ea, 'EA'],
      ['Rework rate', kpi.rework_rate_pct == null ? null : kpi.rework_rate_pct * 100, '%', 1],
      ['Route adherence', kpi.route_adherence_pct == null ? null : kpi.route_adherence_pct * 100, '%', 1],
      ['Schedule attainment', kpi.schedule_attainment_pct == null ? null : kpi.schedule_attainment_pct * 100, '%', 1],
    ]);
    const context = { releaseId: payload.release.release_id, filters: Object.fromEntries(new FormData(form)) };
    const dates = [...new Set(payload.queue.map((row) => String(row.movement_date)))];
    const operations = [...new Set(payload.queue.map((row) => row.operation))];
    const heatmap = payload.queue.map((row) => [
      dates.indexOf(String(row.movement_date)),
      operations.indexOf(row.operation),
      row.p90_queue_age_minutes,
    ]);
    await charts.draw('queue-heatmap', chartSpec({
      title: 'P90 queue age by date and operation',
      metric: 'P90 queue age', unit: 'MIN', grain: 'DAY', source: 'srv_operations_queue',
      xTitle: 'Date', xValues: dates, yTitle: 'Operation',
      yType: 'category', yValues: operations,
      summary: 'Daily 90th percentile queue age by governed operation.',
      zoom: false, tooltip: 'item',
      rows: payload.queue.map((row) => [row.movement_date, row.operation, row.p90_queue_age_minutes]),
      columns: ['Date', 'Operation', 'P90 queue age minutes'],
      visualMap: {
        min: Math.min(0, ...heatmap.map((item) => item[2] || 0)),
        max: Math.max(1, ...heatmap.map((item) => item[2] || 0)),
        calculable: true, orient: 'horizontal',
      },
      series: [{ name: 'P90 queue age', type: 'heatmap', data: heatmap }],
    }), context);
    const cycleDates = [...new Set(payload.cycle_time.map((row) => String(row.release_date)))];
    const cycleValue = (date, key) => {
      const matches = payload.cycle_time.filter((row) => String(row.release_date) === date);
      return matches.length ? matches.reduce((sum, row) => sum + Number(row[key] || 0), 0) / matches.length : null;
    };
    await charts.draw('cycle-chart', chartSpec({
      title: 'Cycle-time percentile trend',
      metric: 'Lot cycle time', unit: 'MIN', grain: 'DAY', source: 'srv_operations_cycle_time',
      xTitle: 'Release date', xValues: cycleDates, yTitle: 'Cycle time (minutes)',
      summary: 'Daily average of published product-level P50 and P90 lot cycle-time percentiles.',
      series: [
        { name: 'P50 cycle time', type: 'line', color: SEMANTIC_COLORS.normalCapacity, data: cycleDates.map((date) => cycleValue(date, 'p50_cycle_time_minutes')) },
        { name: 'P90 cycle time', type: 'line', color: SEMANTIC_COLORS.warning, data: cycleDates.map((date) => cycleValue(date, 'p90_cycle_time_minutes')) },
      ],
    }), context);
    const throughput = aggregateByDate(payload.throughput, 'movement_date', 'throughput_quantity_ea');
    const rework = aggregateByDate(payload.rework, 'movement_date', 'rework_count');
    const flowDates = [...new Set([...throughput.map(([date]) => date), ...rework.map(([date]) => date)])].sort();
    await charts.draw('throughput-chart', chartSpec({
      title: 'Throughput and rework movements',
      metric: 'Output and rework count', unit: 'EA / MOVEMENTS', grain: 'DAY',
      source: 'srv_operations_throughput, srv_operations_rework',
      xTitle: 'Movement date', xValues: flowDates, yTitle: 'Quantity',
      summary: 'Daily throughput quantity and recorded rework movement count.',
      series: [
        { name: 'Throughput EA', type: 'bar', color: SEMANTIC_COLORS.actualOutput, data: flowDates.map((date) => throughput.find(([key]) => key === date)?.[1] ?? 0) },
        { name: 'Rework movements', type: 'line', color: SEMANTIC_COLORS.shortage, data: flowDates.map((date) => rework.find(([key]) => key === date)?.[1] ?? 0) },
      ],
    }), context);
    const center = payload.queue_control_chart;
    const queueByDate = dates.map((date) => {
      const matches = payload.queue.filter((row) => String(row.movement_date) === date);
      return matches.length ? matches.reduce((sum, row) => sum + Number(row.p90_queue_age_minutes || 0), 0) / matches.length : null;
    });
    await charts.draw('control-chart', chartSpec({
      title: 'Descriptive queue-age control chart',
      metric: 'P90 queue age', unit: 'MIN', grain: 'DAY', source: 'srv_operations_queue',
      xTitle: 'Movement date', xValues: dates, yTitle: 'P90 queue age (minutes)',
      summary: `Published P90 queue age with descriptive mean plus or minus three population standard deviations. Qualified: ${center.qualified}.`,
      series: [
        { name: 'P90 queue age', type: 'line', color: SEMANTIC_COLORS.actualOutput, data: queueByDate },
        { name: 'Center line', type: 'line', color: SEMANTIC_COLORS.baseline, data: dates.map(() => center.center_line_minutes) },
        { name: 'Upper control limit', type: 'line', color: SEMANTIC_COLORS.shortage, data: dates.map(() => center.upper_control_limit_minutes) },
        { name: 'Lower control limit', type: 'line', color: SEMANTIC_COLORS.positiveHeadroom, data: dates.map(() => center.lower_control_limit_minutes) },
      ],
    }), context);
    const bottleneckDates = payload.bottleneck_movement.map((row) => String(row.movement_date));
    await charts.draw('bottleneck-chart', chartSpec({
      title: 'Dynamic bottleneck migration',
      metric: 'P90 queue age of daily leading bottleneck', unit: 'MIN', grain: 'DAY',
      source: 'srv_operations_bottleneck_movement',
      xTitle: 'Movement date', xValues: bottleneckDates, yTitle: 'P90 queue age (minutes)',
      summary: 'Daily leading bottleneck operation and its published P90 queue age.',
      series: [{ name: 'Leading bottleneck P90', type: 'line', color: SEMANTIC_COLORS.shortage, data: payload.bottleneck_movement.map((row) => row.p90_queue_age_minutes) }],
    }), context);
    renderTable('bottleneck-table', 'Daily leading bottleneck and movement flag.', [
      { key: 'movement_date', label: 'Date' }, { key: 'site_name', label: 'Site full name' },
      { key: 'operation', label: 'Bottleneck operation' }, { key: 'equipment_name', label: 'Resource full name' },
      { key: 'prior_bottleneck_operation', label: 'Prior bottleneck' },
      { key: 'bottleneck_moved', label: 'Moved' },
      { key: 'p90_queue_age_minutes', label: 'P90 queue minutes', numeric: true, format: (v) => formatNumber(v, 1) },
    ], payload.bottleneck_movement);
    renderTable('wip-table', 'Current work in process by operation and resource.', [
      { key: 'site_name', label: 'Site full name' }, { key: 'product_description', label: 'Product full name' },
      { key: 'current_operation', label: 'Current operation' }, { key: 'equipment_name', label: 'Resource full name' },
      { key: 'work_order_count', label: 'Work orders', numeric: true },
      { key: 'lot_count', label: 'Lots', numeric: true },
      { key: 'wip_quantity_ea', label: 'WIP EA', numeric: true, format: formatNumber },
      { key: 'maximum_queue_age_minutes', label: 'Max queue minutes', numeric: true, format: (v) => formatNumber(v, 1) },
    ], payload.wip);
    renderTable('route-table', 'Observed route adherence at lot grain.', [
      { key: 'site_name', label: 'Site full name' }, { key: 'product_description', label: 'Product full name' },
      { key: 'work_order_id', label: 'Work order' }, { key: 'lot_id', label: 'Lot' },
      { key: 'route_id', label: 'Route' }, { key: 'observed_step_count', label: 'Observed steps', numeric: true },
      { key: 'expected_step_count', label: 'Expected steps', numeric: true },
      { key: 'route_adherent', label: 'Adherent' },
    ], payload.route_adherence);
    renderTable('schedule-table', 'Schedule attainment uses published schedule facts.', [
      { key: 'schedule_date', label: 'Schedule date' }, { key: 'site_name', label: 'Site full name' },
      { key: 'product_description', label: 'Product full name' },
      { key: 'scheduled_work_order_count', label: 'Scheduled orders', numeric: true },
      { key: 'attained_work_order_count', label: 'Attained orders', numeric: true },
      { key: 'planned_quantity_ea', label: 'Planned EA', numeric: true, format: formatNumber },
      { key: 'completed_quantity_ea', label: 'Completed EA', numeric: true, format: formatNumber },
      { key: 'schedule_attainment_pct', label: 'Attainment %', numeric: true, format: (v) => formatNumber(Number(v) * 100, 1) },
    ], payload.schedule_attainment);
    const sankeyState = document.getElementById('sankey-state');
    sankeyState.textContent = payload.sankey.reason;
    sankeyState.className = payload.sankey.available ? '' : 'unavailable';
    if (payload.sankey.available) {
      const totals = new Map();
      payload.sankey.rows.forEach((row) => {
        const route = row.route_id;
        const sequence = Number(row.route_step_sequence);
        const source = route && Number.isFinite(sequence)
          ? `${route} · ${sequence - 1} · ${row.from_operation}`
          : `FROM · ${row.from_operation}`;
        const target = route && Number.isFinite(sequence)
          ? `${route} · ${sequence} · ${row.to_operation}`
          : `TO · ${row.to_operation}`;
        const key = `${source}\u0000${target}`;
        totals.set(key, (totals.get(key) || 0) + Number(row.output_quantity_ea || 0));
      });
      const links = [...totals.entries()].map(([key, value]) => {
        const [source, target] = key.split('\u0000');
        return { source, target, value };
      });
      const nodeNames = [...new Set(links.flatMap((link) => [link.source, link.target]))];
      await charts.draw('sankey-chart', chartSpec({
        title: 'Quantity flow through manufacturing operations',
        metric: 'Recorded output quantity', unit: 'EA', grain: 'DAY',
        source: 'srv_operations_route_flow',
        xTitle: '', xValues: [], yTitle: '', axesVisible: false, zoom: false,
        tooltip: 'item',
        summary: 'Recorded output quantity flowing between consecutive operations.',
        rows: links.map((link) => [link.source, link.target, link.value]),
        columns: ['From operation', 'To operation', 'Output quantity EA'],
        series: [{
          name: 'Route flow',
          type: 'sankey',
          data: nodeNames.map((name) => ({ name })),
          links,
          draggable: false,
          emphasis: { focus: 'adjacency' },
          lineStyle: { color: 'gradient', opacity: 0.45 },
        }],
      }), context);
    } else {
      document.getElementById('sankey-chart').replaceChildren();
    }
  } catch (error) {
    const release = document.getElementById('release-status');
    release.textContent = 'Not ready'; release.dataset.state = 'error';
    setViewState(error.message || 'Operations Flow is not ready.', 'error');
  }
}

bindTabs((view) => {
  activeView = view;
  applyRoleView(view);
  void loadFilters().then(loadDashboard);
});
form.addEventListener('submit', (event) => { event.preventDefault(); void loadDashboard(); });
void loadFilters().then(loadDashboard).catch((error) => setViewState(error.message, 'error'));
