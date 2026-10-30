import { readFileSync } from 'node:fs';
import vm from 'node:vm';
import test from 'node:test';
import assert from 'node:assert/strict';
import ts from 'typescript';

const source = readFileSync(new URL('../app/monitorView.ts', import.meta.url), 'utf8');
const output = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;
const exported = {};
vm.runInNewContext(output, { exports: exported });

test('fresh counts exclude stale, future, invalid and missing readings', () => {
  for (const reading of [undefined, {}, { timestamp: 100 }, { timestamp: 116, status: 'NORMAL' }, { timestamp: 50, status: 'CRITICAL' }, { timestamp: 100, status: 'STALE_DATA' }, { timestamp: NaN, status: 'NORMAL' }]) {
    assert.equal(exported.isFreshReading(reading, 110), false);
  }
  assert.equal(exported.isFreshReading({ timestamp: 100, status: 'CRITICAL' }, 110), true);
  assert.equal(exported.isFreshReading({ timestamp: 100, status: 'NORMAL' }, 0), false);
  assert.equal(exported.isFreshReading({ timestamp: 100, status: 'NORMAL' }, 115), true);
  assert.equal(exported.isFreshReading({ timestamp: 100, status: 'NORMAL' }, 116), false);
});

function serviceWorker() {
  const handlers = {}, shown = [], navigated = [];
  const self = {
    location: { origin: 'https://ward.example.org' },
    addEventListener: (name, handler) => { handlers[name] = handler; },
    registration: { showNotification: async (title, options) => { shown.push({ title, ...options }); } },
    clients: { matchAll: async () => [], openWindow: async (url) => { navigated.push(url); } },
  };
  vm.runInNewContext(readFileSync(new URL('../public/sw.js', import.meta.url), 'utf8'), { self, URL });
  return { handlers, shown, navigated };
}

test('lock-screen content ignores patient details supplied in a payload', async () => {
  const worker = serviceWorker();
  let done;
  worker.handlers.push({ data: { json: () => ({ title: 'Patient A001', body: 'SpO2 85%', url: 'https://evil.test', tag: 'ward-review' }) }, waitUntil: (promise) => { done = promise; } });
  await done;
  assert.equal(worker.shown.length, 1);
  assert.equal(worker.shown[0].data.url, '/?section=alerts');
  assert.doesNotMatch(JSON.stringify(worker.shown), /A001|SpO2|evil/);
  assert.equal(worker.handlers.fetch, undefined, 'must not cache patient/API responses');
});

test('malformed push remains generic and notification clicks stay same-origin', async () => {
  const worker = serviceWorker();
  let done;
  worker.handlers.push({ data: { json: () => { throw new Error('bad payload'); } }, waitUntil: (promise) => { done = promise; } });
  await done;
  assert.equal(worker.shown.length, 1);
  worker.handlers.notificationclick({ notification: { close() {}, data: { url: 'https://evil.test' } }, waitUntil: (promise) => { done = promise; } });
  await done;
  assert.deepEqual(worker.navigated, ['https://ward.example.org/?section=alerts']);
});

test('test notifications open the setup page, not a real clinical alert', async () => {
  const worker = serviceWorker();
  let done;
  worker.handlers.push({ data: { json: () => ({ tag: 'ward-test' }) }, waitUntil: (promise) => { done = promise; } });
  await done;
  assert.equal(worker.shown[0].data.url, '/?section=notifications');
  assert.match(worker.shown[0].title, /ทดสอบ/);
});

test('chat notifications open the matching portal without exposing message text', async () => {
  for (const url of ['/?section=chat', '/?section=triage']) {
    const worker = serviceWorker();
    let done;
    worker.handlers.push({ data: { json: () => ({ tag: 'ward-chat', url, body: 'private message' }) }, waitUntil: p => { done = p; } });
    await done;
    assert.equal(worker.shown[0].data.url, url);
    assert.doesNotMatch(JSON.stringify(worker.shown), /private message/);
    worker.handlers.notificationclick({ notification: { close() {}, data: worker.shown[0].data }, waitUntil: p => { done = p; } });
    await done;
    assert.equal(worker.navigated[0], 'https://ward.example.org' + url);
  }
});

test('simulation notification is explicitly identified as TEST', async () => {
  const worker = serviceWorker();
  let done;
  worker.handlers.push({ data: { json: () => ({ tag: 'ward-simulation', url: '/' }) }, waitUntil: p => { done = p; } });
  await done;
  assert.match(worker.shown[0].title, /จำลอง TEST/);
  assert.equal(worker.shown[0].data.url, '/');
});

test('clinician dashboard and patient portal expose accessibility and triage controls', () => {
  const staffSource = readFileSync(new URL('../app/StaffDashboard.tsx', import.meta.url), 'utf8');
  assert.match(staffSource, /playCriticalChime/);
  assert.match(staffSource, /เสียงเตือนวิกฤต/);
  assert.match(staffSource, /กรองระดับความเร่งด่วนหน้าภาพรวม/);

  const patientSource = readFileSync(new URL('../app/PatientPortal.tsx', import.meta.url), 'utf8');
  assert.doesNotMatch(patientSource, /ก\+ ตัวอักษรใหญ่/);
  assert.doesNotMatch(patientSource, /largeText/);
  assert.match(patientSource, /คำอธิบายค่าสัญญาณชีพเบื้องต้น/);

  const careMessagesSource = readFileSync(new URL('../app/CareMessages.tsx', import.meta.url), 'utf8');
  assert.match(careMessagesSource, /ข้อความด่วนสำหรับผู้ป่วย/);

  const careChatSource = readFileSync(new URL('../app/CareChat.tsx', import.meta.url), 'utf8');
  assert.match(careChatSource, /ข้อความแชทด่วนสำหรับผู้ป่วย/);
});

test('R1 contract: removal of text enlargement toggle and largeText CSS mode in patient portal', () => {
  const patientSource = readFileSync(new URL('../app/PatientPortal.tsx', import.meta.url), 'utf8');
  const patientCss = readFileSync(new URL('../app/PatientPortal.module.css', import.meta.url), 'utf8');

  assert.doesNotMatch(patientSource, /ก\+ ตัวอักษรใหญ่/);
  assert.doesNotMatch(patientSource, /largeText/);
  assert.doesNotMatch(patientCss, /largeText/);
  assert.match(patientSource, /คำอธิบายค่าสัญญาณชีพเบื้องต้น/);
});

test('R2 contract: single bottom-right floating AI launcher and centered modal with centered text', () => {
  const staffSource = readFileSync(new URL('../app/StaffDashboard.tsx', import.meta.url), 'utf8');
  const assistantCss = readFileSync(new URL('../app/AgentAssistant.module.css', import.meta.url), 'utf8');

  assert.doesNotMatch(staffSource, /AskAgent/);
  assert.doesNotMatch(staffSource, /assistantPanel/);
  assert.match(assistantCss, /\.launcher\s*\{[^}]*position:\s*fixed;/);
  assert.match(assistantCss, /\.launcher\s*\{[^}]*right:\s*24px;/);
  assert.match(assistantCss, /\.dialog\s*\{[^}]*margin:\s*auto;/);
  assert.match(assistantCss, /\.dialog\s*\{[^}]*text-align:\s*center;/);
});

test('R3 contract: dedicated doctor-patient chat navigation and separation from triage', () => {
  const staffSource = readFileSync(new URL('../app/StaffDashboard.tsx', import.meta.url), 'utf8');
  const patientSource = readFileSync(new URL('../app/PatientPortal.tsx', import.meta.url), 'utf8');

  assert.match(staffSource, /id:\s*["']chat["']/);
  assert.match(staffSource, /แชทแพทย์-ผู้ป่วย/);

  const triageBlockMatch = staffSource.match(/active === ["']triage["']\)\s*content\s*=\s*<>([\s\S]*?)<\/>;/);
  assert.ok(triageBlockMatch, 'triage content block found');
  assert.doesNotMatch(triageBlockMatch[1], /CareChat/);

  assert.match(staffSource, /<OperationsPanel[\s\S]*?chat=\{\(\)\s*=>\s*setActive\(['"]chat['"]\)\}/);

  assert.match(patientSource, /active === ['"]chat['"]\s*&&\s*<CareChat\s*\/>/);
  assert.match(patientSource, /active === ['"]care['"]\s*&&\s*<>.*<CareMessages\s*\/>.*<\/>/);
});

test('R4 contract: Facebook Messenger layout, message bubbles, receipts, and strict call prohibition', () => {
  const careChatSource = readFileSync(new URL('../app/CareChat.tsx', import.meta.url), 'utf8');
  const careChatCss = readFileSync(new URL('../app/CareChat.module.css', import.meta.url), 'utf8');

  assert.match(careChatCss, /\.activeBadge/);
  assert.match(careChatCss, /#31a24c/);

  assert.match(careChatCss, /\.bubbleMine/);
  assert.match(careChatSource, /อ่านแล้ว/);
  assert.match(careChatSource, /ส่งแล้ว/);

  assert.match(careChatCss, /\.bubbleOther/);
  assert.match(careChatCss, /\.composerPill/);

  assert.match(careChatCss, /\.quickPill/);
  assert.match(careChatSource, /aria-label=["']ข้อความแชทด่วนสำหรับผู้ป่วย["']/);

  assert.doesNotMatch(careChatSource, /video|call|เสียงเรียกเข้า|โทร|วิดีโอ/i);
});

test('evidence replay and agent team provide clear transparency on PhysioNet BIDMC 1Hz, 30s forecast and abstention', () => {
  const evidenceSource = readFileSync(new URL('../app/EvidencePanel.tsx', import.meta.url), 'utf8');
  assert.match(evidenceSource, /PhysioNet BIDMC/);
  assert.match(evidenceSource, /1 Hz/);
  assert.match(evidenceSource, /Train \/ Validation \/ Test/);
  assert.match(evidenceSource, /Zero Data Leakage|ไม่มีข้อมูลรั่วไหล/);
  assert.match(evidenceSource, /Random Forest/);
  assert.match(evidenceSource, /Persistence Baseline/);
  assert.match(evidenceSource, /30 วินาที/);
  assert.match(evidenceSource, /งดพยากรณ์|งดทาย|Abstain/);

  const agentSource = readFileSync(new URL('../app/AgentPanel.tsx', import.meta.url), 'utf8');
  assert.match(agentSource, /PhysioNet BIDMC/);
  assert.match(agentSource, /1 Hz/);
  assert.match(agentSource, /Train \/ Validation \/ Test/);
  assert.match(agentSource, /Data Leakage|รั่วไหล/);
  assert.match(agentSource, /Random Forest/);
  assert.match(agentSource, /Persistence Baseline/);
  assert.match(agentSource, /30 วินาที/);
  assert.match(agentSource, /งดทาย|งดพยากรณ์|Abstain/);
});

test('care templates, shift handoff reminder, patient report/profile guides, and research scope callout are present', () => {
  const carePanelSource = readFileSync(new URL('../app/CarePanel.tsx', import.meta.url), 'utf8');
  assert.match(carePanelSource, /แม่แบบแผนดูแลด่วน/);
  assert.match(carePanelSource, /พลิกตัวและตรวจผิวหนังทุก 2 ชม\./);

  const opsSource = readFileSync(new URL('../app/OperationsPanel.tsx', import.meta.url), 'utf8');
  assert.match(opsSource, /Shift Handoff Reminder/);

  const patientSectionsSource = readFileSync(new URL('../app/PatientSections.tsx', import.meta.url), 'utf8');
  assert.match(patientSectionsSource, /คำแนะนำการใช้รายงานสรุปประจำวัน/);
  assert.match(patientSectionsSource, /ต้องการแจ้งแก้ไขประวัติแพ้ยาหรือรายการยา/);

  const researchSource = readFileSync(new URL('../app/ResearchPanel.tsx', import.meta.url), 'utf8');
  assert.match(researchSource, /โมเดลเฝ้าระวังสัญญาณชีพสด 1 Hz/);
  assert.match(researchSource, /โมเดลวิจัยย้อนหลัง ICU Sepsis Benchmark/);
});

test('Sprint 1-2 contract: CareChat responsive 768px 100dvh, Ward high-contrast status tokens, and fetchUnreadChatSummary', () => {
  const careChatCss = readFileSync(new URL('../app/CareChat.module.css', import.meta.url), 'utf8');
  assert.match(careChatCss, /@media[^{]*max-width:\s*768px/);
  assert.match(careChatCss, /100dvh/);

  const wardCss = readFileSync(new URL('../app/Ward.module.css', import.meta.url), 'utf8');
  assert.match(wardCss, /--status-critical-bg:\s*#fff0f2/);
  assert.match(wardCss, /--status-critical-bg:\s*#2d0e12/);

  const apiRequestSource = readFileSync(new URL('../app/apiRequest.ts', import.meta.url), 'utf8');
  assert.match(apiRequestSource, /export\s+(async\s+)?function\s+fetchUnreadChatSummary/);
});

test('Formal-Minimalist Clinical UI contract: progressive disclosure Learn More drawers and smooth design tokens', () => {
  const globalsCss = readFileSync(new URL('../app/globals.css', import.meta.url), 'utf8');
  assert.match(globalsCss, /--ease-smooth:\s*cubic-bezier\(0\.22,\s*1,\s*0\.36,\s*1\)/);
  assert.match(globalsCss, /backdrop-filter:\s*blur\(14px\)/);

  const staffSource = readFileSync(new URL('../app/StaffDashboard.tsx', import.meta.url), 'utf8');
  const patientSource = readFileSync(new URL('../app/PatientPortal.tsx', import.meta.url), 'utf8');
  const opsSource = readFileSync(new URL('../app/OperationsPanel.tsx', import.meta.url), 'utf8');
  const carePanelSource = readFileSync(new URL('../app/CarePanel.tsx', import.meta.url), 'utf8');
  const evidenceSource = readFileSync(new URL('../app/EvidencePanel.tsx', import.meta.url), 'utf8');
  const researchSource = readFileSync(new URL('../app/ResearchPanel.tsx', import.meta.url), 'utf8');

  for (const src of [staffSource, patientSource, opsSource, carePanelSource, evidenceSource, researchSource]) {
    assert.match(src, /learnMoreDrawer/);
    assert.match(src, /Learn More/);
  }
});

test('Sprint 4 Full Frontend Overhaul contract: Night Shift toggle, SBAR summary, Modified NEWS2 score, and CSS Module purity', () => {
  const staffSource = readFileSync(new URL('../app/StaffDashboard.tsx', import.meta.url), 'utf8');
  assert.match(staffSource, /smart-ward-night-shift/);
  assert.match(staffSource, /โหมดเวรดึก/);
  assert.match(staffSource, /SBAR/);
  assert.match(staffSource, /คัดลอก SBAR/);

  const monitorSource = readFileSync(new URL('../app/MonitorPanel.tsx', import.meta.url), 'utf8');
  assert.match(monitorSource, /calculateModifiedNews2/);
  assert.match(monitorSource, /Modified NEWS2/);

  const moduleCssFiles = [
    '../app/Ward.module.css',
    '../app/PatientPortal.module.css',
    '../app/CareChat.module.css',
    '../app/AgentAssistant.module.css',
    '../app/ResearchPanel.module.css',
  ];
  for (const relPath of moduleCssFiles) {
    const css = readFileSync(new URL(relPath, import.meta.url), 'utf8');
    assert.doesNotMatch(css, /(^|\n)\s*:root\s*\{/, `${relPath} must not contain bare :root selector`);
    assert.doesNotMatch(css, /(^|\n)\s*(body|html)\s*\{/, `${relPath} must not contain bare body/html selector`);
  }

  const overhauledModules = [
    '../app/AlertWorkflow.tsx',
    '../app/CareProfilePanel.tsx',
    '../app/DailySummaryPanel.tsx',
    '../app/NotificationPanel.tsx',
    '../app/BedsidePanel.tsx',
    '../app/PosturePanel.tsx',
    '../app/AgentPanel.tsx',
  ];
  for (const relPath of overhauledModules) {
    const src = readFileSync(new URL(relPath, import.meta.url), 'utf8');
    assert.match(src, /learnMoreDrawer/, `${relPath} must include learnMoreDrawer`);
    assert.match(src, /Learn More/, `${relPath} must include Learn More progressive disclosure`);
  }

  const patientCss = readFileSync(new URL('../app/PatientPortal.module.css', import.meta.url), 'utf8');
  assert.match(patientCss, /\.modalDialog\s*\{[^}]*display:\s*none;/, 'modalDialog must be hidden until opened');
  assert.match(patientCss, /\.modalDialog\[open\]\s*\{[^}]*display:\s*flex;/, 'modalDialog[open] must display flex when opened');
  assert.match(patientCss, /:where\(button:not\(\[class\]\)\)/, 'PatientPortal button styles must not bleed into classed child buttons');

  const careChatCss = readFileSync(new URL('../app/CareChat.module.css', import.meta.url), 'utf8');
  assert.match(careChatCss, /\.chat\s*\{[^}]*min-height:\s*560px;/, 'Standalone patient CareChat must have explicit container height');
});



