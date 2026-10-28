import { apiJson } from '/shared/static/dashboard.js';
import { installYuktiWidget } from '/shared/static/yukti.js';

const shellHost = document.querySelector('[data-shared-shell]');
const pageHeader = document.querySelector('[data-shared-page-header]');
const mainTarget = document.querySelector('main[id], [data-skip-target]');

function applicationIsActive(application) {
  if (application.route === '/') return window.location.pathname === '/';
  return window.location.pathname.startsWith(application.route);
}

function linkFor(application, { menu = false } = {}) {
  const link = document.createElement('a');
  link.textContent = application.title;
  link.href = application.enabled ? application.route : '#';
  link.dataset.appId = application.app_id;
  if (applicationIsActive(application)) link.setAttribute('aria-current', 'page');
  if (!application.enabled) {
    link.setAttribute('aria-disabled', 'true');
    link.addEventListener('click', (event) => event.preventDefault());
  }
  if (menu) {
    link.setAttribute('role', 'menuitem');
    link.tabIndex = -1;
    const state = document.createElement('small');
    state.textContent = application.enabled ? '' : 'PLANNED';
    link.append(state);
  }
  return link;
}

function installPlanningMenu(container, applications) {
  const wrapper = document.createElement('div');
  wrapper.className = 'ct-menu';
  const button = document.createElement('button');
  button.className = 'ct-menu-button';
  button.type = 'button';
  button.textContent = 'Planning';
  button.setAttribute('aria-haspopup', 'menu');
  button.setAttribute('aria-expanded', 'false');

  const list = document.createElement('ul');
  list.className = 'ct-menu-list';
  list.id = 'ct-planning-menu';
  list.hidden = true;
  list.setAttribute('role', 'menu');
  button.setAttribute('aria-controls', list.id);
  applications.forEach((application) => {
    const item = document.createElement('li');
    item.setAttribute('role', 'none');
    item.append(linkFor(application, { menu: true }));
    list.append(item);
  });

  const items = () => [...list.querySelectorAll('[role="menuitem"]')];
  const open = (focus = true) => {
    list.hidden = false;
    button.setAttribute('aria-expanded', 'true');
    if (focus) items()[0]?.focus();
  };
  const close = (restoreFocus = true) => {
    list.hidden = true;
    button.setAttribute('aria-expanded', 'false');
    if (restoreFocus) button.focus();
  };

  button.addEventListener('click', () => {
    if (list.hidden) open(false);
    else close(false);
  });
  button.addEventListener('keydown', (event) => {
    if (['ArrowDown', 'Enter', ' '].includes(event.key)) {
      event.preventDefault();
      open();
    } else if (event.key === 'ArrowUp') {
      event.preventDefault();
      open(false);
      items().at(-1)?.focus();
    }
  });
  list.addEventListener('keydown', (event) => {
    const menuItems = items();
    const index = menuItems.indexOf(document.activeElement);
    if (event.key === 'Escape') {
      event.preventDefault();
      close();
    } else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      const delta = event.key === 'ArrowDown' ? 1 : -1;
      menuItems[(index + delta + menuItems.length) % menuItems.length]?.focus();
    } else if (event.key === 'Home' || event.key === 'End') {
      event.preventDefault();
      menuItems[event.key === 'Home' ? 0 : menuItems.length - 1]?.focus();
    } else if (event.key === 'Tab') {
      close(false);
    }
  });
  document.addEventListener('pointerdown', (event) => {
    if (!wrapper.contains(event.target)) close(false);
  });
  wrapper.append(button, list);
  container.append(wrapper);
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
  installPlanningMenu(nav, applications.filter((application) => application.group === 'planning'));
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
