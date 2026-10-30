import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import assert from 'node:assert/strict';
import ts from 'typescript';

const source = readFileSync(new URL('../app/evidenceView.ts', import.meta.url), 'utf8');
const exported = {};
vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, { exports: exported });
const point = (second, heart_rate) => ({ second, heart_rate, spo2: 98, respiratory_rate: 18 });

test('forecast marker never invents a future observation or changes the input', () => {
  const input = [point(58, 80), point(59, 82)], observed = [point(60, 81)];
  const before = JSON.stringify(input);
  const result = exported.replayChart(input, observed, 89, 85, 82, 'heart_rate');
  assert.equal(result.at(-1).actual, null);
  assert.equal(result.at(-1).forecast, 85);
  assert.equal(result.at(-1).baseline, 82);
  assert.equal(result[2].actual, 81);
  assert.equal(JSON.stringify(input), before);
});

test('revealed target has one actual point and frozen forecast', () => {
  const result = exported.replayChart([point(59, 82)], [point(89, 90)], 89, 85, 82, 'heart_rate');
  assert.equal(result.length, 2);
  assert.equal(result[1].actual, 90);
  assert.equal(result[1].forecast, 85);
});

test('abstention omits forecast and missing metrics are not converted to zero', () => {
  const result = exported.replayChart([point(10, 80)], [], 40, null, 80, 'heart_rate');
  assert.equal(result.length, 1);
  assert.equal(result[0].forecast, null);
  for (const value of [undefined, null, NaN, Infinity]) assert.equal(exported.metric(value), '—');
  assert.equal(exported.metric(0), '0.00');
});
