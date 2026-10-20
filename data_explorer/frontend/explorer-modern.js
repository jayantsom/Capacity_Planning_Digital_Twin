'use strict';

const API = '/explorer/api';
const LAYERS = ['raw', 'bronze', 'silver', 'gold'];
const FILTER_PRIORITY = [
  'site_code', 'site_id', 'factory_code', 'product_number', 'product_id',
  'test_type', 'test_type_id', 'month_key', 'month', 'snapshot_id',
  'capacity_mode', 'bottleneck_severity', 'risk_tier', 'anomaly_severity',
  'platform', 'product_family', 'region', 'supplier_name', 'equipment_id',
  'equipment_type', 'product_status', 'retest_type',
];
const state = {
  sources: [],
  source: null,
  sourceLabel: '',
  table: null,
  layer: null,
  schema: [],
  rows: [],
  total: 0,
  pages: 1,
  page: 1,
  pageSize: 100,
  filters: {},
  sortColumn: null,
  sortDirection: 'asc',
};

const ui = {
  sourceStatus: document.getElementById('sourceStatus'),
  catalogStatus: document.getElementById('catalogStatus'),
  navigation: document.getElementById('layerNavigation'),
  filterForm: document.getElementById('filterForm'),
  activeFilters: document.getElementById('activeFilters'),
  tableState: document.getElementById('tableState'),
  tableRegion: document.getElementById('tableRegion'),
  tableScroll: document.getElementById('tableScroll'),
  tableHead: document.getElementById('tableHead'),
  tableBody: document.getElementById('tableBody'),
  pagination: document.getElementById('pagination'),
};

function node(tag, className, text) {
  const item = document.createElement(tag);
  if (className) item.className = className;
  if (text !== undefined) item.textContent = text;
  return item;
}

async function jsonRequest(url, options) {
  const response = await fetch(url, { headers: { Accept: 'application/json', ...(options?.headers || {}) }, ...options });
  let data;
  try { data = await response.json(); } catch { data = {}; }
  if (!response.ok) throw new Error(data.detail || data.error || `Request failed (${response.status})`);
  return data;
}

function setSourceStatus(kind, label) {
  ui.sourceStatus.className = `service-status status-${kind}`;
  ui.sourceStatus.firstElementChild.textContent = kind === 'ready' ? '●' : ['degraded', 'no-sources'].includes(kind) ? '▲' : '×';
  ui.sourceStatus.lastElementChild.textContent = label;
}

function normaliseSources(sources) {
  const layers = Object.fromEntries(LAYERS.map((layer) => [layer, []]));
  sources.forEach((source) => {
    if (source.layer === 'multi' && source.layers) {
      Object.entries(source.layers).forEach(([layer, metadata]) => {
        (metadata.tables || []).forEach((table) => layers[layer]?.push({
          source: source.id, sourceLabel: source.label || source.id, table: table.name, layer,
        }));
      });
    } else {
      (source.tables || []).forEach((table) => layers.raw.push({
        source: source.id, sourceLabel: source.label || source.id, table: table.name, layer: 'raw',
      }));
    }
  });
  return layers;
}

function buildCatalog(sources) {
  ui.navigation.replaceChildren();
  const layers = normaliseSources(sources);
  LAYERS.forEach((layer) => {
    const section = node('section', 'layer-section');
    const toggle = node('button', `layer-toggle layer-${layer}`);
    toggle.type = 'button';
    toggle.setAttribute('aria-expanded', 'true');
    const dot = node('span', 'layer-dot');
    dot.setAttribute('aria-hidden', 'true');
    const name = node('span', '', `${layer[0].toUpperCase()}${layer.slice(1)} layer`);
    const count = node('span', 'count', String(layers[layer].length));
    const list = node('div', 'table-list');
    toggle.append(dot, name, count);
    toggle.addEventListener('click', () => {
      const expanded = toggle.getAttribute('aria-expanded') === 'true';
      toggle.setAttribute('aria-expanded', String(!expanded));
      list.hidden = expanded;
    });
    if (!layers[layer].length) {
      list.append(node('p', 'layer-empty', 'No tables published'));
    } else {
      layers[layer].forEach((entry) => {
        const button = node('button', 'table-link', entry.table);
        button.type = 'button';
        button.title = `${entry.sourceLabel} → ${entry.table}`;
        button.dataset.source = entry.source;
        button.dataset.table = entry.table;
        button.addEventListener('click', () => void selectTable(entry, button));
        list.append(button);
      });
    }
    section.append(toggle, list);
    ui.navigation.append(section);
  });
}

async function initialise() {
  try {
    const sources = await jsonRequest(`${API}/sources`);
    state.sources = Array.isArray(sources) ? sources : [];
    buildCatalog(state.sources);
    ui.catalogStatus.textContent = state.sources.length
      ? `${state.sources.length} promoted source${state.sources.length === 1 ? '' : 's'} available`
      : 'NO SOURCES';
    setSourceStatus(state.sources.length ? 'ready' : 'no-sources', state.sources.length ? 'READY' : 'NO SOURCES');
  } catch (error) {
    ui.catalogStatus.textContent = 'Source catalog unavailable. Retry by reloading the page.';
    ui.catalogStatus.classList.add('error');
    ui.navigation.replaceChildren(node('p', 'layer-empty', error.message));
    setSourceStatus('offline', 'OFFLINE');
  }
}

function encodePath(value) {
  return encodeURIComponent(String(value));
}

async function selectTable(entry, button) {
  document.querySelectorAll('.table-link').forEach((item) => item.classList.remove('active'));
  button.classList.add('active');
  state.source = entry.source;
  state.sourceLabel = entry.sourceLabel;
  state.table = entry.table;
  state.layer = entry.layer;
  state.page = 1;
  state.filters = {};
  state.sortColumn = null;
  state.sortDirection = 'asc';
  showLoading(`Loading ${entry.table}…`);
  closeDrawers();

  const base = `${encodePath(entry.source)}/${encodePath(entry.table)}`;
  try {
    const [schema, data] = await Promise.all([
      jsonRequest(`${API}/schema/${base}`),
      jsonRequest(`${API}/data/${base}?page=1&page_size=${state.pageSize}`),
    ]);
    state.schema = schema.columns || [];
    applyDataResponse(data);
    updateTableIdentity();
    updateSummary();
    renderSchema();
    buildFilters();
    updateChartSelectors();
    document.getElementById('schemaButton').disabled = false;
    document.getElementById('exportButton').disabled = false;
    document.getElementById('chartButton').disabled = false;
    document.getElementById('sqlEditor').value = `SELECT *\nFROM ${entry.table}\nLIMIT 100`;
  } catch (error) {
    showState('Unable to load table', error.message, 'error');
  }
}

function applyDataResponse(data) {
  state.rows = data.rows || [];
  state.total = Number(data.total ?? data.row_count ?? state.rows.length);
  state.pages = Math.max(1, Number(data.total_pages || Math.ceil(state.total / state.pageSize) || 1));
  renderTable();
  updatePagination();
}

function updateTableIdentity() {
  document.getElementById('tableTitle').textContent = state.table;
  document.getElementById('tableContext').textContent = `${state.sourceLabel} · read-only records`;
  document.getElementById('tableCaption').textContent = `${state.table} records`;
  const badge = document.getElementById('layerBadge');
  badge.hidden = false;
  badge.className = `layer-badge layer-${state.layer}`;
  badge.textContent = state.layer;
}

function updateSummary() {
  document.getElementById('kpiStrip').hidden = false;
  document.getElementById('kpiTotal').textContent = state.total.toLocaleString();
  document.getElementById('kpiColumns').textContent = String(state.schema.length);
  document.getElementById('kpiSource').textContent = state.sourceLabel || state.source;
  document.getElementById('kpiPage').textContent = `${state.page} / ${state.pages}`;
  document.getElementById('kpiFreshness').textContent = new Intl.DateTimeFormat([], { hour: '2-digit', minute: '2-digit' }).format(new Date());
}

function showLoading(label) {
  ui.tableRegion.setAttribute('aria-busy', 'true');
  ui.tableScroll.hidden = true;
  ui.tableState.hidden = false;
  ui.tableState.className = 'state-panel';
  ui.tableState.replaceChildren(node('strong', '', label), node('div', 'loading-block'));
}

function showState(title, message, kind = '') {
  ui.tableRegion.setAttribute('aria-busy', 'false');
  ui.tableScroll.hidden = true;
  ui.tableState.hidden = false;
  ui.tableState.className = `state-panel ${kind}`;
  ui.tableState.replaceChildren(node('strong', '', title), node('p', '', message));
}

function columnNames() {
  return state.schema.length ? state.schema.map((column) => column.name) : Object.keys(state.rows[0] || {});
}

function numericColumns() {
  return new Set(state.schema.filter((column) => /int|double|float|decimal|bigint|hugeint|numeric/i.test(column.type || '')).map((column) => column.name));
}

function formatNumber(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return String(value);
  if (Number.isInteger(number)) return number.toLocaleString();
  if (Math.abs(number) < 1) return number.toLocaleString(undefined, { maximumFractionDigits: 4 });
  return number.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function renderTable() {
  ui.tableRegion.setAttribute('aria-busy', 'false');
  if (!state.rows.length) {
    showState('No matching rows', Object.keys(state.filters).length ? 'Clear or change the active filters and try again.' : 'This table is currently empty.');
    return;
  }
  const columns = columnNames();
  const numeric = numericColumns();
  const headerRow = document.createElement('tr');
  columns.forEach((column) => {
    const cell = document.createElement('th');
    cell.scope = 'col';
    const sort = node('button');
    sort.type = 'button';
    sort.append(document.createTextNode(column), node('span', '', state.sortColumn === column ? (state.sortDirection === 'asc' ? '▲' : '▼') : '↕'));
    sort.setAttribute('aria-label', `Sort by ${column}${state.sortColumn === column ? `, currently ${state.sortDirection}` : ''}`);
    sort.addEventListener('click', () => void sortBy(column));
    cell.append(sort);
    headerRow.append(cell);
  });
  ui.tableHead.replaceChildren(headerRow);
  const fragment = document.createDocumentFragment();
  state.rows.forEach((row) => {
    const tableRow = document.createElement('tr');
    columns.forEach((column) => {
      const cell = document.createElement('td');
      const value = row[column];
      if (value === null || value === undefined) {
        cell.className = 'null';
        cell.textContent = 'null';
      } else {
        cell.textContent = numeric.has(column) ? formatNumber(value) : String(value);
        if (numeric.has(column)) cell.classList.add('numeric');
        cell.title = String(value);
      }
      tableRow.append(cell);
    });
    fragment.append(tableRow);
  });
  ui.tableBody.replaceChildren(fragment);
  ui.tableState.hidden = true;
  ui.tableScroll.hidden = false;
}

async function loadData() {
  if (!state.source || !state.table) return;
  showLoading('Refreshing records…');
  const filters = encodeURIComponent(JSON.stringify(state.filters));
  const sort = state.sortColumn
    ? `&sort_col=${encodeURIComponent(state.sortColumn)}&sort_dir=${state.sortDirection}`
    : '';
  const base = `${encodePath(state.source)}/${encodePath(state.table)}`;
  try {
    const data = await jsonRequest(`${API}/data/${base}?page=${state.page}&page_size=${state.pageSize}&filters=${filters}${sort}`);
    applyDataResponse(data);
    updateSummary();
  } catch (error) {
    showState('Unable to refresh records', error.message, 'error');
  }
}

async function sortBy(column) {
  if (state.sortColumn === column) state.sortDirection = state.sortDirection === 'asc' ? 'desc' : 'asc';
  else {
    state.sortColumn = column;
    state.sortDirection = 'asc';
  }
  state.page = 1;
  await loadData();
}

function isCategorical(column) {
  return /varchar|text|char|string/i.test(column.type || '');
}

function filterCandidates() {
  const names = state.schema.map((column) => column.name);
  return FILTER_PRIORITY.filter((name) => names.includes(name))
    .concat(state.schema.filter(isCategorical).map((column) => column.name).filter((name) => !FILTER_PRIORITY.includes(name)))
    .slice(0, 6);
}

function buildFilters() {
  ui.filterForm.replaceChildren();
  const candidates = filterCandidates();
  if (!candidates.length) {
    ui.filterForm.append(node('p', 'empty-state', 'No categorical filters were detected for this table.'));
    return;
  }
  candidates.forEach((column) => {
    const group = node('div', 'filter-group');
    const label = node('label', '', column.replaceAll('_', ' '));
    const select = document.createElement('select');
    select.dataset.column = column;
    label.htmlFor = `filter-${column}`;
    select.id = `filter-${column}`;
    select.append(new Option(`All ${column.replaceAll('_', ' ')}`, ''));
    group.append(label, select);
    ui.filterForm.append(group);
    const base = `${encodePath(state.source)}/${encodePath(state.table)}/${encodePath(column)}`;
    void jsonRequest(`${API}/distinct/${base}?limit=150`)
      .then((data) => {
        (data.values || []).forEach((value) => select.append(new Option(value === null ? '(null)' : String(value), value === null ? '' : String(value))));
      })
      .catch(() => {
        select.disabled = true;
        select.firstElementChild.textContent = 'Values unavailable';
      });
  });
}

function applyFilters() {
  state.filters = {};
  ui.filterForm.querySelectorAll('select[data-column]').forEach((select) => {
    if (select.value) state.filters[select.dataset.column] = select.value;
  });
  state.page = 1;
  renderActiveFilters();
  void loadData();
}

function clearFilters() {
  ui.filterForm.querySelectorAll('select[data-column]').forEach((select) => { select.value = ''; });
  state.filters = {};
  state.page = 1;
  renderActiveFilters();
  void loadData();
}

function renderActiveFilters() {
  ui.activeFilters.replaceChildren();
  const entries = Object.entries(state.filters);
  if (!entries.length) {
    ui.activeFilters.append(node('span', '', 'No active filters'));
    return;
  }
  entries.forEach(([column, value]) => ui.activeFilters.append(node('span', 'filter-chip', `${column}: ${value}`)));
}

function updatePagination() {
  ui.pagination.hidden = false;
  const start = state.total ? ((state.page - 1) * state.pageSize) + 1 : 0;
  const end = Math.min(state.page * state.pageSize, state.total);
  document.getElementById('pageInfo').textContent = `${start.toLocaleString()}–${end.toLocaleString()} of ${state.total.toLocaleString()} rows`;
  document.getElementById('previousPage').disabled = state.page <= 1;
  document.getElementById('nextPage').disabled = state.page >= state.pages;
}

function renderSchema() {
  const grid = document.getElementById('schemaGrid');
  grid.replaceChildren();
  state.schema.forEach((column) => {
    const item = node('div', 'schema-item');
    item.append(node('span', '', column.name), node('span', '', column.type || 'unknown'));
    grid.append(item);
  });
}

function setSelectOptions(select, values, preferred) {
  select.replaceChildren();
  values.forEach((value) => {
    const option = new Option(value, value);
    option.selected = value === preferred;
    select.append(option);
  });
}

function updateChartSelectors() {
  const columns = columnNames();
  const numeric = [...numericColumns()];
  setSelectOptions(document.getElementById('chartX'), columns, columns.find((column) => !numeric.includes(column)) || columns[0]);
  setSelectOptions(document.getElementById('chartY'), numeric, numeric[0]);
}

function renderChart() {
  const canvas = document.getElementById('chartCanvas');
  const xColumn = document.getElementById('chartX').value;
  const yColumn = document.getElementById('chartY').value;
  canvas.replaceChildren();
  if (!xColumn || !yColumn || !state.rows.length) {
    canvas.append(node('p', 'empty-state', 'Choose a numeric Y axis to chart the current page.'));
    return;
  }
  const values = state.rows.slice(0, 60).map((row) => Number(row[yColumn])).filter(Number.isFinite);
  const maximum = Math.max(...values.map(Math.abs), 1);
  state.rows.slice(0, 60).forEach((row) => {
    const value = Number(row[yColumn]);
    if (!Number.isFinite(value)) return;
    const bar = node('span', 'chart-bar');
    bar.style.height = `${Math.max(2, (Math.abs(value) / maximum) * 140)}px`;
    bar.title = `${row[xColumn]}: ${formatNumber(value)}`;
    bar.setAttribute('aria-hidden', 'true');
    canvas.append(bar);
  });
}

async function runSql() {
  const editor = document.getElementById('sqlEditor');
  const status = document.getElementById('sqlStatus');
  const sql = editor.value.trim();
  if (!sql) {
    status.textContent = 'Enter a query first.';
    status.className = 'error';
    return;
  }
  const source = state.source || state.sources.find((item) => item.layer === 'multi')?.id || state.sources[0]?.id;
  if (!source) {
    status.textContent = 'No data source is available.';
    status.className = 'error';
    return;
  }
  status.textContent = 'Running query…';
  status.className = '';
  try {
    const data = await jsonRequest(`${API}/query/${encodePath(source)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sql, limit: 500 }),
    });
    state.schema = (data.columns || []).map((name) => ({ name, type: '' }));
    state.rows = data.rows || [];
    state.total = Number(data.row_count || state.rows.length);
    state.pages = 1;
    state.page = 1;
    renderTable();
    renderSchema();
    updateChartSelectors();
    updateSummary();
    updatePagination();
    status.textContent = `${state.total.toLocaleString()} rows returned.`;
    status.className = 'success';
  } catch (error) {
    status.textContent = error.message;
    status.className = 'error';
  }
}

function exportCsv() {
  if (!state.rows.length) return;
  const columns = columnNames();
  const quote = (value) => {
    if (value === null || value === undefined) return '';
    const text = String(value);
    return /[",\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
  };
  const csv = [columns.map(quote).join(','), ...state.rows.map((row) => columns.map((column) => quote(row[column])).join(','))].join('\n');
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = `${state.table || 'query-results'}.csv`;
  link.click();
  URL.revokeObjectURL(url);
}

function toggleUtility(panelId) {
  const panel = document.getElementById(panelId);
  const willOpen = panel.hidden;
  document.querySelectorAll('.utility-panel').forEach((item) => { item.hidden = true; });
  panel.hidden = !willOpen;
  if (willOpen && panelId === 'chartPanel') renderChart();
  if (willOpen && panelId === 'sqlPanel') document.getElementById('sqlEditor').focus();
}

function toggleSourcePanel() {
  const sidebar = document.getElementById('sidebar');
  if (window.matchMedia('(min-width: 801px)').matches) {
    const closed = sidebar.classList.toggle('closed');
    updateSourceToggle(!closed);
    return;
  }
  const open = !sidebar.classList.contains('open');
  sidebar.classList.toggle('open', open);
  sidebar.classList.toggle('closed', !open);
  updateSourceToggle(open);
  document.getElementById('scrim').hidden = !open;
}

function updateSourceToggle(expanded) {
  const toggle = document.getElementById('sourceToggle');
  const action = expanded ? 'Collapse' : 'Expand';
  toggle.setAttribute('aria-expanded', String(expanded));
  toggle.setAttribute('aria-label', `${action} data catalog`);
  toggle.title = `${action} data catalog`;
  toggle.firstElementChild.textContent = expanded ? '‹' : '›';
}

function closeDrawers() {
  const sidebar = document.getElementById('sidebar');
  if (window.matchMedia('(max-width: 800px)').matches) {
    sidebar.classList.remove('open');
    sidebar.classList.add('closed');
  }
  const expanded = !sidebar.classList.contains('closed');
  updateSourceToggle(expanded);
  document.getElementById('scrim').hidden = true;
}

function toggleFilterPanel() {
  const panel = document.getElementById('filterPanel');
  const closed = panel.classList.toggle('closed');
  document.getElementById('filterToggle').setAttribute('aria-expanded', String(!closed));
}

ui.filterForm.addEventListener('submit', (event) => { event.preventDefault(); applyFilters(); });
document.getElementById('clearFilters').addEventListener('click', clearFilters);
document.getElementById('previousPage').addEventListener('click', () => { if (state.page > 1) { state.page -= 1; void loadData(); } });
document.getElementById('nextPage').addEventListener('click', () => { if (state.page < state.pages) { state.page += 1; void loadData(); } });
document.getElementById('pageSize').addEventListener('change', (event) => {
  state.pageSize = Number(event.target.value);
  state.page = 1;
  void loadData();
});
document.getElementById('schemaButton').addEventListener('click', () => toggleUtility('schemaPanel'));
document.getElementById('chartButton').addEventListener('click', () => toggleUtility('chartPanel'));
document.getElementById('sqlButton').addEventListener('click', () => toggleUtility('sqlPanel'));
document.getElementById('exportButton').addEventListener('click', exportCsv);
document.getElementById('runSql').addEventListener('click', () => void runSql());
document.getElementById('sqlEditor').addEventListener('keydown', (event) => {
  if ((event.ctrlKey || event.metaKey) && event.key === 'Enter') {
    event.preventDefault();
    void runSql();
  }
});
document.getElementById('chartX').addEventListener('change', renderChart);
document.getElementById('chartY').addEventListener('change', renderChart);
document.querySelectorAll('[data-close-panel]').forEach((button) => button.addEventListener('click', () => {
  document.getElementById(button.dataset.closePanel).hidden = true;
}));
document.getElementById('sourceToggle').addEventListener('click', toggleSourcePanel);
document.getElementById('filterToggle').addEventListener('click', toggleFilterPanel);
document.getElementById('scrim').addEventListener('click', closeDrawers);

const compactLayout = window.matchMedia('(max-width: 800px)');
function syncResponsivePanels() {
  const sidebar = document.getElementById('sidebar');
  sidebar.classList.remove('open');
  sidebar.classList.add('closed');
  updateSourceToggle(false);
  document.getElementById('scrim').hidden = true;
}
compactLayout.addEventListener('change', syncResponsivePanels);
syncResponsivePanels();

void initialise();
