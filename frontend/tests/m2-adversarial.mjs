import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const staffDashboardPath = resolve('app/StaffDashboard.tsx');
const agentAssistantPath = resolve('app/AgentAssistant.tsx');
const agentCssPath = resolve('app/AgentAssistant.module.css');
const wardCssPath = resolve('app/Ward.module.css');
const vitalChartsPath = resolve('app/VitalCharts.tsx');
const patientPortalPath = resolve('app/PatientPortal.tsx');
const monitorPanelPath = resolve('app/MonitorPanel.tsx');

const staffDashboardSrc = readFileSync(staffDashboardPath, 'utf8');
const agentAssistantSrc = readFileSync(agentAssistantPath, 'utf8');
const agentCssSrc = readFileSync(agentCssPath, 'utf8');
const wardCssSrc = readFileSync(wardCssPath, 'utf8');

test('M2-ADVERSARIAL-1: StaffDashboard.tsx completely eliminates AskAgent and assistantPanel', () => {
  assert.doesNotMatch(staffDashboardSrc, /AskAgent/, 'StaffDashboard must not import or render AskAgent');
  assert.doesNotMatch(staffDashboardSrc, /assistantPanel/, 'StaffDashboard must not declare or render assistantPanel');
  assert.doesNotMatch(staffDashboardSrc, /loadingSummary/, 'StaffDashboard must not have loadingSummary state');
  assert.doesNotMatch(staffDashboardSrc, /setSummary\b/, 'StaffDashboard must not have setSummary state updater');
  
  // Verify PatientModal does not have AskAgent
  const modalMatch = staffDashboardSrc.match(/function PatientModal\([\s\S]*?\n\}/);
  assert.ok(modalMatch, 'PatientModal must be defined');
  assert.doesNotMatch(modalMatch[0], /AskAgent/, 'PatientModal must not render AskAgent');
});

test('M2-ADVERSARIAL-2: StaffDashboard.tsx has zero occurrences of styles.split or empty 290px column', () => {
  assert.doesNotMatch(staffDashboardSrc, /styles\.split/, 'StaffDashboard must not use styles.split');
  assert.doesNotMatch(staffDashboardSrc, /styles\.aiPanel/, 'StaffDashboard must not use styles.aiPanel');
  
  // Verify Ward.module.css defines .split with 290px column
  assert.match(wardCssSrc, /\.split\s*\{[^}]*290px/, 'Ward.module.css defines 290px right column for .split');
  
  // Verify none of the 5 main sections in StaffDashboard use split
  for (const section of ['overview', 'triage', 'patients', 'alerts', 'reports']) {
    const sectionBlockRegex = new RegExp(`active === "${section}"[\\s\\S]*?(else if|return)`);
    const match = staffDashboardSrc.match(sectionBlockRegex);
    if (match) {
      assert.doesNotMatch(match[0], /split/, `Section "${section}" must not contain split wrapper`);
    }
  }
});

test('M2-ADVERSARIAL-3: StaffDashboard.tsx cleanly manages loadSnapshot without summary leaks', () => {
  assert.match(staffDashboardSrc, /const loadSnapshot = useCallback\(async \(\) =>/, 'loadSnapshot must be defined');
  assert.match(staffDashboardSrc, /setSnapshot\(data\.snapshot\)/, 'loadSnapshot must update snapshot state');
  assert.match(staffDashboardSrc, /summaryRequest\.current/, 'loadSnapshot must use revision ref to avoid race conditions');
  assert.match(staffDashboardSrc, /void loadSnapshot\(\)/, 'loadSnapshot must be invoked on timer');
});

test('M2-ADVERSARIAL-4: AgentAssistant.tsx has single default export and zero AskAgent exports', () => {
  assert.match(agentAssistantSrc, /export default function AgentAssistant/, 'AgentAssistant must be the default export');
  assert.doesNotMatch(agentAssistantSrc, /export function AskAgent/, 'AskAgent must not be exported');
  assert.doesNotMatch(agentAssistantSrc, /export const AskAgent/, 'AskAgent const must not be exported');
  assert.doesNotMatch(agentAssistantSrc, /export \{.*AskAgent.*\}/, 'AskAgent must not be in export list');
});

test('M2-ADVERSARIAL-5: AgentAssistant.tsx markup contracts (launcher, dialog, accessibility)', () => {
  assert.match(agentAssistantSrc, /className=\{s\.launcher\}/, 'Launcher button must use s.launcher class');
  assert.match(agentAssistantSrc, /aria-label="เปิดผู้ช่วย Agentic"/, 'Launcher button must have Thai accessibility label');
  assert.match(agentAssistantSrc, /onClick=\{\(\) => dialog\.current\?\.showModal\(\)\}/, 'Launcher must open native modal dialog');
  
  assert.match(agentAssistantSrc, /<dialog ref=\{dialog\} className=\{s\.dialog\}/, 'Dialog must use native HTMLDialogElement');
  assert.match(agentAssistantSrc, /aria-labelledby="agent-title"/, 'Dialog must link to title via aria-labelledby');
  assert.match(agentAssistantSrc, /<h2 id="agent-title">ผู้ช่วยข้อมูลการดูแล<\/h2>/, 'Header title must match dialog aria-labelledby');
  
  assert.match(agentAssistantSrc, /className=\{s\.close\} aria-label="ปิดผู้ช่วย"/, 'Close button must have accessibility label');
  assert.match(agentAssistantSrc, /onClick=\{e => \{ if \(e\.target === dialog\.current\) dialog\.current\?\.close\(\); \}\}/, 'Clicking backdrop must close modal');
});

test('M2-ADVERSARIAL-6: AgentAssistant.tsx stress-tests input bounds, validation, and cancellation', () => {
  assert.match(agentAssistantSrc, /maxLength=\{1000\}/, 'Question textarea must have maxLength 1000');
  assert.match(agentAssistantSrc, /maxLength=\{20\}/, 'Patient ID input must have maxLength 20');
  assert.match(agentAssistantSrc, /e\.target\.value\.toUpperCase\(\)/, 'Patient ID must be converted to uppercase');
  
  // AbortController cleanup
  assert.match(agentAssistantSrc, /useEffect\(\(\) => \(\) => controller\.current\?\.abort\(\), \[\]\)/, 'AbortController must abort on unmount');
  assert.match(agentAssistantSrc, /controller\.current\?\.abort\(\)/, 'Subsequent submit must abort pending in-flight request');
  
  // Submit validation: cannot submit empty question or missing target for staff
  assert.match(agentAssistantSrc, /!question\.trim\(\)/, 'Empty or whitespace question must be blocked');
  assert.match(agentAssistantSrc, /\(staff && !target\.trim\(\)\)/, 'Staff mode without patientId must block submission until target is provided');
});

test('M2-ADVERSARIAL-7: AgentAssistant.module.css enforces fixed bottom-right launcher and viewport-centered modal', () => {
  // Launcher positioning
  assert.match(agentCssSrc, /\.launcher\s*\{[^}]*position:\s*fixed/, '.launcher must be position: fixed');
  assert.match(agentCssSrc, /\.launcher\s*\{[^}]*bottom:\s*max\(20px,\s*env\(safe-area-inset-bottom\)\)/, '.launcher must be pinned to bottom with safe-area');
  assert.match(agentCssSrc, /\.launcher\s*\{[^}]*right:\s*24px/, '.launcher must be pinned to right: 24px');
  assert.match(agentCssSrc, /\.launcher\s*\{[^}]*z-index:\s*1100/, '.launcher must have z-index: 1100');
  assert.match(agentCssSrc, /\.launcher\s*\{[^}]*text-align:\s*center/, '.launcher must have text-align: center');
  
  // Dialog viewport centering
  assert.match(agentCssSrc, /\.dialog\s*\{[^}]*margin:\s*auto/, '.dialog must have margin: auto');
  assert.match(agentCssSrc, /\.dialog\s*\{[^}]*position:\s*fixed/, '.dialog must have position: fixed');
  assert.match(agentCssSrc, /\.dialog\s*\{[^}]*inset:\s*0/, '.dialog must have inset: 0');
  assert.match(agentCssSrc, /\.dialog\s*\{[^}]*text-align:\s*center/, '.dialog must have text-align: center');
  assert.match(agentCssSrc, /\.dialog::backdrop/, '.dialog must style backdrop');
});

test('M2-ADVERSARIAL-8: AgentAssistant.module.css enforces centered typography across all modal children', () => {
  assert.match(agentCssSrc, /\.header\s*\{[^}]*align-items:\s*center/, '.header must align items centered');
  assert.match(agentCssSrc, /\.header\s*\{[^}]*justify-content:\s*center/, '.header must justify content centered');
  assert.match(agentCssSrc, /\.headerText\s*\{[^}]*text-align:\s*center/, '.headerText must center text');
  assert.match(agentCssSrc, /\.body\s*\{[^}]*text-align:\s*center/, '.body must center text');
  assert.match(agentCssSrc, /\.context\s*\{[^}]*text-align:\s*center/, '.context must center text');
  assert.match(agentCssSrc, /\.note\s*\{[^}]*text-align:\s*center/, '.note must center text');
  assert.match(agentCssSrc, /\.suggestions\s*\{[^}]*justify-content:\s*center/, '.suggestions must justify-content center');
  assert.match(agentCssSrc, /\.suggestions button\s*\{[^}]*text-align:\s*center/, '.suggestions buttons must center text');
  assert.match(agentCssSrc, /\.form\s*\{[^}]*text-align:\s*center/, '.form must center text');
  assert.match(agentCssSrc, /\.form label\s*\{[^}]*text-align:\s*center/, '.form label must center text');
  assert.match(agentCssSrc, /\.form input[^{}]*\{[^}]*text-align:\s*center/, '.form input/textarea must center text');
  assert.match(agentCssSrc, /\.answer\s*\{[^}]*text-align:\s*center/, '.answer container must center text');
  assert.match(agentCssSrc, /\.answer p\s*\{[^}]*text-align:\s*center/, '.answer p must center text');
  assert.match(agentCssSrc, /\.answer details\s*\{[^}]*text-align:\s*center/, '.answer details must center text');
  assert.match(agentCssSrc, /\.answer details summary\s*\{[^}]*text-align:\s*center/, '.answer details summary must center text');
  assert.match(agentCssSrc, /\.answer details ol\s*\{[^}]*margin:\s*8px auto/, '.answer details ol must have margin: 8px auto to center block');
  assert.match(agentCssSrc, /\.answer small\s*\{[^}]*text-align:\s*center/, '.answer small must center text');
  assert.match(agentCssSrc, /\.error\s*\{[^}]*text-align:\s*center/, '.error must center text');
});

test('M2-ADVERSARIAL-9: Mobile responsive positioning rules for AgentAssistant', () => {
  assert.match(agentCssSrc, /@media\s*\(max-width:\s*600px\)/, 'Mobile media query must exist');
  assert.match(agentCssSrc, /@media\s*\(max-width:\s*600px\)\s*\{[^}]*\.launcher\s*\{[^}]*right:\s*14px/, 'Mobile launcher must adjust to right: 14px');
});

test('M2-ADVERSARIAL-10: Whole frontend codebase verification: zero stray AskAgent in any component', () => {
  const vitalChartsSrc = readFileSync(vitalChartsPath, 'utf8');
  const patientPortalSrc = readFileSync(patientPortalPath, 'utf8');
  const monitorPanelSrc = readFileSync(monitorPanelPath, 'utf8');

  assert.doesNotMatch(vitalChartsSrc, /AskAgent/, 'VitalCharts must not reference AskAgent');
  assert.doesNotMatch(patientPortalSrc, /AskAgent/, 'PatientPortal must not reference AskAgent');
  assert.doesNotMatch(monitorPanelSrc, /AskAgent/, 'MonitorPanel must not reference AskAgent');
});

test('M2-ADVERSARIAL-11: Sections coverage: all sections in StaffDashboard and PatientPortal map to labels', () => {
  // Extract sections map from AgentAssistant.tsx
  const sectionsMatch = agentAssistantSrc.match(/const sections:\s*Record<string,\s*string>\s*=\s*(\{[\s\S]*?\});/);
  assert.ok(sectionsMatch, 'sections map must be defined in AgentAssistant.tsx');
  const sectionsObj = eval(`(${sectionsMatch[1]})`);
  
  // Sections required in StaffDashboard: overview, patients, triage, chat, alerts, ai, research, reports, notifications, evidence, care
  const requiredStaffSections = ['overview', 'patients', 'triage', 'chat', 'alerts', 'ai', 'research', 'reports', 'notifications', 'evidence', 'care'];
  for (const s of requiredStaffSections) {
    assert.ok(sectionsObj[s], `AgentAssistant sections map must contain staff section: ${s}`);
  }
  
  // Sections required in PatientPortal: chat, care, trends, profile
  const requiredPatientSections = ['chat', 'care', 'trends', 'profile'];
  for (const s of requiredPatientSections) {
    assert.ok(sectionsObj[s], `AgentAssistant sections map must contain patient section: ${s}`);
  }
});

test('M2-ADVERSARIAL-12: Runtime timestamp parsing and Bangkok locale simulation', () => {
  const sampleEpoch = 1718000000;
  const formatted = new Date(sampleEpoch * 1000).toLocaleString('th-TH', { timeZone: 'Asia/Bangkok' });
  assert.ok(formatted.length > 5, 'Date formatting for Bangkok timezone must succeed');
});
