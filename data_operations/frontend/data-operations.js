'use strict';

import { apiJson as api, appendTextCell } from '/shared/static/dashboard.js';
import { loadECharts } from '/shared/static/chart.js?v=20261027c';

const elements = {
  health: document.getElementById('healthStatus'),
  generatorStatus: document.getElementById('generatorStatus'),
  pipelineStatus: document.getElementById('pipelineStatus'),
  pipelineGuidance: document.getElementById('pipelineGuidance'),
  jobPhase: document.getElementById('jobPhase'),
  jobDetail: document.getElementById('jobDetail'),
  jobProgress: document.getElementById('jobProgress'),
  jobPercent: document.getElementById('jobPercent'),
  progressTrack: document.querySelector('[role="progressbar"]'),
  historyBody: document.getElementById('historyBody'),
  clearRawSummary: document.getElementById('clearRawSummary'),
  clearAllSummary: document.getElementById('clearAllSummary'),
  clearStatus: document.getElementById('clearStatus'),
  architectureLayer: document.getElementById('architectureLayer'),
  architectureSearch: document.getElementById('architectureSearch'),
  architectureStatus: document.getElementById('architectureStatus'),
  architectureCounts: document.getElementById('architectureCounts'),
  architectureGraph: document.getElementById('architectureGraph'),
  architectureDetails: document.getElementById('architectureDetails'),
  architectureSchema: document.getElementById('architectureSchema'),
};

let activeJobId = null;
let pollTimer = null;
let latestHealth = null;
let architecture = null;
let architectureChart = null;

function sentenceCase(value) {
  const text = String(value || '').replaceAll('_', ' ').toLowerCase();
  return text ? `${text[0].toUpperCase()}${text.slice(1)}` : '-';
}

function setStatusBadge(element, stateName, baseClass) {
  const state = String(stateName || 'checking').toLowerCase().replaceAll('_', '-');
  const icon = state === 'ready'
    ? '●'
    : ['degraded', 'stale', 'no-data'].includes(state)
      ? '▲'
      : ['offline', 'failed'].includes(state) ? '×' : '◌';
  element.className = `${baseClass} status-${state}`;
  element.firstElementChild.textContent = icon;
  element.lastElementChild.textContent = state.replaceAll('-', ' ').toUpperCase();
}

function setHealthStatus(stateName) {
  setStatusBadge(elements.health, stateName, 'service-status');
}

function selectTab(name) {
  document.querySelectorAll('[role="tab"]').forEach((tab) => {
    const selected = tab.dataset.tab === name;
    tab.setAttribute('aria-selected', String(selected));
    tab.tabIndex = selected ? 0 : -1;
  });
  ['generator', 'pipeline', 'architecture'].forEach((panel) => {
    document.getElementById(`${panel}Panel`).hidden = name !== panel;
  });
  document.getElementById('jobBand').hidden = name === 'architecture';
  document.getElementById('operationsHistory').hidden = name === 'architecture';
  document.getElementById('operationsDanger').hidden = name === 'architecture';
  window.history.replaceState(null, '', `#${name}`);
  if (name === 'architecture') void loadArchitecture();
}

function optionsPayload() {
  const optionalNumber = (id) => {
    const value = document.getElementById(id).value;
    return value ? Number(value) : null;
  };
  return {
    profile: document.getElementById('profile').value,
    random_seed: Number(document.getElementById('randomSeed').value),
    actual_start: document.getElementById('actualStart').value,
    actual_end: document.getElementById('actualEnd').value,
    forecast_start: document.getElementById('forecastStart').value,
    forecast_end: document.getElementById('forecastEnd').value,
    plan_as_of_dates: document.getElementById('planAsOfDates').value
      .split(',')
      .map((value) => value.trim())
      .filter(Boolean),
    noise_profile: document.getElementById('noiseProfile').value,
    max_active_sites: optionalNumber('maxSites'),
    max_active_products: optionalNumber('maxProducts'),
    max_active_test_types: optionalNumber('maxTestTypes'),
    max_systems: optionalNumber('maxSystems'),
    max_fixtures_handlers: optionalNumber('maxFixtures'),
  };
}

function applyDefaults(defaults) {
  document.getElementById('profile').value = defaults.profile;
  document.getElementById('randomSeed').value = defaults.random_seed;
  document.getElementById('actualStart').value = defaults.actual_start;
  document.getElementById('actualEnd').value = defaults.actual_end;
  document.getElementById('forecastStart').value = defaults.forecast_start;
  document.getElementById('forecastEnd').value = defaults.forecast_end;
  document.getElementById('planAsOfDates').value = defaults.plan_as_of_dates.join(', ');
  document.getElementById('noiseProfile').value = defaults.noise_profile;
}

function formatBytes(value) {
  if (!Number.isFinite(value)) return '-';
  const units = ['B', 'KB', 'MB', 'GB'];
  let size = value;
  let unit = 0;
  while (size >= 1024 && unit < units.length - 1) {
    size /= 1024;
    unit += 1;
  }
  return `${size.toFixed(unit > 1 ? 1 : 0)} ${units[unit]}`;
}

function renderEstimate(estimate) {
  document.getElementById('estimateRows').textContent = Number(estimate.estimated_rows).toLocaleString();
  document.getElementById('estimateBytes').textContent = formatBytes(estimate.estimated_raw_bytes);
  document.getElementById('estimateMinutes').textContent = `${estimate.estimated_minutes} min`;
  document.getElementById('estimateLimit').textContent = estimate.within_local_limits ? 'PASS' : 'EXCEEDS';
}

async function updateEstimate() {
  try {
    const estimate = await api('/data-operations/api/estimate', {
      method: 'POST',
      body: JSON.stringify(optionsPayload()),
    });
    renderEstimate(estimate);
  } catch (error) {
    elements.jobPhase.textContent = 'Invalid configuration';
    elements.jobDetail.textContent = error.message;
  }
}

function setButtonsDisabled(disabled) {
  document.getElementById('generateButton').disabled = disabled;
  document.getElementById('pipelineButton').disabled = disabled;
  document.getElementById('rollbackButton').disabled = disabled || !latestHealth?.rollback_available;
  document.getElementById('clearRawButton').disabled = disabled || !latestHealth?.raw_file_count;
  document.getElementById('clearAllButton').disabled = disabled || !latestHealth?.total_file_count;
}

function renderJob(job) {
  const progress = Number(job.progress_pct || 0);
  elements.jobPhase.textContent = `${sentenceCase(job.kind)} · ${job.phase}`;
  elements.jobDetail.textContent = job.detail;
  elements.jobProgress.style.width = `${progress}%`;
  elements.jobPercent.textContent = `${progress}%`;
  elements.progressTrack.setAttribute('aria-valuenow', String(progress));
  const running = ['PENDING', 'RUNNING'].includes(job.status);
  setButtonsDisabled(running);
  return running;
}

async function pollJob() {
  if (!activeJobId) return;
  try {
    const job = await api(`/data-operations/api/jobs/${encodeURIComponent(activeJobId)}`);
    if (renderJob(job)) {
      pollTimer = window.setTimeout(pollJob, 1000);
    } else {
      activeJobId = null;
      await Promise.allSettled([loadHealth(), loadHistory()]);
    }
  } catch (error) {
    elements.jobDetail.textContent = error.message;
    setButtonsDisabled(false);
  }
}

async function startJob(path, body) {
  if (!window.confirm('Start this local compute job?')) return;
  try {
    const job = await api(path, { method: 'POST', body: JSON.stringify(body) });
    activeJobId = job.job_id;
    renderJob(job);
    window.clearTimeout(pollTimer);
    pollTimer = window.setTimeout(pollJob, 500);
  } catch (error) {
    elements.jobPhase.textContent = 'Job not started';
    elements.jobDetail.textContent = error.message;
  }
}

async function loadHealth() {
  try {
    const health = await api('/data-operations/api/health');
    latestHealth = health;
    const generator = health.generator || {
      status: health.raw_database_count > 0 ? 'ready' : 'no-data',
      database_count: health.raw_database_count,
    };
    const pipeline = health.pipeline || {
      status: health.active_run_id ? 'ready' : 'no-data',
    };
    setHealthStatus(health.status);
    setStatusBadge(elements.generatorStatus, generator.status, 'component-status');
    setStatusBadge(elements.pipelineStatus, pipeline.status, 'component-status');
    elements.pipelineGuidance.hidden = pipeline.status !== 'stale';
    elements.pipelineGuidance.textContent = pipeline.status === 'stale'
      ? 'Raw data changed. Run the pipeline to synchronize Data Operations.'
      : '';
    document.getElementById('rawCount').textContent = generator.database_count ?? health.raw_database_count;
    document.getElementById('activeRun').textContent = health.active_run_id || 'NONE';
    document.getElementById('promotedAt').textContent = health.promoted_at
      ? new Date(health.promoted_at).toLocaleString()
      : 'NOT PROMOTED';
    document.getElementById('javaStatus').textContent = health.java_available ? 'READY' : 'MISSING';
    elements.clearRawSummary.textContent = `${health.raw_file_count || 0} files · ${formatBytes(health.raw_size_bytes || 0)}`;
    elements.clearAllSummary.textContent = `${health.total_file_count || 0} files · ${formatBytes(health.total_data_size_bytes || 0)}`;
    setButtonsDisabled(Boolean(activeJobId));
  } catch (error) {
    latestHealth = null;
    setHealthStatus('offline');
    setStatusBadge(elements.generatorStatus, 'offline', 'component-status');
    setStatusBadge(elements.pipelineStatus, 'offline', 'component-status');
    elements.clearRawSummary.textContent = 'Status unavailable';
    elements.clearAllSummary.textContent = 'Status unavailable';
    setButtonsDisabled(true);
    throw error;
  }
}

async function clearData(scope) {
  const isRaw = scope === 'raw';
  const phrase = isRaw ? 'CLEAR RAW' : 'CLEAR ALL';
  const summary = isRaw ? elements.clearRawSummary.textContent : elements.clearAllSummary.textContent;
  const warning = isRaw
    ? `Remove Raw data and generator artifacts (${summary})? The pipeline output will be preserved but marked STALE.`
    : `Remove all generated and derived data (${summary})? This cannot be rolled back.`;
  const confirmation = window.prompt(`${warning}\n\nType ${phrase} to continue:`);
  if (confirmation === null) return;
  if (confirmation !== phrase) {
    elements.clearStatus.textContent = `Not cleared. Type ${phrase} exactly.`;
    return;
  }
  setButtonsDisabled(true);
  elements.clearStatus.textContent = 'Clearing data…';
  try {
    const path = isRaw
      ? '/data-operations/api/data/clear-raw'
      : '/data-operations/api/data/clear-all';
    const result = await api(path, {
      method: 'POST',
      body: JSON.stringify({ confirmation }),
    });
    elements.clearStatus.textContent = `${result.message}.`;
    await Promise.allSettled([loadHealth(), loadHistory()]);
  } catch (error) {
    elements.clearStatus.textContent = error.message;
    setButtonsDisabled(false);
  }
}

async function loadHistory() {
  const payload = await api('/data-operations/api/jobs?limit=20');
  elements.historyBody.replaceChildren();
  payload.jobs.forEach((job) => {
    const row = document.createElement('tr');
    appendTextCell(row, job.job_id);
    appendTextCell(row, sentenceCase(job.kind));
    appendTextCell(row, String(job.status).replaceAll('_', ' '));
    appendTextCell(row, job.phase);
    appendTextCell(row, job.started_at ? new Date(job.started_at).toLocaleString() : '-');
    appendTextCell(row, job.completed_at ? new Date(job.completed_at).toLocaleString() : '-');
    elements.historyBody.append(row);
  });
  const running = payload.jobs.find((job) => ['PENDING', 'RUNNING'].includes(job.status));
  if (running && !activeJobId) {
    activeJobId = running.job_id;
    renderJob(running);
    window.clearTimeout(pollTimer);
    pollTimer = window.setTimeout(pollJob, 500);
  }
}

const ARCHITECTURE_COLORS = {
  raw: '#315f8f',
  reference: '#5b4b8a',
  mapping: '#7c5c9e',
  bronze: '#b45309',
  silver: '#64748b',
  gold: '#d97706',
  serving: '#006d77',
  ml: '#7c3aed',
};

function architectureLayerLabel(layer) {
  return layer === 'ml' ? 'ML' : sentenceCase(layer);
}

function renderArchitectureCounts() {
  elements.architectureCounts.replaceChildren();
  architecture.layers.forEach((layer) => {
    const card = document.createElement('div');
    const label = document.createElement('span');
    label.textContent = architectureLayerLabel(layer);
    const value = document.createElement('strong');
    value.textContent = architecture.layer_counts[layer] || 0;
    card.append(label, value);
    elements.architectureCounts.append(card);
  });
}

function architectureSelection() {
  const selectedLayer = elements.architectureLayer.value;
  const search = elements.architectureSearch.value.trim().toLowerCase();
  let selected = new Set(
    architecture.nodes
      .filter((node) => !selectedLayer || node.layer === selectedLayer)
      .filter((node) => !search || node.id.toLowerCase().includes(search))
      .map((node) => node.id),
  );
  if (selectedLayer || search) {
    architecture.edges.forEach((edge) => {
      if (selected.has(edge.source) || selected.has(edge.target)) {
        selected.add(edge.source);
        selected.add(edge.target);
      }
    });
  } else {
    selected = new Set(architecture.nodes.map((node) => node.id));
  }
  return selected;
}

function renderArchitectureDetails(node) {
  elements.architectureDetails.replaceChildren();
  const fields = [
    ['Object', node.id],
    ['Layer', node.layer === 'ml' ? 'ML' : sentenceCase(node.layer)],
    ['Owner', node.owner],
    ['Grain', node.grain],
    ['Formula', node.formula],
    ['Natural keys', node.natural_keys?.join(', ')],
    ['Canonical keys', node.canonical_keys?.join(', ')],
    ['Units', node.units ? JSON.stringify(node.units) : null],
    ['Consumers', node.consuming_apps?.join(', ')],
  ];
  fields.forEach(([name, value]) => {
    if (value == null || value === '') return;
    const term = document.createElement('dt');
    term.textContent = name;
    const description = document.createElement('dd');
    description.textContent = String(value);
    elements.architectureDetails.append(term, description);
  });
  void renderArchitectureSchema(node);
}

async function renderArchitectureSchema(node) {
  elements.architectureSchema.replaceChildren();
  const caption = document.createElement('caption');
  caption.textContent = 'Published schema';
  elements.architectureSchema.append(caption);
  if (!node.catalog_source || !node.catalog_table) {
    const body = document.createElement('tbody');
    const row = document.createElement('tr');
    appendTextCell(row, 'No physical catalog object is mapped.');
    body.append(row);
    elements.architectureSchema.append(body);
    return;
  }
  try {
    const schema = await api(
      `/explorer/api/schema/${encodeURIComponent(node.catalog_source)}/${encodeURIComponent(node.catalog_table)}`,
    );
    const head = document.createElement('thead');
    const headRow = document.createElement('tr');
    ['Column', 'Type'].forEach((label) => {
      const header = document.createElement('th');
      header.textContent = label;
      headRow.append(header);
    });
    head.append(headRow);
    const body = document.createElement('tbody');
    schema.columns.forEach((column) => {
      const row = document.createElement('tr');
      appendTextCell(row, column.name);
      appendTextCell(row, column.type);
      body.append(row);
    });
    caption.textContent = `${schema.row_count.toLocaleString()} rows | ${schema.native_grain} grain`;
    elements.architectureSchema.append(head, body);
  } catch (error) {
    const body = document.createElement('tbody');
    const row = document.createElement('tr');
    appendTextCell(row, error.message);
    body.append(row);
    elements.architectureSchema.append(body);
  }
}

async function renderArchitectureGraph() {
  if (!architecture) return;
  const visible = architectureSelection();
  const nodes = architecture.nodes.filter((node) => visible.has(node.id));
  const edges = architecture.edges.filter(
    (edge) => visible.has(edge.source) && visible.has(edge.target),
  );
  const grouped = new Map(architecture.layers.map((layer) => [layer, []]));
  nodes.forEach((node) => grouped.get(node.layer)?.push(node));
  const graphNodes = [];
  architecture.layers.forEach((layer, layerIndex) => {
    const layerNodes = grouped.get(layer) || [];
    layerNodes.forEach((node, nodeIndex) => {
      graphNodes.push({
        id: node.id,
        name: node.label,
        objectId: node.id,
        category: architectureLayerLabel(layer),
        x: layerIndex * 220,
        y: (nodeIndex - (layerNodes.length - 1) / 2) * 54,
        symbolSize: 18,
        itemStyle: { color: ARCHITECTURE_COLORS[layer] },
      });
    });
  });
  const echarts = await loadECharts();
  if (architectureChart) architectureChart.dispose();
  architectureChart = echarts.init(elements.architectureGraph, null, { renderer: 'canvas' });
  architectureChart.setOption({
    animation: !window.matchMedia('(prefers-reduced-motion: reduce)').matches,
    tooltip: {
      trigger: 'item',
      formatter: (params) => (
        params.dataType === 'edge'
          ? `${params.data.source} -> ${params.data.target}<br>${params.data.relation}`
          : params.data.objectId
      ),
    },
    legend: [{
      data: architecture.layers.map((layer) => ({
        name: architectureLayerLabel(layer),
        itemStyle: { color: ARCHITECTURE_COLORS[layer] },
      })),
    }],
    series: [{
      type: 'graph',
      layout: 'none',
      roam: true,
      categories: architecture.layers.map((layer) => ({
        name: architectureLayerLabel(layer),
      })),
      data: graphNodes,
      links: edges,
      edgeSymbol: ['none', 'arrow'],
      edgeSymbolSize: 7,
      lineStyle: { color: '#8b949c', width: 1, curveness: 0.08, opacity: 0.65 },
      label: {
        show: nodes.length <= 120,
        position: 'right',
        formatter: '{b}',
        fontSize: 9,
      },
      emphasis: { focus: 'adjacency', lineStyle: { width: 2, opacity: 1 } },
    }],
  });
  architectureChart.on('click', (params) => {
    if (params.dataType !== 'node') return;
    const node = architecture.nodes.find((item) => item.id === params.data.objectId);
    if (node) renderArchitectureDetails(node);
  });
  elements.architectureStatus.textContent = `${nodes.length} objects | ${edges.length} lineage links`;
}

async function loadArchitecture() {
  if (architecture) {
    await renderArchitectureGraph();
    return;
  }
  try {
    architecture = await api('/data-operations/api/architecture');
    elements.architectureLayer.replaceChildren(new Option('All layers', ''));
    architecture.layers.forEach((layer) => {
      const label = architectureLayerLabel(layer);
      elements.architectureLayer.add(new Option(label, layer));
    });
    renderArchitectureCounts();
    await renderArchitectureGraph();
    const firstGold = architecture.nodes.find((node) => node.layer === 'gold');
    if (firstGold) renderArchitectureDetails(firstGold);
  } catch (error) {
    elements.architectureStatus.textContent = error.message;
  }
}

async function initialize() {
  try {
    const configuration = await api('/data-operations/api/config');
    applyDefaults(configuration.defaults);
    renderEstimate(configuration.estimate);
    await Promise.allSettled([loadHealth(), loadHistory()]);
  } catch (error) {
    setHealthStatus('offline');
    elements.jobDetail.textContent = error.message;
  } finally {
    const requested = window.location.hash.slice(1);
    selectTab(['generator', 'pipeline', 'architecture'].includes(requested)
      ? requested : 'generator');
  }
}

document.querySelectorAll('[role="tab"]').forEach((tab) => {
  tab.addEventListener('click', () => selectTab(tab.dataset.tab));
  tab.addEventListener('keydown', (event) => {
    if (!['ArrowLeft', 'ArrowRight'].includes(event.key)) return;
    event.preventDefault();
    const tabs = [...document.querySelectorAll('[role="tab"]')];
    const offset = event.key === 'ArrowRight' ? 1 : -1;
    const next = tabs[(tabs.indexOf(tab) + offset + tabs.length) % tabs.length];
    selectTab(next.dataset.tab);
    next.focus();
  });
});
document.getElementById('generatorForm').addEventListener('submit', (event) => {
  event.preventDefault();
  void startJob('/data-operations/api/jobs/generate', { generator: optionsPayload() });
});
document.getElementById('pipelineButton').addEventListener('click', () => {
  void startJob('/data-operations/api/jobs/pipeline', { command: 'run' });
});
document.getElementById('rollbackButton').addEventListener('click', async () => {
  if (!window.confirm('Activate the previous validated pipeline run?')) return;
  try {
    await api('/data-operations/api/rollback', { method: 'POST', body: '{}' });
    await loadHealth();
  } catch (error) {
    elements.jobDetail.textContent = error.message;
  }
});
document.getElementById('clearRawButton').addEventListener('click', () => void clearData('raw'));
document.getElementById('clearAllButton').addEventListener('click', () => void clearData('all'));
document.getElementById('estimateButton').addEventListener('click', () => void updateEstimate());
document.getElementById('refreshButton').addEventListener('click', () => {
  void Promise.allSettled([loadHealth(), loadHistory()]);
});
elements.architectureLayer.addEventListener('change', () => void renderArchitectureGraph());
elements.architectureSearch.addEventListener('input', () => void renderArchitectureGraph());
document.getElementById('resetArchitecture').addEventListener('click', () => {
  elements.architectureLayer.value = '';
  elements.architectureSearch.value = '';
  void renderArchitectureGraph();
});
window.addEventListener('resize', () => architectureChart?.resize());

void initialize();
