import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import assert from 'node:assert/strict';
import ts from 'typescript';

const source = readFileSync(new URL('../app/vitalView.ts', import.meta.url), 'utf8');
const view = {};
vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, { exports: view });

test('vital summaries never turn missing data into zero', () => {
  const summary = view.vitalSummary([{ heart_rate: null }, {}, { heart_rate: NaN }, { heart_rate: 78 }, { heart_rate: 82 }], 'heart_rate');
  assert.deepEqual(JSON.parse(JSON.stringify(summary)), { count: 2, latest: 82, min: 78, max: 82 });
  assert.equal(view.finiteVital(undefined), null);
  assert.equal(view.finiteVital(Infinity), null);
  assert.equal(view.finiteVital(0), 0);
});

test('all three monitored vital signs have labels, units and distinct colors', () => {
  assert.deepEqual(Array.from(view.vitalKeys), ['heart_rate', 'spo2', 'respiratory_rate']);
  assert.equal(new Set(view.vitalKeys.map((key) => view.vitalMeta[key].color)).size, 3);
  for (const key of view.vitalKeys) assert.ok(view.vitalMeta[key].label && view.vitalMeta[key].unit);
});
