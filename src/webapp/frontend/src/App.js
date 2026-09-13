// Tiny framework-free "component": renders backend health and shows which HTTP
// version actually carried the request, which is how an HTTP/3 upgrade becomes
// visible in the browser.
//
// Two API bases exist on purpose (see apps/base/webapp/README.md):
//   - same-origin `/api`  -> proxied by nginx over TCP (HTTP/1.1 or h2)
//   - VITE_API_BASE       -> the HTTP/3-capable origin (UDP/443, bypasses ingress)
export const SAME_ORIGIN_API = '/api';
export const HTTP3_API = import.meta.env?.VITE_API_BASE || '';

export function render(state) {
  const rows = Object.entries(state.payload || {})
    .map(([key, value]) => `<tr><th>${key}</th><td>${String(value)}</td></tr>`)
    .join('');

  return `
    <h1>homelab webapp</h1>
    <p class="source">source: <code>${state.source}</code></p>
    <p class="status ${state.ok ? 'ok' : 'error'}">${state.ok ? 'backend reachable' : state.error}</p>
    <table>${rows}</table>
    <p class="hint">
      Reload once, then check DevTools &rarr; Network &rarr; Protocol. The first
      response carries <code>alt-svc: h3=":443"</code>; subsequent requests to the
      HTTP/3 origin should report <code>h3</code>.
    </p>
  `;
}

export async function fetchHealth(base = SAME_ORIGIN_API, fetchImpl = fetch) {
  const url = `${base.replace(/\/$/, '')}/health`;
  try {
    const response = await fetchImpl(url, { headers: { accept: 'application/json' } });
    if (!response.ok) {
      return { ok: false, source: url, error: `HTTP ${response.status}`, payload: {} };
    }
    return { ok: true, source: url, payload: await response.json() };
  } catch (error) {
    return { ok: false, source: url, error: String(error), payload: {} };
  }
}

export async function mountApp(root, base = HTTP3_API || SAME_ORIGIN_API) {
  root.innerHTML = render({ ok: false, source: base, error: 'loading…', payload: {} });
  const state = await fetchHealth(base);
  root.innerHTML = render(state);
  return state;
}
