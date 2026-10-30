import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import assert from 'node:assert/strict';
import ts from 'typescript';

const source = readFileSync(new URL('../app/careView.ts', import.meta.url), 'utf8');
const exported = {};
vm.runInNewContext(ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText, { exports: exported });
const ranges = (fields = {}) => {
  const form = new FormData();
  for (const [key, value] of Object.entries(fields)) form.set(key, value);
  return JSON.parse(JSON.stringify(exported.formRanges(form)));
};

test('daily report date follows Bangkok midnight, not browser timezone', () => {
  assert.equal(exported.bangkokDay(new Date('2026-09-28T16:59:59Z')), '2026-09-28');
  assert.equal(exported.bangkokDay(new Date('2026-09-28T17:00:00Z')), '2026-09-29');
});

test('empty personal ranges stay unknown instead of becoming zero or defaults', () => {
  assert.deepEqual(ranges(), {});
  assert.deepEqual(ranges({ heart_rate_low: ' ', heart_rate_high: '' }), {});
  assert.deepEqual(ranges({ heart_rate_low: '70', heart_rate_high: '100' }), { heart_rate: { low: 70, high: 100 } });
});

test('personal ranges reject partial, reversed, nonfinite and unsupported values', () => {
  for (const fields of [
    { heart_rate_low: '70' }, { heart_rate_low: '100', heart_rate_high: '70' },
    { heart_rate_low: '70', heart_rate_high: 'NaN' }, { heart_rate_low: '0', heart_rate_high: '100' },
    { spo2_low: '90', spo2_high: '101' }, { respiratory_rate_low: '10', respiratory_rate_high: '81' },
  ]) assert.throws(() => ranges(fields));
});
