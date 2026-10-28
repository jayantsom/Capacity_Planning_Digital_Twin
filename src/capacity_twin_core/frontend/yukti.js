import { apiJson } from '/shared/static/dashboard.js';

const SUGGESTIONS = {
  'data-explorer': [
    'Show the selected table schema.',
    'Write a read-only SQL query for the current filters.',
  ],
  'capacity-analysis': [
    'Where is capacity constrained?',
    'Compare normal and maximum capacity.',
  ],
  'decision-intelligence': [
    'Explain the most important result on this workflow.',
    'Which records need review first?',
  ],
  'data-operations': ['Explain the current pipeline status.', 'Which published tables are available?'],
  documentation: ['Explain this page in simple language.', 'Where can I learn about the data model?'],
  home: ['What can I do in this application?', 'Where should a capacity planner start?'],
};

function activeApplication(applications) {
  return applications.find((application) => (
    application.route === '/'
      ? window.location.pathname === '/'
      : window.location.pathname.startsWith(application.route)
  )) || applications.find((application) => application.app_id === 'home');
}

function currentView() {
  const selected = document.querySelector('[role="tab"][aria-selected="true"]');
  return selected?.dataset.workflow || selected?.dataset.view
    || window.location.hash.replace(/^#/, '') || null;
}

function currentFilters() {
  const values = {};
  const form = document.querySelector('form[id*="filter"], form#filters');
  if (!form) return values;
  new FormData(form).forEach((value, key) => {
    if (value !== '') values[key] = String(value).slice(0, 150);
  });
  return values;
}

function selectedTable() {
  const selected = document.querySelector(
    '[data-table][aria-selected="true"], [data-selected-table]',
  );
  const explicit = selected?.dataset.table || selected?.dataset.selectedTable;
  if (explicit) return explicit;
  const explorerTitle = document.getElementById('tableTitle')?.textContent?.trim();
  return explorerTitle && explorerTitle !== 'Select a table' ? explorerTitle : null;
}

function pageContext(application) {
  return {
    app_id: application.app_id,
    path: window.location.pathname,
    view: currentView(),
    selected_table: selectedTable(),
    filters: currentFilters(),
  };
}

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text != null) node.textContent = text;
  return node;
}

function addMessage(container, role, text = '') {
  const article = element('article', `ct-yukti-message ct-yukti-${role}`);
  const label = element('strong', '', role === 'user' ? 'You' : 'Yukti');
  const body = element('p', '', text);
  article.append(label, body);
  container.append(article);
  container.scrollTop = container.scrollHeight;
  return body;
}

async function streamAnswer(payload, output, status) {
  const response = await fetch('/shared/api/yukti/chat/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
  if (!response.ok || !response.body) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed with status ${response.status}`);
  }
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    const events = buffer.split('\n\n');
    buffer = events.pop() || '';
    for (const event of events) {
      const line = event.split('\n').find((item) => item.startsWith('data: '));
      if (!line) continue;
      const message = JSON.parse(line.slice(6));
      if (message.type === 'token') {
        output.textContent += String(message.data || '');
      } else if (message.type === 'pipeline') {
        status.textContent = message.data?.detail || 'Working';
      } else if (message.type === 'done') {
        status.textContent = `Answered by ${message.data?.agent || 'Yukti'}`;
      } else if (message.type === 'error') {
        throw new Error(String(message.data || 'The request failed.'));
      }
    }
    if (done) break;
  }
}

export function installYuktiWidget(container, applications) {
  const application = activeApplication(applications);
  const mount = element('aside', 'ct-yukti-mount');
  mount.id = 'yukti-mount';
  mount.hidden = true;
  mount.setAttribute('aria-label', 'Yukti AI assistant');

  const head = element('div', 'ct-yukti-head');
  const identity = element('div');
  identity.append(
    element('strong', '', 'Yukti'),
    element('small', '', `AI assistant | ${application.title}`),
  );
  const close = element('button', '', 'Close');
  close.type = 'button';
  head.append(identity, close);

  const inspector = document.createElement('details');
  inspector.className = 'ct-yukti-context';
  const inspectorLabel = element('summary', '', 'Current page context');
  const inspectorBody = element('pre');
  inspector.append(inspectorLabel, inspectorBody);

  const suggestions = element('div', 'ct-yukti-suggestions');
  (SUGGESTIONS[application.app_id] || SUGGESTIONS.home).forEach((text) => {
    const button = element('button', '', text);
    button.type = 'button';
    button.dataset.suggestion = text;
    suggestions.append(button);
  });

  const messages = element('div', 'ct-yukti-messages');
  messages.setAttribute('aria-live', 'polite');
  addMessage(
    messages,
    'assistant',
    `Ask about ${application.title}. I use the current page context and governed read-only data.`,
  );

  const status = element('p', 'ct-yukti-status', 'Ready');
  status.setAttribute('role', 'status');
  const form = element('form', 'ct-yukti-form');
  const input = document.createElement('textarea');
  input.name = 'question';
  input.rows = 2;
  input.maxLength = 4000;
  input.required = true;
  input.placeholder = 'Ask Yukti a question';
  const clear = element('button', 'ct-yukti-clear', 'Clear');
  clear.type = 'button';
  const send = element('button', 'ct-yukti-send', 'Send');
  send.type = 'submit';
  form.append(input, clear, send);
  mount.append(head, inspector, suggestions, messages, status, form);
  document.body.append(mount);

  const toggle = element('button', 'ct-yukti-toggle', 'Yukti');
  toggle.type = 'button';
  toggle.setAttribute('aria-controls', mount.id);
  toggle.setAttribute('aria-expanded', 'false');
  container.append(toggle);

  const refreshContext = () => {
    const context = pageContext(application);
    inspectorBody.textContent = JSON.stringify(context, null, 2);
    return context;
  };
  const setOpen = (open) => {
    mount.hidden = !open;
    toggle.setAttribute('aria-expanded', String(open));
    if (open) {
      refreshContext();
      input.focus();
    }
  };
  toggle.addEventListener('click', () => setOpen(mount.hidden));
  close.addEventListener('click', () => setOpen(false));
  suggestions.addEventListener('click', (event) => {
    const text = event.target.closest('[data-suggestion]')?.dataset.suggestion;
    if (!text) return;
    input.value = text;
    input.focus();
  });
  clear.addEventListener('click', () => {
    messages.replaceChildren();
    addMessage(messages, 'assistant', 'Chat cleared. What would you like to know?');
    status.textContent = 'Ready';
    input.focus();
  });
  form.addEventListener('submit', async (event) => {
    event.preventDefault();
    const question = input.value.trim();
    if (!question) return;
    addMessage(messages, 'user', question);
    input.value = '';
    input.disabled = true;
    send.disabled = true;
    const output = addMessage(messages, 'assistant');
    status.textContent = 'Checking the current page context';
    try {
      await streamAnswer({ question, context: refreshContext() }, output, status);
      if (!output.textContent.trim()) output.textContent = 'No answer was returned.';
    } catch (error) {
      output.textContent = error.message;
      status.textContent = 'Request failed';
    } finally {
      input.disabled = false;
      send.disabled = false;
      input.focus();
    }
  });

  apiJson('/shared/api/yukti/health')
    .then((health) => {
      status.textContent = health.status === 'ready' ? 'Ready' : 'Limited availability';
    })
    .catch(() => {
      status.textContent = 'Assistant is unavailable';
    });
}
