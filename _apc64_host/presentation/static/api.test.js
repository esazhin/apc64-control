// s9 collaboration: the requests api.js sends and how 400/409 answers become plain problems (T34).
import test from 'node:test';
import assert from 'node:assert/strict';
import { createApi, problemText, socketUrl } from './api.js';

function fakeFetch(answers = {}) {
  const calls = [];
  const fetch = async (url, init) => {
    calls.push({ url, method: init.method, body: init.body === undefined ? undefined : JSON.parse(init.body) });
    const [status, body] = answers[`${init.method} ${url}`] ?? [200, {}];
    if (status === 'down') throw new TypeError('Failed to fetch');
    return { ok: status >= 200 && status < 300, status, json: async () => body };
  };
  return { fetch, calls };
}

test('every route is called with the method, path and body of docs/api.md', async () => {
  const { fetch, calls } = fakeFetch();
  const api = createApi(fetch);
  await api.state(); await api.surface(); await api.take(); await api.decline(); await api.release();
  await api.ports(); await api.layouts(); await api.validate('name: X', 'x.yaml'); await api.load('Tonnetz C');
  await api.page(3); await api.bank(2); await api.shift(true); await api.press('pad r1c1'); await api.unpress('pad r1c1');
  await api.move('strip 4', 16383); await api.card('pad r1c1'); await api.overview(); await api.versions('jam');
  await api.restore('jam', 'v1'); await api.tweak({ control: 'pad r1c3', field: 'colour', value: 'red', base_hash: 'h' });
  await api.learn('midi', 'mpc', 'pad r2c1'); await api.learn('off'); await api.calibrate('start');
  await api.activity(); await api.deviceLog(50);
  assert.deepEqual(calls.map((c) => `${c.method} ${c.url}`), [
    'GET /api/state', 'GET /api/surface', 'POST /api/unit/take', 'POST /api/unit/decline', 'POST /api/unit/release',
    'GET /api/ports', 'GET /api/layouts', 'POST /api/validate', 'POST /api/layout', 'POST /api/page', 'POST /api/bank',
    'POST /api/shift', 'POST /api/control/pad%20r1c1/press', 'POST /api/control/pad%20r1c1/release',
    'POST /api/control/strip%204/move', 'GET /api/controls/pad%20r1c1', 'GET /api/overview',
    'GET /api/layouts/jam/versions', 'POST /api/layouts/jam/restore', 'POST /api/tweak', 'POST /api/learn',
    'POST /api/learn', 'POST /api/calibrate', 'GET /api/activity?limit=200', 'GET /api/device-log?limit=50',
  ]);
  const bodies = Object.fromEntries(calls.filter((c) => c.body !== undefined).map((c) => [c.url, c.body]));
  assert.deepEqual(bodies['/api/unit/take'], { source: 'banner' });
  assert.deepEqual(bodies['/api/validate'], { text: 'name: X', file: 'x.yaml' });
  assert.deepEqual(bodies['/api/layout'], { name: 'Tonnetz C' });
  assert.deepEqual(bodies['/api/page'], { n: 3 });
  assert.deepEqual(bodies['/api/shift'], { held: true });
  assert.deepEqual(bodies['/api/control/pad%20r1c1/press'], { value: 127 });
  assert.deepEqual(bodies['/api/control/strip%204/move'], { value: 16383 });
  assert.deepEqual(bodies['/api/layouts/jam/restore'], { id: 'v1' });
  assert.deepEqual(calls.filter((c) => c.url === '/api/learn').map((c) => c.body),
    [{ mode: 'midi', port: 'mpc', control: 'pad r2c1' }, { mode: 'off' }]);
});

test('200 answers carry the data; 400 and 409 become the problem with allowed values and issues', async () => {
  const { fetch } = fakeFetch({
    'GET /api/state': [200, { layout: 'jam' }],
    'POST /api/page': [400, { problem: 'page must be 1–8', allowed: [1, 2, 3, 4, 5, 6, 7, 8] }],
    'POST /api/unit/take': [409, { problem: 'Busy: held by Bitwig Studio' }],
    'POST /api/tweak': [400, { problem: 'jam.yaml line 7, pad r1c1: channel must be 1–16', issues: [{ text: 'x' }] }],
    'POST /api/layout': [403, { problem: 'not on the home network' }],
    'POST /api/bank': [500, null],
  });
  const api = createApi(fetch);
  assert.deepEqual(await api.state(), { ok: true, status: 200, data: { layout: 'jam' } });
  const page = await api.page(0);
  assert.equal(page.ok, false);
  assert.equal(page.problem, 'page must be 1–8');
  assert.deepEqual(page.allowed, [1, 2, 3, 4, 5, 6, 7, 8]);
  assert.equal((await api.take()).problem, 'Busy: held by Bitwig Studio');
  const tweak = await api.tweak({});
  assert.match(tweak.problem, /channel must be 1–16/);
  assert.deepEqual(tweak.issues, [{ text: 'x' }]);
  assert.equal((await api.load('x')).problem, 'not on the home network');
  assert.equal((await api.bank(1)).problem, 'Request failed (500).');
});

test('an unreachable host is a problem, not an exception', async () => {
  const { fetch } = fakeFetch({ 'GET /api/state': ['down'] });
  const answer = await createApi(fetch).state();
  assert.deepEqual(answer, { ok: false, status: 0, problem: 'The APC64 host is not reachable.', allowed: null, issues: [] });
  assert.equal(problemText(403, null), 'Refused: not on the home network.');
});

test('socket URLs follow the page', () => {
  assert.equal(socketUrl('/ws', { protocol: 'http:', host: '192.168.1.10:5058' }), 'ws://192.168.1.10:5058/ws');
  assert.equal(socketUrl('/ws/play', { protocol: 'https:', host: 'studio-pc' }), 'wss://studio-pc/ws/play');
});
