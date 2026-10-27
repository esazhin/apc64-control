// Shared test data for the page's node --test suites (not loaded by the page).
export function snapshot(overrides = {}) {
  return {
    unit: { status: 'held', text: 'Held', held: true, holder: null, taken_by: 'banner', firmware: '1.2.1.6',
      warnings: [], notices: [], view: 'session' },
    layout: 'jam', layout_name: 'Jam', file_deleted: false,
    page: { n: 1, name: 'Drums', display: 'Drums', defined: true, current: true },
    bank: { n: 1, name: 'Mix', display: 'Mix', defined: true, current: true },
    shift: false,
    pages: [1, 2, 3, 4, 5, 6, 7, 8].map((n) => ({ n, name: n === 1 ? 'Drums' : null, display: n === 1 ? 'Drums' : '',
      defined: n === 1, current: n === 1 })),
    banks: [1, 2, 3, 4, 5, 6].map((n) => ({ n, name: n === 1 ? 'Mix' : null, display: n === 1 ? 'Mix' : '',
      defined: n === 1, current: n === 1 })),
    controls: {
      'pad r1c1': { label_base: 'Note 36 → mpc', label_shift: 'Note 48 → mpc', empty: false, missing: [], toggle: null,
        led: { colour: 5, behaviour: 1, rgb: '#ff0000', brightness: 0.25, animation: null, off: false }, bar: null,
        role: 'bindable', selected: false },
      'pad r8c8': { label_base: '', label_shift: '', empty: true, missing: [], toggle: null,
        led: { colour: 0, behaviour: 6, rgb: '#000000', brightness: 0, animation: null, off: true }, bar: null,
        role: 'bindable', selected: false },
    },
    oled: ['Jam', 'P1 Drums | B1'], errors: [], warnings: [],
    routing: { notes: 'mpc ch 2', custom: null, status: '' },
    calibration: null, calibration_label: 'pad position unknown', calibration_step: 'idle',
    learn: { mode: 'off', selected: null, port: null, device: null, last: null },
    played: [], layouts: [{ id: 'jam', name: 'Jam', file: 'jam.yaml', valid: true, pages: 1, banks: 1 }],
    ...overrides,
  };
}
