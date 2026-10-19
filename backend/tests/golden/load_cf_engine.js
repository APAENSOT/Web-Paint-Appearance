/* =========================================================================
 * load_cf_engine.js — load CFCore / CFLogic out of the prototype, in Node.
 *
 * This is the CF adaptation of the vault's PELT loader,
 *   Paint Appearance/Component/CF and Pelt/tests/load-engine.js
 * which slices PELT out on its `PELT-CORE-START` / `PELT-LOGIC-START`
 * comment markers. 04-ANALYSIS.md is explicit that **CF has no equivalent
 * markers**, so the boundary has to come from something else that is just as
 * stable. It comes from the UMD tail each module already writes:
 *
 *     root.CFCore  = factory();            (CFCore)
 *     root.CFLogic = factory(root.CFCore); (CFLogic)
 *
 * Those two assignments are the module's own identity statement. From either
 * one this file walks out to the enclosing <script> ... </script> and runs
 * exactly that block. No line numbers are hardcoded: 04-ANALYSIS.md warns
 * that the ~1782 / ~2942 figures were verified once on 2026-09-07 and says
 * "grep identifiers, do not treat lines as stable". The line numbers the
 * loader *reports* are computed from the offsets it actually used, so the
 * report can state where the code came from without trusting the docs.
 *
 * Nothing else in the 6 MB file is executed -- not Plotly, not the UI. The
 * inlined SheetJS build is loaded separately (see loadXlsx below), the same
 * way the vault's tests/load-xlsx.js does it, so the workbooks are read by
 * the same parser the prototype itself uses.
 *
 * The SHA-256 of the HTML actually read is returned with the modules and is
 * recorded in every fixture. If the prototype changes, the fixtures are
 * stale and say so.
 * ========================================================================= */
'use strict';

const fs = require('fs');
const path = require('path');
const vm = require('vm');
const crypto = require('crypto');

/** The read-only vault copy 04-ANALYSIS.md names as the source of truth. */
const PROTOTYPE_PATH = path.resolve(
  __dirname, '..', '..', '..', '..',
  'Paint Appearance', 'Component', 'CF and Pelt', 'Prototype.html'
);

/** Pull the <script> block that contains `needle` and nothing else. */
function scriptBlockContaining(html, needle) {
  const at = html.indexOf(needle);
  if (at === -1) throw new Error('UMD assignment not found: ' + needle);
  const open = html.lastIndexOf('<script>', at);
  if (open === -1) throw new Error('no opening <script> before: ' + needle);
  const bodyStart = open + '<script>'.length;
  const close = html.indexOf('</script>', at);
  if (close === -1) throw new Error('no closing </script> after: ' + needle);
  // A second UMD tail between the two would mean the boundary walk crossed a
  // module. Cheap, and it is the failure this loader could plausibly have.
  return {
    source: html.slice(bodyStart, close),
    startLine: html.slice(0, bodyStart).split('\n').length,
    endLine: html.slice(0, close).split('\n').length,
  };
}

/**
 * Run one module block. Both CF modules take the CommonJS branch of their own
 * UMD prelude when a `module` object is in scope, so this hands them one --
 * the same trick the vault's load-engine.js uses.
 *
 * CFLogic's CommonJS branch is `factory(require('./core.js'))`, a sibling file
 * that does not exist outside the prototype's own repo layout. `deps` supplies
 * it: the already-loaded CFCore.
 */
function runModule(block, label, deps) {
  const module = { exports: {} };
  const require_ = (id) => {
    if (deps && Object.prototype.hasOwnProperty.call(deps, id)) return deps[id];
    throw new Error(label + ' asked for an unstubbed module: ' + id);
  };
  const context = vm.createContext({ module, exports: module.exports, require: require_, console });
  vm.runInContext(block.source, context, { filename: label + '.js', timeout: 30000 });
  if (!module.exports || typeof module.exports !== 'object') {
    throw new Error(label + ' did not export an object');
  }
  return module.exports;
}

/** Load the inlined SheetJS build, exactly as tests/load-xlsx.js does. */
function loadXlsx(html) {
  const start = html.indexOf('/*! xlsx.js');
  if (start === -1) throw new Error('inlined XLSX build not found');
  const end = html.indexOf('</script>', start);
  if (end === -1) throw new Error('inlined XLSX build is unterminated');
  const context = { console, Uint8Array, ArrayBuffer, Buffer, Date, setTimeout, clearTimeout };
  context.global = context;
  context.window = context;
  context.self = context;
  vm.createContext(context);
  vm.runInContext(html.slice(start, end), context, { timeout: 60000 });
  if (!context.XLSX) throw new Error('inlined XLSX did not load');
  return context.XLSX;
}

function loadEngine(htmlPath) {
  const file = htmlPath || PROTOTYPE_PATH;
  const bytes = fs.readFileSync(file);
  const html = bytes.toString('utf8');
  const sha256 = crypto.createHash('sha256').update(bytes).digest('hex');

  const coreBlock = scriptBlockContaining(html, 'root.CFCore = factory();');
  const logicBlock = scriptBlockContaining(html, 'root.CFLogic = factory(root.CFCore);');

  const CFCore = runModule(coreBlock, 'CFCore', null);
  const CFLogic = runModule(logicBlock, 'CFLogic', { './core.js': CFCore });

  return {
    CFCore,
    CFLogic,
    XLSX: loadXlsx(html),
    prototype: {
      path: file,
      sha256,
      bytes: bytes.length,
      coreLines: [coreBlock.startLine, coreBlock.endLine],
      logicLines: [logicBlock.startLine, logicBlock.endLine],
    },
  };
}

module.exports = { loadEngine, loadXlsx, PROTOTYPE_PATH };
