'use strict';

import { apiJson } from '/shared/static/dashboard.js';

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

function cardFor(application) {
  const card = document.createElement('a');
  card.className = 'app-card';
  card.href = application.route;
  card.dataset.app = application.app_id;
  const top = document.createElement('span');
  top.className = 'card-top';
  const mark = document.createElement('b');
  mark.textContent = application.monogram;
  const status = document.createElement('span');
  status.className = 'status status-pending';
  status.dataset.statusFor = application.app_id;
  status.textContent = 'CHECKING';
  top.append(mark, status);
  const bottom = document.createElement('span');
  bottom.className = 'card-bottom';
  const title = document.createElement('strong');
  title.textContent = application.title;
  const detail = document.createElement('small');
  detail.dataset.detailFor = application.app_id;
  detail.textContent = application.description;
  bottom.append(title, detail);
  card.append(top, bottom);
  return card;
}

async function loadApplications() {
  const payload = await apiJson('/shared/api/applications');
  const applications = payload.applications.filter(
    (application) => application.enabled && application.show_on_home,
  );
  const container = document.getElementById('applicationCards');
  container.replaceChildren(...applications.map(cardFor));
  await Promise.allSettled(applications.map(checkApplication));
}

async function checkApplication(application) {
  const badge = document.querySelector(`[data-status-for="${application.app_id}"]`);
  const detail = document.querySelector(`[data-detail-for="${application.app_id}"]`);
  if (!application.health_route) {
    setBadge(badge, 'ready', 'READY');
    return;
  }
  try {
    const payload = await apiJson(application.health_route, {}, 5000);
    const hasSources = Array.isArray(payload) ? payload.length > 0 : true;
    const rawState = Array.isArray(payload) ? (hasSources ? 'ready' : 'no-sources') : payload.status;
    const state = ['ready', 'ok', 'healthy', 'running'].includes(String(rawState).toLowerCase())
      ? 'ready'
      : 'degraded';
    setBadge(badge, state, state.toUpperCase());
    detail.textContent = application.description;
  } catch {
    setBadge(badge, 'offline', 'OFFLINE');
    detail.textContent = `${application.description} · unavailable`;
  }
}

function refreshStatus() {
  void loadApplications().catch(() => {
    document.getElementById('applicationCards').textContent = 'Application registry is unavailable.';
  });
}

document.getElementById('refresh-status').addEventListener('click', refreshStatus);
refreshStatus();
