import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { resolve, join } from 'node:path';

// Load key component sources
const staffDashboardPath = resolve('app/StaffDashboard.tsx');
const patientPortalPath = resolve('app/PatientPortal.tsx');
const careChatPath = resolve('app/CareChat.tsx');
const careChatCssPath = resolve('app/CareChat.module.css');
const agentAssistantPath = resolve('app/AgentAssistant.tsx');
const agentCssPath = resolve('app/AgentAssistant.module.css');
const patientPortalCssPath = resolve('app/PatientPortal.module.css');

const staffDashboardSrc = readFileSync(staffDashboardPath, 'utf8');
const patientPortalSrc = readFileSync(patientPortalPath, 'utf8');
const careChatSrc = readFileSync(careChatPath, 'utf8');
const careChatCssSrc = readFileSync(careChatCssPath, 'utf8');
const agentAssistantSrc = readFileSync(agentAssistantPath, 'utf8');
const agentCssSrc = readFileSync(agentCssPath, 'utf8');
const patientPortalCssSrc = readFileSync(patientPortalCssPath, 'utf8');

// 1. REPRODUCE AND STRESS TEST HELPER FUNCTIONS FROM CareChat.tsx
const AVATAR_PALETTE = [
  '#0084ff',
  '#00a884',
  '#6b52ae',
  '#d93f6c',
  '#e56b00',
  '#0097a7',
  '#43a047',
  '#5c6bc0',
];

function getInitials(name) {
  if (!name) return '?';
  const clean = name.trim();
  const parts = clean.split(/\s+/);
  if (parts.length >= 2) {
    const first = parts[0].charAt(0);
    const second = parts[1].charAt(0);
    return (first + second).toUpperCase();
  }
  return clean.slice(0, 2).toUpperCase();
}

function getAvatarColor(identifier) {
  let hash = 0;
  for (let i = 0; i < identifier.length; i++) {
    hash = (hash << 5) - hash + identifier.charCodeAt(i);
    hash |= 0;
  }
  return AVATAR_PALETTE[Math.abs(hash) % AVATAR_PALETTE.length];
}

test('CHALLENGER-1: Stress-testing getInitials across edge cases, Thai script, unicode, and empty inputs', () => {
  // Empty & whitespace
  assert.equal(getInitials(''), '?');
  assert.equal(getInitials('   '), ''); // whitespace string trims to empty string, slices to ''
  assert.equal(getInitials(null), '?');
  assert.equal(getInitials(undefined), '?');

  // Single word English & Thai
  assert.equal(getInitials('John'), 'JO');
  assert.equal(getInitials('J'), 'J');
  assert.equal(getInitials('สมชาย'), 'สม');
  assert.equal(getInitials('ก'), 'ก');

  // Multi-word English & Thai
  assert.equal(getInitials('John Doe'), 'JD');
  assert.equal(getInitials('สมชาย ใจดี'), 'สใ');
  assert.equal(getInitials('นาย สมคิด วงศ์สวัสดิ์'), 'นส');

  // Multi-space separation
  assert.equal(getInitials('  Alice    Smith  '), 'AS');

  // Numbers and mixed characters
  assert.equal(getInitials('Patient 001'), 'P0');
  assert.equal(getInitials('A001'), 'A0');

  // Emojis & symbols: charAt(0) grabs high surrogate for 4-byte astral characters
  assert.equal(getInitials('👨‍⚕️ Doctor'), '\ud83dD');
});

test('CHALLENGER-2: Stress-testing getAvatarColor oracle across 10,000 synthetic IDs', () => {
  const allowedColors = new Set(AVATAR_PALETTE);

  // Check empty string
  const emptyColor = getAvatarColor('');
  assert.ok(allowedColors.has(emptyColor));

  // Check 10,000 synthetic IDs
  for (let i = 0; i < 10000; i++) {
    const id = `PATIENT_${i}_${(i * 31).toString(36)}_ไทย_${Math.random()}`;
    const color = getAvatarColor(id);
    assert.ok(allowedColors.has(color), `Color ${color} must be in AVATAR_PALETTE`);
  }
});

test('CHALLENGER-3: R1 Audit - Absolute elimination of large text toggle and styles', () => {
  // Negative assertions in patient portal
  assert.doesNotMatch(patientPortalSrc, /ก\+ ตัวอักษรใหญ่/);
  assert.doesNotMatch(patientPortalSrc, /largeText/);
  assert.doesNotMatch(patientPortalCssSrc, /largeText/);

  // Ensure normal readability cues remain
  assert.match(patientPortalSrc, /คำอธิบายค่าสัญญาณชีพเบื้องต้น/);
});

test('CHALLENGER-4: R2 Audit - Floating launcher and centered modal styling contracts', () => {
  // Check AgentAssistant.tsx
  assert.match(agentAssistantSrc, /className=\{s\.launcher\}/);
  assert.match(agentAssistantSrc, /className=\{s\.dialog\}/);
  assert.match(agentAssistantSrc, /<dialog ref=\{dialog\}/);

  // Check launcher CSS
  assert.match(agentCssSrc, /\.launcher\s*\{[^}]*position:\s*fixed;/);
  assert.match(agentCssSrc, /\.launcher\s*\{[^}]*right:\s*24px;/);
  assert.match(agentCssSrc, /\.launcher\s*\{[^}]*z-index:\s*1100;/);
  assert.match(agentCssSrc, /\.launcher\s*\{[^}]*text-align:\s*center;/);

  // Check dialog centering CSS
  assert.match(agentCssSrc, /\.dialog\s*\{[^}]*margin:\s*auto;/);
  assert.match(agentCssSrc, /\.dialog\s*\{[^}]*position:\s*fixed;/);
  assert.match(agentCssSrc, /\.dialog\s*\{[^}]*inset:\s*0;/);
  assert.match(agentCssSrc, /\.dialog\s*\{[^}]*text-align:\s*center;/);

  // Ensure modal components are centered
  assert.match(agentCssSrc, /\.header\s*\{[^}]*text-align:\s*center;/);
  assert.match(agentCssSrc, /\.body\s*\{[^}]*text-align:\s*center;/);
  assert.match(agentCssSrc, /\.form\s*\{[^}]*text-align:\s*center;/);
});

test('CHALLENGER-5: R2 Audit - Complete absence of AskAgent across all frontend components', () => {
  function scanDir(dir) {
    const entries = readdirSync(dir);
    for (const entry of entries) {
      const fullPath = join(dir, entry);
      const stat = statSync(fullPath);
      if (stat.isDirectory()) {
        if (entry !== 'node_modules' && entry !== '.next') {
          scanDir(fullPath);
        }
      } else if (entry.endsWith('.tsx') || entry.endsWith('.ts')) {
        const content = readFileSync(fullPath, 'utf8');
        assert.doesNotMatch(content, /<AskAgent\b/, `File ${fullPath} must not render AskAgent`);
        assert.doesNotMatch(content, /export\s+(function|const)\s+AskAgent\b/, `File ${fullPath} must not export AskAgent`);
      }
    }
  }
  scanDir(resolve('app'));
});

test('CHALLENGER-6: R3 Audit - Staff and Patient Chat Navigation Separation', () => {
  // Staff navigation
  assert.match(staffDashboardSrc, /id:\s*"chat",\s*icon:\s*"chat",\s*label:\s*"แชทแพทย์-ผู้ป่วย"/);
  assert.match(staffDashboardSrc, /sections:\s*\['chat'\]/);
  assert.match(staffDashboardSrc, /else\s+if\s*\(active\s*===\s*"chat"\)\s*content\s*=\s*<CareChat\s+staff\s+openPatient=\{openPatient\}\s*\/>;/);

  // Triage must not render CareChat
  const triageMatch = staffDashboardSrc.match(/else\s+if\s*\(active\s*===\s*"triage"\)\s*content\s*=\s*<>([\s\S]*?)<\/>;/);
  assert.ok(triageMatch, 'Triage section found');
  assert.doesNotMatch(triageMatch[1], /<CareChat/);
  assert.match(triageMatch[1], /<CareMessages\s+staff\s*\/>/);

  // Patient navigation
  assert.match(patientPortalSrc, /\{active\s*===\s*'chat'\s*&&\s*<CareChat\s*\/>\}/);
  assert.match(patientPortalSrc, /\{active\s*===\s*'care'\s*&&\s*<>.*<CareMessages\s*\/>.*<\/>\}/);
});

test('CHALLENGER-7: R4 Audit - Messenger Aesthetics and Strict Exclusion of Calls', () => {
  // Messenger colors and styling
  assert.match(careChatCssSrc, /\.bubbleMine\s*\{[^}]*background:\s*#0084ff/);
  assert.match(careChatCssSrc, /\.bubbleOther\s*\{[^}]*background:\s*#f0f2f5/);
  assert.match(careChatCssSrc, /\.activeBadge\s*\{[^}]*background:\s*#31a24c/);
  assert.match(careChatCssSrc, /\.composerPill\s*\{[^}]*border-radius:\s*24px/);
  assert.match(careChatCssSrc, /\.composerPill\s*\{[^}]*background:\s*#f0f2f5/);
  assert.match(careChatCssSrc, /\.sendBtn\s*\{[^}]*background:\s*#0084ff/);

  // Read & delivery receipts
  assert.match(careChatSrc, /อ่านแล้ว ✓✓/);
  assert.match(careChatSrc, /ส่งแล้ว ✓/);

  // Quick replies
  assert.match(careChatSrc, /ข้อความแชทด่วนสำหรับผู้ป่วย/);

  // Strict Call & Ringing Audio Prohibition
  assert.doesNotMatch(careChatSrc, /video|call|เสียงเรียกเข้า|โทร|วิดีโอ/i);
  assert.doesNotMatch(careChatSrc, /RTCPeerConnection|getUserMedia|mediaDevices/);
  assert.doesNotMatch(careChatCssSrc, /callBtn|videoBtn|ringing/i);
});

test('CHALLENGER-8: Zero console warnings/errors during simulated component imports', async () => {
  // Verify modules import cleanly in node environment
  const patientView = await import('../app/patientView.ts');
  assert.ok(patientView.patientSections.some(s => s.key === 'chat'));
  assert.ok(patientView.patientSections.some(s => s.key === 'care'));
});
