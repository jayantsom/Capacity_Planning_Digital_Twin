/**
 * Governed local Apache ECharts wrapper.
 *
 * ECharts 5.6.0 is loaded only from /shared/static/vendor/echarts/echarts.min.js.
 */

export const CHART_CONTRACT_VERSION = '1.0.0';
export const DEFAULT_POINT_LIMIT = 5000;
export const ECHARTS_ASSET = '/shared/static/vendor/echarts/echarts.min.js';
export const SEMANTIC_COLORS = Object.freeze({
  demand: '#2878b5',
  baseline: '#737b84',
  normalCapacity: '#008c95',
  maximumCapacity: '#7652a8',
  demonstratedCapacity: '#26734d',
  actualOutput: '#164b75',
  warning: '#9a6500',
  shortage: '#b02a37',
  positiveHeadroom: '#26734d',
});

const REQUIRED_TEXT = ['title', 'metric', 'unit', 'grain', 'aggregation', 'source'];
const ALLOWED_GRAINS = new Set(['NONE', 'DAY', 'WEEK', 'MONTH', 'QUARTER', 'YEAR']);
let echartsPromise;

function requireObject(value, field) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) {
    throw new TypeError(`${field} must be an object`);
  }
}

export function validateChartSpec(spec, pointLimit = DEFAULT_POINT_LIMIT) {
  requireObject(spec, 'chart spec');
  const errors = [];
  REQUIRED_TEXT.forEach((field) => {
    if (typeof spec[field] !== 'string' || !spec[field].trim()) {
      errors.push(`${field} is required`);
    }
  });
  if (!ALLOWED_GRAINS.has(spec.grain)) errors.push('grain is not governed');
  ['axes', 'legend', 'tooltip', 'dataZoom', 'export', 'emptyState', 'accessibility']
    .forEach((field) => {
      if (!spec[field] || typeof spec[field] !== 'object') errors.push(`${field} is required`);
    });
  if (!Array.isArray(spec.series) || spec.series.length === 0) {
    errors.push('series must contain at least one series');
  }
  if (Array.isArray(spec.series)) {
    const names = spec.series.map((series) => (
      typeof series.name === 'string' ? series.name.trim() : ''
    ));
    if (names.some((name) => !name)) errors.push('every series requires a name');
    if (new Set(names).size !== names.length) errors.push('series names must be unique');
  }
  const totalPoints = Array.isArray(spec.series)
    ? spec.series.reduce((count, series) => count + (Array.isArray(series.data) ? series.data.length : 0), 0)
    : 0;
  if (totalPoints > pointLimit) errors.push(`chart exceeds the ${pointLimit} point limit`);
  if (spec.thresholds != null && !Array.isArray(spec.thresholds)) {
    errors.push('thresholds must be an array');
  }
  if (!spec.accessibility?.summary || spec.accessibility?.table !== true) {
    errors.push('accessible summary and data table are required');
  }
  if (
    spec.accessibility?.rows
    && (!Array.isArray(spec.accessibility.rows) || !Array.isArray(spec.accessibility.columns))
  ) {
    errors.push('custom accessible rows require accessible columns');
  }
  if (spec.visualMap != null && typeof spec.visualMap !== 'object') {
    errors.push('visualMap must be an object');
  }
  if (!['displayed', 'complete-filtered'].includes(spec.export?.rowScope)) {
    errors.push('export.rowScope must be displayed or complete-filtered');
  }
  if (errors.length) throw new TypeError(`Invalid chart spec: ${errors.join('; ')}`);
  return Object.freeze({ ...spec, pointCount: totalPoints });
}

export function escapeCsvCell(value) {
  let text = value == null ? '' : String(value);
  if (/^\s*[=+\-@]/.test(text)) text = `'${text}`;
  return `"${text.replaceAll('"', '""')}"`;
}

export function rowsToCsv(columns, rows) {
  const header = columns.map(escapeCsvCell).join(',');
  const body = rows.map((row) => columns.map((column) => escapeCsvCell(row[column])).join(','));
  return [header, ...body].join('\r\n');
}

export function imageMetadata(spec, context = {}) {
  return {
    contractVersion: CHART_CONTRACT_VERSION,
    title: spec.title,
    metric: spec.metric,
    unit: spec.unit,
    grain: spec.grain,
    source: spec.source,
    filters: context.filters || {},
    freshness: context.freshness || null,
    releaseId: context.releaseId || null,
    exportedAt: new Date().toISOString(),
  };
}

export function loadECharts() {
  if (globalThis.echarts) return Promise.resolve(globalThis.echarts);
  if (!echartsPromise) {
    echartsPromise = new Promise((resolve, reject) => {
      const script = document.createElement('script');
      script.src = ECHARTS_ASSET;
      script.async = true;
      script.dataset.localEcharts = '5.6.0';
      script.onload = () => resolve(globalThis.echarts);
      script.onerror = () => reject(new Error('Local ECharts asset could not be loaded'));
      document.head.append(script);
    });
  }
  return echartsPromise;
}

function thresholdMarkLine(thresholds = []) {
  if (!thresholds.length) return undefined;
  return {
    silent: true,
    symbol: 'none',
    data: thresholds.map((threshold) => ({
      name: threshold.label,
      yAxis: threshold.value,
      lineStyle: {
        color: threshold.color || SEMANTIC_COLORS.warning,
        type: threshold.lineStyle || 'dashed',
      },
      label: { formatter: threshold.label },
    })),
  };
}

function buildOption(spec) {
  const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  return {
    animation: !reducedMotion,
    aria: {
      enabled: true,
      decal: { show: true },
      description: spec.accessibility.summary,
    },
    title: {
      text: spec.metric,
      subtext: `${spec.unit} · ${spec.grain}`,
      left: 'center',
      top: 0,
      textStyle: { fontSize: 13, lineHeight: 18, fontWeight: 600 },
      subtextStyle: { fontSize: 10, lineHeight: 14 },
    },
    color: spec.colors || Object.values(SEMANTIC_COLORS),
    legend: {
      show: spec.legend.show !== false,
      type: spec.legend.type || 'scroll',
      orient: spec.legend.orient || 'horizontal',
      top: 52,
      left: 'center',
    },
    tooltip: {
      show: spec.tooltip.show !== false,
      trigger: spec.tooltip.trigger || 'axis',
      valueFormatter: (value) => `${value ?? '-'} ${spec.unit}`,
    },
    grid: {
      containLabel: true,
      left: 16,
      right: 24,
      top: spec.legend.show !== false ? 104 : 78,
      bottom: spec.dataZoom.enabled ? 72 : 34,
    },
    xAxis: {
      type: spec.axes.x.type || 'category',
      show: spec.axes.x.show !== false,
      name: spec.axes.x.title || '',
      data: spec.axes.x.values || [],
      axisLabel: { hideOverlap: true },
    },
    yAxis: {
      type: spec.axes.y.type || 'value',
      show: spec.axes.y.show !== false,
      name: spec.axes.y.title || spec.unit,
      data: spec.axes.y.values || undefined,
      min: spec.axes.y.min,
      max: spec.axes.y.max,
    },
    visualMap: spec.visualMap,
    dataZoom: spec.dataZoom.enabled
      ? [{ type: 'inside' }, { type: 'slider', show: true }]
      : [],
    series: spec.series.map((series, index) => ({
      name: series.name,
      type: series.type || 'line',
      data: series.data,
      links: series.links,
      encode: series.encode,
      layout: series.layout,
      orient: series.orient,
      nodeAlign: series.nodeAlign,
      draggable: series.draggable,
      emphasis: series.emphasis,
      levels: series.levels,
      radius: series.radius,
      smooth: series.smooth === true,
      symbol: series.symbol || 'circle',
      showSymbol: series.showSymbol ?? series.data.length < 100,
      stack: series.stack,
      barGap: series.barGap,
      barWidth: series.barWidth,
      label: series.label,
      areaStyle: series.areaStyle,
      itemStyle: { ...(series.itemStyle || {}), color: series.color },
      lineStyle: { ...(series.lineStyle || {}), color: series.color },
      markLine: index === 0 ? thresholdMarkLine(spec.thresholds) : undefined,
    })),
  };
}

function accessibleTable(spec) {
  const details = document.createElement('details');
  details.className = 'ct-chart-data';
  const summary = document.createElement('summary');
  summary.textContent = `View data for ${spec.title}`;
  const description = document.createElement('p');
  description.textContent = spec.accessibility.summary;
  const scroll = document.createElement('div');
  scroll.className = 'ct-table-scroll';
  const table = document.createElement('table');
  const caption = document.createElement('caption');
  caption.textContent = `${spec.title}. Unit: ${spec.unit}. Grain: ${spec.grain}. Source: ${spec.source}.`;
  const head = document.createElement('thead');
  const headRow = document.createElement('tr');
  const customRows = spec.accessibility.rows;
  const columns = customRows
    ? spec.accessibility.columns
    : ['Category', ...spec.series.map((series) => series.name)];
  columns.forEach((label) => {
    const cell = document.createElement('th');
    cell.scope = 'col';
    cell.textContent = label;
    headRow.append(cell);
  });
  head.append(headRow);
  const body = document.createElement('tbody');
  const rows = customRows || (spec.axes.x.values || []).map(
    (category, rowIndex) => [
      category,
      ...spec.series.map((series) => series.data[rowIndex] ?? '-'),
    ],
  );
  rows.forEach((values) => {
    const row = document.createElement('tr');
    values.forEach((value) => {
      const cell = document.createElement('td');
      cell.textContent = String(value);
      row.append(cell);
    });
    body.append(row);
  });
  table.append(caption, head, body);
  scroll.append(table);
  details.append(summary, description, scroll);
  return details;
}

export async function renderGovernedChart(container, rawSpec, context = {}) {
  if (!(container instanceof HTMLElement)) throw new TypeError('container must be an HTMLElement');
  const spec = validateChartSpec(rawSpec, context.pointLimit || DEFAULT_POINT_LIMIT);
  container.replaceChildren();
  container.classList.add('ct-chart');
  if (spec.series.every((series) => series.data.length === 0)) {
    const empty = document.createElement('p');
    empty.className = 'ct-chart-empty';
    empty.textContent = spec.emptyState.message || 'No data matches the selected filters.';
    container.append(empty, accessibleTable(spec));
    return { chart: null, spec, dispose() {} };
  }

  const chartHost = document.createElement('div');
  chartHost.className = 'ct-chart-canvas';
  chartHost.style.minHeight = `${spec.height || 360}px`;
  container.append(chartHost, accessibleTable(spec));
  const echarts = await loadECharts();
  const chart = echarts.init(chartHost, null, { renderer: 'canvas' });
  chart.setOption(buildOption(spec), { notMerge: true });
  const observer = new ResizeObserver(() => chart.resize());
  observer.observe(chartHost);

  return {
    chart,
    spec,
    exportCsv(rows, columns) {
      return rowsToCsv(columns, rows);
    },
    exportImage(options = {}) {
      return {
        dataUrl: chart.getDataURL({ type: options.type || 'png', pixelRatio: 2, backgroundColor: '#fff' }),
        metadata: imageMetadata(spec, context),
      };
    },
    dispose() {
      observer.disconnect();
      chart.dispose();
    },
  };
}
