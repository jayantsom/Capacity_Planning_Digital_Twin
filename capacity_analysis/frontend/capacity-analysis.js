import { apiJson } from '/shared/static/dashboard.js';
import {
  renderGovernedChart,
  SEMANTIC_COLORS,
} from '/shared/static/chart.js?v=20261027c';

const form = document.getElementById('capacity-filters');
const state = document.getElementById('view-state');
const releaseStatus = document.getElementById('release-status');
const tabs = [...document.querySelectorAll('[role="tab"]')];
let activeTab = 'tactical';
let chartHandles = [];

function number(value, digits = 0) {
  if (value == null || Number.isNaN(Number(value))) return '-';
  return Number(value).toLocaleString(undefined, { maximumFractionDigits: digits });
}

function monthValue(value) {
  return value ? value.replace('-', '') : '';
}

function queryString() {
  const data = new FormData(form);
  const params = new URLSearchParams();
  for (const [key, value] of data.entries()) {
    const normalized = key.startsWith('month_') ? monthValue(value) : value;
    if (normalized !== '') params.set(key, normalized);
  }
  return params.toString();
}

function setState(message, kind = 'ready') {
  state.textContent = message;
  state.dataset.state = kind;
}

function fillSelect(name, options, placeholder) {
  const select = form.elements[name];
  const selected = select.value;
  select.replaceChildren();
  if (placeholder) {
    const option = document.createElement('option');
    option.value = '';
    option.textContent = placeholder;
    select.append(option);
  }
  options.forEach((item) => {
    const option = document.createElement('option');
    option.value = item.value;
    option.textContent = item.label;
    select.append(option);
  });
  if ([...select.options].some((option) => option.value === selected)) {
    select.value = selected;
  }
}

function chartSpec(overrides) {
  return {
    title: overrides.title,
    metric: overrides.metric,
    unit: overrides.unit,
    grain: 'MONTH',
    aggregation: overrides.aggregation || 'SUM',
    source: overrides.source,
    axes: overrides.axes,
    legend: { show: overrides.legend !== false, type: 'scroll' },
    tooltip: { show: true, trigger: overrides.tooltipTrigger || 'axis' },
    thresholds: overrides.thresholds || [],
    dataZoom: { enabled: overrides.zoom !== false },
    export: { rowScope: 'displayed' },
    emptyState: { message: 'No data matches the selected filters.' },
    accessibility: {
      summary: overrides.summary,
      table: true,
      columns: overrides.accessibilityColumns,
      rows: overrides.accessibilityRows,
    },
    visualMap: overrides.visualMap,
    series: overrides.series,
    height: overrides.height || 340,
  };
}

async function draw(containerId, spec, release) {
  const handle = await renderGovernedChart(
    document.getElementById(containerId),
    spec,
    { releaseId: release.release_id, filters: Object.fromEntries(new FormData(form)) },
  );
  chartHandles.push(handle);
}

function disposeCharts() {
  chartHandles.forEach((handle) => handle.dispose());
  chartHandles = [];
}

function renderKpis(containerId, entries) {
  const container = document.getElementById(containerId);
  container.replaceChildren(...entries.map(([label, value, unit]) => {
    const card = document.createElement('article');
    const title = document.createElement('small');
    title.textContent = label;
    const metric = document.createElement('strong');
    metric.textContent = number(value, unit === '%' ? 1 : 0);
    const suffix = document.createElement('span');
    suffix.textContent = unit;
    const valueRow = document.createElement('div');
    valueRow.className = 'ct-kpi-value';
    valueRow.append(metric, suffix);
    card.append(title, valueRow);
    return card;
  }));
}

function renderTable(id, captionText, columns, rows) {
  const table = document.getElementById(id);
  const caption = document.createElement('caption');
  caption.textContent = captionText;
  const head = document.createElement('thead');
  const headRow = document.createElement('tr');
  columns.forEach((column) => {
    const th = document.createElement('th');
    th.scope = 'col';
    th.textContent = column.label;
    headRow.append(th);
  });
  head.append(headRow);
  const body = document.createElement('tbody');
  rows.forEach((item) => {
    const row = document.createElement('tr');
    columns.forEach((column) => {
      const cell = document.createElement('td');
      const raw = item[column.key];
      cell.textContent = column.format ? column.format(raw, item) : (raw ?? '-');
      if (column.numeric) cell.classList.add('numeric');
      if (column.key === 'bottleneck_severity') {
        cell.classList.add('severity');
        cell.dataset.severity = raw;
      }
      row.append(cell);
    });
    body.append(row);
  });
  table.replaceChildren(caption, head, body);
}

async function renderTactical(payload) {
  const kpi = payload.kpis;
  renderKpis('tactical-kpis', [
    ['Demand', kpi.demand, 'EA'],
    ['Normal Capacity', kpi.normal_capacity, 'EA'],
    ['Maximum Capacity', kpi.maximum_capacity, 'EA'],
    ['Actual Output', kpi.actual_output, 'EA measured'],
    ['Demonstrated Capacity', kpi.demonstrated_capacity, 'EA/month'],
    ['Selected gap', kpi.selected_gap, 'EA'],
    ['Selected utilization', kpi.selected_utilization == null ? null : kpi.selected_utilization * 100, '%'],
  ]);
  const months = payload.trend.map((row) => String(row.month));
  await draw('trend-chart', chartSpec({
    title: 'Demand and supply trend',
    metric: 'Demand, supply, measured output, and demonstrated capacity',
    unit: 'EA',
    source: 'srv_vw_capacity_summary, srv_actual_output, srv_demonstrated_capacity',
    axes: { x: { type: 'category', title: 'Month', values: months }, y: { type: 'value', title: 'Units (EA)' } },
    summary: 'Monthly demand compared with Normal Capacity, Maximum Capacity, Actual Output, and Demonstrated Capacity.',
    series: [
      { name: 'Demand', type: 'line', color: SEMANTIC_COLORS.demand, data: payload.trend.map((row) => row.demand) },
      { name: 'Normal Capacity', type: 'line', color: SEMANTIC_COLORS.normalCapacity, data: payload.trend.map((row) => row.normal_capacity) },
      { name: 'Maximum Capacity', type: 'line', color: SEMANTIC_COLORS.maximumCapacity, data: payload.trend.map((row) => row.maximum_capacity) },
      { name: 'Actual Output', type: 'line', color: SEMANTIC_COLORS.actualOutput, data: payload.trend.map((row) => row.actual_output) },
      { name: 'Demonstrated Capacity', type: 'line', color: SEMANTIC_COLORS.demonstratedCapacity, data: payload.trend.map((row) => row.demonstrated_capacity) },
    ],
  }), payload.release);

  const bridge = payload.capacity_loss_waterfall.components;
  await draw('waterfall-chart', chartSpec({
    title: 'Maximum-to-Normal capacity bridge',
    metric: 'Capacity loss',
    unit: 'EA',
    source: 'srv_vw_capacity_summary',
    axes: { x: { type: 'category', title: 'Bridge component', values: bridge.map((item) => item.label) }, y: { type: 'value', title: 'Capacity (EA)' } },
    summary: `Maximum Capacity plus the signed schedule loss equals Normal Capacity exactly. Reconciliation delta ${payload.capacity_loss_waterfall.reconciliation_delta}.`,
    zoom: false,
    legend: false,
    series: [{ name: 'Capacity bridge', type: 'bar', data: bridge.map((item) => item.value), color: SEMANTIC_COLORS.normalCapacity, label: { show: true } }],
  }), payload.release);

  const sites = [...new Set(payload.site_test_gap_heatmap.map((row) => row.site_label))];
  const tests = [...new Set(payload.site_test_gap_heatmap.map((row) => row.test_type_label))];
  const heatmapRows = payload.site_test_gap_heatmap.map((row) => [
    sites.indexOf(row.site_label),
    tests.indexOf(row.test_type_label),
    row.gap_qty,
  ]);
  await draw('gap-heatmap', chartSpec({
    title: 'Site-test capacity gap',
    metric: 'Capacity gap',
    unit: 'EA',
    source: 'srv_vw_capacity_summary',
    axes: {
      x: { type: 'category', title: 'Site full name', values: sites },
      y: { type: 'category', title: 'Test type full name', values: tests },
    },
    tooltipTrigger: 'item',
    summary: 'Capacity gap by site and test type. Negative values indicate shortage.',
    zoom: false,
    visualMap: { min: Math.min(0, ...heatmapRows.map((row) => row[2])), max: Math.max(0, ...heatmapRows.map((row) => row[2])), calculable: true, orient: 'horizontal' },
    accessibilityColumns: ['Site', 'Test type', 'Gap EA'],
    accessibilityRows: payload.site_test_gap_heatmap.map((row) => [row.site_label, row.test_type_label, row.gap_qty]),
    series: [{ name: 'Gap', type: 'heatmap', data: heatmapRows }],
  }), payload.release);

  const ranking = payload.constrained_resource_ranking.slice(0, 30);
  await draw('constraint-ranking', chartSpec({
    title: 'Constrained resources by hour gap',
    metric: 'Resource-hour gap',
    unit: 'resource hours',
    source: 'srv_resource_constraints',
    axes: {
      x: { type: 'category', title: 'Resource constraint', values: ranking.map((row) => `${row.resource_constraint_id} · ${row.site_label}`) },
      y: { type: 'value', title: 'Gap (resource hours)' },
    },
    summary: 'Most constrained governed resources ranked by available minus required resource hours.',
    series: [{ name: 'Resource-hour gap', type: 'bar', color: SEMANTIC_COLORS.shortage, data: ranking.map((row) => row.gap_resource_hours) }],
  }), payload.release);

  renderTable('equipment-table', 'Equipment requirements for the selected capacity mode.', [
    { key: 'site_label', label: 'Site full name' },
    { key: 'site_code', label: 'Site code' },
    { key: 'test_type_label', label: 'Test type full name' },
    { key: 'test_type', label: 'Test code' },
    { key: 'equipment_type', label: 'Equipment type' },
    { key: 'demand_qty', label: 'Demand EA', numeric: true, format: (value) => number(value) },
    { key: 'capacity_qty', label: 'Capacity EA', numeric: true, format: (value) => number(value) },
    { key: 'required_additional_units', label: 'Additional units', numeric: true, format: (value) => number(value) },
  ], payload.equipment_requirements);
  renderAlternatives('alternative-table', payload.alternative_resources);
}

function renderAlternatives(id, rows) {
  renderTable(id, 'Only governed qualified alternative or shared resources are shown.', [
    { key: 'site_label', label: 'Site full name' },
    { key: 'site_code', label: 'Site code' },
    { key: 'product_label', label: 'Product full name' },
    { key: 'product_number', label: 'Product code' },
    { key: 'test_type_label', label: 'Test type full name' },
    { key: 'resource_behavior', label: 'Behavior' },
    { key: 'alternative_group', label: 'Resource group' },
    { key: 'qualified_resources', label: 'Qualified resources' },
    { key: 'qualification_evidence', label: 'Qualification evidence' },
  ], rows);
}

async function renderBottlenecks(payload) {
  const kpi = payload.kpis;
  renderKpis('bottleneck-kpis', [
    ['High / critical constraints', kpi.high_or_critical_constraints, 'resources'],
    ['Resource-hour shortfall', kpi.resource_hour_shortfall, 'hours'],
    ['Affected products', kpi.affected_products, 'product impacts'],
    ['Investment need', kpi.investment_need_units, 'equipment units'],
  ]);
  const latest = payload.constraints.slice(0, 40);
  const labels = latest.map((row) => `${row.resource_constraint_id} · ${row.site_label}`);
  await draw('resource-hour-chart', chartSpec({
    title: 'Required versus available resource hours',
    metric: 'Resource-hour constraint',
    unit: 'resource hours',
    source: 'srv_resource_constraints',
    axes: { x: { type: 'category', title: 'Resource constraint', values: labels }, y: { type: 'value', title: 'Resource hours' } },
    summary: 'Required and available resource hours for constrained resources.',
    series: [
      { name: 'Required resource hours', type: 'bar', color: SEMANTIC_COLORS.demand, data: latest.map((row) => row.required_resource_hours) },
      { name: 'Available resource hours', type: 'bar', color: SEMANTIC_COLORS.normalCapacity, data: latest.map((row) => row.available_resource_hours) },
    ],
  }), payload.release);

  const resources = [...new Set(payload.movement.map((row) => row.resource_constraint_id))].slice(0, 8);
  const months = [...new Set(payload.movement.map((row) => String(row.month)))];
  await draw('movement-chart', chartSpec({
    title: 'Bottleneck movement over time',
    metric: 'Resource-hour gap',
    unit: 'resource hours',
    source: 'srv_resource_constraints',
    axes: { x: { type: 'category', title: 'Month', values: months }, y: { type: 'value', title: 'Gap (resource hours)' } },
    summary: 'Monthly resource-hour gap for the eight most prominent constrained resources.',
    series: resources.map((resource) => ({
      name: resource,
      type: 'line',
      data: months.map((month) => payload.movement.find((row) => row.resource_constraint_id === resource && String(row.month) === month)?.gap_resource_hours ?? null),
    })),
  }), payload.release);

  renderTable('constraints-table', 'Severity is shown with text and a non-color marker.', [
    { key: 'month', label: 'Month' },
    { key: 'site_label', label: 'Site full name' },
    { key: 'test_type_label', label: 'Test type full name' },
    { key: 'resource_constraint_id', label: 'Resource' },
    { key: 'resource_behavior', label: 'Behavior' },
    { key: 'bottleneck_severity', label: 'Severity' },
    { key: 'affected_products', label: 'Affected products', numeric: true, format: (value) => number(value) },
    { key: 'required_resource_hours', label: 'Required hours', numeric: true, format: (value) => number(value, 1) },
    { key: 'available_resource_hours', label: 'Available hours', numeric: true, format: (value) => number(value, 1) },
    { key: 'gap_resource_hours', label: 'Gap hours', numeric: true, format: (value) => number(value, 1) },
  ], payload.constraints);
  renderTable('investment-table', 'Equipment investment need derived from the selected governed capacity scenario.', [
    { key: 'site_label', label: 'Site full name' },
    { key: 'site_code', label: 'Site code' },
    { key: 'test_type_label', label: 'Test type full name' },
    { key: 'equipment_type', label: 'Equipment type' },
    { key: 'investment_need_units', label: 'Investment units', numeric: true, format: (value) => number(value) },
    { key: 'affected_demand_qty', label: 'Affected demand EA', numeric: true, format: (value) => number(value) },
    { key: 'worst_gap_pct', label: 'Worst gap %', numeric: true, format: (value) => number(Number(value) * 100, 1) },
  ], payload.investment_need);
  renderAlternatives('bottleneck-alternative-table', payload.alternative_resources);
}

async function loadFilters() {
  const payload = await apiJson(`/capacity-analysis/api/filters/${activeTab}`);
  fillSelect('site', payload.options.site, 'All sites');
  fillSelect('product', payload.options.product, 'All products');
  fillSelect('test_type', payload.options.test_type, 'All test types');
  fillSelect('capacity_mode', payload.options.capacity_mode);
  fillSelect('retest', payload.options.retest);
  fillSelect('planning_version', payload.options.planning_version, 'All planning versions');
  const minimum = String(payload.month_range.minimum || '');
  const maximum = String(payload.month_range.maximum || '');
  for (const name of ['month_from', 'month_to']) {
    const input = form.elements[name];
    if (minimum.length === 6) input.min = `${minimum.slice(0, 4)}-${minimum.slice(4)}`;
    if (maximum.length === 6) input.max = `${maximum.slice(0, 4)}-${maximum.slice(4)}`;
  }
}

async function loadDashboard() {
  disposeCharts();
  setState(`Loading ${activeTab === 'tactical' ? 'Tactical Capacity' : 'Bottleneck Analysis'}.`);
  try {
    const endpoint = activeTab === 'tactical' ? 'tactical' : 'bottlenecks';
    const payload = await apiJson(`/capacity-analysis/api/${endpoint}?${queryString()}`);
    releaseStatus.dataset.state = payload.status === 'ready' ? 'ready' : 'warning';
    releaseStatus.textContent = `Release ${payload.release.release_id || 'unknown'}`;
    if (payload.status === 'empty') {
      setState(payload.message, 'empty');
    } else {
      setState(`Showing ${activeTab === 'tactical' ? 'Tactical Capacity' : 'Bottleneck Analysis'} at monthly grain.`);
    }
    if (activeTab === 'tactical') await renderTactical(payload);
    else await renderBottlenecks(payload);
  } catch (error) {
    console.error('Capacity Analysis dashboard error', error);
    releaseStatus.dataset.state = 'error';
    releaseStatus.textContent = 'Not ready';
    setState(error.message || 'Capacity Analysis could not be loaded.', 'error');
  }
}

async function activateTab(tab) {
  activeTab = tab.dataset.tab;
  tabs.forEach((button) => {
    const selected = button === tab;
    button.setAttribute('aria-selected', String(selected));
    button.tabIndex = selected ? 0 : -1;
    document.getElementById(button.getAttribute('aria-controls')).hidden = !selected;
  });
  await loadFilters();
  await loadDashboard();
}

tabs.forEach((tab, index) => {
  tab.addEventListener('click', () => void activateTab(tab));
  tab.addEventListener('keydown', (event) => {
    if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
    event.preventDefault();
    const target = event.key === 'Home'
      ? tabs[0]
      : event.key === 'End'
        ? tabs.at(-1)
        : tabs[(index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length];
    target.focus();
    void activateTab(target);
  });
});
form.addEventListener('submit', (event) => {
  event.preventDefault();
  void loadDashboard();
});

void loadFilters().then(loadDashboard).catch((error) => {
  releaseStatus.dataset.state = 'error';
  releaseStatus.textContent = 'Not ready';
  setState(error.message || 'Capacity Analysis is not ready.', 'error');
});
