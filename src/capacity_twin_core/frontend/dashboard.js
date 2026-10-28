/* Small, dependency-free helpers shared by local dashboards. */

export async function apiJson(url, options = {}, timeoutMs = 15000) {
  const controller = new AbortController();
  const timeout = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetch(url, {
      ...options,
      signal: controller.signal,
      headers: {
        Accept: 'application/json',
        'Content-Type': 'application/json',
        ...(options.headers || {}),
      },
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(body.detail || `Request failed (${response.status})`);
    }
    return body;
  } finally {
    window.clearTimeout(timeout);
  }
}

export function readableLabel(key) {
  return key.replaceAll('_', ' ').replace(/\b\w/g, (letter) => letter.toUpperCase());
}

export function appendTextCell(row, value) {
  const cell = document.createElement('td');
  cell.textContent = value == null ? '-' : String(value);
  row.append(cell);
}
