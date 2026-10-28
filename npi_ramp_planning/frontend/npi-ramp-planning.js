import { apiJson } from '/shared/static/dashboard.js';
import { SEMANTIC_COLORS } from '/shared/static/chart.js?v=20261027c';
import {
  applyRoleView, bindTabs, chartManager, chartSpec, fillSelect, formatNumber, queryFromForm,
  renderKpis, renderTable, setViewState,
} from '/shared/static/planning.js?v=20261027e';

const form = document.getElementById('filters');
const charts = chartManager();
let activeView = 'program';

async function loadFilters() {
  const payload = await apiJson(`/npi-ramp-planning/api/filters/${activeView}`);
  fillSelect(form, 'program', payload.options.program, 'All programs');
  fillSelect(form, 'site', payload.options.site, 'All sites');
  fillSelect(form, 'product', payload.options.product, 'All products');
}

async function loadDashboard() {
  charts.dispose();
  setViewState(`Loading ${activeView} view.`);
  try {
    const payload = await apiJson(`/npi-ramp-planning/api/dashboard/${activeView}?${queryFromForm(form)}`);
    const release = document.getElementById('release-status');
    release.textContent = `Release ${payload.release.release_id || 'unknown'}`;
    release.dataset.state = payload.status === 'empty' ? 'warning' : 'ready';
    setViewState(payload.message || `${activeView} view at monthly grain.`, payload.status);
    const kpi = payload.kpis;
    renderKpis('npi-kpis', [
      ['Programs', kpi.program_count, 'programs'],
      ['Average readiness', kpi.average_readiness_pct == null ? null : kpi.average_readiness_pct * 100, '%', 1],
      ['High-risk programs', kpi.high_risk_programs, 'programs'],
      ['Tooling items at risk', kpi.tooling_items_at_risk, 'items'],
      ['Target launch capacity', kpi.target_launch_quantity_ea, 'EA'],
      ['Actual launch output', kpi.actual_launch_quantity_ea, 'EA'],
      ['Launch quantity variance', kpi.launch_quantity_variance_ea, 'EA'],
    ]);
    const months = payload.monthly_ramp.map((row) => String(row.month));
    const context = { releaseId: payload.release.release_id, filters: Object.fromEntries(new FormData(form)) };
    await charts.draw('ramp-chart', chartSpec({
      title: 'Target versus actual launch ramp',
      metric: 'Launch quantity',
      unit: 'EA', grain: 'MONTH', source: 'srv_npi_ramp',
      xTitle: 'Month', xValues: months, yTitle: 'Units (EA)',
      summary: 'Monthly target ramp quantity compared with recorded actual ramp quantity.',
      series: [
        { name: 'Target ramp', type: 'line', color: SEMANTIC_COLORS.demand, data: payload.monthly_ramp.map((row) => row.target_quantity_ea) },
        { name: 'Actual ramp', type: 'line', color: SEMANTIC_COLORS.actualOutput, data: payload.monthly_ramp.map((row) => row.actual_quantity_ea) },
      ],
    }), context);
    await charts.draw('yield-chart', chartSpec({
      title: 'Target versus actual NPI yield',
      metric: 'NPI yield',
      unit: 'PCT', grain: 'MONTH', source: 'srv_npi_ramp',
      xTitle: 'Month', xValues: months, yTitle: 'Yield ratio',
      summary: 'Monthly target yield compared with recorded actual NPI yield.',
      series: [
        { name: 'Target yield', type: 'line', color: SEMANTIC_COLORS.maximumCapacity, data: payload.monthly_ramp.map((row) => row.target_yield_pct) },
        { name: 'Actual yield', type: 'line', color: SEMANTIC_COLORS.demonstratedCapacity, data: payload.monthly_ramp.map((row) => row.actual_yield_pct) },
      ],
    }), context);
    const learningState = document.getElementById('learning-state');
    learningState.textContent = payload.learning_curve.available
      ? 'Recorded cumulative production supports this learning curve.'
      : payload.learning_curve.reason;
    learningState.className = payload.learning_curve.available ? '' : 'unavailable';
    if (payload.learning_curve.available) {
      const learning = [...payload.learning_curve.rows].sort(
        (a, b) => a.cumulative_quantity_ea - b.cumulative_quantity_ea,
      );
      await charts.draw('learning-chart', chartSpec({
        title: 'Yield by cumulative production',
        metric: 'Recorded learning curve',
        unit: 'PCT', grain: 'NONE', source: 'srv_npi_ramp',
        xTitle: 'Cumulative production (EA)',
        xValues: learning.map((row) => row.cumulative_quantity_ea),
        yTitle: 'Actual yield ratio',
        summary: 'Actual NPI yield ordered by recorded cumulative production.',
        series: [{ name: 'Actual yield', type: 'line', color: SEMANTIC_COLORS.demonstratedCapacity, data: learning.map((row) => row.actual_yield_pct) }],
      }), context);
    } else {
      document.getElementById('learning-chart').replaceChildren();
    }
    const timelineState = document.getElementById('timeline-state');
    timelineState.textContent = payload.stage_gate_timeline.reason;
    timelineState.className = payload.stage_gate_timeline.available ? '' : 'unavailable';
    if (payload.stage_gate_timeline.available) {
      const gates = payload.stage_gate_timeline.rows;
      const dateValues = [...new Set(gates.flatMap(
        (row) => [row.planned_gate_date, row.actual_gate_date].filter(Boolean).map(String),
      ))].sort();
      const programValues = [...new Set(gates.map((row) => row.program_name))];
      await charts.draw('timeline-chart', chartSpec({
        title: 'Stage-gate plan versus actual',
        metric: 'Stage-gate date',
        unit: 'DATE', grain: 'DAY', source: 'srv_npi_stage_gate',
        xTitle: 'Gate date', xValues: dateValues,
        yTitle: 'NPI program', yType: 'category', yValues: programValues,
        summary: 'Planned and actual stage-gate dates by NPI program.',
        tooltip: 'item',
        rows: gates.map((row) => [
          row.program_name, row.gate_name, row.planned_gate_date,
          row.actual_gate_date, row.gate_status,
        ]),
        columns: ['Program', 'Gate', 'Planned date', 'Actual date', 'Status'],
        series: [
          {
            name: 'Planned gate',
            type: 'scatter',
            symbol: 'diamond',
            color: SEMANTIC_COLORS.demand,
            data: gates.filter((row) => row.planned_gate_date).map(
              (row) => [dateValues.indexOf(String(row.planned_gate_date)), programValues.indexOf(row.program_name)],
            ),
          },
          {
            name: 'Actual gate',
            type: 'scatter',
            symbol: 'circle',
            color: SEMANTIC_COLORS.actualOutput,
            data: gates.filter((row) => row.actual_gate_date).map(
              (row) => [dateValues.indexOf(String(row.actual_gate_date)), programValues.indexOf(row.program_name)],
            ),
          },
        ],
      }), context);
    } else {
      document.getElementById('timeline-chart').replaceChildren();
    }
    renderTable('readiness-table', 'Program-level readiness aggregates and planned launch date.', [
      { key: 'program_name', label: 'Program full name' },
      { key: 'program_id', label: 'Program code' },
      { key: 'product_description', label: 'Product full name' },
      { key: 'site_name', label: 'Lead site full name' },
      { key: 'planned_launch_date', label: 'Planned launch' },
      { key: 'program_status', label: 'Program status' },
      { key: 'gates_passed', label: 'Gates passed', numeric: true },
      { key: 'gate_count', label: 'Gate count', numeric: true },
      { key: 'milestones_complete', label: 'Milestones complete', numeric: true },
      { key: 'tooling_readiness_pct', label: 'Tooling readiness %', numeric: true, format: (v) => formatNumber(Number(v) * 100, 1) },
      { key: 'readiness_score_pct', label: 'Readiness score %', numeric: true, format: (v) => formatNumber(Number(v) * 100, 1) },
      { key: 'launch_risk_tier', label: 'Launch risk', status: true },
      { key: 'open_risk_count', label: 'Open risks', numeric: true },
    ], payload.readiness);
    renderTable('qualification-table', 'Qualification and pilot-lot evidence at program grain.', [
      { key: 'program_name', label: 'Program full name' },
      { key: 'program_id', label: 'Program code' },
      { key: 'qualification_count', label: 'Qualification records', numeric: true },
      { key: 'qualifications_accepted', label: 'Accepted', numeric: true },
      { key: 'pilot_lot_count', label: 'Pilot lots', numeric: true },
      { key: 'pilot_yield_pct', label: 'Pilot yield %', numeric: true, format: (v) => formatNumber(Number(v) * 100, 1) },
    ], payload.qualification_matrix.rows);
    renderTable('ramp-table', 'Target and actual launch capacity by program, site, and month.', [
      { key: 'program_id', label: 'Program code' }, { key: 'site_name', label: 'Site full name' },
      { key: 'product_description', label: 'Product full name' }, { key: 'month_key', label: 'Month' },
      { key: 'target_quantity_ea', label: 'Target EA', numeric: true, format: formatNumber },
      { key: 'actual_quantity_ea', label: 'Actual EA', numeric: true, format: formatNumber },
      { key: 'ramp_quantity_variance_ea', label: 'Variance EA', numeric: true, format: formatNumber },
      { key: 'target_status', label: 'Target status' }, { key: 'actual_status', label: 'Actual status' },
    ], payload.ramp);
  } catch (error) {
    const release = document.getElementById('release-status');
    release.textContent = 'Not ready'; release.dataset.state = 'error';
    setViewState(error.message || 'NPI Ramp Planning is not ready.', 'error');
  }
}

bindTabs((view) => {
  activeView = view;
  applyRoleView(view);
  void loadFilters().then(loadDashboard);
});
form.addEventListener('submit', (event) => { event.preventDefault(); void loadDashboard(); });
void loadFilters().then(loadDashboard).catch((error) => setViewState(error.message, 'error'));
