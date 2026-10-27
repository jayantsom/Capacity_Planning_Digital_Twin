const STORAGE_KEY = 'capacityTwin.comparisonWindow';
const VALID_IDS = new Set(['total', 'band_1', 'band_2']);

function requestedWindow() {
  const url = new URL(window.location.href);
  const fromUrl = url.searchParams.get('window');
  if (VALID_IDS.has(fromUrl)) return fromUrl;
  const fromSession = window.sessionStorage.getItem(STORAGE_KEY);
  return VALID_IDS.has(fromSession) ? fromSession : 'total';
}

function persistWindow(windowId) {
  window.sessionStorage.setItem(STORAGE_KEY, windowId);
  const url = new URL(window.location.href);
  url.searchParams.set('window', windowId);
  window.history.replaceState({}, '', url);
}

export async function mountComparisonBand(root, onChange) {
  if (!root) return null;
  const response = await fetch('/shared/api/comparison-windows');
  if (!response.ok) throw new Error('Comparison windows are unavailable.');
  const payload = await response.json();
  const windows = payload.windows || [];
  let active = requestedWindow();
  if (!windows.some((item) => item.window_id === active)) active = 'total';

  const select = (windowId, notify = true) => {
    if (!windows.some((item) => item.window_id === windowId)) return;
    active = windowId;
    persistWindow(active);
    render();
    if (notify) {
      onChange?.(active, windows.find((item) => item.window_id === active));
    }
  };

  const render = () => {
    root.replaceChildren();
    windows.forEach((item) => {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'comparison-window';
      button.dataset.window = item.window_id;
      button.setAttribute('aria-pressed', String(item.window_id === active));

      const name = document.createElement('strong');
      name.textContent = item.display_name.toUpperCase();
      const dates = document.createElement('span');
      dates.textContent = item.start_date
        ? `${item.start_date} — ${item.end_date}`
        : 'Full available range';
      button.append(name, dates);
      button.addEventListener('click', () => {
        if (active === item.window_id) return;
        select(item.window_id);
      });
      root.append(button);
    });
  };

  persistWindow(active);
  render();
  const selected = windows.find((item) => item.window_id === active);
  return { windowId: active, window: selected, windows, select };
}
