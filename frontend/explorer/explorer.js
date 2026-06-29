/* explorer.js — Data Explorer full application logic */

const API = '/explorer/api';

// ── State ──────────────────────────────────────────────────────────────────────
const state = {
  sources:      [],
  activeSource: null,
  activeTable:  null,
  activeLayer:  null,
  schema:       [],
  data:         [],
  total:        0,
  totalPages:   1,
  page:         1,
  pageSize:     100,
  filters:      {},
  sortCol:      null,
  sortDir:      'asc',
  chartInstance: null,
  chartVisible:  false,
  sqlVisible:    false,
};

// ── Theme ──────────────────────────────────────────────────────────────────────
document.getElementById('themeToggle').addEventListener('click', () => {
  const html = document.documentElement;
  const next = html.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
  html.setAttribute('data-theme', next);
  localStorage.setItem('explorer-theme', next);
  if (state.chartInstance) renderChart();
});

// Restore saved theme
const savedTheme = localStorage.getItem('explorer-theme');
if (savedTheme) document.documentElement.setAttribute('data-theme', savedTheme);

// ── Init ───────────────────────────────────────────────────────────────────────
async function init() {
  try {
    const res  = await fetch(`${API}/sources`);
    state.sources = await res.json();
    buildSidebar(state.sources);
  } catch (e) {
    console.error('Failed to load sources:', e);
  }
}

// ── Sidebar ────────────────────────────────────────────────────────────────────
function buildSidebar(sources) {
  const layers = { raw: [], bronze: [], silver: [], gold: [] };

  sources.forEach(src => {
    if (src.layer === 'multi' && src.layers) {
      // DuckDB — grouped by sub-layer
      Object.entries(src.layers).forEach(([lyr, meta]) => {
        meta.tables.forEach(t => {
          layers[lyr]?.push({ source: src.id, table: t.name, layer: lyr, sourceLabel: src.label });
        });
      });
    } else {
      // SQLite raw sources
      (src.tables || []).forEach(t => {
        layers.raw.push({ source: src.id, table: t.name, layer: 'raw', sourceLabel: src.label });
      });
    }
  });

  // Populate each layer section
  const LAYER_COLORS = { raw: '#6e7681', bronze: '#b45309', silver: '#64748b', gold: '#d97706' };
  Object.entries(layers).forEach(([lyr, tables]) => {
    const countEl = document.getElementById(`${lyr}-count`);
    const itemsEl = document.getElementById(`${lyr}-items`);
    if (!countEl || !itemsEl) return;
    countEl.textContent = tables.length;
    itemsEl.innerHTML = '';

    if (tables.length === 0) {
      itemsEl.innerHTML = '<div class="nav-loading">No tables</div>';
      return;
    }

    tables.forEach(({ source, table, layer }) => {
      const item = document.createElement('div');
      item.className = 'nav-item';
      item.dataset.source = source;
      item.dataset.table  = table;
      item.dataset.layer  = layer;
      item.title = `${source} → ${table}`;

      // Icon dot matching layer color
      const dot = `<span style="width:6px;height:6px;border-radius:50%;background:${LAYER_COLORS[lyr]};flex-shrink:0;display:inline-block"></span>`;
      item.innerHTML = `${dot}<span style="overflow:hidden;text-overflow:ellipsis">${table}</span>`;

      item.addEventListener('click', () => selectTable(source, table, layer, item));
      itemsEl.appendChild(item);
    });
  });

  // Open gold by default
  toggleSection('gold', false);
  toggleSection('silver', false);
  toggleSection('bronze', false);
  toggleSection('raw', false);
}

function toggleSection(layer, forceState) {
  const items   = document.getElementById(`${layer}-items`);
  const chevron = document.getElementById(`${layer}-chevron`);
  if (!items) return;

  const isOpen = forceState !== undefined ? forceState : items.classList.contains('collapsed');
  items.classList.toggle('collapsed', !isOpen);
  chevron?.classList.toggle('open', isOpen);
  chevron?.classList.toggle('closed', !isOpen);
}

// ── Table selection ────────────────────────────────────────────────────────────
async function selectTable(sourceId, tableName, layer, navItem) {
  // Highlight nav item
  document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
  navItem?.classList.add('active');

  state.activeSource = sourceId;
  state.activeTable  = tableName;
  state.activeLayer  = layer;
  state.page         = 1;
  state.filters      = {};
  state.sortCol      = null;
  state.sortDir      = 'asc';

  // Breadcrumb
  document.getElementById('bcCurrent').textContent = tableName;

  // Load schema + data in parallel
  showLoading(true);
  try {
    const [schemaRes, dataRes] = await Promise.all([
      fetch(`${API}/schema/${sourceId}/${tableName}`).then(r => r.json()),
      fetch(`${API}/data/${sourceId}/${tableName}?page=1&page_size=${state.pageSize}`).then(r => r.json()),
    ]);

    state.schema     = schemaRes.columns || [];
    state.total      = dataRes.total || 0;
    state.totalPages = dataRes.total_pages || 1;
    state.data       = dataRes.rows || [];

    updateKPIs(schemaRes);
    buildFilters(schemaRes.columns, sourceId, tableName);
    renderTable(state.data, state.schema, layer);
    updatePagination();

    // Enable action buttons
    document.getElementById('btnExport').disabled = false;
    document.getElementById('btnChart').disabled  = false;

    // Pre-fill SQL editor
    const editor = document.getElementById('sqlEditor');
    if (editor && !editor.value) {
      editor.value = `SELECT *\nFROM ${tableName}\nLIMIT 100`;
    }

    // Update chart column selectors
    updateChartSelectors(state.schema);

    // Re-render chart if visible
    if (state.chartVisible) renderChart();

  } catch (e) {
    showError(`Failed to load ${tableName}: ${e.message}`);
  } finally {
    showLoading(false);
  }
}

// ── KPIs ───────────────────────────────────────────────────────────────────────
function updateKPIs(schema) {
  const LAYER_COLORS = { raw: '#6e7681', bronze: '#b45309', silver: '#64748b', gold: '#d97706' };
  const lyr   = schema.layer || state.activeLayer || 'raw';
  const color = LAYER_COLORS[lyr] || '#8b949e';

  document.getElementById('kpiTotal').textContent  = state.total.toLocaleString();
  document.getElementById('kpiCols').textContent   = (schema.columns || []).length;
  document.getElementById('kpiLayer').textContent  = lyr.toUpperCase();
  document.getElementById('kpiLayer').style.color  = color;
  document.getElementById('kpiSource').textContent = state.activeSource?.replace('raw_', '') || '–';
  document.getElementById('kpiPage').textContent   = `${state.page} / ${state.totalPages}`;
  document.getElementById('kpiStrip').style.display = 'flex';
}

// ── Filters ────────────────────────────────────────────────────────────────────
const FILTER_COLS_PRIORITY = [
  'site_code','site_id','factory_code','product_number','product_id',
  'test_type','test_type_id','month_key','month','snapshot_id',
  'capacity_mode','bottleneck_severity','risk_tier','anomaly_severity',
  'platform','product_family','region','supplier_name','equipment_id',
  'equipment_type','product_status','retest_type',
];

function buildFilters(columns, sourceId, tableName) {
  const body = document.getElementById('filterBody');
  body.innerHTML = '';

  // Pick columns to show as filters (priority list + categorical columns)
  const colNames = columns.map(c => c.name);
  const filterCols = FILTER_COLS_PRIORITY.filter(c => colNames.includes(c))
    .concat(colNames.filter(c => !FILTER_COLS_PRIORITY.includes(c) && isLikelyCategorical(c, columns)));

  const shown = filterCols.slice(0, 12);  // max 12 filter groups

  if (shown.length === 0) {
    body.innerHTML = '<div class="filter-empty">No filterable columns detected.</div>';
    return;
  }

  shown.forEach(col => {
    const group = document.createElement('div');
    group.className = 'filter-group';

    const colType = columns.find(c => c.name === col)?.type || 'TEXT';
    const isNumeric = /int|double|float|decimal|bigint|hugeint/i.test(colType);

    const label = document.createElement('div');
    label.className = 'filter-label';
    label.textContent = col.replace(/_/g, ' ');

    group.appendChild(label);

    if (isNumeric) {
      // Numeric range inputs
      const row = document.createElement('div');
      row.style.cssText = 'display:flex;gap:6px';

      const minIn = document.createElement('input');
      minIn.type = 'number';
      minIn.className = 'filter-input';
      minIn.placeholder = 'Min';
      minIn.dataset.col = col;
      minIn.dataset.bound = 'min';
      minIn.style.width = '50%';

      const maxIn = document.createElement('input');
      maxIn.type = 'number';
      maxIn.className = 'filter-input';
      maxIn.placeholder = 'Max';
      maxIn.dataset.col = col;
      maxIn.dataset.bound = 'max';
      maxIn.style.width = '50%';

      row.appendChild(minIn);
      row.appendChild(maxIn);
      group.appendChild(row);
    } else {
      // Dropdown with async distinct values
      const sel = document.createElement('select');
      sel.className = 'filter-select';
      sel.dataset.col = col;
      sel.innerHTML = `<option value="">All ${col.replace(/_/g,' ')}…</option>`;

      // Load distinct values async
      fetch(`${API}/distinct/${sourceId}/${tableName}/${col}?limit=150`)
        .then(r => r.json())
        .then(data => {
          (data.values || []).forEach(v => {
            const opt = document.createElement('option');
            opt.value = String(v);
            opt.textContent = v === null ? '(null)' : String(v);
            sel.appendChild(opt);
          });
        })
        .catch(() => {});

      group.appendChild(sel);
    }

    body.appendChild(group);
  });
}

function isLikelyCategorical(colName, columns) {
  const col = columns.find(c => c.name === colName);
  if (!col) return false;
  const t = col.type?.toLowerCase() || '';
  return t.includes('varchar') || t.includes('text') || t.includes('char');
}

function applyFilters() {
  const filters = {};
  const selects = document.querySelectorAll('.filter-select[data-col]');
  selects.forEach(sel => {
    if (sel.value) filters[sel.dataset.col] = sel.value;
  });

  // Numeric filters — skip for now (would need WHERE col BETWEEN min AND max)
  state.filters = filters;
  state.page    = 1;
  loadData();
}

function clearAllFilters() {
  document.querySelectorAll('.filter-select[data-col]').forEach(s => s.value = '');
  document.querySelectorAll('.filter-input[data-col]').forEach(i => i.value = '');
  state.filters = {};
  state.page    = 1;
  loadData();
}

// ── Data loading ───────────────────────────────────────────────────────────────
async function loadData() {
  if (!state.activeSource || !state.activeTable) return;
  showLoading(true);
  try {
    const filtersParam = encodeURIComponent(JSON.stringify(state.filters));
    const sortParam    = state.sortCol
      ? `&sort_col=${encodeURIComponent(state.sortCol)}&sort_dir=${state.sortDir}`
      : '';
    const url = `${API}/data/${state.activeSource}/${state.activeTable}` +
      `?page=${state.page}&page_size=${state.pageSize}&filters=${filtersParam}${sortParam}`;

    const res  = await fetch(url);
    const data = await res.json();

    state.total      = data.total || 0;
    state.totalPages = data.total_pages || 1;
    state.data       = data.rows || [];

    renderTable(state.data, state.schema, state.activeLayer);
    updatePagination();
    document.getElementById('kpiTotal').textContent = state.total.toLocaleString();
    document.getElementById('kpiPage').textContent  = `${state.page} / ${state.totalPages}`;

    if (state.chartVisible) renderChart();
  } catch (e) {
    showError(e.message);
  } finally {
    showLoading(false);
  }
}

// ── Table rendering ────────────────────────────────────────────────────────────
function renderTable(rows, schema, layer) {
  const tableEl = document.getElementById('dataTable');
  const emptyEl = document.getElementById('tableEmpty');
  const head    = document.getElementById('tableHead');
  const body    = document.getElementById('tableBody');

  if (!rows || rows.length === 0) {
    tableEl.style.display = 'none';
    emptyEl.innerHTML = '<svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1" opacity=".3"><rect x="3" y="3" width="18" height="18" rx="2"/></svg><p>No rows match the current filters.</p>';
    emptyEl.style.display = 'flex';
    return;
  }

  emptyEl.style.display  = 'none';
  tableEl.style.display  = 'table';

  const cols = schema.length ? schema.map(c => c.name) : Object.keys(rows[0]);

  // Header
  head.innerHTML = '<tr>' + cols.map(col => {
    const isSorted = state.sortCol === col;
    const icon = isSorted ? (state.sortDir === 'asc' ? '▲' : '▼') : '▲';
    return `<th class="${isSorted ? 'sorted' : ''}" onclick="sortBy('${col}')">
      ${escHtml(col)} <span class="sort-icon">${icon}</span>
    </th>`;
  }).join('') + '</tr>';

  // Detect numeric columns for alignment
  const numericCols = new Set(
    schema.filter(c => /int|double|float|decimal|bigint|hugeint/i.test(c.type || ''))
          .map(c => c.name)
  );

  // Body
  body.innerHTML = rows.map(row => {
    const cells = cols.map(col => {
      const val = row[col];
      if (val === null || val === undefined) return `<td class="null-val">null</td>`;
      const isNum = numericCols.has(col);
      const display = isNum ? fmtNum(val) : escHtml(String(val));
      return `<td class="${isNum ? 'num' : ''}" title="${escHtml(String(val))}">${display}</td>`;
    }).join('');
    return `<tr class="layer-${layer}">${cells}</tr>`;
  }).join('');
}

function fmtNum(val) {
  const n = Number(val);
  if (isNaN(n)) return escHtml(String(val));
  if (Number.isInteger(n) && Math.abs(n) < 1e9) return n.toLocaleString();
  if (Math.abs(n) < 1) return n.toFixed(4);
  return n.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

// ── Sorting ────────────────────────────────────────────────────────────────────
function sortBy(col) {
  if (state.sortCol === col) {
    state.sortDir = state.sortDir === 'asc' ? 'desc' : 'asc';
  } else {
    state.sortCol = col;
    state.sortDir = 'asc';
  }
  state.page = 1;
  loadData();
}

// ── Pagination ─────────────────────────────────────────────────────────────────
function updatePagination() {
  const pg = document.getElementById('pagination');
  pg.style.display = state.totalPages > 1 ? 'flex' : 'flex';

  const start = (state.page - 1) * state.pageSize + 1;
  const end   = Math.min(state.page * state.pageSize, state.total);
  document.getElementById('pageInfo').textContent =
    `${start.toLocaleString()}–${end.toLocaleString()} of ${state.total.toLocaleString()} rows`;

  document.getElementById('btnPrev').disabled = state.page <= 1;
  document.getElementById('btnNext').disabled = state.page >= state.totalPages;
  pg.style.display = 'flex';
}

function changePage(delta) {
  const next = state.page + delta;
  if (next < 1 || next > state.totalPages) return;
  state.page = next;
  loadData();
}

function changePageSize() {
  state.pageSize = parseInt(document.getElementById('pageSizeSelect').value);
  state.page = 1;
  loadData();
}

// ── Chart ──────────────────────────────────────────────────────────────────────
function toggleChart() {
  state.chartVisible = !state.chartVisible;
  document.getElementById('chartPanel').style.display = state.chartVisible ? 'block' : 'none';
  if (state.chartVisible) renderChart();
}

function closeChart() {
  state.chartVisible = false;
  document.getElementById('chartPanel').style.display = 'none';
}

function updateChartSelectors(schema) {
  const xSel = document.getElementById('chartX');
  const ySel = document.getElementById('chartY');
  const gSel = document.getElementById('chartGroup');
  if (!xSel || !ySel) return;

  const cols    = schema.map(c => c.name);
  const numCols = schema.filter(c => /int|double|float|decimal|bigint|hugeint/i.test(c.type||'')).map(c => c.name);
  const catCols = schema.filter(c => /varchar|text|char/i.test(c.type||'')).map(c => c.name);

  const makeOpts = (arr, selected) => arr.map(c =>
    `<option value="${c}" ${c === selected ? 'selected' : ''}>${c}</option>`
  ).join('');

  xSel.innerHTML = makeOpts(cols, catCols[0] || cols[0]);
  ySel.innerHTML = makeOpts(numCols, numCols[0]);
  gSel.innerHTML = '<option value="">None</option>' + makeOpts(catCols, '');
}

function renderChart() {
  const xCol  = document.getElementById('chartX')?.value;
  const yCol  = document.getElementById('chartY')?.value;
  const gCol  = document.getElementById('chartGroup')?.value;
  const type  = document.getElementById('chartType')?.value || 'bar';
  const rows  = state.data;

  if (!xCol || !yCol || !rows.length) return;

  const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
  const gridColor   = isDark ? 'rgba(255,255,255,0.06)' : 'rgba(0,0,0,0.08)';
  const textColor   = isDark ? '#8b949e' : '#57606a';
  const PALETTE = ['#58a6ff','#3fb950','#d29922','#f85149','#ab47bc','#00b4d8','#ef6c00'];

  // Build datasets
  let datasets = [];
  if (gCol) {
    const groups = [...new Set(rows.map(r => r[gCol]))];
    datasets = groups.map((g, i) => {
      const subset = rows.filter(r => r[gCol] === g);
      return {
        label: String(g),
        data:  subset.map(r => ({ x: r[xCol], y: Number(r[yCol]) })),
        backgroundColor: PALETTE[i % PALETTE.length] + (type === 'line' ? '33' : 'bb'),
        borderColor:     PALETTE[i % PALETTE.length],
        borderWidth: 1.5,
        tension: 0.4,
        pointRadius: type === 'scatter' ? 3 : 2,
      };
    });
  } else {
    datasets = [{
      label: yCol,
      data: rows.map(r => ({ x: r[xCol], y: Number(r[yCol]) })),
      backgroundColor: PALETTE[0] + (type === 'line' ? '33' : 'bb'),
      borderColor: PALETTE[0],
      borderWidth: 1.5,
      tension: 0.4,
    }];
  }

  const canvas = document.getElementById('mainChart');
  if (state.chartInstance) state.chartInstance.destroy();

  state.chartInstance = new Chart(canvas, {
    type: type === 'scatter' ? 'scatter' : type,
    data: { datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 300 },
      plugins: {
        legend: { labels: { color: textColor, font: { family: 'Inter', size: 11 }, boxWidth: 12 } },
      },
      scales: {
        x: {
          type: 'category',
          ticks: { color: textColor, font: { family: 'JetBrains Mono', size: 10 }, maxTicksLimit: 20 },
          grid: { color: gridColor },
        },
        y: {
          ticks: { color: textColor, font: { family: 'JetBrains Mono', size: 10 } },
          grid: { color: gridColor },
        },
      },
    },
  });
}

// ── SQL Editor ─────────────────────────────────────────────────────────────────
function openSQLEditor() {
  state.sqlVisible = true;
  document.getElementById('sqlPanel').style.display = 'block';
  const editor = document.getElementById('sqlEditor');
  if (state.activeTable && !editor.value.trim()) {
    editor.value = `SELECT *\nFROM ${state.activeTable}\nLIMIT 100`;
  }
  editor.focus();
}

function closeSQLEditor() {
  state.sqlVisible = false;
  document.getElementById('sqlPanel').style.display = 'none';
}

function sqlKeydown(e) {
  if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
    e.preventDefault();
    runSQL();
  }
}

async function runSQL() {
  const sql    = document.getElementById('sqlEditor').value.trim();
  const status = document.getElementById('sqlStatus');
  if (!sql) return;

  const src = state.activeSource || Object.values(state.sources).find(s => s.layer === 'multi')?.id
              || state.sources[0]?.id;
  if (!src) { status.textContent = 'No source selected.'; status.className = 'sql-status error'; return; }

  status.textContent = 'Running…';
  status.className   = 'sql-status';

  try {
    const res  = await fetch(`${API}/query/${src}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ sql, limit: 500 }),
    });
    const data = await res.json();

    if (!res.ok) throw new Error(data.detail || 'Query failed');

    // Update table with SQL results
    state.schema = (data.columns || []).map(c => ({ name: c, type: '' }));
    state.data   = data.rows || [];
    state.total  = data.row_count || 0;

    renderTable(state.data, state.schema, state.activeLayer || 'raw');
    updateChartSelectors(state.schema);
    if (state.chartVisible) renderChart();

    status.textContent = `✓ ${data.row_count} rows returned`;
    status.className   = 'sql-status ok';

    document.getElementById('kpiTotal').textContent = data.row_count.toLocaleString();

  } catch (e) {
    status.textContent = `✗ ${e.message}`;
    status.className   = 'sql-status error';
  }
}

// ── Export CSV ─────────────────────────────────────────────────────────────────
function exportCSV() {
  if (!state.data.length) return;
  const cols = state.schema.map(c => c.name);
  const csv  = [
    cols.join(','),
    ...state.data.map(row => cols.map(c => {
      const v = row[c];
      if (v === null || v === undefined) return '';
      const s = String(v);
      return s.includes(',') || s.includes('"') || s.includes('\n')
        ? `"${s.replace(/"/g, '""')}"`
        : s;
    }).join(',')),
  ].join('\n');

  const blob = new Blob([csv], { type: 'text/csv' });
  const url  = URL.createObjectURL(blob);
  const a    = document.createElement('a');
  a.href     = url;
  a.download = `${state.activeTable || 'export'}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

// ── Loading / error ────────────────────────────────────────────────────────────
function showLoading(show) {
  const wrap = document.getElementById('tableWrap');
  let overlay = document.getElementById('loadingOverlay');
  if (show) {
    if (!overlay) {
      overlay    = document.createElement('div');
      overlay.id = 'loadingOverlay';
      overlay.className = 'loading-overlay';
      overlay.innerHTML = '<div class="spinner"></div>';
      wrap.appendChild(overlay);
    }
  } else {
    overlay?.remove();
  }
}

function showError(msg) {
  const empty = document.getElementById('tableEmpty');
  empty.innerHTML = `<p style="color:var(--error)">${escHtml(msg)}</p>`;
  empty.style.display = 'flex';
  document.getElementById('dataTable').style.display = 'none';
}

// ── Utilities ──────────────────────────────────────────────────────────────────
function escHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;')
    .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

// ── Boot ───────────────────────────────────────────────────────────────────────
init();
