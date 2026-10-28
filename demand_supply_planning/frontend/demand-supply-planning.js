import { apiJson } from '/shared/static/dashboard.js';
import { SEMANTIC_COLORS } from '/shared/static/chart.js?v=20261027c';
import {
  applyRoleView, bindTabs, chartManager, chartSpec, downloadText, escapeCsvCell, fillSelect,
  formatNumber, parseCsvLine, queryFromForm, renderKpis, renderTable, setViewState,
} from '/shared/static/planning.js?v=20261027e';

const ACTION_SCHEMA = 'capacity-twin/sop-actions/1.0.0';
const ACTION_KEY = 'capacity-twin.sop.actions.v1';
const form = document.getElementById('filters');
const charts = chartManager();
let activeView = 'executive';
let actions = JSON.parse(sessionStorage.getItem(ACTION_KEY) || '[]');

function renderActions() {
  renderTable('actions-table', 'Browser-session S&OP action register.', [
    { key: 'action', label: 'Action' },
    { key: 'owner', label: 'Owner' },
    { key: 'due_date', label: 'Due date' },
    { key: 'status', label: 'Status' },
  ], actions);
  sessionStorage.setItem(ACTION_KEY, JSON.stringify(actions));
}

async function loadFilters() {
  const payload = await apiJson(`/demand-supply-planning/api/filters/${activeView}`);
  fillSelect(form, 'site', payload.options.site, 'All sites');
  fillSelect(form, 'product', payload.options.product, 'All products');
  fillSelect(form, 'planning_version', payload.options.planning_version, 'All versions');
}

async function loadDashboard() {
  charts.dispose();
  setViewState(`Loading ${activeView.replace('-', ' ')} view.`);
  try {
    const payload = await apiJson(`/demand-supply-planning/api/dashboard/${activeView}?${queryFromForm(form)}`);
    const release = document.getElementById('release-status');
    release.textContent = `Release ${payload.release.release_id || 'unknown'}`;
    release.dataset.state = payload.status === 'empty' ? 'warning' : 'ready';
    setViewState(payload.message || `${activeView.replace('-', ' ')} view at monthly grain.`, payload.status);
    const kpi = payload.kpis;
    renderKpis('sop-kpis', [
      ['Demand', kpi.demand_ea, 'EA'],
      ['Constrained production', kpi.constrained_production_ea, 'EA'],
      ['Supply-demand gap', kpi.supply_demand_gap_ea, 'EA'],
      ['Shipments', kpi.shipments_ea, 'EA'],
      ['Ending inventory', kpi.ending_inventory_ea, 'EA'],
      ['Ending backlog', kpi.ending_backlog_ea, 'EA'],
      ['Exceptions', kpi.exception_count, 'rows'],
      ['Max reconciliation variance', kpi.maximum_reconciliation_variance_ea, 'EA', 6],
    ]);
    const months = payload.trend.map((row) => String(row.month));
    const context = { releaseId: payload.release.release_id, filters: Object.fromEntries(new FormData(form)) };
    await charts.draw('horizon-chart', chartSpec({
      title: 'Demand and constrained supply horizon',
      metric: 'Demand, constrained production, receipts, and shipments',
      unit: 'EA', grain: 'MONTH', source: 'srv_sop_balance',
      xTitle: 'Month', xValues: months, yTitle: 'Units (EA)',
      summary: 'Monthly customer orders, constrained production, inbound receipts, and shipments.',
      series: [
        { name: 'Customer demand', type: 'line', color: SEMANTIC_COLORS.demand, data: payload.trend.map((row) => row.demand_ea) },
        { name: 'Constrained production', type: 'line', color: SEMANTIC_COLORS.normalCapacity, data: payload.trend.map((row) => row.constrained_production_ea) },
        { name: 'Receipts', type: 'bar', color: SEMANTIC_COLORS.demonstratedCapacity, data: payload.trend.map((row) => row.receipts_ea) },
        { name: 'Shipments', type: 'bar', color: SEMANTIC_COLORS.actualOutput, data: payload.trend.map((row) => row.shipments_ea) },
      ],
    }), context);
    await charts.draw('inventory-chart', chartSpec({
      title: 'Inventory and backlog position',
      metric: 'Ending inventory, safety stock, and separate backlog',
      unit: 'EA', grain: 'MONTH', source: 'srv_sop_balance',
      xTitle: 'Month', xValues: months, yTitle: 'Units (EA)',
      summary: 'Ending inventory and safety stock compared with backlog, which is maintained as a separate balance.',
      series: [
        { name: 'Ending inventory', type: 'line', color: SEMANTIC_COLORS.normalCapacity, data: payload.trend.map((row) => row.ending_inventory_ea) },
        { name: 'Safety stock', type: 'line', color: SEMANTIC_COLORS.warning, data: payload.trend.map((row) => row.safety_stock_ea) },
        { name: 'Ending backlog', type: 'bar', color: SEMANTIC_COLORS.shortage, data: payload.trend.map((row) => row.ending_backlog_ea) },
      ],
    }), context);
    await charts.draw('service-chart', chartSpec({
      title: 'Coverage and service target',
      metric: 'Inventory coverage and declared fill-rate target',
      unit: 'PCT / MONTHS', grain: 'MONTH', source: 'srv_sop_balance',
      xTitle: 'Month', xValues: months, yTitle: 'Coverage months / target ratio',
      summary: 'Inventory coverage in months and the declared fill-rate target. No actual service rate is inferred.',
      series: [
        { name: 'Inventory coverage months', type: 'line', color: SEMANTIC_COLORS.actualOutput, data: payload.trend.map((row) => row.inventory_coverage_months) },
        { name: 'Fill-rate target', type: 'line', color: SEMANTIC_COLORS.maximumCapacity, data: payload.trend.map((row) => row.fill_rate_target_pct) },
      ],
    }), context);
    renderTable('allocation-table', 'Governed shared-resource allocation hours.', [
      { key: 'month_key', label: 'Month' },
      { key: 'site_name', label: 'Site full name' },
      { key: 'product_description', label: 'Product full name' },
      { key: 'equipment_name', label: 'Resource full name' },
      { key: 'allocated_resource_hours', label: 'Allocated hours', numeric: true, format: (v) => formatNumber(v, 1) },
    ], payload.allocation);
    renderTable('exceptions-table', 'Service-risk exceptions only.', [
      { key: 'site_name', label: 'Site full name' },
      { key: 'product_description', label: 'Product full name' },
      { key: 'month_key', label: 'Month' },
      { key: 'service_risk_status', label: 'Risk status', status: true },
      { key: 'ending_backlog_ea', label: 'Backlog EA', numeric: true, format: formatNumber },
      { key: 'oldest_backlog_days', label: 'Oldest backlog days', numeric: true, format: formatNumber },
      { key: 'ending_inventory_ea', label: 'Inventory EA', numeric: true, format: formatNumber },
      { key: 'safety_stock_quantity_ea', label: 'Safety stock EA', numeric: true, format: formatNumber },
    ], payload.exceptions);
    renderTable('reconciliation-table', 'Every displayed row reconciles to ending inventory.', [
      { key: 'site_name', label: 'Site full name' }, { key: 'product_description', label: 'Product full name' },
      { key: 'month_key', label: 'Month' },
      { key: 'beginning_inventory_ea', label: 'Beginning EA', numeric: true, format: formatNumber },
      { key: 'constrained_production_ea', label: 'Production EA', numeric: true, format: formatNumber },
      { key: 'receipt_quantity_ea', label: 'Receipts EA', numeric: true, format: formatNumber },
      { key: 'shipment_quantity_ea', label: 'Shipments EA', numeric: true, format: formatNumber },
      { key: 'ending_inventory_ea', label: 'Ending EA', numeric: true, format: formatNumber },
      { key: 'inventory_balance_variance_ea', label: 'Variance EA', numeric: true, format: (v) => formatNumber(v, 6) },
    ], payload.reconciliation);
  } catch (error) {
    const release = document.getElementById('release-status');
    release.textContent = 'Not ready'; release.dataset.state = 'error';
    setViewState(error.message || 'S&OP Planning is not ready.', 'error');
  }
}

function exportActions(type) {
  if (type === 'json') {
    downloadText('sop-actions-v1.json', JSON.stringify({ schema: ACTION_SCHEMA, actions }, null, 2), 'application/json');
    return;
  }
  const rows = [['schema', 'action', 'owner', 'due_date', 'status'], ...actions.map(
    (item) => [ACTION_SCHEMA, item.action, item.owner, item.due_date, item.status],
  )];
  downloadText('sop-actions-v1.csv', rows.map((row) => row.map(escapeCsvCell).join(',')).join('\r\n'), 'text/csv');
}

document.getElementById('action-form').addEventListener('submit', (event) => {
  event.preventDefault();
  const values = Object.fromEntries(new FormData(event.currentTarget));
  actions.push({ ...values, status: 'OPEN' });
  actions = actions.slice(-200);
  event.currentTarget.reset();
  renderActions();
});
document.getElementById('export-actions-json').addEventListener('click', () => exportActions('json'));
document.getElementById('export-actions-csv').addEventListener('click', () => exportActions('csv'));
document.getElementById('import-actions').addEventListener('change', async (event) => {
  try {
    const file = event.target.files[0];
    if (!file) return;
    const text = await file.text();
    let imported;
    if (file.name.toLowerCase().endsWith('.json')) {
      const payload = JSON.parse(text);
      if (payload.schema !== ACTION_SCHEMA || !Array.isArray(payload.actions)) throw new Error('Unsupported action register schema.');
      imported = payload.actions;
    } else {
      imported = text.split(/\r?\n/).filter(Boolean).slice(1).map((line) => {
        const cells = parseCsvLine(line);
        if (cells[0] !== ACTION_SCHEMA) throw new Error('Unsupported action register CSV schema.');
        return { action: cells[1], owner: cells[2], due_date: cells[3], status: cells[4] };
      });
    }
    actions = imported.slice(0, 200).map((item) => ({
      action: String(item.action || '').slice(0, 240),
      owner: String(item.owner || '').slice(0, 80),
      due_date: String(item.due_date || '').slice(0, 10),
      status: String(item.status || 'OPEN').slice(0, 20),
    }));
    renderActions();
  } catch (error) { setViewState(error.message, 'error'); }
});
bindTabs((view) => {
  activeView = view;
  applyRoleView(view);
  void loadFilters().then(loadDashboard);
});
form.addEventListener('submit', (event) => { event.preventDefault(); void loadDashboard(); });
renderActions();
void loadFilters().then(loadDashboard).catch((error) => setViewState(error.message, 'error'));
