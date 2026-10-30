import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import ts from 'typescript';

const staffDashboardPath = resolve('app/StaffDashboard.tsx');
const careChatPath = resolve('app/CareChat.tsx');
const careChatCssPath = resolve('app/CareChat.module.css');
const patientPortalPath = resolve('app/PatientPortal.tsx');
const operationsPanelPath = resolve('app/OperationsPanel.tsx');
const chatNotifyPath = resolve('app/chatNotify.ts');

const staffDashboardSrc = readFileSync(staffDashboardPath, 'utf8');
const careChatSrc = readFileSync(careChatPath, 'utf8');
const careChatCssSrc = readFileSync(careChatCssPath, 'utf8');
const patientPortalSrc = readFileSync(patientPortalPath, 'utf8');
const operationsPanelSrc = readFileSync(operationsPanelPath, 'utf8');
const chatNotifySrc = readFileSync(chatNotifyPath, 'utf8');

test('M3-ADVERSARIAL-1: StaffDashboard.tsx type safety & top-level chat navigation structure', () => {
  // R3: Section union type must include "chat"
  assert.match(staffDashboardSrc, /type\s+Section\s*=\s*[^;]*"chat"[^;]*;/, 'Section union must include "chat"');

  // R3: nav array must register 'chat' with icon and Thai label
  assert.match(staffDashboardSrc, /\{\s*id:\s*"chat",\s*icon:\s*"chat",\s*label:\s*"แชทแพทย์-ผู้ป่วย",\s*detail:\s*"[^"]+"\s*\}/, 'nav array must contain chat entry');

  // R3: navGroups must feature a top-level dedicated group for 'chat'
  assert.match(staffDashboardSrc, /\{\s*label:\s*'แชทแพทย์-ผู้ป่วย',\s*icon:\s*'chat',\s*sections:\s*\['chat'\]\s*\}/, 'navGroups must contain dedicated chat group');

  // R3: History state updates must reflect ?section=chat
  assert.match(staffDashboardSrc, /history\.replaceState\(null,\s*'',\s*`\?section=\$\{group\.sections\[0\]\}`\)/, 'Nav click must update history with section');
});

test('M3-ADVERSARIAL-2: StaffDashboard.tsx strict triage & chat isolation', () => {
  // R3: Dedicated active === "chat" branch must render CareChat with staff and openPatient props
  assert.match(staffDashboardSrc, /else\s+if\s*\(active\s*===\s*"chat"\)\s*content\s*=\s*<CareChat\s+staff\s+openPatient=\{openPatient\}\s*\/>;/, 'active === "chat" must render CareChat');

  // Extract the entire active === "triage" block
  const triageBlockMatch = staffDashboardSrc.match(/else\s+if\s*\(active\s*===\s*"triage"\)\s*content\s*=\s*<>([\s\S]*?)<\/>;/);
  assert.ok(triageBlockMatch, 'active === "triage" block must exist');
  const triageBlock = triageBlockMatch[1];

  // R3: Triage must render CareMessages (asynchronous care requests), NEVER CareChat
  assert.match(triageBlock, /<CareMessages\s+staff\s*\/>/, 'Triage must render CareMessages');
  assert.doesNotMatch(triageBlock, /<CareChat/i, 'Triage must NEVER embed CareChat');
  assert.doesNotMatch(triageBlock, /แชทระหว่างแพทย์และผู้ป่วย/, 'Triage must not contain previous embedded chat summary');

  // Ensure CareChat is not rendered in any other section
  const nonChatContent = staffDashboardSrc.replace(/else\s+if\s*\(active\s*===\s*"chat"\)\s*content\s*=\s*<CareChat[\s\S]*?;/, '');
  assert.doesNotMatch(nonChatContent, /<CareChat/i, 'CareChat must not be rendered anywhere outside active === "chat"');
});

test('M3-ADVERSARIAL-3: OperationsPanel wiring to chat vs messages', () => {
  // OperationsPanel props interface must declare optional chat callback
  assert.match(operationsPanelSrc, /chat\?:\s*\(\)\s*=>\s*void/, 'OperationsPanel must declare optional chat prop');

  // OperationsPanel must connect unread chat button to chat callback
  assert.match(operationsPanelSrc, /<button\s+className=\{s\.primary\}\s+onClick=\{chat\s*\?\?\s*messages\}>แชทแพทย์-ผู้ป่วยยังไม่อ่าน\s*\{data\.chat_unread\}<\/button>/, 'Unread chat button must trigger chat callback');

  // StaffDashboard must pass chat={() => setActive('chat')} to OperationsPanel
  assert.match(staffDashboardSrc, /<OperationsPanel[\s\S]*?chat=\{\(\)\s*=>\s*setActive\('chat'\)\}/, 'StaffDashboard must pass setActive("chat") to OperationsPanel');

  // StaffDashboard messages callback must route to triage, not chat
  assert.match(staffDashboardSrc, /messages=\{\(\)\s*=>\s*\{\s*setShowMessages\(true\);\s*setActive\('triage'\);\s*\}\}/, 'OperationsPanel messages must route to triage with showMessages');
});

test('M3-ADVERSARIAL-4: PatientPortal.tsx chat vs care separation', () => {
  // R3: PatientPortal imports CareChat and CareMessages separately
  assert.match(patientPortalSrc, /import\s+CareChat\s+from\s+'\.\/CareChat';/, 'PatientPortal must import CareChat');
  assert.match(patientPortalSrc, /import\s+CareMessages\s+from\s+'\.\/CareMessages';/, 'PatientPortal must import CareMessages');

  // R3: active === 'chat' renders CareChat; active === 'care' renders CareMessages
  assert.match(patientPortalSrc, /\{active\s*===\s*'chat'\s*&&\s*<CareChat\s*\/>\}/, 'PatientPortal active === "chat" must render CareChat');
  assert.match(patientPortalSrc, /\{active\s*===\s*'care'\s*&&\s*<>[\s\S]*?<CareMessages\s*\/>[\s\S]*?<\/>\}/, 'PatientPortal active === "care" must render CareMessages');

  // Distinct action buttons in hero
  assert.match(patientPortalSrc, /onClick=\{\(\)\s*=>\s*setActive\('chat'\)\}>[\s\S]*?แชทข้อความกับแพทย์และทีมดูแล\s*\(Messenger\)/, 'PatientPortal must provide Messenger chat button');
  assert.match(patientPortalSrc, /onClick=\{\(\)\s*=>\s*setActive\('care'\)\}>แจ้งเรื่อง\s*\/\s*ติดตามงานดูแล/, 'PatientPortal must provide separate care requests button');
});

test('M3-ADVERSARIAL-5: CareChat multi-contact sidebar & conversation filtering (Facebook Messenger layout)', () => {
  // Layout grid definition: sidebar minmax(280px, 330px) + chat minmax(0, 1fr)
  assert.match(careChatCssSrc, /\.staffLayout\s*\{[^}]*grid-template-columns:\s*minmax\(280px,\s*330px\)\s+minmax\(0,\s*1fr\)/, 'CSS must define 2-column Messenger layout');
  assert.match(careChatCssSrc, /\.staffLayout\s*\{[^}]*height:\s*740px/, 'staffLayout must have fixed Messenger height');

  // Sidebar header with title and unread pill
  assert.match(careChatSrc, /แชทผู้ป่วย/, 'Sidebar must title section "แชทผู้ป่วย"');
  assert.match(careChatSrc, /className=\{s\.unreadPill\}/, 'Sidebar header must render unread pill');
  assert.match(careChatCssSrc, /\.unreadPill\s*\{[^}]*background:\s*#0084ff/, 'Unread pill must be Messenger blue');

  // Filter tabs: role="tablist", "ทั้งหมด", "ยังไม่อ่าน"
  assert.match(careChatSrc, /role="tablist"\s+aria-label="ตัวกรองบทสนทนา"/, 'Filter tabs must be an accessible tablist');
  assert.match(careChatSrc, /aria-selected=\{filterTab\s*===\s*'all'\}/, 'All tab must bind aria-selected');
  assert.match(careChatSrc, /aria-selected=\{filterTab\s*===\s*'unread'\}/, 'Unread tab must bind aria-selected');
  assert.match(careChatCssSrc, /\.filterTabs\s*\{[^}]*background:\s*#f0f2f5/, 'Filter tabs container must have gray Messenger pill background');
  assert.match(careChatCssSrc, /\.filterTabActive\s*\{[^}]*color:\s*#0084ff/, 'Active filter tab must have Messenger blue text');

  // Room item with active badge and unread badge
  assert.match(careChatSrc, /className=\{`\$\{s\.roomItem\}\s+\$\{isSelected\s*\?\s*s\.roomItemActive\s*:\s*''\}`\}/, 'Room item must toggle active styling');
  assert.match(careChatCssSrc, /\.roomItemActive\s*\{[^}]*background:\s*#eaf3fe/, 'Active room must have light blue tint');
  assert.match(careChatSrc, /<span\s+className=\{s\.activeBadge\}\s+title="พร้อมติดต่อ \/ ใช้งานอยู่"\s*\/>/, 'Room item must display active presence badge');
  assert.match(careChatCssSrc, /\.activeBadge\s*\{[^}]*background:\s*#31a24c/, 'Active badge must be Messenger green #31a24c');
  assert.match(careChatCssSrc, /\.activeBadge\s*\{[^}]*border-radius:\s*50%/, 'Active badge must be circular');
  assert.match(careChatCssSrc, /\.activeBadge\s*\{[^}]*border:\s*2px solid #ffffff/, 'Active badge must have 2px white border');
});

test('M3-ADVERSARIAL-6: Avatar Initials & Color Generation Oracles', () => {
  // Extract getInitials, AVATAR_PALETTE, and getAvatarColor functions from source
  const getInitialsCode = careChatSrc.match(/function getInitials\(name:\s*string\):\s*string\s*\{([\s\S]*?)\n\}/);
  assert.ok(getInitialsCode, 'getInitials function must exist');

  const paletteCode = careChatSrc.match(/const AVATAR_PALETTE\s*=\s*(\[[\s\S]*?\]);/);
  assert.ok(paletteCode, 'AVATAR_PALETTE must exist');

  const getAvatarColorCode = careChatSrc.match(/function getAvatarColor\(identifier:\s*string\):\s*string\s*\{([\s\S]*?)\n\}/);
  assert.ok(getAvatarColorCode, 'getAvatarColor function must exist');

  // Transpile TypeScript snippets to plain JavaScript
  const tsCode = `
    ${paletteCode[0]}
    ${getAvatarColorCode[0]}
    ${getInitialsCode[0]}
    export { getInitials, getAvatarColor, AVATAR_PALETTE };
  `;
  const jsCode = ts.transpileModule(tsCode, { compilerOptions: { module: ts.ModuleKind.CommonJS } }).outputText;

  const oracleModule = { exports: {} };
  new Function('exports', jsCode)(oracleModule.exports);

  const { getInitials, getAvatarColor, AVATAR_PALETTE } = oracleModule.exports;

  // Oracle 1: getInitials behavior
  assert.equal(getInitials(''), '?', 'Empty string must return "?"');
  assert.ok(['?', ''].includes(getInitials('   ')), 'Whitespace only returns fallback "?" or empty string');
  assert.equal(getInitials('John Doe'), 'JD', 'Two English words must return first letters');
  assert.equal(getInitials('Dr. Jane Smith'), 'DJ', 'Three English words must return first two words initials');
  assert.equal(getInitials('Alice'), 'AL', 'Single English word must return first two characters');
  assert.equal(getInitials('สมชาย ใจดี'), 'สใ', 'Two Thai words must return first characters');
  assert.equal(getInitials('สมชาย'), 'สม', 'Single Thai word must return first two characters');
  assert.equal(getInitials('  วิชัย   สวัสดี  '), 'วส', 'Multiple spaces must be normalized');

  // Oracle 2: getAvatarColor behavior
  assert.ok(AVATAR_PALETTE.includes('#0084ff'), 'Palette must include Messenger blue');
  assert.ok(AVATAR_PALETTE.length >= 6, 'Palette must have at least 6 distinct colors');

  // Determinism check: same input always produces same color
  for (const id of ['P001', 'P002', 'B104', 'PT-999', 'care-team', 'แพทย์ประจำเวร']) {
    const col1 = getAvatarColor(id);
    const col2 = getAvatarColor(id);
    assert.equal(col1, col2, `getAvatarColor must be deterministic for ${id}`);
    assert.ok(AVATAR_PALETTE.includes(col1), `Color ${col1} must belong to AVATAR_PALETTE`);
  }

  // Distribution check: different IDs should cover diverse colors
  const colorSet = new Set(['P001', 'P002', 'P003', 'P004', 'P005', 'P006', 'P007', 'P008'].map(getAvatarColor));
  assert.ok(colorSet.size >= 3, 'Hashing must distribute patient IDs across multiple colors');
});

test('M3-ADVERSARIAL-7: Messenger Room Header & Controls', () => {
  // Header structure: profile with avatar, active badge, status text
  assert.match(careChatSrc, /<header\s+className=\{s\.chatHeader\}>/, 'Chat must render chatHeader');
  assert.match(careChatSrc, /className=\{s\.avatar\}[\s\S]*?background:\s*getAvatarColor\(avatarIdentifier\)/, 'Header must render colored avatar');
  assert.match(careChatSrc, /<span\s+className=\{s\.statusDot\}\s*\/>/, 'Header must render active status dot');
  assert.match(careChatSrc, /<span>พร้อมติดต่อ \/ ใช้งานอยู่<\/span>/, 'Header must display presence label');

  // Staff patient profile inspection shortcut
  assert.match(careChatSrc, /openPatient\(room\.data!\.patient_id\)/, 'Staff header must provide profile shortcut button');
  assert.match(careChatSrc, />\s*ดูโปรไฟล์และสัญญาณชีพ\s*<\/button>/, 'Header button label must be explicit');

  // Refresh and Push notifications toggle buttons
  assert.match(careChatSrc, /room\.refresh/, 'Header must provide refresh button');
  assert.match(careChatSrc, /setShowPush\(value\s*=>\s*!value\)/, 'Header must provide push configuration button');
});

test('M3-ADVERSARIAL-8: Facebook Messenger Message Bubbles & Delivery Status', () => {
  // Outgoing bubbles (mine):
  assert.match(careChatSrc, /mine\s*\?\s*s\.rowMine\s*:\s*s\.rowOther/, 'Message row must align mine right and other left');
  assert.match(careChatSrc, /mine\s*\?\s*s\.bubbleMine\s*:\s*s\.bubbleOther/, 'Message bubble must apply mine vs other class');

  // CSS: .bubbleMine
  assert.match(careChatCssSrc, /\.bubbleMine\s*\{[^}]*background:\s*#0084ff/, 'bubbleMine must use Messenger blue #0084ff');
  assert.match(careChatCssSrc, /\.bubbleMine\s*\{[^}]*color:\s*#ffffff/, 'bubbleMine must use white text');
  assert.match(careChatCssSrc, /\.bubbleMine\s*\{[^}]*border-radius:\s*18px\s+18px\s+4px\s+18px/, 'bubbleMine must have Messenger asymmetric rounded corners');

  // Delivery status receipts for outgoing messages
  assert.match(careChatSrc, /item\.read\s*\?\s*' · อ่านแล้ว ✓✓'\s*:\s*' · ส่งแล้ว ✓'/, 'Outgoing messages must display read (✓✓) or sent (✓) receipts');

  // Incoming bubbles (other):
  assert.match(careChatCssSrc, /\.bubbleOther\s*\{[^}]*background:\s*#f0f2f5/, 'bubbleOther must use Messenger gray #f0f2f5');
  assert.match(careChatCssSrc, /\.bubbleOther\s*\{[^}]*color:\s*#050505/, 'bubbleOther must use dark text');
  assert.match(careChatCssSrc, /\.bubbleOther\s*\{[^}]*border-radius:\s*18px\s+18px\s+18px\s+4px/, 'bubbleOther must have Messenger asymmetric left corners');
  assert.match(careChatSrc, /<div\s+className=\{s\.avatarSmall\}\s+style=\{\{\s*background:\s*senderColor\s*\}\}/, 'Incoming messages must show small sender initials avatar');
  assert.match(careChatSrc, /<b\s+className=\{s\.senderName\}>\{item\.sender_display_name\}<\/b>/, 'Incoming messages must show sender display name');
});

test('M3-ADVERSARIAL-9: Rounded Pill Composer & Quick Replies', () => {
  // Pill composer wrapper
  assert.match(careChatSrc, /<div\s+className=\{s\.composerPill\}>/, 'Composer must render pill wrapper');
  assert.match(careChatCssSrc, /\.composerPill\s*\{[^}]*border-radius:\s*24px/, 'composerPill must have 24px border radius');
  assert.match(careChatCssSrc, /\.composerPill\s*\{[^}]*background:\s*#f0f2f5/, 'composerPill must have #f0f2f5 gray background');
  assert.match(careChatCssSrc, /\.composerPill:focus-within\s*\{[^}]*border-color:\s*#0084ff/, 'composerPill focus-within must highlight with Messenger blue');

  // Circular Send Button
  assert.match(careChatSrc, /<button\s+type="submit"\s+className=\{s\.sendBtn\}\s+aria-label="ส่งข้อความ"/, 'Send button must be submit type with aria-label');
  assert.match(careChatCssSrc, /\.sendBtn\s*\{[^}]*width:\s*34px;\s*height:\s*34px;\s*border-radius:\s*50%/, 'sendBtn must be 34px circle');
  assert.match(careChatCssSrc, /\.sendBtn\s*\{[^}]*background:\s*#0084ff/, 'sendBtn must have #0084ff blue background');

  // Keyboard shortcut: Enter to send, Shift+Enter for newline
  assert.match(careChatSrc, /if\s*\(event\.key\s*===\s*'Enter'\s*&&\s*!event\.shiftKey\)/, 'Enter key without Shift must trigger send');
  assert.match(careChatSrc, /event\.preventDefault\(\)/, 'Enter key default must be prevented');

  // Textarea constraints: maxLength 2000
  assert.match(careChatSrc, /maxLength=\{2000\}/, 'Composer textarea must enforce maxLength 2000');
  assert.match(careChatSrc, /\{draft\.text\.length\}\/2,000 ตัวอักษร/, 'Composer must show character counter');

  // Quick replies for patients
  assert.match(careChatSrc, /\{!staff\s*&&\s*\([\s\S]*?s\.quickSection[\s\S]*?\)\}/, 'Quick replies must only render when !staff');
  assert.match(careChatSrc, /aria-label="ข้อความแชทด่วนสำหรับผู้ป่วย"/, 'Quick replies row must have exact accessibility label');
  assert.match(careChatCssSrc, /\.quickPill\s*\{[^}]*border-radius:\s*20px/, 'quickPill must have 20px pill border-radius');
  assert.match(careChatCssSrc, /\.quickPill\s*\{[^}]*color:\s*#0084ff/, 'quickPill text must be Messenger blue');
});

test('M3-ADVERSARIAL-10: Strict exclusion of Voice/Video Call Controls, Dialers, and Ringing Audio', () => {
  // Comprehensive forbidden regex covering English and Thai call, video, audio, phone, and ringing vocabulary
  const forbiddenPatterns = [
    /\b(call|video|camera|phone|webrtc|audio_call|video_call|ringer|ringing|incoming_call|dial)\b/i,
    /สายเรียกเข้า|เสียงเรียกเข้า|วิดีโอคอล|คอล|โทรศัพท์|โทรฟรี|โทรออก|โทรหา/i,
    /<audio\b/i,
    /<video\b/i,
  ];

  for (const pattern of forbiddenPatterns) {
    assert.doesNotMatch(careChatSrc, pattern, `CareChat.tsx must NOT match forbidden call pattern: ${pattern}`);
    assert.doesNotMatch(careChatCssSrc, pattern, `CareChat.module.css must NOT match forbidden call pattern: ${pattern}`);
  }

  // Verify that emergency notice does NOT use "โทร 1669" (must use "ติดต่อ 1669")
  assert.doesNotMatch(careChatSrc, /โทร\s*1669/, 'CareChat.tsx must not say "โทร 1669"');
  assert.match(careChatSrc, /ติดต่อ\s*1669/, 'CareChat.tsx must say "ติดต่อ 1669"');

  // Verify that NotificationPanel does not trigger audio calls
  const notificationPanelSrc = readFileSync(resolve('app/NotificationPanel.tsx'), 'utf8');
  assert.doesNotMatch(notificationPanelSrc, /สายเรียกเข้า|เสียงเรียกเข้า|incoming_call/i, 'NotificationPanel must not contain call rings');
});

test('M3-ADVERSARIAL-11: Silent Web Push Notification contract for chat', () => {
  // Verify chatNotify.ts issues silent text notifications without audio or ringing
  assert.match(chatNotifySrc, /tag:\s*'smart-ward-care-chat'/, 'notifyNewChat must set chat tag');
  assert.match(chatNotifySrc, /Smart Ward · มีข้อความใหม่/, 'notifyNewChat must provide generic text notification title');
  assert.doesNotMatch(chatNotifySrc, /Audio|play|sound|ring/i, 'notifyNewChat must not play audio or ringtone');
});

test('M3-ADVERSARIAL-12: Responsive Breakpoints and Mobile Touch Targets', () => {
  // Tablet breakpoint (max-width: 820px)
  const tabletMedia = careChatCssSrc.match(/@media\s*\(max-width:\s*820px\)\s*\{([\s\S]*?)\n\}/);
  assert.ok(tabletMedia, 'Tablet media query must exist');
  assert.match(tabletMedia[1], /\.staffLayout\s*\{[^}]*grid-template-columns:\s*1fr/, 'Tablet media query must collapse staffLayout into single column');

  // Mobile breakpoint (max-width: 520px)
  const mobileMedia = careChatCssSrc.match(/@media\s*\(max-width:\s*520px\)\s*\{([\s\S]*?)\n\}/);
  assert.ok(mobileMedia, 'Mobile media query must exist');
  assert.match(mobileMedia[1], /\.bubbleMine,\s*\.bubbleOther\s*\{[^}]*max-width:\s*86%/, 'Mobile media query must widen bubble max-width to 86%');
  assert.match(mobileMedia[1], /\.chatHeader\s*\{[^}]*flex-direction:\s*column/, 'Mobile header must stack vertically');
});
