/* =========================================================================
 * build_fixtures.js — freeze the CF grading oracle.
 *
 *   node backend/tests/golden/build_fixtures.js
 *
 * Runs the prototype's own CFCore against the read-only WaveScan workbooks in
 * the vault and writes JSON fixtures under ./fixtures/. The workbooks are
 * never copied here (03-SECURITY.md section 8); only their SHA-256 and the
 * numbers the oracle produced are.
 *
 * ORACLE GRAIN -- stated here as well as in docs/reports/T05-GOLDEN.md.
 *
 * One fixture row per measurement row, which is one record out of
 * `CFCore.parseSheets` after its own dedupe, graded by `CFCore.zoneStatuses`
 * (~2864). That function is the prototype's per-checkzone detail table, and it
 * is the only place in the prototype that grades a single reading rather than
 * a group average. Its status line is:
 *
 *     pair   = stdPair(targetsFor(rec.family, standards, rec.color), rec.orient)
 *     hasStd = pair.ford !== null
 *     status = hasStd ? statusOf(rec.cf, pair.ford, pair.min) : null
 *
 * `standards` is passed as **null**, so `targetsFor` takes its first branch and
 * every target comes from DEFAULT_STANDARDS. There are therefore **no colour
 * overrides in this freeze** and no colour map is written into this repo. D2
 * stays open; `ref_color.grading_family` stays NULL.
 *
 * This is a REGRESSION ORACLE, not the product KPI. D1 (whether the dashboard
 * groups by checkzone, by colour x orientation, or by both) is untouched by it.
 *
 * A second fixture, boundary.json, is generated from the same loaded CFCore
 * over a synthetic grid: the EPS edges, non-finite values, missing specs,
 * unknown families, the legacy flat standards shape, and the colour-override
 * fall-through of `targetsFor`. Real workbook data lands almost nowhere near a
 * band edge, so without it a mutant epsilon would survive.
 * ========================================================================= */
'use strict';

const fs = require('fs');
const path = require('path');
const crypto = require('crypto');
const { loadEngine } = require('./load_cf_engine.js');

const FIXTURE_DIR = path.join(__dirname, 'fixtures');
const VAULT_WAVESCAN = path.resolve(
  __dirname, '..', '..', '..', '..',
  'Paint Appearance', 'Component', 'Database', 'Excel Template', 'WaveScan'
);

/** Stable key order, so a re-run produces a byte-identical file. */
function writeJson(name, value) {
  const file = path.join(FIXTURE_DIR, name);
  fs.writeFileSync(file, JSON.stringify(value, null, 2) + '\n', 'utf8');
  const sha = crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
  console.log('  wrote ' + name + '  sha256=' + sha.slice(0, 16) + '...');
  return sha;
}

function findWorkbooks(root) {
  const out = [];
  if (!fs.existsSync(root)) return out;
  for (const plant of fs.readdirSync(root).sort()) {
    const dir = path.join(root, plant);
    if (!fs.statSync(dir).isDirectory()) continue;
    for (const name of fs.readdirSync(dir).sort()) {
      // "~$..." is Excel's lock file, not a workbook.
      if (name.startsWith('~$')) continue;
      if (!/\.xlsx?$/i.test(name)) continue;
      out.push({ plant, name, file: path.join(dir, name) });
    }
  }
  return out;
}

/** Feed the workbook to CFCore the way the prototype's own importer does. */
function sheetsOf(XLSX, buffer) {
  const wb = XLSX.read(buffer, { type: 'buffer', cellDates: false });
  return wb.SheetNames.map((name) => ({
    name,
    rows: XLSX.utils.sheet_to_json(wb.Sheets[name], { header: 1, raw: true, defval: null }),
  }));
}

function histogram(rows, key) {
  const out = {};
  for (const r of rows) {
    const k = r[key] === null ? '(null)' : String(r[key]);
    out[k] = (out[k] || 0) + 1;
  }
  return Object.keys(out).sort().reduce((acc, k) => ((acc[k] = out[k]), acc), {});
}

/* ---------------------------------------------------------------------
 * 1. The workbook oracle
 * ------------------------------------------------------------------ */
function buildWorkbookFixture(engine) {
  const { CFCore, XLSX } = engine;
  const books = findWorkbooks(VAULT_WAVESCAN);
  const files = [];
  const rows = [];

  for (const book of books) {
    const bytes = fs.readFileSync(book.file);
    let parsed;
    try {
      parsed = CFCore.parseSheets(sheetsOf(XLSX, bytes), { filename: book.name });
    } catch (err) {
      files.push({
        plant: book.plant, file: book.name,
        sha256: crypto.createHash('sha256').update(bytes).digest('hex'),
        bytes: bytes.length, rows: 0, skipped: 'parse failed: ' + err.message,
      });
      console.log('  ! ' + book.name + ' -- parse failed: ' + err.message);
      continue;
    }

    // standards = null: DEFAULT_STANDARDS only, no colour overrides.
    const graded = CFCore.zoneStatuses(parsed.records, null);
    const first = rows.length;
    for (const g of graded) {
      rows.push({
        row: rows.length,
        family: g.family === undefined ? null : g.family,
        orient: g.orient,
        cf: g.cf,
        ford: g.ford,
        min: g.minStd,
        status: g.status,
      });
    }
    const mine = rows.slice(first);
    files.push({
      plant: book.plant,
      file: book.name,
      sha256: crypto.createHash('sha256').update(bytes).digest('hex'),
      bytes: bytes.length,
      sheets: parsed.records.length ? undefined : 0,
      rows: mine.length,
      firstRow: first,
      status: histogram(mine, 'status'),
      family: histogram(mine, 'family'),
      orient: histogram(mine, 'orient'),
    });
    console.log('  ' + book.plant + '/' + book.name + ' -> ' + mine.length + ' rows');
  }

  return {
    _readme:
      'Generated by backend/tests/golden/build_fixtures.js from the prototype ' +
      'named in .prototype. One entry per measurement row: (family, orient, cf) ' +
      'are the inputs, (ford, min, status) are what the prototype produced with ' +
      'standards=null. Do not hand-edit. Regenerate, and say so in the report.',
    grain: 'per measurement row; CFCore.zoneStatuses(parseSheets(book).records, null)',
    standards: 'DEFAULT_STANDARDS only (targetsFor(family, null, color)); no colour overrides',
    generatedBy: 'backend/tests/golden/build_fixtures.js',
    prototype: engine.prototype,
    source: 'Paint Appearance/Component/Database/Excel Template/WaveScan (read-only; not copied)',
    files,
    totals: {
      rows: rows.length,
      status: histogram(rows, 'status'),
      family: histogram(rows, 'family'),
      orient: histogram(rows, 'orient'),
    },
    rows,
  };
}

/* ---------------------------------------------------------------------
 * 2. The boundary oracle
 *
 * Every case here is answered by the loaded prototype, never by hand. The
 * point is coverage the real data cannot give: an exact band edge, an EPS
 * step either side of it, a non-finite reading, a family with no spec, and
 * the two `targetsFor` branches (per-colour override, legacy flat shape)
 * that the workbook freeze deliberately does not exercise.
 * ------------------------------------------------------------------ */
function buildBoundaryFixture(engine) {
  const { CFCore } = engine;
  const EPS = 1e-9;
  const cases = [];

  const families = Object.keys(CFCore.DEFAULT_STANDARDS).concat(['Unknown Family', null]);
  const orients = ['H', 'V'];

  for (const family of families) {
    for (const orient of orients) {
      const std = CFCore.targetsFor(family, null, null);
      const pair = CFCore.stdPair(std, orient);
      // 1e-7 is the probe that pins EPS to the prototype's value. It sits
      // inside a 1e-6 tolerance and outside a 1e-9 one, so an epsilon
      // "tidied up" to a rounder number changes this row's band and gets
      // caught. The EPS-scaled probes either side of it cannot do that on
      // their own -- they move with the number being tested.
      const edges = [];
      if (pair.min !== null && pair.min !== undefined) {
        edges.push(pair.min - 1, pair.min - 1e-7, pair.min - EPS, pair.min - EPS / 2,
                   pair.min, pair.min + EPS, pair.min + 1e-7, pair.min + 1);
      }
      if (pair.ford !== null && pair.ford !== undefined) {
        edges.push(pair.ford - 1, pair.ford - 1e-7, pair.ford - EPS, pair.ford - EPS / 2,
                   pair.ford, pair.ford + EPS, pair.ford + 1e-7, pair.ford + 1);
      }
      // Values that must survive the port unchanged, spec or no spec.
      edges.push(0, -1, 100, 49.95, 50.2000007629395, NaN, Infinity, -Infinity, null);

      for (const cf of edges) {
        const hasStd = pair.ford !== null && pair.ford !== undefined;
        cases.push({
          case: cases.length,
          family,
          orient,
          cf: Number.isFinite(cf) ? cf : (cf === null ? null : String(cf)),
          ford: pair.ford === undefined ? null : pair.ford,
          min: pair.min === undefined ? null : pair.min,
          // Both are frozen: `statusOf` on its own (which does NOT guard a
          // null spec) and the guarded call site zoneStatuses uses.
          statusOfRaw: CFCore.statusOf(cf, pair.ford, pair.min),
          status: hasStd ? CFCore.statusOf(cf, pair.ford, pair.min) : null,
        });
      }
    }
  }

  /* targetsFor's resolution chain, answered by the prototype. */
  const OVERRIDE = { fordH: 99, fordV: 98, minH: 97, minV: 96 };
  const FAMILY_EDIT = { fordH: 70, fordV: 60, minH: 65, minV: 55 };
  const resolutionCases = [
    { label: 'no standards -> DEFAULT_STANDARDS',
      family: 'Light Solids', color: 'Arctic White', standards: null },
    { label: 'per-colour override with targets wins',
      family: 'Light Solids', color: 'Arctic White',
      standards: { families: {}, colors: { 'Arctic White': OVERRIDE } } },
    { label: 'per-colour entry without targets falls through to family (Phase 6)',
      family: 'Light Solids', color: 'Arctic White',
      standards: { families: { 'Light Solids': FAMILY_EDIT }, colors: { 'Arctic White': { family: 'Light Solids' } } } },
    { label: 'edited family beats the default',
      family: 'Light Solids', color: 'Arctic White',
      standards: { families: { 'Light Solids': FAMILY_EDIT }, colors: {} } },
    { label: 'family absent from an edited set falls back to the default',
      family: 'Dark Solids', color: 'Ebony',
      standards: { families: { 'Light Solids': FAMILY_EDIT }, colors: {} } },
    { label: 'legacy flat shape is still accepted',
      family: 'Light Solids', color: 'Arctic White',
      standards: { 'Light Solids': FAMILY_EDIT } },
    { label: 'unknown family, no standards -> null',
      family: 'Unknown Family', color: 'Nothing', standards: null },
    { label: 'colour override is ignored when the colour does not match',
      family: 'Light Solids', color: 'Ebony',
      standards: { families: {}, colors: { 'Arctic White': OVERRIDE } } },
  ];

  const resolution = resolutionCases.map((c, i) => {
    const std = CFCore.targetsFor(c.family, c.standards, c.color);
    return {
      case: i,
      label: c.label,
      family: c.family,
      color: c.color,
      standards: c.standards,
      targets: std === null || std === undefined ? null : std,
      pairH: CFCore.stdPair(std, 'H'),
      pairV: CFCore.stdPair(std, 'V'),
    };
  });

  return {
    _readme:
      'Generated by backend/tests/golden/build_fixtures.js. Synthetic inputs, ' +
      'prototype answers. Covers the band edges and the targetsFor chain that ' +
      'the workbook freeze cannot reach. Do not hand-edit.',
    grain: 'one case per (family, orientation, probe value); prototype-answered',
    prototype: engine.prototype,
    eps: EPS,
    defaultStandards: CFCore.DEFAULT_STANDARDS,
    colorFamilyOrder: CFCore.COLOR_FAMILY_ORDER,
    cases,
    resolution,
  };
}

/* ---------------------------------------------------------------------
 * 3. The orientation fixture
 *
 * `stdPair` routes on H/V, and T05 is explicit that orientation must come
 * from `wavescan.tolerance_group` -- there must not be a second orientation
 * implementation. `domain/cleaner.py` already derives it (T04's
 * `derive_tolerance`). This freezes the prototype's `orientationOf` over every
 * distinct checkzone string the vault workbooks actually contain, so a pytest
 * can prove the two rules agree instead of asserting they look similar.
 * ------------------------------------------------------------------ */
function buildOrientationFixture(engine) {
  const { CFCore, XLSX } = engine;
  const seen = new Map();
  for (const book of findWorkbooks(VAULT_WAVESCAN)) {
    let parsed;
    try {
      parsed = CFCore.parseSheets(sheetsOf(XLSX, fs.readFileSync(book.file)), { filename: book.name });
    } catch (err) {
      continue;
    }
    for (const rec of parsed.records) {
      const zone = String(rec.zone === null || rec.zone === undefined ? '' : rec.zone);
      if (!seen.has(zone)) seen.set(zone, CFCore.orientationOf(rec.zone));
    }
  }
  const zones = [...seen.keys()].sort().map((zone) => ({ zone, orient: seen.get(zone) }));
  return {
    _readme:
      'Generated by backend/tests/golden/build_fixtures.js. Every distinct ' +
      'checkzone string in the vault workbooks, with the orientation the ' +
      'prototype derives from it (CFCore.orientationOf, ~2132). Python must ' +
      'reach the same answer through domain.cleaner.derive_tolerance -- one ' +
      'orientation rule, not two.',
    prototype: engine.prototype,
    rule: "orientationOf(zone) = /(HOOD|ROOF)/i.test(zone) ? 'H' : 'V'",
    zones,
    totals: { zones: zones.length, orient: histogram(zones, 'orient') },
  };
}

/* ------------------------------------------------------------------ */
function main() {
  const engine = loadEngine();
  console.log('prototype ' + engine.prototype.path);
  console.log('  sha256 ' + engine.prototype.sha256);
  console.log('  CFCore  lines ' + engine.prototype.coreLines.join('-'));
  console.log('  CFLogic lines ' + engine.prototype.logicLines.join('-'));

  if (!fs.existsSync(FIXTURE_DIR)) fs.mkdirSync(FIXTURE_DIR, { recursive: true });

  console.log('\nworkbooks:');
  const workbook = buildWorkbookFixture(engine);
  if (!workbook.rows.length) {
    console.log('  ! no rows -- vault absent or every workbook failed to parse');
  }
  writeJson('wavescan_rows.json', workbook);

  console.log('\nboundaries:');
  const boundary = buildBoundaryFixture(engine);
  writeJson('boundary.json', boundary);

  console.log('\norientation:');
  const orientation = buildOrientationFixture(engine);
  writeJson('orientation.json', orientation);

  console.log('\n' + workbook.totals.rows + ' workbook rows, ' +
    boundary.cases.length + ' boundary cases, ' +
    boundary.resolution.length + ' resolution cases, ' +
    orientation.zones.length + ' distinct checkzones');
}

if (require.main === module) main();
module.exports = {
  buildWorkbookFixture, buildBoundaryFixture, buildOrientationFixture, VAULT_WAVESCAN,
};
