import { readFileSync } from 'node:fs';
import test from 'node:test';
import assert from 'node:assert/strict';

test('Doctor-Patient chat is separated into dedicated section in StaffDashboard', () => {
  const staffSource = readFileSync(new URL('../app/StaffDashboard.tsx', import.meta.url), 'utf8');

  // R3: Section union includes 'chat'
  assert.match(staffSource, /type\s+Section\s*=\s*[^;]*"chat"/);

  // R3: Nav has 'chat' with label 'แชทแพทย์-ผู้ป่วย'
  assert.match(staffSource, /id:\s*"chat",\s*icon:\s*"chat",\s*label:\s*"แชทแพทย์-ผู้ป่วย"/);

  // R3: NavGroups has 'แชทแพทย์-ผู้ป่วย'
  assert.match(staffSource, /label:\s*'แชทแพทย์-ผู้ป่วย',\s*icon:\s*'chat',\s*sections:\s*\['chat'\]/);

  // R3: OperationsPanel chat prop is connected
  assert.match(staffSource, /chat=\{\(\)\s*=>\s*setActive\('chat'\)\}/);

  // R3: Dedicated active === "chat" section renders CareChat
  assert.match(staffSource, /active === "chat"\)\s*content\s*=\s*<CareChat staff openPatient=\{openPatient\} \/>/);

  // R3: Triage section does NOT embed CareChat
  assert.doesNotMatch(staffSource, /active === "triage"\)\s*content\s*=\s*<>[\s\S]*?<CareChat/);
});

test('CareChat renders Facebook Messenger UI layout and adheres to strict call exclusion', () => {
  const careChatSource = readFileSync(new URL('../app/CareChat.tsx', import.meta.url), 'utf8');
  const cssSource = readFileSync(new URL('../app/CareChat.module.css', import.meta.url), 'utf8');

  // R4: Multi-contact sidebar with avatars, initials, and active badge
  assert.match(careChatSource, /getInitials/);
  assert.match(careChatSource, /getAvatarColor/);
  assert.match(careChatSource, /activeBadge/);
  assert.match(cssSource, /\.activeBadge\s*\{[^}]*background:\s*#31a24c/);

  // R4: Conversation filter tabs
  assert.match(careChatSource, /filterTab/);
  assert.match(careChatSource, /ทั้งหมด/);
  assert.match(careChatSource, /ยังไม่อ่าน/);

  // R4: Message bubbles with Messenger blue (#0084ff) and gray (#f0f2f5)
  assert.match(careChatSource, /bubbleMine/);
  assert.match(careChatSource, /bubbleOther/);
  assert.match(cssSource, /\.bubbleMine\s*\{[^}]*background:\s*#0084ff/);
  assert.match(cssSource, /\.bubbleOther\s*\{[^}]*background:\s*#f0f2f5/);

  // R4: Delivery and read receipts
  assert.match(careChatSource, /อ่านแล้ว ✓✓/);
  assert.match(careChatSource, /ส่งแล้ว ✓/);

  // R4: Quick replies for patients
  assert.match(careChatSource, /ข้อความแชทด่วนสำหรับผู้ป่วย/);
  assert.match(careChatSource, /quickPill/);

  // R4: Rounded pill composer with circular send button
  assert.match(careChatSource, /composerPill/);
  assert.match(cssSource, /\.composerPill\s*\{[^}]*border-radius:\s*24px/);
  assert.match(cssSource, /\.composerPill\s*\{[^}]*background:\s*#f0f2f5/);
  assert.match(careChatSource, /sendBtn/);
  assert.match(cssSource, /\.sendBtn\s*\{[^}]*background:\s*#0084ff/);

  // R4: Strict exclusion of voice/video call controls and ringing notifications
  assert.doesNotMatch(careChatSource, /video|call|เสียงเรียกเข้า|โทร|วิดีโอ/i);
});
