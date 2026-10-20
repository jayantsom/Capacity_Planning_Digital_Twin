'use strict';

const AGENTS = {
  capacity: 'Capacity Agent',
  yield: 'Yield Agent',
  maintenance: 'Maintenance Agent',
  forecast: 'Forecast Agent',
  capex: 'CapEx Agent',
  unknown: 'Yukti',
};

const ui = {
  messages: document.getElementById('messages'),
  input: document.getElementById('questionInput'),
  send: document.getElementById('sendButton'),
  cancel: document.getElementById('cancelButton'),
  state: document.getElementById('composerState'),
  inspector: document.getElementById('inspector'),
  inspectorToggle: document.getElementById('inspectorToggle'),
  scrim: document.getElementById('scrim'),
  trace: document.getElementById('traceLog'),
  serviceFlow: document.getElementById('serviceFlow'),
};

let requestController = null;
let retryQuestion = '';

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function setServiceStatus(state, text) {
  const status = document.getElementById('serviceStatus');
  status.className = `service-status status-${state}`;
  status.firstElementChild.textContent = state === 'ready' ? '●' : state === 'degraded' ? '▲' : '×';
  document.getElementById('statusText').textContent = text;
}

async function checkHealth() {
  try {
    const response = await fetch('/api/health', { headers: { Accept: 'application/json' } });
    if (!response.ok) throw new Error();
    const data = await response.json();
    const degraded = data.status && !['ok', 'healthy', 'ready'].includes(String(data.status).toLowerCase());
    setServiceStatus(degraded ? 'degraded' : 'ready', degraded ? 'DEGRADED' : 'READY');
  } catch {
    setServiceStatus('offline', 'OFFLINE');
  }
}

async function loadAgents() {
  const container = document.getElementById('agentList');
  try {
    const response = await fetch('/api/agents', { headers: { Accept: 'application/json' } });
    if (!response.ok) throw new Error();
    const data = await response.json();
    container.replaceChildren();
    (data.agents || []).forEach((agent) => {
      const card = element('article', 'agent-card');
      card.append(element('strong', '', AGENTS[agent.name] || agent.name || 'Agent'));
      card.append(element('p', '', agent.description || 'No description provided.'));
      container.append(card);
    });
    if (!container.children.length) container.append(element('p', 'empty-state', 'No agents reported.'));
  } catch {
    container.replaceChildren(element('p', 'empty-state', 'Agent details are unavailable.'));
  }
}

function toggleInspector(open = !ui.inspector.classList.contains('open')) {
  ui.inspector.classList.toggle('open', open);
  ui.inspector.querySelector('.inspector-heading-copy').setAttribute('aria-hidden', String(!open));
  ui.inspector.querySelectorAll('details').forEach((section) => { section.hidden = !open; });
  ui.inspectorToggle.setAttribute('aria-expanded', String(open));
  const action = open ? 'Collapse' : 'Expand';
  ui.inspectorToggle.setAttribute('aria-label', `${action} analysis inspector`);
  ui.inspectorToggle.title = `${action} analysis inspector`;
  ui.inspectorToggle.firstElementChild.textContent = open ? '‹' : '›';
  ui.scrim.hidden = !open;
}

function now() {
  return new Intl.DateTimeFormat([], { hour: '2-digit', minute: '2-digit' }).format(new Date());
}

function createMessage(role, agent = '') {
  const message = element('article', `message message-${role}`);
  const avatar = element('div', 'message-avatar', role === 'user' ? 'U' : role === 'error' ? '!' : 'Y');
  avatar.setAttribute('aria-hidden', 'true');
  const body = element('div', 'message-body');
  const meta = element('div', 'message-meta');
  if (agent) {
    const specialist = AGENTS[agent] || agent;
    const name = role === 'assistant' && agent !== 'unknown' ? `Yukti · ${specialist}` : specialist;
    meta.append(element('span', 'agent-tag', name));
  }
  meta.append(element('time', '', now()));
  const content = element('div', 'message-content');
  body.append(meta, content);
  message.append(avatar, body);
  if (role === 'error') message.classList.add('message-error');
  return { message, body, content, meta };
}

function appendUserMessage(text) {
  document.getElementById('welcome')?.remove();
  const parts = createMessage('user');
  parts.content.textContent = text;
  ui.messages.append(parts.message);
  scrollConversation();
}

function appendThinking() {
  const parts = createMessage('assistant', 'unknown');
  parts.message.id = 'thinkingMessage';
  const indicator = element('span', 'thinking');
  indicator.setAttribute('aria-label', 'Yukti is thinking');
  indicator.append(element('span'), element('span'), element('span'), document.createTextNode(' Analysing request'));
  parts.content.append(indicator);
  ui.messages.append(parts.message);
  scrollConversation();
}

function appendError(text, question) {
  document.getElementById('thinkingMessage')?.remove();
  const parts = createMessage('error');
  parts.content.textContent = text || 'The request could not be completed.';
  const actions = element('div', 'message-actions');
  const retry = element('button', '', 'Retry request');
  retry.type = 'button';
  retry.addEventListener('click', () => sendQuestion(question));
  actions.append(retry);
  parts.body.append(actions);
  ui.messages.append(parts.message);
  scrollConversation();
}

function renderSafeMarkdown(container, source) {
  container.replaceChildren();
  const lines = String(source || '').split(/\r?\n/);
  let list = null;
  let paragraph = [];

  function appendInline(parent, text) {
    const pattern = /(\*\*[^*]+\*\*|`[^`]+`)/g;
    let cursor = 0;
    for (const match of text.matchAll(pattern)) {
      parent.append(document.createTextNode(text.slice(cursor, match.index)));
      const token = match[0];
      parent.append(element(token.startsWith('**') ? 'strong' : 'code', '', token.startsWith('**') ? token.slice(2, -2) : token.slice(1, -1)));
      cursor = match.index + token.length;
    }
    parent.append(document.createTextNode(text.slice(cursor)));
  }

  function flushParagraph() {
    if (!paragraph.length) return;
    const p = element('p');
    appendInline(p, paragraph.join(' '));
    container.append(p);
    paragraph = [];
  }

  lines.forEach((line) => {
    const bullet = line.match(/^\s*[-*•]\s+(.+)/);
    if (bullet) {
      flushParagraph();
      if (!list) {
        list = element('ul');
        container.append(list);
      }
      const item = element('li');
      appendInline(item, bullet[1]);
      list.append(item);
    } else {
      list = null;
      if (!line.trim()) flushParagraph();
      else paragraph.push(line.trim());
    }
  });
  flushParagraph();
  if (!container.children.length) container.append(element('p', '', 'No response content was returned.'));
}

function startAssistantMessage(agent) {
  document.getElementById('thinkingMessage')?.remove();
  const parts = createMessage('assistant', agent);
  const actions = element('div', 'message-actions');
  const copy = element('button', '', 'Copy response');
  copy.type = 'button';
  copy.addEventListener('click', async () => {
    await navigator.clipboard.writeText(parts.content.textContent || '');
    copy.textContent = 'Copied';
    window.setTimeout(() => { copy.textContent = 'Copy response'; }, 1500);
  });
  actions.append(copy);
  parts.body.append(actions);
  ui.messages.append(parts.message);
  scrollConversation();
  return parts;
}

function addTools(body, tools) {
  if (!tools?.length) return;
  const strip = element('div', 'message-tools');
  tools.forEach((tool) => strip.append(element('span', 'tool-chip', `Evidence · ${tool}`)));
  body.insertBefore(strip, body.querySelector('.message-actions'));
}

function addTrace(label, detail) {
  ui.trace.querySelector('.empty-state')?.remove();
  const item = element('li');
  item.append(element('strong', '', `${label}: `), document.createTextNode(detail));
  ui.trace.append(item);
  ui.trace.scrollTop = ui.trace.scrollHeight;
}

function activateStep(step) {
  ui.serviceFlow.querySelectorAll('li').forEach((item) => item.classList.toggle('active', item.dataset.step === step));
}

function clearTrace() {
  ui.trace.replaceChildren(element('li', 'empty-state', 'Ask a question to see processing steps.'));
  ui.serviceFlow.querySelectorAll('li').forEach((item) => item.classList.remove('active'));
}

function setBusy(busy, message = 'Ready') {
  ui.send.disabled = busy;
  ui.cancel.hidden = !busy;
  ui.input.disabled = busy;
  ui.state.textContent = message;
}

function scrollConversation() {
  ui.messages.scrollTop = ui.messages.scrollHeight;
}

function handlePipeline(data, context) {
  const step = data.step;
  if (step === 'router') {
    context.agent = data.agent || 'unknown';
    activateStep('router');
    addTrace('Router', AGENTS[context.agent] || context.agent);
  } else if (step === 'tool_selection') {
    activateStep('agent');
    addTrace('Agent', data.detail || 'Selected evidence tools');
  } else if (step === 'mcp_tool') {
    activateStep('mcp');
    if (data.tool) context.tools.push(data.tool);
    addTrace('Data tool', `${data.tool || 'query'} · ${data.row_count ?? 0} rows`);
  } else if (step === 'synthesis') {
    activateStep('model');
    addTrace('Model', data.detail || 'Synthesising response');
  }
}

async function sendQuestion(forcedQuestion = '') {
  if (requestController) return;
  const question = (forcedQuestion || ui.input.value).trim();
  if (!question) {
    ui.state.textContent = 'Enter a question first';
    ui.input.focus();
    return;
  }

  retryQuestion = question;
  ui.input.value = '';
  ui.input.style.height = 'auto';
  appendUserMessage(question);
  appendThinking();
  clearTrace();
  setBusy(true, 'Thinking…');
  requestController = new AbortController();

  const context = { agent: 'unknown', tools: [], answer: '', message: null };
  try {
    const response = await fetch('/api/chat/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify({ question }),
      signal: requestController.signal,
    });
    if (!response.ok || !response.body) throw new Error(`Request failed (${response.status})`);

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split(/\r?\n/);
      buffer = lines.pop() || '';
      for (const line of lines) {
        if (!line.startsWith('data:')) continue;
        let event;
        try { event = JSON.parse(line.slice(5).trim()); } catch { continue; }
        if (event.type === 'pipeline') handlePipeline(event.data || {}, context);
        if (event.type === 'token') {
          if (!context.message) context.message = startAssistantMessage(context.agent);
          context.answer += String(event.data || '');
          renderSafeMarkdown(context.message.content, context.answer);
          scrollConversation();
          setBusy(true, 'Streaming response…');
        }
        if (event.type === 'done') {
          if (!context.message) context.message = startAssistantMessage(context.agent);
          addTools(context.message.body, event.data?.tools_called || context.tools);
          activateStep('response');
          addTrace('Response', `Complete · ${event.data?.tool_count ?? context.tools.length} tool(s)`);
        }
        if (event.type === 'error') throw new Error(String(event.data || 'The service returned an error.'));
      }
    }
    if (!context.message) throw new Error('The service returned no response.');
    setServiceStatus('ready', 'READY');
  } catch (error) {
    const cancelled = error.name === 'AbortError';
    appendError(cancelled ? 'Request cancelled.' : 'Yukti is unavailable or the request failed. Check service health and retry.', retryQuestion);
    setServiceStatus(cancelled ? 'ready' : 'offline', cancelled ? 'READY' : 'OFFLINE');
  } finally {
    requestController = null;
    setBusy(false, 'Ready');
    ui.input.disabled = false;
    ui.input.focus();
  }
}

function resetConversation() {
  if (requestController) requestController.abort();
  ui.messages.replaceChildren();
  const welcome = element('div', 'welcome');
  welcome.id = 'welcome';
  welcome.append(element('h2', '', 'What would you like Yukti to analyse?'), element('p', '', 'Use the composer below to start a new capacity-planning conversation.'));
  ui.messages.append(welcome);
  clearTrace();
}

document.getElementById('composer').addEventListener('submit', (event) => {
  event.preventDefault();
  void sendQuestion();
});
ui.input.addEventListener('keydown', (event) => {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    void sendQuestion();
  }
});
ui.input.addEventListener('input', () => {
  ui.input.style.height = 'auto';
  ui.input.style.height = `${Math.min(ui.input.scrollHeight, 160)}px`;
});
document.getElementById('suggestions').addEventListener('click', (event) => {
  const button = event.target.closest('[data-question]');
  if (button) void sendQuestion(button.dataset.question);
});
ui.cancel.addEventListener('click', () => requestController?.abort());
ui.inspectorToggle.addEventListener('click', () => toggleInspector());
ui.scrim.addEventListener('click', () => toggleInspector(false));
document.getElementById('clearTrace').addEventListener('click', (event) => {
  event.preventDefault();
  clearTrace();
});
document.getElementById('clearChat').addEventListener('click', resetConversation);

void checkHealth();
void loadAgents();
