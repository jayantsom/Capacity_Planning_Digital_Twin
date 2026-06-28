/* app.js — Capacity Planning Twin Chat UI */

const API = '';   // same origin — FastAPI serves both

// ── State ──────────────────────────────────────────────────────────────────────
let isStreaming = false;
let currentAiMsg = null;
let currentAnswer = '';

// ── Agent color map ────────────────────────────────────────────────────────────
const AGENT_META = {
  capacity:    { label: 'Capacity Agent',    color: '#00b4d8' },
  yield:       { label: 'Yield Agent',       color: '#06d6a0' },
  maintenance: { label: 'Maintenance Agent', color: '#ef6c00' },
  forecast:    { label: 'Forecast Agent',    color: '#ab47bc' },
  capex:       { label: 'CapEx Agent',       color: '#ffd166' },
  unknown:     { label: 'Agent',             color: '#8899bb' },
};

// Architecture node → arch-diagram node id mapping
const ARCH_NODE_MAP = {
  router:         'arch-router',
  tool_selection: 'arch-agent',
  mcp_tool:       'arch-mcp',
  duckdb:         'arch-duckdb',
  synthesis:      'arch-ollama',
};

// ── Init ───────────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  checkHealth();
  loadAgentCards();
});

async function checkHealth() {
  const dot  = document.querySelector('.status-dot');
  const text = document.getElementById('statusText');
  try {
    const r = await fetch(`${API}/api/health`);
    if (r.ok) {
      dot.className  = 'status-dot online';
      text.textContent = 'Connected';
    } else {
      throw new Error('not ok');
    }
  } catch {
    dot.className  = 'status-dot error';
    text.textContent = 'Offline';
  }
}

async function loadAgentCards() {
  try {
    const r    = await fetch(`${API}/api/agents`);
    const data = await r.json();
    const container = document.getElementById('agentCards');
    container.innerHTML = '';

    data.agents.forEach(agent => {
      const meta = AGENT_META[agent.name] || AGENT_META.unknown;
      const card = document.createElement('div');
      card.className = 'agent-card';
      card.innerHTML = `
        <div class="agent-card-name" style="color:${meta.color}">${meta.label}</div>
        <div class="agent-card-desc">${agent.description}</div>
      `;
      container.appendChild(card);
    });
  } catch {
    // silently fail — not critical
  }
}

// ── UI helpers ─────────────────────────────────────────────────────────────────
function togglePipeline() {
  document.getElementById('pipelinePanel').classList.toggle('collapsed');
}

function clearChat() {
  const msgs = document.getElementById('messages');
  msgs.innerHTML = '';
  msgs.appendChild(createWelcome());
  clearTrace();
  resetArchNodes();
  setAgentIndicator('');
}

function createWelcome() {
  const div = document.createElement('div');
  div.id = 'welcome';
  div.className = 'welcome';
  div.innerHTML = `
    <div class="welcome-title">What would you like to analyse?</div>
    <div class="welcome-sub">Ask anything about capacity, yield, maintenance, forecasts, or CapEx.</div>
    <div class="suggestions">
      <button class="suggestion" onclick="sendSuggestion(this)">Which sites have CRITICAL bottlenecks?</button>
      <button class="suggestion" onclick="sendSuggestion(this)">What drives yield loss for OTA tests?</button>
      <button class="suggestion" onclick="sendSuggestion(this)">Show HIGH maintenance risk equipment</button>
      <button class="suggestion" onclick="sendSuggestion(this)">What is the P80 CapEx for OTA testers?</button>
      <button class="suggestion" onclick="sendSuggestion(this)">Demand forecast for next 6 months</button>
    </div>
  `;
  return div;
}

function clearTrace() {
  const log = document.getElementById('traceLog');
  log.innerHTML = '<div class="trace-empty">Ask a question to see the pipeline trace.</div>';
}

function resetArchNodes() {
  ['arch-router','arch-agent','arch-mcp','arch-duckdb','arch-ollama'].forEach(id => {
    const el = document.getElementById(id);
    if (el) {
      el.classList.remove('active','pulsing');
      const badge = el.querySelector('.arch-badge');
      if (badge) { badge.textContent = ''; badge.classList.remove('visible'); }
    }
  });
}

function activateArchNode(nodeId, badgeText = '') {
  resetArchNodes();
  const el = document.getElementById(nodeId);
  if (!el) return;
  el.classList.add('active', 'pulsing');
  const badge = el.querySelector('.arch-badge');
  if (badge && badgeText) {
    badge.textContent = badgeText;
    badge.classList.add('visible');
  }
}

function setArchNodeDone(nodeId, badgeText = '') {
  const el = document.getElementById(nodeId);
  if (!el) return;
  el.classList.remove('pulsing');
  el.classList.add('active');
  const badge = el.querySelector('.arch-badge');
  if (badge && badgeText) {
    badge.textContent = badgeText;
    badge.classList.add('visible');
  }
}

function addTrace(step, detail) {
  const log = document.getElementById('traceLog');
  const empty = log.querySelector('.trace-empty');
  if (empty) empty.remove();

  const item = document.createElement('div');
  item.className = 'trace-item';
  item.innerHTML = `
    <div class="trace-dot ${step}"></div>
    <div class="trace-text">${escapeHtml(detail)}</div>
  `;
  log.appendChild(item);
  log.scrollTop = log.scrollHeight;
}

function setAgentIndicator(agentName) {
  const el   = document.getElementById('agentIndicator');
  const meta = AGENT_META[agentName] || null;
  if (meta && agentName) {
    el.textContent = meta.label;
    el.className   = `agent-indicator agent--${agentName} visible`;
  } else {
    el.textContent = '';
    el.className   = 'agent-indicator';
  }
}

function setStatus(state) {
  const dot  = document.querySelector('.status-dot');
  const text = document.getElementById('statusText');
  if (state === 'loading') {
    dot.className   = 'status-dot loading';
    text.textContent = 'Thinking…';
  } else if (state === 'online') {
    dot.className   = 'status-dot online';
    text.textContent = 'Connected';
  } else if (state === 'error') {
    dot.className   = 'status-dot error';
    text.textContent = 'Error';
  }
}

// ── Message rendering ──────────────────────────────────────────────────────────
function removeWelcome() {
  const w = document.getElementById('welcome');
  if (w) w.remove();
}

function appendUserMessage(text) {
  removeWelcome();
  const msgs = document.getElementById('messages');
  const msg  = document.createElement('div');
  msg.className = 'msg msg--user';
  msg.innerHTML = `
    <div class="msg-avatar">U</div>
    <div class="msg-body">
      <div class="msg-content">${escapeHtml(text)}</div>
    </div>
  `;
  msgs.appendChild(msg);
  msgs.scrollTop = msgs.scrollHeight;
}

function appendTypingIndicator() {
  const msgs = document.getElementById('messages');
  const msg  = document.createElement('div');
  msg.className = 'msg msg--ai';
  msg.id = 'typingMsg';
  msg.innerHTML = `
    <div class="msg-avatar">AI</div>
    <div class="msg-body">
      <div class="typing-dots">
        <div class="typing-dot"></div>
        <div class="typing-dot"></div>
        <div class="typing-dot"></div>
      </div>
    </div>
  `;
  msgs.appendChild(msg);
  msgs.scrollTop = msgs.scrollHeight;
}

function removeTypingIndicator() {
  const t = document.getElementById('typingMsg');
  if (t) t.remove();
}

function startAiMessage(agentName) {
  removeTypingIndicator();
  const msgs = document.getElementById('messages');
  const meta = AGENT_META[agentName] || AGENT_META.unknown;

  const msg = document.createElement('div');
  msg.className = 'msg msg--ai';
  msg.innerHTML = `
    <div class="msg-avatar">AI</div>
    <div class="msg-body">
      <div class="msg-agent-tag agent--${agentName}">
        <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5">
          <circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3"/>
        </svg>
        ${escapeHtml(meta.label)}
      </div>
      <div class="msg-content" id="aiContent"></div>
      <div class="msg-tools" id="aiTools"></div>
    </div>
  `;
  msgs.appendChild(msg);
  currentAiMsg = msg;
  msgs.scrollTop = msgs.scrollHeight;
}

function appendToken(token) {
  const content = document.getElementById('aiContent');
  if (!content) return;
  currentAnswer += token;
  content.innerHTML = formatAnswer(currentAnswer);
  const msgs = document.getElementById('messages');
  msgs.scrollTop = msgs.scrollHeight;
}

function finalizeAiMessage(toolsUsed) {
  const toolsDiv = document.getElementById('aiTools');
  if (!toolsDiv || !toolsUsed?.length) return;
  toolsDiv.innerHTML = toolsUsed.map(t => `
    <div class="tool-chip">
      <div class="tool-chip-dot"></div>
      ${escapeHtml(t)}
    </div>
  `).join('');
}

// ── Answer formatter (basic markdown → HTML) ───────────────────────────────────
function formatAnswer(text) {
  return text
    // Bold
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    // Inline code
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    // Bullet lines
    .replace(/^[*•]\s+(.+)$/gm, '<li>$1</li>')
    // Wrap consecutive <li> in <ul>
    .replace(/(<li>.*<\/li>(\n|$))+/g, m => `<ul>${m}</ul>`)
    // Line breaks → paragraphs (double newline)
    .split(/\n\n+/)
    .map(p => p.trim())
    .filter(Boolean)
    .map(p => p.startsWith('<ul>') ? p : `<p>${p.replace(/\n/g, '<br>')}</p>`)
    .join('');
}

// ── Send flow ──────────────────────────────────────────────────────────────────
function sendSuggestion(btn) {
  document.getElementById('questionInput').value = btn.textContent;
  sendQuestion();
}

function handleKey(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendQuestion();
  }
}

function autoResize(el) {
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 160) + 'px';
}

async function sendQuestion() {
  if (isStreaming) return;

  const input    = document.getElementById('questionInput');
  const sendBtn  = document.getElementById('sendBtn');
  const question = input.value.trim();
  if (!question) return;

  // Reset
  input.value = '';
  input.style.height = 'auto';
  isStreaming  = true;
  currentAnswer = '';
  currentAiMsg  = null;
  sendBtn.disabled = true;
  clearTrace();
  resetArchNodes();

  setStatus('loading');
  appendUserMessage(question);
  appendTypingIndicator();

  try {
    const response = await fetch(`${API}/api/chat/stream`, {
      method:  'POST',
      headers: { 'Content-Type': 'application/json' },
      body:    JSON.stringify({ question }),
    });

    if (!response.ok) throw new Error(`HTTP ${response.status}`);

    const reader  = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let agentName  = 'unknown';
    let toolsUsed  = [];
    let msgStarted = false;

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop();    // keep incomplete line

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        try {
          const event = JSON.parse(line.slice(6));
          handleSSEEvent(event);

          if (event.type === 'pipeline') {
            const step = event.data.step;

            if (step === 'router') {
              agentName = event.data.agent;
              setAgentIndicator(agentName);
              activateArchNode('arch-router', agentName.toUpperCase());
              addTrace('router', `→ ${(AGENT_META[agentName] || AGENT_META.unknown).label}`);
            }

            if (step === 'tool_selection') {
              setArchNodeDone('arch-router', agentName.toUpperCase());
              activateArchNode('arch-agent', event.data.detail.match(/\d+/)?.[0] + ' tools');
              addTrace('tool_selection', event.data.detail);
              if (!msgStarted) {
                startAiMessage(agentName);
                msgStarted = true;
              }
            }

            if (step === 'mcp_tool') {
              setArchNodeDone('arch-agent');
              activateArchNode('arch-mcp', event.data.tool);
              setTimeout(() => {
                setArchNodeDone('arch-mcp');
                activateArchNode('arch-duckdb', event.data.row_count + ' rows');
              }, 300);
              toolsUsed.push(event.data.tool);
              addTrace('mcp_tool', `${event.data.tool} → ${event.data.row_count} rows`);
            }

            if (step === 'synthesis') {
              setArchNodeDone('arch-duckdb');
              activateArchNode('arch-ollama', 'llama3.1:8b');
              addTrace('synthesis', 'Synthesizing via Ollama llama3.1:8b…');
            }
          }

          if (event.type === 'token') {
            if (!msgStarted) {
              startAiMessage(agentName);
              msgStarted = true;
            }
            appendToken(event.data);
          }

          if (event.type === 'done') {
            setArchNodeDone('arch-ollama', '✓');
            finalizeAiMessage(event.data.tools_called);
            addTrace('synthesis', `Done · ${event.data.tool_count} tool(s) called`);
          }

          if (event.type === 'error') {
            removeTypingIndicator();
            appendErrorMessage(event.data);
            addTrace('error', event.data);
          }

        } catch { /* skip malformed lines */ }
      }
    }

  } catch (err) {
    removeTypingIndicator();
    appendErrorMessage(err.message);
    setStatus('error');
  } finally {
    isStreaming = false;
    sendBtn.disabled = false;
    setStatus('online');
  }
}

function handleSSEEvent(event) {
  // extensible hook — called for every parsed SSE event
}

function appendErrorMessage(text) {
  const msgs = document.getElementById('messages');
  const msg  = document.createElement('div');
  msg.className = 'msg msg--ai';
  msg.innerHTML = `
    <div class="msg-avatar" style="color:#ef5350;border-color:#ef5350">!</div>
    <div class="msg-body">
      <div class="msg-content" style="border-color:rgba(239,83,80,0.3);color:#ef5350">
        ${escapeHtml(text)}
      </div>
    </div>
  `;
  msgs.appendChild(msg);
  msgs.scrollTop = msgs.scrollHeight;
}

function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}
