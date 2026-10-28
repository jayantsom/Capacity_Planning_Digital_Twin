import { apiJson } from '/shared/static/dashboard.js';
import { installYuktiWidget } from '/shared/static/yukti.js?v=20261027a';

const shellHost = document.querySelector('[data-shared-shell]');
const pageHeader = document.querySelector('[data-shared-page-header]');
const mainTarget = document.querySelector('main[id], [data-skip-target]');

function applicationIsActive(application) {
  if (application.route === '/') return window.location.pathname === '/';
  return window.location.pathname.startsWith(application.route);
}

function linkFor(application) {
  const link = document.createElement('a');
  link.textContent = application.title;
  link.href = application.enabled ? application.route : '#';
  link.dataset.appId = application.app_id;
  if (applicationIsActive(application)) link.setAttribute('aria-current', 'page');
  if (!application.enabled) {
    link.setAttribute('aria-disabled', 'true');
    link.addEventListener('click', (event) => event.preventDefault());
  }
  return link;
}

function renderShell(applications) {
  if (!shellHost) return;
  const skip = document.createElement('a');
  skip.className = 'ct-skip-link';
  skip.href = `#${mainTarget?.id || 'main'}`;
  skip.textContent = 'Skip to main content';

  const header = document.createElement('header');
  header.className = 'ct-header';
  const brand = document.createElement('a');
  brand.className = 'ct-brand';
  brand.href = '/';
  brand.setAttribute('aria-label', 'Capacity Planning Digital Twin home');
  brand.innerHTML = '<span class="ct-brand-mark" aria-hidden="true">CP</span>';
  const nav = document.createElement('nav');
  nav.className = 'ct-nav';
  nav.setAttribute('aria-label', 'Primary navigation');

  const byId = new Map(applications.map((application) => [application.app_id, application]));
  ['home', 'data-explorer', 'capacity-analysis', 'decision-intelligence']
    .forEach((id) => nav.append(linkFor(byId.get(id))));
  ['data-operations', 'documentation'].forEach((id) => nav.append(linkFor(byId.get(id))));
  installYuktiWidget(nav, applications);
  header.append(brand, nav);
  shellHost.replaceChildren(skip, header);
}

function renderPageHeader() {
  if (!pageHeader) return;
  pageHeader.classList.add('ct-page-header');
  const actions = pageHeader.querySelector('[data-page-actions]');
  const identity = document.createElement('div');
  identity.className = 'ct-page-identity';
  const mark = document.createElement('span');
  mark.className = 'ct-page-mark';
  mark.setAttribute('aria-hidden', 'true');
  mark.textContent = pageHeader.dataset.mark || 'CP';
  const copy = document.createElement('div');
  const eyebrow = document.createElement('p');
  eyebrow.className = 'ct-eyebrow';
  eyebrow.textContent = pageHeader.dataset.eyebrow || '';
  const title = document.createElement('h1');
  title.id = pageHeader.dataset.titleId || 'page-title';
  title.textContent = pageHeader.dataset.title || document.title;
  copy.append(eyebrow, title);
  identity.append(mark, copy);
  pageHeader.replaceChildren(identity);
  if (actions) pageHeader.append(actions);
}

export function formatStatus(state) {
  const normalized = String(state || 'pending').toLowerCase();
  const category = ['error', 'failed', 'offline'].includes(normalized)
    ? 'error'
    : ['warning', 'degraded', 'stale', 'no-data'].includes(normalized)
      ? 'warning'
      : ['ready', 'ok', 'healthy'].includes(normalized) ? 'ready' : 'pending';
  return { state: category, label: normalized.replaceAll('-', ' ').toUpperCase() };
}

renderPageHeader();
apiJson('/shared/api/applications')
  .then((payload) => renderShell(payload.applications))
  .catch(() => {
    if (shellHost) shellHost.textContent = 'Shared navigation is unavailable.';
  });
