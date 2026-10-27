// Contract 2 T21 (a13): the page shell's module-panel registry. Without modules the shell is unchanged.
import { test } from 'node:test';
import assert from 'node:assert/strict';

import { createPanelLoader } from './app.js';
import { sideChoices, toolbarView } from './learn.js';
import {
  SIDE_PANELS, currentModulePanel, initialModel, modulePanels, ownedByUnit, reduce, sidePanels, topicData,
} from './state.js';

const LAB = { name: 'lab', title: 'Lab', entry: '/modules/lab/lab.js' };

function stateWith(extra = {}) {
  return { unit: { view: 'session' }, controls: {}, ...extra };
}

function withLab(extra = {}) {
  return reduce(initialModel(), { type: 'snapshot', data: stateWith({ modules: [LAB], ...extra }) });
}

test('without modules the side-panel registry is contract 1\'s', () => {
  const model = reduce(initialModel(), { type: 'snapshot', data: stateWith() });
  assert.deepEqual(sidePanels(model), SIDE_PANELS);
  assert.deepEqual(modulePanels(model), []);
  assert.deepEqual(sideChoices(model).map(([p]) => p), ['overview', 'card', 'none']);
  assert.equal(reduce(model, { type: 'side', panel: 'lab' }).ui.side, 'overview');
  assert.equal('pendingSide' in reduce(model, { type: 'side', panel: 'card' }).ui, false);
});

test('a state listing the lab panel adds a Lab side panel and its toolbar choice', () => {
  const model = withLab();
  assert.deepEqual(sidePanels(model), ['overview', 'card', 'lab', 'none']);
  const shown = reduce(model, { type: 'side', panel: 'lab' });
  assert.equal(shown.ui.side, 'lab');
  assert.deepEqual(currentModulePanel(shown), LAB);
  assert.deepEqual(sideChoices(model)[2], ['lab', 'Lab', 'The Lab panel beside the surface']);
  const buttons = [];
  const walk = (node) => {
    if (!node || typeof node !== 'object') return;
    if (Array.isArray(node)) { node.forEach(walk); return; }
    if (node.tag === 'button' && node.props?.data?.side) buttons.push(node.props.data.side);
    walk(node.children);
  };
  walk(toolbarView(shown, {}));
  assert.deepEqual(buttons, ['overview', 'card', 'lab', 'none']);
});

test('a module panel remembered from the last visit is shown once the snapshot lists it', () => {
  let model = reduce(initialModel(), { type: 'side', panel: 'lab' });
  assert.equal(model.ui.side, 'overview');
  model = reduce(model, { type: 'snapshot', data: stateWith({ modules: [LAB] }) });
  assert.equal(model.ui.side, 'lab');
  assert.equal('pendingSide' in model.ui, false);
});

test('topic messages keep the latest payload per topic and kind', () => {
  let model = withLab();
  model = reduce(model, { type: 'topic', topic: 'lab', data: { kind: 'harmony', chord: 'C' } });
  model = reduce(model, { type: 'topic', topic: 'lab', data: { kind: 'lab', active: { layout: 'Tonnetz C' } } });
  model = reduce(model, { type: 'topic', topic: 'lab', data: { kind: 'harmony', chord: 'Am' } });
  assert.equal(topicData(model, 'lab', 'harmony').chord, 'Am');
  assert.equal(topicData(model, 'lab', 'lab').active.layout, 'Tonnetz C');
  assert.equal(topicData(model, 'other'), null);
  assert.equal(reduce(model, { type: 'topic', data: {} }), model);
});

test('in Custom view the page turns the encoder when a module action binds it (A37), not otherwise', () => {
  const custom = (controls) => withLab({ unit: { view: 'custom' }, controls });
  assert.equal(ownedByUnit(custom({ encoder: { label_base: 'CC30 → mpc' } }), 'encoder'), true);
  assert.equal(ownedByUnit(custom({ encoder: { label_base: 'window shift', module_action: 'lab.window_shift' } }), 'encoder'), false);
  assert.equal(ownedByUnit(custom({ encoder: { module_action: 'lab.window_shift' } }), 'strip 1'), true);
});

test('the panel loader imports each module panel once, mounts it and shows the chosen one', async () => {
  const imported = [];
  const created = [];
  const mounted = [];
  const shown = new Map();
  const loader = createPanelLoader({
    importer: async (url) => { imported.push(url); return { mountPanel: (element, context) => mounted.push([element.id, context.panel.name, context.store]) }; },
    container: {
      create: (panel) => { const element = { id: `module-${panel.name}` }; created.push(element.id); return element; },
      show: (element, on) => shown.set(element.id, on),
    },
    context: { store: 'the store' },
  });
  loader.sync(initialModel());
  assert.deepEqual(created, []); // no modules: nothing created
  const model = withLab();
  loader.sync(model);
  loader.sync(reduce(model, { type: 'side', panel: 'lab' }));
  await loader.loaded.get('lab').ready;
  assert.deepEqual(imported, ['/modules/lab/lab.js']);
  assert.deepEqual(created, ['module-lab']);
  assert.deepEqual(mounted, [['module-lab', 'lab', 'the store']]);
  assert.equal(shown.get('module-lab'), true);
});

test('a panel that fails to load says so in its section', async () => {
  const problems = [];
  const loader = createPanelLoader({
    importer: async () => { throw new Error('404'); },
    container: { create: () => ({}), problem: (element, text) => problems.push(text) },
  });
  loader.sync(withLab());
  await loader.loaded.get('lab').ready;
  assert.deepEqual(problems, ['Lab panel could not load: 404']);
});
