import { renderGovernedChart } from '/shared/static/chart.js?v=20261027c';

export function formatNumber(value, digits = 0) {
  if (value == null || Number.isNaN(Number(value))) return '-';
  return Number(value).toLocaleString(undefined, { maximumFractionDigits: digits });
}

export function setViewState(message, kind = 'ready') {
  const state = document.getElementById('view-state');
  state.textContent = message;
  state.dataset.state = kind;
}

export function queryFromForm(form) {
  const params = new URLSearchParams();
  new FormData(form).forEach((value, key) => {
    const normalized = key.startsWith('month_') ? String(value).replace('-', '') : value;
    if (normalized !== '') params.set(key, normalized);
  });
  return params.toString();
}

export function fillSelect(form, name, options, placeholder) {
  const select = form.elements[name];
  const selected = select.value;
  select.replaceChildren();
  if (placeholder) select.add(new Option(placeholder, ''));
  options.forEach((item) => select.add(new Option(item.label, item.value)));
  if ([...select.options].some((item) => item.value === selected)) select.value = selected;
}

export function renderKpis(containerId, entries) {
  const container = document.getElementById(containerId);
  container.replaceChildren(...entries.map(([label, value, unit, digits = 0]) => {
    const card = document.createElement('article');
    const title = document.createElement('small');
    title.textContent = label;
    const metric = document.createElement('strong');
    metric.textContent = formatNumber(value, digits);
    const suffix = document.createElement('span');
    suffix.textContent = unit;
    const valueRow = document.createElement('div');
    valueRow.className = 'ct-kpi-value';
    valueRow.append(metric, suffix);
    card.append(title, valueRow);
    return card;
  }));
}

export function renderTable(id, captionText, columns, rows) {
  const table = document.getElementById(id);
  const caption = document.createElement('caption');
  caption.textContent = captionText;
  const head = document.createElement('thead');
  const headRow = document.createElement('tr');
  columns.forEach((column) => {
    const cell = document.createElement('th');
    cell.scope = 'col';
    cell.textContent = column.label;
    headRow.append(cell);
  });
  head.append(headRow);
  const body = document.createElement('tbody');
  rows.forEach((item) => {
    const row = document.createElement('tr');
    columns.forEach((column) => {
      const cell = document.createElement('td');
      const value = item[column.key];
      cell.textContent = column.format ? column.format(value) : (value ?? '-');
      if (column.numeric) cell.className = 'numeric';
      if (column.status) {
        cell.classList.add('status-marker');
        cell.dataset.status = value;
      }
      row.append(cell);
    });
    body.append(row);
  });
  table.replaceChildren(caption, head, body);
}

export function chartSpec({
  title, metric, unit, grain, source, xTitle, xValues, yTitle, series,
  summary, zoom = true, rows, columns, visualMap, tooltip = 'axis',
  xType = 'category', yType = 'value', yValues, axesVisible = true,
}) {
  return {
    title, metric, unit, grain, aggregation: 'SUM', source,
    axes: {
      x: { type: xType, title: xTitle, values: xValues, show: axesVisible },
      y: { type: yType, title: yTitle, values: yValues, show: axesVisible },
    },
    legend: { show: series.length > 1, type: 'scroll' },
    tooltip: { show: true, trigger: tooltip },
    thresholds: [],
    dataZoom: { enabled: zoom },
    export: { rowScope: 'displayed' },
    emptyState: { message: 'No data matches the selected filters.' },
    accessibility: { summary, table: true, rows, columns },
    visualMap,
    series,
    height: 340,
  };
}

export function chartManager() {
  let handles = [];
  return {
    async draw(id, spec, context) {
      handles.push(await renderGovernedChart(document.getElementById(id), spec, context));
    },
    dispose() {
      handles.forEach((handle) => handle.dispose());
      handles = [];
    },
  };
}

export function downloadText(name, text, type) {
  const url = URL.createObjectURL(new Blob([text], { type }));
  const link = document.createElement('a');
  link.href = url;
  link.download = name;
  link.click();
  URL.revokeObjectURL(url);
}

export function escapeCsvCell(value) {
  let text = value == null ? '' : String(value);
  if (/^\s*[=+\-@]/.test(text)) text = `'${text}`;
  return `"${text.replaceAll('"', '""')}"`;
}

export function parseCsvLine(line) {
  const cells = [];
  let value = '';
  let quoted = false;
  for (let index = 0; index < line.length; index += 1) {
    const character = line[index];
    if (character === '"' && quoted && line[index + 1] === '"') {
      value += '"';
      index += 1;
    } else if (character === '"') {
      quoted = !quoted;
    } else if (character === ',' && !quoted) {
      cells.push(value.replace(/^'/, ''));
      value = '';
    } else {
      value += character;
    }
  }
  cells.push(value.replace(/^'/, ''));
  return cells;
}

export function bindTabs(onChange) {
  const tabs = [...document.querySelectorAll('[role="tab"]')];
  tabs.forEach((tab, index) => {
    const activate = () => {
      tabs.forEach((item) => {
        const selected = item === tab;
        item.setAttribute('aria-selected', String(selected));
        item.tabIndex = selected ? 0 : -1;
        const panel = document.getElementById(item.getAttribute('aria-controls'));
        if (panel) panel.hidden = !selected;
      });
      onChange?.(tab.dataset.view);
    };
    tab.addEventListener('click', activate);
    tab.addEventListener('keydown', (event) => {
      if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
      event.preventDefault();
      const target = event.key === 'Home' ? tabs[0] : event.key === 'End'
        ? tabs.at(-1) : tabs[(index + (event.key === 'ArrowRight' ? 1 : -1) + tabs.length) % tabs.length];
      target.focus();
      target.click();
    });
  });
}

export function applyRoleView(view) {
  document.querySelectorAll('[data-views]').forEach((section) => {
    const views = section.dataset.views.split(/\s+/).filter(Boolean);
    section.hidden = !views.includes(view);
  });
}
