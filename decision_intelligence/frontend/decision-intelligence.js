'use strict';

import { apiJson as api, readableLabel as labelFor } from '/shared/dashboard.js';
import { mountComparisonBand } from '/shared/comparison-band.js';

const FILTER_STORAGE_KEY = 'capacityTwin.decisionIntelligenceFilters';

const state = {
  workflow: 'demand',
  priority: 1,
  rows: [],
  activeJobId: null,
  pollTimer: null,
  comparisonWindow: 'total',
  comparisonController: null,
};

const elements = {
  health: document.getElementById('healthStatus'),
  jobBand: document.getElementById('jobBand'),
  jobPhase: document.getElementById('jobPhase'),
  jobDetail: document.getElementById('jobDetail'),
  jobProgress: document.getElementById('jobProgress'),
  jobPercent: document.getElementById('jobPercent'),
  kpis: document.getElementById('kpiStrip'),
  trend: document.getElementById('trendChart'),
  trendSummary: document.getElementById('trendSummary'),
  primaryTitle: document.getElementById('primaryChartTitle'),
  secondaryTitle: document.getElementById('secondaryChartTitle'),
  rankings: document.getElementById('rankings'),
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
  if (value == null || Number.isNaN(Number(value))) return value == null ? '—' : String(value);
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
  params.set('window', state.comparisonWindow);
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
  stored[state.workflow] = Object.fromEntries(
    [...params.entries()].filter(([key]) => key !== 'window'),
  );
  window.sessionStorage.setItem(FILTER_STORAGE_KEY, JSON.stringify(stored));
}

function applyComparisonWindow(windowId) {
  state.comparisonWindow = windowId;
  const locked = windowId !== 'total';
  ['monthFrom', 'monthTo'].forEach((id) => {
    const input = document.getElementById(id);
    input.disabled = locked;
    if (locked) input.value = '';
  });
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

function renderTrend(chart) {
  const series = chart?.points || [];
  elements.trend.replaceChildren();
  elements.primaryTitle.textContent = chart?.title || 'Workflow analysis';
  if (!series.length) {
    const empty = document.createElement('p');
    empty.className = 'empty';
    empty.textContent = 'No analytical records match the selected filters.';
    elements.trend.append(empty);
    elements.trendSummary.textContent = chart?.unit || 'No data';
    return;
  }
  if (chart.kind === 'percentile_range') {
    const maximum = Math.max(1, ...series.map((row) => Number(row.eq_needed_p95 || 0)));
    series.forEach((row) => {
      const group = document.createElement('div');
      group.className = 'percentile-group';
      ['eq_needed_p50', 'eq_needed_p80', 'eq_needed_p95'].forEach((key) => {
        const bar = document.createElement('i');
        bar.className = `percentile-bar ${key.replace('eq_needed_', '')}`;
        bar.style.height = `${Math.max(2, Number(row[key] || 0) / maximum * 220)}px`;
        bar.title = `${key.replace('eq_needed_', '').toUpperCase()}: ${formatValue(row[key])}`;
        group.append(bar);
      });
      const name = document.createElement('em');
      name.textContent = [
        row.site_name || row.site_code,
        row.test_type_name || row.test_type,
      ].filter(Boolean).join(' · ');
      group.append(name);
      elements.trend.append(group);
    });
    elements.trendSummary.textContent = `${series.length} site-test combinations`;
    return;
  }
  const keys = [
    ['value', chart.primary_label, 'primary'],
    ['secondary', chart.secondary_label, 'secondary'],
    ['target', chart.target_label, 'target'],
  ].filter(([key, label]) => label && series.some((row) => row[key] != null));
  const maximum = Math.max(1, ...series.flatMap((row) => keys.map(([key]) => Number(row[key] || 0))));
  const minimum = Math.min(0, ...series.flatMap((row) => keys.map(([key]) => Number(row[key] || 0))));
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 1000 220');
  svg.setAttribute('preserveAspectRatio', 'none');
  svg.setAttribute('aria-hidden', 'true');
  series.forEach((row, index) => {
    const column = document.createElement('div');
    column.className = 'trend-column';
    const period = document.createElement('em');
    period.textContent = row.period;
    column.append(period);
    elements.trend.append(column);
  });
  keys.forEach(([key, label, className]) => {
    const points = series
      .map((row, index) => {
        if (row[key] == null) return null;
        const x = series.length === 1 ? 500 : index / (series.length - 1) * 1000;
        const y = 210 - (Number(row[key]) - minimum) / (maximum - minimum || 1) * 190;
        return `${x},${y}`;
      })
      .filter(Boolean);
    if (points.length < 2) return;
    const line = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
    line.setAttribute('points', points.join(' '));
    line.setAttribute('class', className);
    line.setAttribute('vector-effect', 'non-scaling-stroke');
    line.setAttribute('aria-label', label);
    svg.append(line);
  });
  elements.trend.prepend(svg);
  const legend = document.createElement('div');
  legend.className = 'chart-legend';
  keys.forEach(([, label, className]) => {
    const item = document.createElement('span');
    item.className = className;
    item.textContent = label;
    legend.append(item);
  });
  elements.trend.prepend(legend);
  elements.trendSummary.textContent = `${series.length} periods · ${chart.unit}`;
}

function renderRankings(chart) {
  const rankings = chart?.points || [];
  elements.secondaryTitle.textContent = chart?.title || 'Priority analysis';
  elements.rankings.replaceChildren();
  if (!rankings.length) {
    const empty = document.createElement('p');
    empty.className = 'empty';
    empty.textContent = 'No ranked records match these filters.';
    elements.rankings.append(empty);
    return;
  }
  const maximum = Math.max(1, ...rankings.map((row) => Number(row.value || 0)));
  rankings.slice(0, 12).forEach((row, index) => {
    const item = document.createElement('div');
    item.className = 'rank-row';
    const rank = document.createElement('b');
    rank.textContent = String(index + 1).padStart(2, '0');
    const label = document.createElement('span');
    label.className = 'rank-label';
    label.textContent = row.label;
    label.title = row.label;
    const track = document.createElement('span');
    track.className = 'rank-track';
    const fill = document.createElement('span');
    fill.style.width = `${Math.max(1, Number(row.value || 0) / maximum * 100)}%`;
    track.append(fill);
    const value = document.createElement('span');
    value.className = 'rank-value';
    value.textContent = formatValue(
      row.value,
      chart?.unit === 'usd' ? 'usd' : chart?.unit === 'percent' ? 'pct' : '',
    );
    item.append(rank, label, track, value);
    elements.rankings.append(item);
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
    renderTrend(payload.charts?.[0]);
    renderRankings(payload.charts?.[1]);
    renderTable(payload.rows);
    renderOperational(payload.operational);
    elements.pageStatus.textContent = payload.notice
      || `Updated ${new Date().toLocaleTimeString()} · ${payload.scope || 'analytics'}`;
  } catch (error) {
    elements.pageStatus.textContent = error.message;
    renderKpis({});
    renderTrend(null);
    renderRankings(null);
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
  state.comparisonController?.select('total', false);
  applyComparisonWindow('total');
  void loadFilterMetadata().then(loadDashboard);
});
document.getElementById('runAll').addEventListener('click', () => void startRun(null));
document.getElementById('runSelected').addEventListener('click', () => void startRun([state.priority]));
document.getElementById('exportCsv').addEventListener('click', exportCsv);

async function initialize() {
  try {
    state.comparisonController = await mountComparisonBand(
      document.getElementById('comparisonBand'),
      (windowId) => {
        applyComparisonWindow(windowId);
        void loadDashboard();
      },
    );
    applyComparisonWindow(state.comparisonController.windowId);
  } catch (error) {
    elements.pageStatus.textContent = error.message;
  }
  const initialTab = document.querySelector(`[data-workflow="${window.location.hash.slice(1)}"]`)
    || document.querySelector('[data-workflow="demand"]');
  await selectWorkflow(initialTab);
  await Promise.allSettled([loadHealth(), resumeActiveJob()]);
}

void initialize();
