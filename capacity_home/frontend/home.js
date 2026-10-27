'use strict';

import { apiJson } from '/shared/dashboard.js';

const statusTargets = {
  operationsAssistant: {
    badge: document.getElementById('operations-assistant-status'),
    detail: document.getElementById('operations-assistant-detail'),
  },
  explorer: {
    badge: document.getElementById('explorer-status'),
    detail: document.getElementById('explorer-detail'),
  },
  decision: {
    badge: document.getElementById('decision-status'),
    detail: document.getElementById('decision-detail'),
  },
  operations: {
    badge: document.getElementById('operations-status'),
    detail: document.getElementById('operations-detail'),
  },
};

const operationsComponents = {
  generator: document.getElementById('generator-home-status'),
  pipeline: document.getElementById('pipeline-home-status'),
};

function setBadge(badge, state, label, baseClass = 'status') {
  badge.className = `${baseClass} status-${state}`;
  badge.replaceChildren();
  const icon = document.createElement('span');
  icon.setAttribute('aria-hidden', 'true');
  const warning = ['degraded', 'stale', 'no-data', 'no-sources'].includes(state);
  icon.textContent = state === 'ready'
    ? '●'
    : warning ? '▲' : ['offline', 'failed'].includes(state) ? '×' : '◌';
  badge.append(icon, document.createTextNode(` ${label}`));
}

function setStatus(target, state, label, detail) {
  setBadge(target.badge, state, label);
  target.detail.textContent = detail;
}

async function fetchJson(url, timeoutMs = 5000) {
  return apiJson(url, {}, timeoutMs);
}

async function checkOperationsAssistant() {
  setStatus(statusTargets.operationsAssistant, 'pending', 'CHECKING', 'Checking service…');
  try {
    const health = await fetchJson('/operations-assistant/api/health');
    const model = health.model || health.ollama || '';
    const isDegraded = health.status && !['ok', 'healthy', 'ready'].includes(String(health.status).toLowerCase());
    setStatus(
      statusTargets.operationsAssistant,
      isDegraded ? 'degraded' : 'ready',
      isDegraded ? 'DEGRADED' : 'READY',
      model ? `API ready · ${model}` : 'API responding',
    );
  } catch {
    setStatus(statusTargets.operationsAssistant, 'offline', 'OFFLINE', 'API not responding');
  }
}

async function checkExplorer() {
  setStatus(statusTargets.explorer, 'pending', 'CHECKING', 'Checking sources…');
  try {
    const sources = await fetchJson('/explorer/api/sources');
    const count = Array.isArray(sources) ? sources.length : 0;
    setStatus(
      statusTargets.explorer,
      count > 0 ? 'ready' : 'no-sources',
      count > 0 ? 'READY' : 'NO SOURCES',
      `${count} source${count === 1 ? '' : 's'} reported`,
    );
  } catch {
    setStatus(statusTargets.explorer, 'offline', 'OFFLINE', 'Source API not responding');
  }
}

async function checkDecisionIntelligence() {
  setStatus(statusTargets.decision, 'pending', 'CHECKING', 'Five model workflows');
  try {
    const health = await fetchJson('/decision-intelligence/api/health');
    const state = health.stale ? 'stale' : health.status === 'ready' ? 'ready' : 'degraded';
    setStatus(
      statusTargets.decision,
      state,
      health.stale ? 'STALE' : health.status === 'ready' ? 'READY' : 'DEGRADED',
      health.run_id ? `Run ${health.run_id}` : 'No model publication',
    );
  } catch {
    setStatus(statusTargets.decision, 'offline', 'OFFLINE', 'Model API unavailable');
  }
}

async function checkDataOperations() {
  setStatus(statusTargets.operations, 'pending', 'CHECKING', 'Raw and medallion status');
  setBadge(operationsComponents.generator, 'pending', 'CHECKING', 'mini-status');
  setBadge(operationsComponents.pipeline, 'pending', 'CHECKING', 'mini-status');
  try {
    const health = await fetchJson('/data-operations/api/health');
    const generatorState = health.generator?.status
      || (health.raw_database_count > 0 ? 'ready' : 'no-data');
    const pipelineState = health.pipeline?.status
      || (health.active_run_id ? 'ready' : 'no-data');
    const state = ['ready', 'running'].includes(health.status) ? health.status : 'degraded';
    setBadge(
      operationsComponents.generator,
      generatorState,
      generatorState.replaceAll('-', ' ').toUpperCase(),
      'mini-status',
    );
    setBadge(
      operationsComponents.pipeline,
      pipelineState,
      pipelineState.replaceAll('-', ' ').toUpperCase(),
      'mini-status',
    );
    setStatus(
      statusTargets.operations,
      state,
      state.toUpperCase(),
      `Generator ${generatorState.replaceAll('-', ' ').toUpperCase()} · Pipeline ${pipelineState.replaceAll('-', ' ').toUpperCase()}`,
    );
  } catch {
    setStatus(statusTargets.operations, 'offline', 'OFFLINE', 'Operations API unavailable');
    setBadge(operationsComponents.generator, 'offline', 'OFFLINE', 'mini-status');
    setBadge(operationsComponents.pipeline, 'offline', 'OFFLINE', 'mini-status');
  }
}

function refreshStatus() {
  void Promise.allSettled([
    checkExplorer(),
    checkDecisionIntelligence(),
    checkOperationsAssistant(),
    checkDataOperations(),
  ]);
}

document.getElementById('refresh-status').addEventListener('click', refreshStatus);
refreshStatus();
