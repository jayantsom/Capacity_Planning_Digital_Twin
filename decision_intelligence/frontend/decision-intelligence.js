'use strict';

import { apiJson as api, readableLabel as labelFor } from '/shared/dashboard.js';

const state = {
  workflow: 'demand',
  priority: 1,
  rows: [],
  activeJobId: null,
  pollTimer: null,
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
  donut: document.getElementById('donutChart'),
  donutValue: document.getElementById('donutValue'),
  donutLegend: document.getElementById('donutLegend'),
  rankings: document.getElementById('rankings'),
  tableHead: document.getElementById('tableHead'),
  tableBody: document.getElementById('tableBody'),
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
  const values = {
    site: document.getElementById('siteFilter').value.trim(),
    product: document.getElementById('productFilter').value.trim(),
    test_type: document.getElementById('testFilter').value.trim(),
    snapshot: document.getElementById('snapshotFilter').value.trim(),
    month_from: document.getElementById('monthFrom').value,
    month_to: document.getElementById('monthTo').value,
  };
  Object.entries(values).forEach(([key, value]) => {
    if (value) params.set(key, value);
  });
  return params;
}

function selectWorkflow(tab) {
  document.querySelectorAll('[role="tab"]').forEach((candidate) => {
    const selected = candidate === tab;
    candidate.setAttribute('aria-selected', String(selected));
    candidate.tabIndex = selected ? 0 : -1;
  });
  state.workflow = tab.dataset.workflow;
  state.priority = Number(tab.dataset.priority);
  window.history.replaceState(null, '', `#${state.workflow}`);
  void loadDashboard();
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

function renderTrend(series) {
  elements.trend.replaceChildren();
  if (!series.length) {
    const empty = document.createElement('p');
    empty.className = 'empty';
    empty.textContent = 'This workflow publishes rankings and scenario records.';
    elements.trend.append(empty);
    elements.trendSummary.textContent = 'No time series';
    return;
  }
  const maximum = Math.max(
    1,
    ...series.flatMap((row) => [Number(row.value || 0), Number(row.secondary || 0)]),
  );
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('viewBox', '0 0 1000 220');
  svg.setAttribute('preserveAspectRatio', 'none');
  svg.setAttribute('aria-hidden', 'true');
  const points = [];
  series.forEach((row, index) => {
    const column = document.createElement('div');
    column.className = 'trend-column';
    if (row.secondary != null) {
      const bar = document.createElement('i');
      bar.className = 'secondary';
      bar.style.height = `${Math.max(1, Number(row.secondary || 0) / maximum * 220)}px`;
      bar.title = `${row.period}: ${formatValue(row.secondary)}`;
      column.append(bar);
    }
    if (row.value != null) {
      const x = series.length === 1 ? 500 : index / (series.length - 1) * 1000;
      const y = 210 - Number(row.value || 0) / maximum * 190;
      points.push(`${x},${y}`);
    }
    const period = document.createElement('em');
    period.textContent = row.period;
    column.append(period);
    elements.trend.append(column);
  });
  if (points.length > 1) {
    const line = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
    line.setAttribute('points', points.join(' '));
    line.setAttribute('vector-effect', 'non-scaling-stroke');
    svg.append(line);
    elements.trend.prepend(svg);
  }
  elements.trendSummary.textContent = `${series.length} periods`;
}

function renderDonut(records) {
  elements.donutLegend.replaceChildren();
  const colors = ['#006d77', '#4f8f95', '#83aeb2', '#b8c8ca', '#dce2e3'];
  const top = records
    .slice(0, 5)
    .map((row) => ({ label: String(row.label), value: Math.max(0, Number(row.value || 0)) }));
  const total = top.reduce((sum, row) => sum + row.value, 0);
  let cursor = 0;
  const segments = top.map((row, index) => {
    const start = cursor;
    cursor += total ? row.value / total * 100 : 0;
    return `${colors[index]} ${start}% ${cursor}%`;
  });
  elements.donut.style.background = total
    ? `conic-gradient(${segments.join(',')})`
    : '#e3e6e8';
  elements.donutValue.textContent = total ? formatValue(total) : '—';
  top.forEach((row, index) => {
    const item = document.createElement('div');
    const swatch = document.createElement('i');
    const label = document.createElement('span');
    swatch.style.background = colors[index];
    label.textContent = row.label;
    item.append(swatch, label);
    elements.donutLegend.append(item);
  });
}

function renderRankings(rankings) {
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
    value.textContent = formatValue(row.value, state.workflow === 'capex' ? 'usd' : '');
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

async function loadDashboard() {
  elements.pageStatus.textContent = 'Loading…';
  try {
    const payload = await api(
      `/decision-intelligence/api/dashboard/${encodeURIComponent(state.workflow)}?${filters()}`,
    );
    renderKpis(payload.kpis);
    renderTrend(payload.series);
    renderDonut(payload.drivers || payload.rankings);
    renderRankings(payload.rankings);
    renderTable(payload.rows);
    elements.pageStatus.textContent = `Updated ${new Date().toLocaleTimeString()}`;
  } catch (error) {
    elements.pageStatus.textContent = error.message;
    renderKpis({});
    renderTrend([]);
    renderDonut([]);
    renderRankings([]);
    renderTable([]);
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
  tab.addEventListener('click', () => selectWorkflow(tab));
  tab.addEventListener('keydown', (event) => {
    if (!['ArrowLeft', 'ArrowRight'].includes(event.key)) return;
    const tabs = [...document.querySelectorAll('[role="tab"]')];
    const offset = event.key === 'ArrowRight' ? 1 : -1;
    const next = tabs[(tabs.indexOf(tab) + offset + tabs.length) % tabs.length];
    event.preventDefault();
    next.focus();
    selectWorkflow(next);
  });
});
document.getElementById('filters').addEventListener('submit', (event) => {
  event.preventDefault();
  void loadDashboard();
});
document.getElementById('clearFilters').addEventListener('click', () => {
  document.getElementById('filters').reset();
  void loadDashboard();
});
document.getElementById('runAll').addEventListener('click', () => void startRun(null));
document.getElementById('runSelected').addEventListener('click', () => void startRun([state.priority]));
document.getElementById('exportCsv').addEventListener('click', exportCsv);

const initialTab = document.querySelector(`[data-workflow="${window.location.hash.slice(1)}"]`)
  || document.querySelector('[data-workflow="demand"]');
selectWorkflow(initialTab);
void Promise.allSettled([loadHealth(), resumeActiveJob()]);
