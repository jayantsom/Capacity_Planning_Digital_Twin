import { apiJson } from '/shared/static/dashboard.js';
import { SEMANTIC_COLORS } from '/shared/static/chart.js?v=20261027c';
import {
  chartManager, chartSpec, downloadText, escapeCsvCell, fillSelect, formatNumber,
  parseCsvLine, queryFromForm, renderKpis, renderTable, setViewState,
} from '/shared/static/planning.js?v=20261027e';

const SCHEMA = 'capacity-twin/scenario/1.0.0';
const STORAGE_KEY = 'capacity-twin.scenario.assumptions.v1';
const form = document.getElementById('filters');
const charts = chartManager();
let baseline;
let assumptions = {};

function scenarioValues(values = assumptions) {
  const baseDemand = baseline.kpis.baseline_demand_ea;
  const baseCapacity = baseline.kpis.baseline_capacity_ea;
  const resourceCount = new Set(baseline.affected_resources.map((row) => row.resource_constraint_id)).size;
  const capacityPerResource = resourceCount ? baseCapacity / resourceCount : 0;
  const demand = baseDemand * values.demand * (1 + values.retest);
  const capacity = baseCapacity * values.yield * values.oee * values.shifts
    * values.allocation * (1 + values.overtime) + values.equipment * capacityPerResource;
  return { demand, capacity, gap: capacity - demand, utilization: capacity ? demand / capacity : null };
}

function persistedAssumptions() {
  try { return JSON.parse(sessionStorage.getItem(STORAGE_KEY) || '{}'); } catch { return {}; }
}

function saveAssumptions() {
  sessionStorage.setItem(STORAGE_KEY, JSON.stringify(assumptions));
}

function renderAssumptions() {
  const container = document.getElementById('assumptions');
  container.replaceChildren();
  baseline.assumptions.forEach((definition) => {
    const label = document.createElement('label');
    label.textContent = definition.label;
    const input = document.createElement('input');
    input.type = 'number';
    input.name = definition.code;
    input.min = definition.minimum;
    input.max = definition.maximum;
    input.step = definition.unit === 'COUNT' ? '1' : '0.01';
    input.value = assumptions[definition.code];
    input.setAttribute('aria-describedby', `${definition.code}-unit`);
    const unit = document.createElement('small');
    unit.id = `${definition.code}-unit`;
    unit.textContent = `${definition.unit} · ${definition.minimum} to ${definition.maximum}`;
    input.addEventListener('change', () => {
      assumptions[definition.code] = Math.min(
        definition.maximum,
        Math.max(definition.minimum, Number(input.value)),
      );
      input.value = assumptions[definition.code];
      saveAssumptions();
      void renderScenario();
    });
    label.append(input, unit);
    container.append(label);
  });
}

function oneAtATimeSensitivity() {
  const current = scenarioValues();
  return baseline.assumptions.map((definition) => {
    const low = { ...assumptions, [definition.code]: definition.minimum };
    const high = { ...assumptions, [definition.code]: definition.maximum };
    return {
      label: definition.label,
      low: scenarioValues(low).gap - current.gap,
      high: scenarioValues(high).gap - current.gap,
    };
  }).sort((a, b) => Math.max(Math.abs(b.low), Math.abs(b.high))
    - Math.max(Math.abs(a.low), Math.abs(a.high)));
}

async function renderScenario() {
  charts.dispose();
  const scenario = scenarioValues();
  renderKpis('scenario-kpis', [
    ['Baseline demand', baseline.kpis.baseline_demand_ea, 'EA'],
    ['Scenario demand', scenario.demand, 'EA'],
    ['Baseline capacity', baseline.kpis.baseline_capacity_ea, 'EA'],
    ['Scenario capacity', scenario.capacity, 'EA'],
    ['Baseline gap', baseline.kpis.baseline_gap_ea, 'EA'],
    ['Scenario gap', scenario.gap, 'EA'],
    ['Scenario utilization', scenario.utilization == null ? null : scenario.utilization * 100, '%', 1],
  ]);
  const months = baseline.trend.map((row) => String(row.month));
  const capacityFactor = baseline.kpis.baseline_capacity_ea
    ? scenario.capacity / baseline.kpis.baseline_capacity_ea : 0;
  const demandFactor = baseline.kpis.baseline_demand_ea
    ? scenario.demand / baseline.kpis.baseline_demand_ea : 0;
  const context = { releaseId: baseline.release.release_id, filters: Object.fromEntries(new FormData(form)) };
  await charts.draw('comparison-chart', chartSpec({
    title: 'Monthly baseline and scenario',
    metric: 'Demand and modeled capacity',
    unit: 'EA',
    grain: 'MONTH',
    source: 'srv_vw_capacity_summary plus browser-session assumptions',
    xTitle: 'Month',
    xValues: months,
    yTitle: 'Units (EA)',
    summary: 'Baseline demand and capacity compared with deterministic session-only scenario outputs.',
    series: [
      { name: 'Baseline demand', type: 'line', color: SEMANTIC_COLORS.baseline, data: baseline.trend.map((row) => row.baseline_demand_ea) },
      { name: 'Scenario demand', type: 'line', color: SEMANTIC_COLORS.demand, data: baseline.trend.map((row) => row.baseline_demand_ea * demandFactor) },
      { name: 'Baseline capacity', type: 'line', color: SEMANTIC_COLORS.normalCapacity, data: baseline.trend.map((row) => row.baseline_capacity_ea) },
      { name: 'Scenario capacity', type: 'line', color: SEMANTIC_COLORS.maximumCapacity, data: baseline.trend.map((row) => row.baseline_capacity_ea * capacityFactor) },
    ],
  }), context);
  const bridge = [
    ['Baseline gap', baseline.kpis.baseline_gap_ea],
    ['Demand effect', -(scenario.demand - baseline.kpis.baseline_demand_ea)],
    ['Capacity effect', scenario.capacity - baseline.kpis.baseline_capacity_ea],
    ['Scenario gap', scenario.gap],
  ];
  await charts.draw('waterfall-chart', chartSpec({
    title: 'Gap variance bridge',
    metric: 'Gap effect',
    unit: 'EA',
    grain: 'NONE',
    source: 'browser-session scenario formula',
    xTitle: 'Variance component',
    xValues: bridge.map((row) => row[0]),
    yTitle: 'Gap effect (EA)',
    summary: 'Baseline gap plus demand and capacity effects reconciles to scenario gap.',
    zoom: false,
    series: [{ name: 'Gap effect', type: 'bar', color: SEMANTIC_COLORS.maximumCapacity, data: bridge.map((row) => row[1]) }],
  }), context);
  const sensitivity = oneAtATimeSensitivity();
  await charts.draw('tornado-chart', chartSpec({
    title: 'One-at-a-time gap sensitivity',
    metric: 'Change from current scenario gap',
    unit: 'EA',
    grain: 'NONE',
    source: 'browser-session assumption bounds',
    xTitle: 'Assumption',
    xValues: sensitivity.map((row) => row.label),
    yTitle: 'Gap change (EA)',
    summary: 'Low and high assumption bounds varied one at a time from the current scenario.',
    series: [
      { name: 'Low bound effect', type: 'bar', color: SEMANTIC_COLORS.shortage, data: sensitivity.map((row) => row.low) },
      { name: 'High bound effect', type: 'bar', color: SEMANTIC_COLORS.positiveHeadroom, data: sensitivity.map((row) => row.high) },
    ],
  }), context);
  const gapRatio = baseline.kpis.baseline_demand_ea ? scenario.demand / baseline.kpis.baseline_demand_ea : 1;
  const capacityRatio = baseline.kpis.baseline_capacity_ea ? scenario.capacity / baseline.kpis.baseline_capacity_ea : 1;
  const resources = baseline.affected_resources.map((row) => ({
    ...row,
    scenario_required_hours: row.required_resource_hours * gapRatio,
    scenario_available_hours: row.available_resource_hours * capacityRatio,
    scenario_gap_hours: row.available_resource_hours * capacityRatio - row.required_resource_hours * gapRatio,
  }));
  renderTable('resources-table', 'Modeled bottleneck movement by governed affected resource.', [
    { key: 'month', label: 'Month' },
    { key: 'site_name', label: 'Site full name' },
    { key: 'product_description', label: 'Product full name' },
    { key: 'test_category_name', label: 'Test full name' },
    { key: 'equipment_name', label: 'Resource full name' },
    { key: 'resource_behavior', label: 'Behavior' },
    { key: 'bottleneck_severity', label: 'Baseline severity', status: true },
    { key: 'gap_resource_hours', label: 'Baseline gap hours', numeric: true, format: (v) => formatNumber(v, 1) },
    { key: 'scenario_gap_hours', label: 'Scenario gap hours', numeric: true, format: (v) => formatNumber(v, 1) },
  ], resources);
}

function exportPayload() {
  return {
    schema: SCHEMA,
    exported_at: new Date().toISOString(),
    release_id: baseline.release.release_id,
    filters: Object.fromEntries(new FormData(form)),
    assumptions,
  };
}

function exportJson() {
  downloadText('scenario-assumptions-v1.json', JSON.stringify(exportPayload(), null, 2), 'application/json');
}

function exportCsv() {
  const header = ['schema', 'assumption_code', 'value'];
  const rows = Object.entries(assumptions).map(([code, value]) => [SCHEMA, code, value]);
  downloadText('scenario-assumptions-v1.csv', [header, ...rows].map(
    (row) => row.map(escapeCsvCell).join(','),
  ).join('\r\n'), 'text/csv');
}

async function importFile(file) {
  const text = await file.text();
  let incoming;
  if (file.name.toLowerCase().endsWith('.json')) {
    const parsed = JSON.parse(text);
    if (parsed.schema !== SCHEMA) throw new Error('Unsupported scenario JSON schema version.');
    incoming = parsed.assumptions;
  } else {
    const lines = text.split(/\r?\n/).filter(Boolean);
    incoming = Object.fromEntries(lines.slice(1).map((line) => {
      const cells = parseCsvLine(line);
      if (cells[0] !== SCHEMA) throw new Error('Unsupported scenario CSV schema version.');
      return [cells[1], Number(cells[2])];
    }));
  }
  baseline.assumptions.forEach((definition) => {
    if (incoming[definition.code] != null) {
      assumptions[definition.code] = Math.min(definition.maximum, Math.max(definition.minimum, Number(incoming[definition.code])));
    }
  });
  saveAssumptions();
  renderAssumptions();
  await renderScenario();
}

async function loadFilters() {
  const payload = await apiJson('/scenario-planning/api/filters');
  fillSelect(form, 'site', payload.options.site, 'All sites');
  fillSelect(form, 'product', payload.options.product, 'All products');
  fillSelect(form, 'planning_version', payload.options.planning_version, 'All versions');
}

async function loadBaseline() {
  setViewState('Loading governed scenario baseline.');
  try {
    baseline = await apiJson(`/scenario-planning/api/baseline?${queryFromForm(form)}`);
    document.getElementById('release-status').textContent = `Release ${baseline.release.release_id || 'unknown'}`;
    document.getElementById('release-status').dataset.state = baseline.status === 'empty' ? 'warning' : 'ready';
    const stored = persistedAssumptions();
    assumptions = Object.fromEntries(baseline.assumptions.map(
      (item) => [item.code, Number.isFinite(Number(stored[item.code])) ? Number(stored[item.code]) : item.default],
    ));
    renderAssumptions();
    document.getElementById('limitations').replaceChildren(...baseline.scenario_model.limitations.map((text) => {
      const item = document.createElement('li'); item.textContent = text; return item;
    }));
    setViewState(baseline.message || 'Scenario baseline ready. Assumptions remain in this browser session.', baseline.status);
    await renderScenario();
  } catch (error) {
    document.getElementById('release-status').textContent = 'Not ready';
    document.getElementById('release-status').dataset.state = 'error';
    setViewState(error.message || 'Scenario Planning is not ready.', 'error');
  }
}

form.addEventListener('submit', (event) => { event.preventDefault(); void loadBaseline(); });
document.getElementById('reset-scenario').addEventListener('click', () => {
  sessionStorage.removeItem(STORAGE_KEY); void loadBaseline();
});
document.getElementById('export-json').addEventListener('click', exportJson);
document.getElementById('export-csv').addEventListener('click', exportCsv);
document.getElementById('import-file').addEventListener('change', (event) => {
  if (event.target.files[0]) importFile(event.target.files[0]).catch((error) => setViewState(error.message, 'error'));
});
void loadFilters().then(loadBaseline).catch((error) => setViewState(error.message, 'error'));
