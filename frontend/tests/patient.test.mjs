import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import assert from 'node:assert/strict';
import ts from 'typescript';

function loadModule(relativePath) {
  const source = readFileSync(new URL(relativePath, import.meta.url), 'utf8');
  const modExports = {};
  const localRequire = (id) => {
    if (id === './careView' || id.endsWith('/careView')) {
      return loadModule('../app/careView.ts');
    }
    throw new Error(`Unexpected require in test sandbox: ${id}`);
  };
  vm.runInNewContext(
    ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText,
    { exports: modExports, require: localRequire, Intl }
  );
  return modExports;
}

const view = loadModule('../app/patientView.ts');

test('patient navigation has six distinct understandable destinations', () => {
  assert.equal(view.patientSections.length, 6);
  assert.equal(new Set(view.patientSections.map((s) => s.key)).size, 6);
});
test('missing values are not zero, normal, or inferred from patient registry', () => {
  for (const value of [undefined, null, NaN, Infinity]) assert.equal(view.displayValue(value), '—');
  assert.equal(view.displayValue(0), '0');
  assert.match(view.sourceLabel('made-up'), /ไม่ทราบ/);
  assert.match(view.careStateLabel('made-up'), /ไม่ทราบ/);
});
test('patient AI explanation refuses stale, future, missing, and unready analyses', () => {
  const state = { analysis: { status: 'READY', evaluated_at: 100, is_anomaly: false } };
  assert.equal(view.safeAnalysis(state, 110, true), state.analysis);
  assert.equal(view.safeAnalysis(state, 131, true), null);
  assert.equal(view.safeAnalysis(state, 99, true), null);
  assert.equal(view.safeAnalysis(state, 110, false), null);
  assert.equal(view.safeAnalysis({ analysis: { status: 'READY' } }, 110, true), null);
  assert.equal(view.safeAnalysis({ analysis: { status: 'INSUFFICIENT_DATA', evaluated_at: 100 } }, 110, true), null);
});
