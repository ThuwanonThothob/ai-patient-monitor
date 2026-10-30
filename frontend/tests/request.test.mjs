import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import assert from 'node:assert/strict';
import ts from 'typescript';

function loadModule(file, globals = {}) {
  const source = readFileSync(new URL('../app/' + file, import.meta.url), 'utf8');
  const output = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
  const exported = {};
  vm.runInNewContext(output, { exports: exported, AbortController, setTimeout, clearTimeout, Event, ...globals });
  return exported;
}

test('API proxy HTML failure becomes a readable message, never a JSON syntax error', async () => {
  const api = loadModule('apiRequest.ts', { fetch: async () => ({ ok: false, status: 502, json: async () => { throw new SyntaxError('Unexpected token <'); } }) });
  await assert.rejects(api.requestJson('/api/me'), error => error.status === 502 && /เซิร์ฟเวอร์/.test(error.message));
});

test('API requests expire instead of leaving a send or login button busy forever', async () => {
  const api = loadModule('apiRequest.ts', { fetch: async (_url, options) => new Promise((_resolve, reject) => options.signal.addEventListener('abort', () => reject(new Error('abort')))) });
  await assert.rejects(api.requestJson('/api/me/chat', {}, 10), /ใช้เวลานานเกินไป/);
});

test('expired authenticated request signals shell, but incorrect login does not', async () => {
  const events = [];
  const api = loadModule('apiRequest.ts', { window: { dispatchEvent: event => events.push(event.type) }, fetch: async () => ({ ok: false, status: 401, json: async () => ({}) }) });
  await assert.rejects(api.requestJson('/api/me'), error => error.status === 401);
  await assert.rejects(api.requestJson('/api/session/login'), error => error.status === 401);
  assert.deepEqual(events, ['ward:session-expired']);
});

test('cancelling a component request cancels its transport', async () => {
  let transport;
  const api = loadModule('apiRequest.ts', { fetch: async (_url, options) => { transport = options.signal; return new Promise((_resolve, reject) => options.signal.addEventListener('abort', () => reject(new Error('abort')))); } });
  const controller = new AbortController();
  const pending = api.requestJson('/api/me', { signal: controller.signal });
  controller.abort();
  await assert.rejects(pending);
  assert.equal(transport.aborted, true);
});

test('authenticated responses are never fetched from a browser cache', async () => {
  let options;
  const api = loadModule('apiRequest.ts', { fetch: async (_url, settings) => { options = settings; return { ok: true, json: async () => ({ patient_id: 'TEST_P' }) }; } });
  assert.equal((await api.requestJson('/api/me')).patient_id, 'TEST_P');
  assert.equal(options.cache, 'no-store');
});

const environment = loadModule('pushEnvironment.ts').pushEnvironment;
const mobile = { userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X)', platform: 'iPhone', maxTouchPoints: 5, standalone: false, secure: true, supported: false };
test('iPhone browser explains installation before unsupported notifications', () => {
  assert.equal(environment(mobile).needsInstall, true);
  assert.equal(environment({ ...mobile, standalone: true, supported: true }).needsInstall, false);
});

test('iPad desktop user agent still receives home-screen installation instructions', () => {
  assert.equal(environment({ ...mobile, userAgent: 'Mozilla/5.0 (Macintosh)', platform: 'MacIntel' }).needsInstall, true);
  assert.equal(environment({ ...mobile, userAgent: 'Mozilla/5.0 (Macintosh)', platform: 'MacIntel', maxTouchPoints: 0 }).needsInstall, false);
});
