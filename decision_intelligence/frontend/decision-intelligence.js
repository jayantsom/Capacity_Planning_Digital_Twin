'use strict';

import { apiJson as api, readableLabel as labelFor } from '/shared/static/dashboard.js';
import {
  renderGovernedChart,
  SEMANTIC_COLORS,
} from '/shared/static/chart.js?v=20261027c';

const FILTER_STORAGE_KEY = 'capacityTwin.decisionIntelligenceFilters';

const state = {
  workflow: 'demand',
  priority: 1,
  rows: [],
  activeJobId: null,
  pollTimer: null,
  chartHandles: [],
};

const elements = {
  health: document.getElementById('healthStatus'),
  jobBand: document.getElementById('jobBand'),
  jobPhase: document.getElementById('jobPhase'),
  jobDetail: document.getElementById('jobDetail'),
  jobProgress: document.getElementById('jobProgress'),
  jobPercent: document.getElementById('jobPercent'),
  kpis: document.getElementById('kpiStrip'),
  workflowCharts: document.getElementById('workflowCharts'),
  modelMetadata: document.getElementById('modelMetadata'),
  tableHead: document.getElementById('tableHead'),
  tableBody: document.getElementById('tableBody'),
  operationalPanel: document.getElementById('operationalPanel'),
  operationalTitle: document.getElementById('operationalTitle'),
  operationalScope: document.getElementById('operationalScope'),
  operationalRows: document.getElementById('operationalRows'),
  pageStatus: document.getElementById('pageStatus'),
};

function setHealthStatus(stateName, label) {
  const warning = ['degraded', 'stale'].includes(stateName);
  const icon = stateName === 'ready' ? '●' : warning ? '▲' : stateName === 'offline' ? '×' : '◌';
  elements.health.className = `service-status status-${stateName}`;
  elements.health.firstElementChild.textContent = icon;
  elements.health.lastElementChild.textContent = label;
}

function formatValue(value, key = '') {
  if (value == null || Number.isNaN(Number(value))) return value == null ? '-' : String(value);
  const number = Number(value);
  if (key.includes('usd')) {
    return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 0 }).format(number);
  }
  if (key.includes('pct')) {
    return `${number.toFixed(2)}%`;
  }
  if (key.includes('yield') || key.includes('prob')) {
    const percent = Math.abs(number) <= 1 ? number * 100 : number;
    return `${percent.toFixed(2)}%`;
  }
  return new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 }).format(number);
}

function filters() {
  const params = new URLSearchParams();
  const controls = {
    site: 'siteFilter',
    product: 'productFilter',
    test_type: 'testFilter',
    machine: 'machineFilter',
    planning_version: 'planningVersionFilter',
    grain: 'grainFilter',
    month_from: 'monthFrom',
    month_to: 'monthTo',
  };
  Object.entries(controls).forEach(([key, id]) => {
    const control = document.getElementById(id);
    const value = control.value.trim();
    if (!control.closest('[data-filter]').hidden && value) params.set(key, value);
  });
  return params;
}

function persistFilterState(params) {
  const url = new URL(window.location.href);
  ['site', 'product', 'test_type', 'machine', 'planning_version', 'grain', 'month_from', 'month_to']
    .forEach((key) => url.searchParams.delete(key));
  params.forEach((value, key) => url.searchParams.set(key, value));
  window.history.replaceState({}, '', url);
  let stored = {};
  try {
    stored = JSON.parse(window.sessionStorage.getItem(FILTER_STORAGE_KEY) || '{}');
  } catch {
    stored = {};
  }
  stored[state.workflow] = Object.fromEntries(params.entries());
  window.sessionStorage.setItem(FILTER_STORAGE_KEY, JSON.stringify(stored));
}

function fillSelect(id, options, placeholder) {
  const select = document.getElementById(id);
  const current = select.value;
  select.replaceChildren();
  const all = document.createElement('option');
  all.value = '';
  all.textContent = placeholder;
  select.append(all);
  options.forEach((item) => {
    const option = document.createElement('option');
    option.value = item.value;
    option.textContent = item.label;
    select.append(option);
  });
  if ([...select.options].some((option) => option.value === current)) {
    select.value = current;
  }
}

async function loadFilterMetadata(restoreFromUrl = false) {
  const selected = new URLSearchParams();
  const selectedControls = {
    site: 'siteFilter',
    product: 'productFilter',
    test_type: 'testFilter',
    machine: 'machineFilter',
    planning_version: 'planningVersionFilter',
    grain: 'grainFilter',
  };
  Object.entries(selectedControls).forEach(([key, id]) => {
    const control = document.getElementById(id);
    if (control.value) selected.set(key, control.value);
  });
  const payload = await api(
    `/decision-intelligence/api/filters/${encodeURIComponent(state.workflow)}?${selected}`,
  );
  const applicable = new Set(payload.applicable_filters || []);
  document.querySelectorAll('[data-filter]').forEach((container) => {
    container.hidden = !applicable.has(container.dataset.filter);
  });
  fillSelect('siteFilter', payload.options?.site || [], 'All sites');
  fillSelect('productFilter', payload.options?.product || [], 'All products');
  fillSelect('testFilter', payload.options?.test_type || [], 'All tests');
  fillSelect('machineFilter', payload.options?.machine || [], 'All machines');
  fillSelect(
    'planningVersionFilter',
    payload.options?.planning_version || [],
    'All planning versions',
  );
  if (!restoreFromUrl) return;
  const url = new URL(window.location.href);
  let stored = {};
  try {
    stored = JSON.parse(window.sessionStorage.getItem(FILTER_STORAGE_KEY) || '{}')
      [state.workflow] || {};
  } catch {
    stored = {};
  }
  const controls = {
    site: 'siteFilter',
    product: 'productFilter',
    test_type: 'testFilter',
    machine: 'machineFilter',
    planning_version: 'planningVersionFilter',
    month_from: 'monthFrom',
    month_to: 'monthTo',
  };
  Object.entries(controls).forEach(([key, id]) => {
    const value = url.searchParams.get(key) ?? stored[key];
    const control = document.getElementById(id);
    if (!value || control.closest('[data-filter]').hidden) return;
    if (control.tagName !== 'SELECT'
        || [...control.options].some((option) => option.value === value)) {
      control.value = value;
    }
  });
}

async function selectWorkflow(tab) {
  document.querySelectorAll('[role="tab"]').forEach((candidate) => {
    const selected = candidate === tab;
    candidate.setAttribute('aria-selected', String(selected));
    candidate.tabIndex = selected ? 0 : -1;
  });
  state.workflow = tab.dataset.workflow;
  state.priority = Number(tab.dataset.priority);
  const url = new URL(window.location.href);
  url.hash = state.workflow;
  window.history.replaceState(null, '', url);
  try {
    await loadFilterMetadata(true);
  } catch (error) {
    elements.pageStatus.textContent = error.message;
  }
  await loadDashboard();
}

function renderKpis(kpis) {
  elements.kpis.replaceChildren();
  Object.entries(kpis).slice(0, 4).forEach(([key, value]) => {
    const card = document.createElement('div');
    const label = document.createElement('span');
    const strong = document.createElement('strong');
    label.textContent = labelFor(key);
    strong.textContent = formatValue(value, key);
    card.append(label, strong);
    elements.kpis.append(card);
  });
}

function chartSpec({
  title, metric, unit, grain = 'MONTH', source, xTitle, xValues = [],
  yTitle, series, summary, xType = 'category', yType = 'value',
  yValues, axesVisible = true, rows, columns, tooltip = 'axis',
}) {
  return {
    title,
    metric,
    unit,
    grain,
    aggregation: 'WORKFLOW_DEFINED',
    source,
    axes: {
      x: { type: xType, title: xTitle, values: xValues, show: axesVisible },
      y: { type: yType, title: yTitle, values: yValues, show: axesVisible },
    },
    legend: { show: series.length > 1, type: 'scroll' },
    tooltip: { show: true, trigger: tooltip },
    thresholds: [],
    dataZoom: { enabled: xValues.length > 12 },
    export: { rowScope: 'displayed' },
    emptyState: { message: 'No analytical records match the selected filters.' },
    accessibility: {
      summary,
      table: true,
      rows,
      columns,
    },
    series,
    height: 350,
  };
}

function rankingSpec(title, metric, unit, source, points, summary, color) {
  const rows = points.slice(0, 12).reverse();
  return chartSpec({
    title,
    metric,
    unit,
    source,
    xTitle: unit,
    xType: 'value',
    yTitle: 'Priority',
    yType: 'category',
    yValues: rows.map((row) => row.label),
    series: [{
      name: metric,
      type: 'bar',
      color,
      data: rows.map((row) => row.value),
    }],
    rows: rows.map((row) => [row.label, row.value]),
    columns: ['Priority', metric],
    summary,
  });
}

function donutSpec(title, metric, source, points, summary) {
  return chartSpec({
    title,
    metric,
    unit: 'RECORDS',
    source,
    xTitle: '',
    yTitle: '',
    axesVisible: false,
    tooltip: 'item',
    series: [{
      name: metric,
      type: 'pie',
      radius: ['42%', '70%'],
      data: points.map((row) => ({ name: row.label, value: row.value })),
    }],
    rows: points.map((row) => [row.label, row.value]),
    columns: ['Category', 'Records'],
    summary,
  });
}

function workflowSpecs(payload) {
  if (payload.workflow === 'demand') {
    const periods = payload.series.map((row) => String(row.period));
    return [
      chartSpec({
        title: 'Historical demand and 18-month forecast',
        metric: 'Demand',
        unit: 'EA',
        source: 'srv_ml_feature_store, ml_demand_forecast',
        xTitle: 'Month',
        xValues: periods,
        yTitle: 'Demand (EA)',
        summary: 'Historical actual demand and the published forward forecast. No prediction interval is claimed.',
        series: [
          { name: 'Actual demand', type: 'line', color: SEMANTIC_COLORS.actualOutput, data: payload.series.map((row) => row.value) },
          { name: 'Forecast demand', type: 'line', color: SEMANTIC_COLORS.demand, data: payload.series.map((row) => row.secondary) },
        ],
      }),
      chartSpec({
        title: 'Forecast demand by horizon',
        metric: 'Forecast demand',
        unit: 'EA',
        source: 'ml_demand_forecast',
        xTitle: 'Months ahead',
        xValues: payload.horizon.map((row) => row.horizon_month),
        yTitle: 'Forecast demand (EA)',
        summary: 'Total forecast demand by months ahead across the selected portfolio.',
        series: [{ name: 'Forecast demand', type: 'bar', color: SEMANTIC_COLORS.demand, data: payload.horizon.map((row) => row.forecast_demand_ea) }],
      }),
      rankingSpec(
        'Forecast error priorities',
        'MAPE',
        'PERCENT',
        'ml_forecast_accuracy',
        payload.rankings,
        'Highest backtest percentage errors by product and site.',
        SEMANTIC_COLORS.shortage,
      ),
    ];
  }
  if (payload.workflow === 'yield') {
    const periods = payload.series.map((row) => String(row.period));
    return [
      chartSpec({
        title: 'Measured, predicted, and target yield',
        metric: 'Yield',
        unit: 'PERCENT',
        source: 'ml_yield_predictions',
        xTitle: 'Month',
        xValues: periods,
        yTitle: 'Yield (%)',
        summary: 'Measured yield compared with model prediction and target.',
        series: [
          { name: 'Measured yield', type: 'line', color: SEMANTIC_COLORS.actualOutput, data: payload.series.map((row) => row.value) },
          { name: 'Predicted yield', type: 'line', color: SEMANTIC_COLORS.demand, data: payload.series.map((row) => row.secondary) },
          { name: 'Target yield', type: 'line', color: SEMANTIC_COLORS.warning, data: payload.series.map((row) => row.target) },
        ],
      }),
      chartSpec({
        title: 'Yield prediction residual by month',
        metric: 'Measured minus predicted yield',
        unit: 'PERCENTAGE POINTS',
        source: 'ml_yield_predictions',
        xTitle: 'Month',
        xValues: periods,
        yTitle: 'Residual (percentage points)',
        summary: 'Positive values mean measured yield exceeded the prediction.',
        series: [{
          name: 'Residual',
          type: 'bar',
          color: SEMANTIC_COLORS.normalCapacity,
          data: payload.series.map((row) => Number(row.value || 0) - Number(row.secondary || 0)),
        }],
      }),
      rankingSpec(
        'Global SHAP driver importance',
        'Mean absolute SHAP',
        'SHAP',
        'ml_yield_shap',
        payload.drivers,
        'Global model-driver importance for the filtered prediction rows.',
        SEMANTIC_COLORS.maximumCapacity,
      ),
    ];
  }
  if (payload.workflow === 'oee-risk') {
    const periods = payload.series.map((row) => String(row.period));
    return [
      chartSpec({
        title: 'OEE degradation risk trend',
        metric: 'Mean degradation risk',
        unit: 'PERCENT',
        source: 'ml_oee_degradation_risk',
        xTitle: 'Month',
        xValues: periods,
        yTitle: 'Risk probability (%)',
        summary: 'Mean predicted degradation risk. This is a risk signal, not a failure prediction.',
        series: [{ name: 'Mean risk', type: 'line', color: SEMANTIC_COLORS.shortage, data: payload.series.map((row) => row.value) }],
      }),
      donutSpec(
        'Risk tier distribution',
        'Risk tier',
        'ml_oee_degradation_risk',
        payload.distribution,
        'Distribution of published machine risk tiers.',
      ),
      rankingSpec(
        'Machines requiring review',
        'Maximum degradation risk',
        'PERCENT',
        'ml_oee_degradation_risk',
        payload.rankings,
        'Machines ranked by maximum degradation risk.',
        SEMANTIC_COLORS.shortage,
      ),
    ];
  }
  if (payload.workflow === 'oee-anomaly') {
    const periods = payload.series.map((row) => String(row.period));
    return [
      chartSpec({
        title: 'OEE across the evaluation window',
        metric: 'Mean OEE',
        unit: 'PERCENT',
        source: 'ml_oee_anomalies',
        xTitle: 'Month',
        xValues: periods,
        yTitle: 'OEE (%)',
        summary: 'Mean OEE in the historical anomaly evaluation window.',
        series: [{ name: 'Mean OEE', type: 'line', color: SEMANTIC_COLORS.actualOutput, data: payload.series.map((row) => row.value) }],
      }),
      chartSpec({
        title: 'Detected anomalies by month',
        metric: 'Anomaly count',
        unit: 'RECORDS',
        source: 'ml_oee_anomalies',
        xTitle: 'Month',
        xValues: periods,
        yTitle: 'Anomalies',
        summary: 'Count of records classified as anomalous in each month.',
        series: [{ name: 'Anomalies', type: 'bar', color: SEMANTIC_COLORS.warning, data: payload.series.map((row) => row.secondary) }],
      }),
      donutSpec(
        'Anomaly severity distribution',
        'Anomaly severity',
        'ml_oee_anomalies',
        payload.distribution,
        'Distribution of calibrated historical anomaly severities.',
      ),
      rankingSpec(
        'Site and test anomaly priorities',
        'Anomaly count',
        'RECORDS',
        'ml_oee_anomalies',
        payload.rankings,
        'Sites and test types ranked by anomaly count.',
        SEMANTIC_COLORS.warning,
      ),
    ];
  }
  const combinations = payload.rows.slice(0, 12);
  const labels = combinations.map(
    (row) => `${row.site_name || row.site_code} | ${row.test_type_name || row.test_type}`,
  );
  const frontier = [...payload.scenarios].sort(
    (left, right) => Number(left.capex_usd) - Number(right.capex_usd),
  );
  return [
    chartSpec({
      title: 'Equipment requirement percentiles',
      metric: 'Required equipment',
      unit: 'EQUIPMENT',
      source: 'ml_capex_summary',
      xTitle: 'Site and test',
      xValues: labels,
      yTitle: 'Equipment count',
      summary: 'P50, P80, and P95 required equipment by site and test combination.',
      series: [
        { name: 'P50', type: 'bar', color: SEMANTIC_COLORS.normalCapacity, data: combinations.map((row) => row.eq_needed_p50) },
        { name: 'P80', type: 'bar', color: SEMANTIC_COLORS.maximumCapacity, data: combinations.map((row) => row.eq_needed_p80) },
        { name: 'P95', type: 'bar', color: SEMANTIC_COLORS.shortage, data: combinations.map((row) => row.eq_needed_p95) },
      ],
    }),
    rankingSpec(
      'P80 capital exposure',
      'P80 capital',
      'USD',
      'ml_capex_summary',
      payload.rankings,
      'Site and test combinations ranked by P80 capital exposure.',
      SEMANTIC_COLORS.maximumCapacity,
    ),
    chartSpec({
      title: 'Investment sufficiency frontier',
      metric: 'Probability of sufficient capacity',
      unit: 'PERCENT',
      source: 'ml_capex_scenarios',
      xTitle: 'Capital investment (USD)',
      xType: 'value',
      yTitle: 'Probability sufficient (%)',
      summary: 'Scenario investment compared with simulated probability of sufficient capacity.',
      tooltip: 'item',
      series: [{
        name: 'Scenario',
        type: 'scatter',
        color: SEMANTIC_COLORS.actualOutput,
        data: frontier.map((row) => [row.capex_usd, Number(row.probability_sufficient || 0) * 100]),
      }],
      rows: frontier.map((row) => [
        row.site_name || row.site_code,
        row.test_type_name || row.test_type,
        row.scenario,
        row.capex_usd,
        Number(row.probability_sufficient || 0) * 100,
      ]),
      columns: ['Site', 'Test', 'Scenario', 'CapEx USD', 'Probability sufficient %'],
    }),
  ];
}

async function renderWorkflowCharts(payload) {
  state.chartHandles.forEach((handle) => handle.dispose());
  state.chartHandles = [];
  elements.workflowCharts.replaceChildren();
  const specs = workflowSpecs(payload);
  for (const spec of specs) {
    const panel = document.createElement('article');
    panel.className = 'panel workflow-chart-panel';
    const host = document.createElement('div');
    panel.append(host);
    elements.workflowCharts.append(panel);
    const handle = await renderGovernedChart(host, spec, {
      releaseId: payload.model_registry?.ml_run_id,
      filters: Object.fromEntries(filters()),
      pointLimit: 5000,
    });
    state.chartHandles.push(handle);
  }
}

function renderModelMetadata(model) {
  elements.modelMetadata.replaceChildren();
  const fields = model ? [
    ['Workflow', model.workflow_name],
    ['Status', model.status],
    ['ML run', model.ml_run_id],
    ['Input pipeline run', model.input_pipeline_run_id],
    ['Serving checksum', model.input_serving_sha256],
  ] : [['Status', 'Model registry is not available']];
  fields.forEach(([name, value]) => {
    const term = document.createElement('dt');
    term.textContent = name;
    const description = document.createElement('dd');
    description.textContent = value || '-';
    elements.modelMetadata.append(term, description);
  });
}

function renderTable(rows) {
  state.rows = rows;
  elements.tableHead.replaceChildren();
  elements.tableBody.replaceChildren();
  if (!rows.length) return;
  const columns = Object.keys(rows[0]);
  const headerRow = document.createElement('tr');
  columns.forEach((column) => {
    const header = document.createElement('th');
    header.textContent = labelFor(column);
    headerRow.append(header);
  });
  elements.tableHead.append(headerRow);
  rows.forEach((record) => {
    const row = document.createElement('tr');
    columns.forEach((column) => {
      const cell = document.createElement('td');
      cell.textContent = formatValue(record[column], column);
      row.append(cell);
    });
    elements.tableBody.append(row);
  });
}

function renderOperational(panel) {
  elements.operationalRows.replaceChildren();
  elements.operationalPanel.hidden = !panel;
  if (!panel) return;
  elements.operationalTitle.textContent = panel.title;
  elements.operationalScope.textContent =
    `DAILY FACTS · ${panel.grain} · NOT AN ML PREDICTION`;
  (panel.rows || []).forEach((record) => {
    const row = document.createElement('tr');
    [
      record.period,
      formatValue(record.yield_pct, 'pct'),
      formatValue(record.oee_pct, 'pct'),
      `${formatValue(record.downtime_hours)} h`,
      `${formatValue(record.throughput_uph)} UPH`,
      formatValue(record.event_count),
      record.partial_period ? 'PARTIAL PERIOD' : 'COMPLETE',
    ].forEach((value) => {
      const cell = document.createElement('td');
      cell.textContent = value;
      row.append(cell);
    });
    elements.operationalRows.append(row);
  });
}

async function loadDashboard() {
  elements.pageStatus.textContent = 'Loading…';
  try {
    const query = filters();
    persistFilterState(query);
    const payload = await api(
      `/decision-intelligence/api/dashboard/${encodeURIComponent(state.workflow)}?${query}`,
    );
    renderKpis(payload.kpis);
    await renderWorkflowCharts(payload);
    renderModelMetadata(payload.model_registry);
    renderTable(payload.rows);
    renderOperational(payload.operational);
    elements.pageStatus.textContent = payload.notice
      || `Updated ${new Date().toLocaleTimeString()} · ${payload.scope || 'analytics'}`;
  } catch (error) {
    elements.pageStatus.textContent = error.message;
    renderKpis({});
    state.chartHandles.forEach((handle) => handle.dispose());
    state.chartHandles = [];
    elements.workflowCharts.replaceChildren();
    renderModelMetadata(null);
    renderTable([]);
    renderOperational(null);
  }
}

function setRunButtons(disabled) {
  document.getElementById('runAll').disabled = disabled;
  document.getElementById('runSelected').disabled = disabled;
}

function renderJob(job) {
  const progress = Number(job.progress_pct || 0);
  elements.jobBand.hidden = false;
  elements.jobPhase.textContent = `${job.phase} · ${String(job.status).replaceAll('_', ' ')}`;
  elements.jobDetail.textContent = job.detail;
  elements.jobProgress.style.width = `${progress}%`;
  elements.jobPercent.textContent = `${progress}%`;
  elements.jobProgress.parentElement.setAttribute('aria-valuenow', String(progress));
  const running = ['PENDING', 'RUNNING'].includes(job.status);
  setRunButtons(running);
  return running;
}

async function pollJob() {
  if (!state.activeJobId) return;
  try {
    const job = await api(`/decision-intelligence/api/jobs/${encodeURIComponent(state.activeJobId)}`);
    if (renderJob(job)) {
      state.pollTimer = window.setTimeout(pollJob, 1000);
    } else {
      state.activeJobId = null;
      await Promise.allSettled([loadHealth(), loadDashboard()]);
    }
  } catch (error) {
    elements.jobDetail.textContent = error.message;
    setRunButtons(false);
  }
}

async function startRun(priorities) {
  const label = priorities ? 'this workflow' : 'all five workflows';
  if (!window.confirm(`Run ${label} on this local machine?`)) return;
  try {
    const job = await api('/decision-intelligence/api/jobs', {
      method: 'POST',
      body: JSON.stringify({ priorities }),
    });
    state.activeJobId = job.job_id;
    renderJob(job);
    state.pollTimer = window.setTimeout(pollJob, 500);
  } catch (error) {
    elements.jobBand.hidden = false;
    elements.jobPhase.textContent = 'Run not started';
    elements.jobDetail.textContent = error.message;
  }
}

async function loadHealth() {
  try {
    const health = await api('/decision-intelligence/api/health');
    const className = health.stale ? 'stale' : health.status;
    setHealthStatus(className, health.stale ? 'STALE' : health.status.toUpperCase());
    elements.health.title = health.run_id ? `Run ${health.run_id}` : health.reason;
  } catch (error) {
    setHealthStatus('offline', 'OFFLINE');
    elements.health.title = error.message;
  }
}

async function resumeActiveJob() {
  const payload = await api('/decision-intelligence/api/jobs?limit=20');
  const running = payload.jobs.find((job) => ['PENDING', 'RUNNING'].includes(job.status));
  if (!running) return;
  state.activeJobId = running.job_id;
  renderJob(running);
  window.clearTimeout(state.pollTimer);
  state.pollTimer = window.setTimeout(pollJob, 500);
}

function exportCsv() {
  if (!state.rows.length) return;
  const columns = Object.keys(state.rows[0]);
  const quote = (value) => `"${String(value ?? '').replaceAll('"', '""')}"`;
  const csv = [
    columns.map(quote).join(','),
    ...state.rows.map((row) => columns.map((column) => quote(row[column])).join(',')),
  ].join('\n');
  const link = document.createElement('a');
  link.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }));
  link.download = `${state.workflow}.csv`;
  link.click();
  URL.revokeObjectURL(link.href);
}

document.querySelectorAll('[role="tab"]').forEach((tab) => {
  tab.addEventListener('click', () => void selectWorkflow(tab));
  tab.addEventListener('keydown', (event) => {
    if (!['ArrowLeft', 'ArrowRight'].includes(event.key)) return;
    const tabs = [...document.querySelectorAll('[role="tab"]')];
    const offset = event.key === 'ArrowRight' ? 1 : -1;
    const next = tabs[(tabs.indexOf(tab) + offset + tabs.length) % tabs.length];
    event.preventDefault();
    next.focus();
    void selectWorkflow(next);
  });
});
document.getElementById('filters').addEventListener('submit', (event) => {
  event.preventDefault();
  void loadDashboard();
});
['siteFilter', 'productFilter', 'testFilter', 'machineFilter', 'planningVersionFilter']
  .forEach((id) => {
    document.getElementById(id).addEventListener('change', () => {
      void loadFilterMetadata();
    });
  });
document.getElementById('grainFilter').addEventListener('change', () => {
  void loadDashboard();
});
document.getElementById('clearFilters').addEventListener('click', () => {
  document.getElementById('filters').reset();
  void loadFilterMetadata().then(loadDashboard);
});
document.getElementById('runAll').addEventListener('click', () => void startRun(null));
document.getElementById('runSelected').addEventListener('click', () => void startRun([state.priority]));
document.getElementById('exportCsv').addEventListener('click', exportCsv);

async function initialize() {
  const initialTab = document.querySelector(`[data-workflow="${window.location.hash.slice(1)}"]`)
    || document.querySelector('[data-workflow="demand"]');
  await selectWorkflow(initialTab);
  await Promise.allSettled([loadHealth(), resumeActiveJob()]);
}

void initialize();
