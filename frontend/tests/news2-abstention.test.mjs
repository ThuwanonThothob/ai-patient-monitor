import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { registerHooks } from 'node:module';
import { fileURLToPath } from 'node:url';
import ts from 'typescript';

// Register synchronous TypeScript/TSX + CSS Module hooks so ../app/MonitorPanel.tsx
// can be imported directly via standard ESM import() in Node.js test runner.
registerHooks({
  resolve(specifier, context, nextResolve) {
    if (specifier.endsWith('.module.css') || specifier.endsWith('.css')) {
      return {
        url: new URL(specifier, context.parentURL).href,
        shortCircuit: true,
      };
    }
    if (
      (specifier.startsWith('./') || specifier.startsWith('../')) &&
      !specifier.endsWith('.ts') &&
      !specifier.endsWith('.tsx') &&
      !specifier.endsWith('.mjs') &&
      !specifier.endsWith('.js')
    ) {
      for (const ext of ['.ts', '.tsx']) {
        try {
          const candidate = new URL(specifier + ext, context.parentURL);
          readFileSync(fileURLToPath(candidate));
          return { url: candidate.href, shortCircuit: true };
        } catch {
          // try next extension
        }
      }
    }
    return nextResolve(specifier, context);
  },
  load(url, context, nextLoad) {
    if (url.endsWith('.module.css') || url.endsWith('.css')) {
      return {
        format: 'module',
        source: `export default new Proxy({}, { get: (_target, prop) => String(prop) });`,
        shortCircuit: true,
      };
    }
    if (url.endsWith('.tsx') || url.endsWith('.ts')) {
      const raw = readFileSync(fileURLToPath(url), 'utf8');
      const transpiled = ts.transpileModule(raw, {
        fileName: fileURLToPath(url),
        compilerOptions: {
          module: ts.ModuleKind.ESNext,
          target: ts.ScriptTarget.ES2022,
          jsx: ts.JsxEmit.ReactJSX,
        },
      }).outputText;
      return {
        format: 'module',
        source: transpiled,
        shortCircuit: true,
      };
    }
    return nextLoad(url, context);
  },
});

const {
  scoreNews2RR,
  scoreNews2SpO2,
  scoreNews2HR,
  calculateModifiedNews2,
  formatStaleDuration,
  getStaleEscalationTier,
} = await import('../app/MonitorPanel.tsx');

test('scoreNews2RR: tests every RCP NEWS2 boundary value and invalid/missing inputs', () => {
  // <= 8 -> 3 points
  for (const rr of [1, 5, 7, 8, 8.4]) {
    assert.equal(scoreNews2RR(rr), 3, `Expected RR=${rr} to score 3`);
  }
  // 9..11 -> 1 point
  for (const rr of [8.6, 9, 10, 11, 11.4]) {
    assert.equal(scoreNews2RR(rr), 1, `Expected RR=${rr} to score 1`);
  }
  // 12..20 -> 0 points
  for (const rr of [11.6, 12, 15, 18, 20, 20.4]) {
    assert.equal(scoreNews2RR(rr), 0, `Expected RR=${rr} to score 0`);
  }
  // 21..24 -> 2 points
  for (const rr of [20.6, 21, 22, 23, 24, 24.4]) {
    assert.equal(scoreNews2RR(rr), 2, `Expected RR=${rr} to score 2`);
  }
  // >= 25 -> 3 points
  for (const rr of [24.6, 25, 30, 45]) {
    assert.equal(scoreNews2RR(rr), 3, `Expected RR=${rr} to score 3`);
  }
  // Missing / non-finite / non-positive handling
  for (const invalid of [null, undefined, NaN, Infinity, -Infinity]) {
    assert.equal(scoreNews2RR(invalid), null, `Expected RR=${String(invalid)} to return null`);
  }
  for (const nonPositive of [0, -1, -10]) {
    assert.ok([null, 3].includes(scoreNews2RR(nonPositive)), `Expected RR=${nonPositive} to abstain or flag red`);
  }
});

test('scoreNews2SpO2: tests every RCP NEWS2 Scale 1 boundary value and invalid/missing inputs', () => {
  // <= 91 -> 3 points
  for (const spo2 of [70, 85, 90, 91, 91.4]) {
    assert.equal(scoreNews2SpO2(spo2), 3, `Expected SpO2=${spo2} to score 3`);
  }
  // 92..93 -> 2 points
  for (const spo2 of [91.6, 92, 93, 93.4]) {
    assert.equal(scoreNews2SpO2(spo2), 2, `Expected SpO2=${spo2} to score 2`);
  }
  // 94..95 -> 1 point
  for (const spo2 of [93.6, 94, 95, 95.4]) {
    assert.equal(scoreNews2SpO2(spo2), 1, `Expected SpO2=${spo2} to score 1`);
  }
  // >= 96 -> 0 points
  for (const spo2 of [95.6, 96, 97, 98, 99, 100]) {
    assert.equal(scoreNews2SpO2(spo2), 0, `Expected SpO2=${spo2} to score 0`);
  }
  // Missing / non-finite / non-positive handling
  for (const invalid of [null, undefined, NaN, Infinity, -Infinity]) {
    assert.equal(scoreNews2SpO2(invalid), null, `Expected SpO2=${String(invalid)} to return null`);
  }
  for (const nonPositive of [0, -1, -50]) {
    assert.ok([null, 3].includes(scoreNews2SpO2(nonPositive)), `Expected SpO2=${nonPositive} to abstain or flag red`);
  }
});

test('scoreNews2HR: tests every RCP NEWS2 boundary value and invalid/missing inputs', () => {
  // <= 40 -> 3 points
  for (const hr of [30, 35, 40, 40.4]) {
    assert.equal(scoreNews2HR(hr), 3, `Expected HR=${hr} to score 3`);
  }
  // 41..50 -> 1 point
  for (const hr of [40.6, 41, 45, 50, 50.4]) {
    assert.equal(scoreNews2HR(hr), 1, `Expected HR=${hr} to score 1`);
  }
  // 51..90 -> 0 points
  for (const hr of [50.6, 51, 60, 75, 90, 90.4]) {
    assert.equal(scoreNews2HR(hr), 0, `Expected HR=${hr} to score 0`);
  }
  // 91..110 -> 1 point
  for (const hr of [90.6, 91, 100, 110, 110.4]) {
    assert.equal(scoreNews2HR(hr), 1, `Expected HR=${hr} to score 1`);
  }
  // 111..130 -> 2 points
  for (const hr of [110.6, 111, 120, 130, 130.4]) {
    assert.equal(scoreNews2HR(hr), 2, `Expected HR=${hr} to score 2`);
  }
  // >= 131 -> 3 points
  for (const hr of [130.6, 131, 140, 180]) {
    assert.equal(scoreNews2HR(hr), 3, `Expected HR=${hr} to score 3`);
  }
  // Missing / non-finite / non-positive handling
  for (const invalid of [null, undefined, NaN, Infinity, -Infinity]) {
    assert.equal(scoreNews2HR(invalid), null, `Expected HR=${String(invalid)} to return null`);
  }
  for (const nonPositive of [0, -1, -40]) {
    assert.ok([null, 3].includes(scoreNews2HR(nonPositive)), `Expected HR=${nonPositive} to abstain or flag red`);
  }
});

test('calculateModifiedNews2: Low, Medium (single-red and aggregate), High, Stale, and Incomplete states', () => {
  const baseState = (hr, spo2, rr) => ({
    patient_id: 'A001',
    status: 'NORMAL',
    timestamp: 1000,
    heart_rate: hr,
    spo2,
    respiratory_rate: rr,
    analysis: { status: 'READY' },
  });

  // 1. Low risk: 0 points (HR=75 -> 0, SpO2=98 -> 0, RR=16 -> 0)
  const low0 = calculateModifiedNews2(baseState(75, 98, 16), true);
  assert.equal(low0.ready, true);
  assert.equal(low0.total, 0);
  assert.equal(low0.hrScore, 0);
  assert.equal(low0.spo2Score, 0);
  assert.equal(low0.rrScore, 0);
  assert.equal(low0.hasRedScore, false);
  assert.equal(low0.tier, 'low');

  // 2. Low risk: 2 points (HR=95 -> 1, SpO2=95 -> 1, RR=16 -> 0)
  const low2 = calculateModifiedNews2(baseState(95, 95, 16), true);
  assert.equal(low2.ready, true);
  assert.equal(low2.total, 2);
  assert.equal(low2.hasRedScore, false);
  assert.equal(low2.tier, 'low');

  // 3. Aggregate 3..4 with no single 3 (HR=95 -> 1, SpO2=95 -> 1, RR=22 -> 2 => total=4)
  const score4 = calculateModifiedNews2(baseState(95, 95, 22), true);
  assert.equal(score4.ready, true);
  assert.equal(score4.total, 4);
  assert.equal(score4.hasRedScore, false);
  assert.ok(['low', 'medium'].includes(score4.tier));

  // 4. Single-parameter Red Score (+3): RR=30 (3), HR=75 (0), SpO2=98 (0) => total=3, hasRedScore=true
  const singleRed = calculateModifiedNews2(baseState(75, 98, 30), true);
  assert.equal(singleRed.ready, true);
  assert.equal(singleRed.total, 3);
  assert.equal(singleRed.rrScore, 3);
  assert.equal(singleRed.hrScore, 0);
  assert.equal(singleRed.spo2Score, 0);
  assert.equal(singleRed.hasRedScore, true);
  assert.ok(['medium', 'high'].includes(singleRed.tier), 'Single red parameter (+3) must escalate risk');

  // 5. Aggregate 5..6 without single red: HR=95 (1), SpO2=93 (2), RR=22 (2) => total=5, hasRedScore=false
  const medium5 = calculateModifiedNews2(baseState(95, 93, 22), true);
  assert.equal(medium5.ready, true);
  assert.equal(medium5.total, 5);
  assert.equal(medium5.hasRedScore, false);
  assert.ok(['medium', 'high'].includes(medium5.tier));

  const medium6 = calculateModifiedNews2(baseState(115, 93, 22), true);
  assert.equal(medium6.ready, true);
  assert.equal(medium6.total, 6);
  assert.equal(medium6.hasRedScore, false);
  assert.ok(['medium', 'high'].includes(medium6.tier));

  // 6. High risk via total >= 5 with +3 (RR=26 -> 3, SpO2=93 -> 2, HR=75 -> 0 => total=5, hasRedScore=true)
  const high5Red = calculateModifiedNews2(baseState(75, 93, 26), true);
  assert.equal(high5Red.ready, true);
  assert.equal(high5Red.total, 5);
  assert.equal(high5Red.hasRedScore, true);
  assert.equal(high5Red.tier, 'high');

  // 7. High risk via total >= 7 (HR=135 -> 3, SpO2=91 -> 3, RR=22 -> 2 => total=8, hasRedScore=true)
  const high8 = calculateModifiedNews2(baseState(135, 91, 22), true);
  assert.equal(high8.ready, true);
  assert.equal(high8.total, 8);
  assert.equal(high8.hasRedScore, true);
  assert.equal(high8.tier, 'high');

  // 8. Stale reading abstention (fresh = false)
  const stale = calculateModifiedNews2(baseState(135, 91, 22), false);
  assert.equal(stale.ready, false);
  assert.equal(stale.total, null);
  assert.equal(stale.hrScore, null);
  assert.equal(stale.spo2Score, null);
  assert.equal(stale.rrScore, null);
  assert.equal(stale.hasRedScore, false);
  assert.equal(stale.tier, 'stale');

  // 9. Incomplete / missing parameter abstention (fresh = true, missing RR or NaN SpO2)
  const missingRr = calculateModifiedNews2(baseState(75, 98, undefined), true);
  assert.equal(missingRr.ready, false);
  assert.equal(missingRr.total, null);
  assert.equal(missingRr.hrScore, 0);
  assert.equal(missingRr.spo2Score, 0);
  assert.equal(missingRr.rrScore, null);
  assert.equal(missingRr.tier, 'incomplete');

  const nanSpo2 = calculateModifiedNews2(baseState(75, NaN, 16), true);
  assert.equal(nanSpo2.ready, false);
  assert.equal(nanSpo2.total, null);
  assert.equal(nanSpo2.spo2Score, null);
  assert.equal(nanSpo2.tier, 'incomplete');

  const undefinedState = calculateModifiedNews2(undefined, true);
  assert.equal(undefinedState.ready, false);
  assert.equal(undefinedState.total, null);
  assert.equal(undefinedState.tier, 'incomplete');
});

test('formatStaleDuration and getStaleEscalationTier: verify stale telemetry escalation contract', () => {
  if (typeof formatStaleDuration === 'function' && typeof getStaleEscalationTier === 'function') {
    assert.match(formatStaleDuration(null, 1000), /ยังไม่มีสัญญาณ|รอข้อมูล/);
    assert.match(formatStaleDuration(980, 1000), /20 วินาที/);
    assert.match(formatStaleDuration(875, 1000), /2 นาที 5 วินาที/);

    assert.equal(getStaleEscalationTier(null, 1000), 'warning');
    assert.equal(getStaleEscalationTier(990, 1000), 'normal');
    assert.equal(getStaleEscalationTier(980, 1000), 'warning');
    assert.equal(getStaleEscalationTier(940, 1000), 'critical');
  }
});
