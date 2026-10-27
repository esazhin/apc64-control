// The page's side of the HTTP API (docs/api.md). Every call answers {ok, status, data} or
// {ok: false, status, problem, allowed, issues}: 400/409 bodies become one plain sentence for the page.

export function problemText(status, data) {
  if (status === 0) return 'The APC64 host is not reachable.';
  const problem = data && typeof data === 'object' ? data.problem : null;
  if (problem) return problem;
  if (status === 403) return 'Refused: not on the home network.';
  return `Request failed (${status}).`;
}

export function createApi(fetchImpl = (...args) => globalThis.fetch(...args), base = '') {
  async function call(method, path, body) {
    const init = { method, headers: { Accept: 'application/json' } };
    if (body !== undefined) {
      init.headers['Content-Type'] = 'application/json';
      init.body = JSON.stringify(body);
    }
    let response;
    try {
      response = await fetchImpl(base + path, init);
    } catch {
      return { ok: false, status: 0, problem: problemText(0), allowed: null, issues: [] };
    }
    let data = null;
    try { data = await response.json(); } catch { data = null; }
    if (response.ok) return { ok: true, status: response.status, data };
    return {
      ok: false, status: response.status, data, problem: problemText(response.status, data),
      allowed: data?.allowed ?? null, issues: data?.issues ?? [],
    };
  }
  const c = (name) => encodeURIComponent(name);
  return {
    call,
    state: () => call('GET', '/api/state'),
    surface: () => call('GET', '/api/surface'),
    take: () => call('POST', '/api/unit/take', { source: 'banner' }),
    decline: () => call('POST', '/api/unit/decline', {}),
    release: () => call('POST', '/api/unit/release', {}),
    ports: () => call('GET', '/api/ports'),
    layouts: () => call('GET', '/api/layouts'),
    validate: (text, file) => call('POST', '/api/validate', { text, file }),
    load: (name) => call('POST', '/api/layout', { name }),
    page: (n) => call('POST', '/api/page', { n }),
    bank: (n) => call('POST', '/api/bank', { n }),
    shift: (held) => call('POST', '/api/shift', { held: Boolean(held) }),
    press: (control, value = 127) => call('POST', `/api/control/${c(control)}/press`, { value }),
    unpress: (control) => call('POST', `/api/control/${c(control)}/release`, {}),
    move: (control, value) => call('POST', `/api/control/${c(control)}/move`, { value }),
    card: (control) => call('GET', `/api/controls/${c(control)}`),
    overview: () => call('GET', '/api/overview'),
    versions: (layout) => call('GET', `/api/layouts/${c(layout)}/versions`),
    restore: (layout, id) => call('POST', `/api/layouts/${c(layout)}/restore`, { id }),
    tweak: (request) => call('POST', '/api/tweak', request),
    learn: (mode, port, control) => {
      const body = { mode };
      if (port) body.port = port;
      if (control) body.control = control;
      return call('POST', '/api/learn', body);
    },
    calibrate: (step) => call('POST', '/api/calibrate', { step }),
    activity: (limit = 200) => call('GET', `/api/activity?limit=${limit}`),
    deviceLog: (limit = 200) => call('GET', `/api/device-log?limit=${limit}`),
  };
}

// The socket URL for /ws or /ws/play, next to the page.
export function socketUrl(path, loc = globalThis.location) {
  const scheme = loc.protocol === 'https:' ? 'wss' : 'ws';
  return `${scheme}://${loc.host}${path}`;
}
