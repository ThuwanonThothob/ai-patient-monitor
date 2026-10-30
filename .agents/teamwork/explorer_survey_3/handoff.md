# Handoff Report: Investigation for Requirements R3 and R4

**Agent**: Explorer Survey 3 (`teamwork_preview_explorer`)  
**Working Directory**: `/Users/thuwanon/ai-patient-monitor/.agents/teamwork/explorer_survey_3`  
**Target Requirements**:
- **R3**: Clarifying and separating real-time Doctor–Patient chat navigation in the Staff Dashboard (`แชทแพทย์-ผู้ป่วย`) and clearly distinguishing it from general triage and asynchronous care requests in the Patient Portal.
- **R4**: Presenting the Doctor–Patient chat interface in a Facebook Messenger-inspired layout (conversation sidebar with avatars/initials, active status badges, rounded left/right bubbles, delivery/read indicators, rounded pill composer with quick replies).
- **R4**: Strictly excluding voice/video call controls and incoming call/ringing notifications across the app.

---

## 1. Observation

### 1.1 Current Staff Dashboard Navigation & Chat Placement (R3)
- **File**: `frontend/app/StaffDashboard.tsx`
  - Lines 24:
    ```tsx
    type Section = "overview" | "triage" | "patients" | "alerts" | "ai" | "research" | "reports" | "notifications" | "evidence" | "care";
    ```
    `"chat"` is completely absent from the `Section` union type.
  - Lines 49–67:
    ```tsx
    const nav: { id: Section; icon: string; label: string; detail: string }[] = [
      { id: "overview", icon: "⌂", label: "ภาพรวม", detail: "สถานะหอผู้ป่วยแบบ real-time" },
      { id: "triage", icon: "⌁", label: "ลำดับการดูแล", detail: "เริ่มจากผู้ป่วยที่ต้องตรวจสอบก่อน แล้วเปิดรายละเอียดเพื่อประเมิน" },
      ...
    ];
    const navGroups: { label: string; icon: string; sections: Section[] }[] = [
      { label: 'ภาพรวม', icon: 'overview', sections: ['overview'] },
      { label: 'ผู้ป่วย', icon: 'patients', sections: ['patients', 'care'] },
      { label: 'งานดูแล', icon: 'alerts', sections: ['triage', 'alerts'] },
      { label: 'AI', icon: 'ai', sections: ['ai', 'evidence', 'research'] },
      { label: 'เพิ่มเติม', icon: 'reports', sections: ['reports', 'notifications'] },
    ];
    ```
    There is no navigation entry for `chat` or `'แชทแพทย์-ผู้ป่วย'`.
  - Lines 410–416:
    ```tsx
    else if (active === "triage") content = <div className={styles.split}><div>
      <details className={styles.panel} open><summary>แชทระหว่างแพทย์และผู้ป่วย</summary><CareChat staff openPatient={openPatient} /></details>
      <details className={styles.panel} open={showMessages} onToggle={e => setShowMessages(e.currentTarget.open)}><summary>ข้อความจากผู้ป่วยและผู้ดูแล</summary><CareMessages staff /></details>
      <Header title="ใครควรได้รับการตรวจสอบก่อน?" text="รวมค่าสัญญาณชีพล่าสุดกับรายการแจ้งเตือนที่ยังไม่ปิด ไม่ใช่การวินิจฉัยของ AI" refresh={loadTriage} />
      ...
    ```
    `CareChat` is currently nested directly inside `active === "triage"`, embedded inside an open `<details>` element alongside `<CareMessages staff />` and the clinical triage board.
  - Lines 397:
    ```tsx
    <OperationsPanel alerts={() => setActive('alerts')} messages={() => { setShowMessages(true); setActive('triage'); }} />
    ```
    `OperationsPanel` accepts an optional `chat` callback (line 5: `chat?: () => void`), but `StaffDashboard.tsx` does not supply it; clicking "แชทแพทย์-ผู้ป่วยยังไม่อ่าน" currently falls back to `messages` which navigates to `triage`.

### 1.2 Patient Portal Chat vs Care Requests Distinction (R3)
- **File**: `frontend/app/PatientPortal.tsx`
  - Lines 43:
    ```tsx
    <button type="button" className={s.primary} onClick={() => setActive('chat')}><Icon name="chat" size={18} />แชทกับแพทย์และทีมดูแล{Boolean(chatStatus.data?.unread) && <span className={s.unread} aria-label={`ข้อความใหม่ ${chatStatus.data?.unread}`}>{chatStatus.data?.unread}</span>}</button>
    ```
  - Lines 68–69:
    ```tsx
    {active === 'care' && <><PatientCare {...careProps} /><CareMessages /></>}
    {active === 'chat' && <CareChat />}
    ```
- **File**: `frontend/app/patientView.ts`
  - Lines 7–8:
    ```ts
    { key: 'care', title: 'แผนดูแลของฉัน', description: 'งานที่ทีมดูแลยืนยันและสถานะล่าสุด', icon: 'care' },
    { key: 'chat', title: 'แชททีมดูแล', description: 'แชทข้อความกับแพทย์และทีมดูแล (Messenger)', icon: 'chat' },
    ```
- **File**: `frontend/app/CareMessages.tsx`
  - Lines 43–44:
    ```tsx
    <h2 className={s.h2}>{staff ? 'ข้อความจากผู้ป่วยและผู้ดูแล' : 'แจ้งเรื่องให้ทีมดูแล'}</h2>
    <p className={s.muted}>ช่องทางติดตามทั่วไป · ไม่มีการเฝ้าตอบรับฉุกเฉิน หากต้องการความช่วยเหลือทันทีให้ติดต่อทีมดูแลโดยตรง</p>
    ```
  - `CareMessages` represents asynchronous care ticketing (symptom, device, care questions), whereas `CareChat` provides direct two-way messaging between doctors and patients.

### 1.3 Current CareChat Component & Styles (R4)
- **File**: `frontend/app/CareChat.tsx`
  - Lines 46–55: Staff sidebar renders plain text buttons:
    ```tsx
    {filtered.map(item => <button type="button" key={item.patient_id} aria-pressed={selectedPatient === item.patient_id} onClick={() => setSelected(item.patient_id)}>
      <strong>{item.patient_display_name}</strong><span>{item.patient_id}{item.unread ? ' · ยังไม่อ่าน ' + item.unread : ''}</span><small>{drafts[item.patient_id]?.text ? 'มีข้อความร่างที่ยังไม่ส่ง' : item.message || 'ยังไม่มีข้อความ'}</small>
    </button>)}
    ```
    Lacks user avatars/initials, active status badges (e.g. green indicator), unread filter tabs, and modern hover/active states.
  - Line 96: Chat room header renders plain text:
    ```tsx
    <header><div><span className={s.kicker}>CARE TEAM CHAT</span><h2>{staff ? room.data?.patient_display_name ?? selectedPatient : 'แชทกับแพทย์และทีมดูแล'}</h2>{staff && <small>Patient ID: {selectedPatient}</small>}</div>...
    ```
    Lacks Messenger avatar with active status badge and clean Messenger profile header.
  - Lines 105–108: Message bubble rendering:
    ```tsx
    <article key={item.id} className={s.bubble + (mine ? ' ' + s.mine : '')}><b>{mine ? 'คุณ' : item.sender_display_name}</b><p>{item.message}</p><small>{time(item.created_at)}{mine ? item.read ? ' · อ่านแล้ว' : ' · ส่งแล้ว' : ''}</small></article>
    ```
  - Lines 110–114: Composer rendering:
    ```tsx
    <form onSubmit={send} className={s.form}><label ...><textarea id={...} rows={3} ... /><button ...>ส่งข้อความ</button></form>
    ```
    Uses a standard blocky textarea with 3 rows and rectangular submit button, rather than a rounded pill composer.
  - Lines 111–113: Quick replies:
    Quick replies are only displayed for `!staff`. The test suite contract in `frontend/tests/ui-contract.test.mjs` line 102 checks:
    ```js
    assert.match(careChatSource, /ข้อความแชทด่วนสำหรับผู้ป่วย/);
    ```

### 1.4 Voice/Video Call Controls & Ringing Notifications Audit (R4)
- Executed pattern searches across all `.ts`, `.tsx`, `.py`, `.css`, and `.html` files in the repository:
  - Query `video`: 0 results.
  - Query `voice`: 0 results.
  - Query `incoming`: 0 results.
  - Query `ring`: Only unrelated strings in documentation and Python AST tests.
  - Query `sound`: Found only `playCriticalChime` in `frontend/app/StaffDashboard.tsx` lines 80–105, which is an ICU vital signs alarm chime triggering when monitored telemetry crosses into `CRITICAL` threshold.
  - Web notifications in `frontend/app/chatNotify.ts` line 24 trigger silent system notifications: `new Notification('Smart Ward · มีข้อความใหม่', options)`.
  - Conclusion: No voice/video calling buttons, WebRTC components, incoming call modals, or call ringers currently exist in the codebase.

### 1.5 Backend & Frontend Test State
- Backend test command: `./.venv/bin/python -m unittest discover -s backend/tests -v`
  - Result: 151 tests run, **151 tests pass** in 7.126s.
  - Chat backend endpoints in `backend/care_chat.py` (`/api/care-chat/conversations`, `/api/care-chat/{id}`, `/api/care-chat/status`, `/api/me/chat`, `/api/me/chat/status`) are completely covered in `backend/tests/test_monitor_portals.py` and pass.
- Frontend test suite: `PATH="/opt/homebrew/bin:$PATH" npm test` in `/Users/thuwanon/ai-patient-monitor/frontend`
  - Fails on existing assertion `/ก\+ ตัวอักษรใหญ่/` because R1 removal is underway.
  - TypeScript check: 1 error in `StaffDashboard.tsx:10:26` due to R2 removal of `AskAgent` from `AgentAssistant.tsx`.
  - ESLint: Passes with 0 errors (`npm run lint`).

---

## 2. Logic Chain

1. **Separation of Doctor–Patient Chat (R3)**:
   - *Observation*: `CareChat` is embedded inside `active === "triage"` in `StaffDashboard.tsx`, while triage is intended for clinical urgency assessment (`ใครควรได้รับการตรวจสอบก่อน?`).
   - *Reasoning*: Triage is a screening workflow based on vital anomalies and unresolved alerts. Interleaving live two-way patient chat in the same screen clutters the interface and prevents direct navigation to conversations.
   - *Actionable Design*:
     1. Add `"chat"` to `Section` type in `StaffDashboard.tsx`.
     2. Add `{ id: "chat", icon: "chat", label: "แชทแพทย์-ผู้ป่วย", detail: "แชทข้อความสองทางแบบเรียลไทม์ระหว่างแพทย์และผู้ป่วย" }` to `nav`.
     3. Add `{ label: 'แชทแพทย์-ผู้ป่วย', icon: 'chat', sections: ['chat'] }` to `navGroups` so it is prominently accessible in the main sidebar.
     4. Remove `<CareChat staff openPatient={openPatient} />` from the `triage` view.
     5. Create dedicated `else if (active === "chat")` content block rendering `<CareChat staff openPatient={openPatient} />`.
     6. Connect `OperationsPanel`'s `chat` prop: `chat={() => setActive('chat')}`.
     7. In `PatientPortal.tsx`, ensure the distinction between `chat` ("แชทแพทย์-ผู้ป่วย / แชทสด") and `care` ("แผนดูแลของฉัน และ แจ้งเรื่อง/คำขอการดูแล (ไม่ใช่แชทสด)") is explicit.

2. **Facebook Messenger Visual Layout (R4)**:
   - *Observation*: Current `CareChat` uses boxy textareas, rectangular buttons, lacks user avatars, has no active status badges, and lacks Messenger-style message bubbles and read status.
   - *Reasoning*: Messenger's hallmark design consists of:
     - Multi-contact sidebar with round avatars with green active dot, unread filter tabs, and snippet previews.
     - Profile header displaying the current contact's avatar, initials, active status badge ("กำลังใช้งาน"), and role.
     - Distinct rounded bubbles: Sender bubbles (`mine`) on the right in Messenger blue (`#0084ff`) with delivery/read receipts (`ส่งแล้ว ✓` / `อ่านแล้ว ✓✓`); Recipient bubbles (`other`) on the left in light gray (`#f0f2f5`) with sender initials avatar.
     - Rounded pill chips for quick replies (`border-radius: 20px`).
     - Rounded pill input composer (`border-radius: 24px`, background `#f0f2f5`) with Enter-to-send and a circular Messenger send button.
   - *Actionable Design*:
     - Update `CareChat.tsx` and `CareChat.module.css` with modular CSS classes implementing this exact design system.
     - Retain `aria-label="ข้อความแชทด่วนสำหรับผู้ป่วย"` to preserve contract compliance with existing UI tests.

3. **Strict Exclusion of Call Controls & Ringing (R4)**:
   - *Observation*: There are currently no voice/video controls or ringing notifications anywhere in the app.
   - *Reasoning*: The requirement strictly forbids any voice/video call buttons or incoming call notifications.
   - *Actionable Design*: Ensure that no phone icon (`<Icon name="phone">`), video icon, or call action is ever added to the Messenger header, and assert this in automated UI contract tests.

---

## 3. Caveats

1. **Active Status Data**: The backend does not currently maintain persistent WebSocket heartbeat presence for patient online/offline status; active status is rendered as a simulated "พร้อมติดต่อ / ใช้งานอยู่" badge based on session authentication and recent messages.
2. **Push Notifications vs Ringing**: Web Push notifications are handled via Service Worker and browser `Notification` API. They deliver silent text notifications (`notifyNewChat`) and do not play audio ringtones or present call-answer overlays.
3. **Telemed / WebRTC**: No WebRTC peer connection or media streaming libraries exist in dependencies. The application is purely text-based communication.

---

## 4. Conclusion & Proposed Implementation

### 4.1 Changes to `frontend/app/StaffDashboard.tsx`
```tsx
// 1. Extend Section type
type Section = "overview" | "chat" | "triage" | "patients" | "alerts" | "ai" | "research" | "reports" | "notifications" | "evidence" | "care";

// 2. Add chat to nav
const nav: { id: Section; icon: string; label: string; detail: string }[] = [
  { id: "overview", icon: "⌂", label: "ภาพรวม", detail: "สถานะหอผู้ป่วยแบบ real-time" },
  { id: "chat", icon: "chat", label: "แชทแพทย์-ผู้ป่วย", detail: "แชทข้อความสองทางแบบเรียลไทม์ระหว่างแพทย์และผู้ป่วย" },
  { id: "triage", icon: "⌁", label: "ลำดับการดูแล", detail: "เริ่มจากผู้ป่วยที่ต้องตรวจสอบก่อน แล้วเปิดรายละเอียดเพื่อประเมิน" },
  ...
];

// 3. Add to navGroups
const navGroups: { label: string; icon: string; sections: Section[] }[] = [
  { label: 'ภาพรวม', icon: 'overview', sections: ['overview'] },
  { label: 'แชทแพทย์-ผู้ป่วย', icon: 'chat', sections: ['chat'] },
  { label: 'ผู้ป่วย', icon: 'patients', sections: ['patients', 'care'] },
  { label: 'งานดูแล', icon: 'alerts', sections: ['triage', 'alerts'] },
  { label: 'AI', icon: 'ai', sections: ['ai', 'evidence', 'research'] },
  { label: 'เพิ่มเติม', icon: 'reports', sections: ['reports', 'notifications'] },
];

// 4. Connect OperationsPanel chat prop
<OperationsPanel
  alerts={() => setActive('alerts')}
  messages={() => { setShowMessages(true); setActive('triage'); }}
  chat={() => setActive('chat')}
/>

// 5. In active === "triage", remove CareChat details block, leaving only CareMessages:
else if (active === "triage") content = <div className={styles.split}><div>
  <details className={styles.panel} open={showMessages} onToggle={e => setShowMessages(e.currentTarget.open)}><summary>ข้อความจากผู้ป่วยและผู้ดูแล (คำขอการดูแล)</summary><CareMessages staff /></details>
  <Header title="ใครควรได้รับการตรวจสอบก่อน?" text="รวมค่าสัญญาณชีพล่าสุดกับรายการแจ้งเตือนที่ยังไม่ปิด ไม่ใช่การวินิจฉัยของ AI" refresh={loadTriage} />
  ...
</div>{assistantPanel}</div>;

// 6. Add dedicated chat section:
else if (active === "chat") content = <div className={styles.split}><div>
  <CareChat staff openPatient={openPatient} />
</div>{assistantPanel}</div>;
```

### 4.2 Changes to `frontend/app/CareChat.tsx`
Replace `CareChat.tsx` with full Messenger structure:
- Avatars with deterministic colored backgrounds and initials (`getInitials`, `getAvatarColor`).
- Active status badges (green dot `#31a24c`).
- Conversation filter tabs ("ทั้งหมด" / "ยังไม่อ่าน").
- Messenger-style profile header with active dot and status text.
- Left/Right message bubbles with delivery and read indicators (`อ่านแล้ว ✓✓` / `ส่งแล้ว ✓`).
- Quick reply pill chips with `aria-label="ข้อความแชทด่วนสำหรับผู้ป่วย"`.
- Rounded pill composer with auto-resize, Enter key handler, and circular send button.
- Zero call buttons (phone/camera) or ringing triggers.

### 4.3 Changes to `frontend/app/CareChat.module.css`
Update styles to provide:
- `.staffLayout`: modern 2-column Messenger desktop frame (310px sidebar + flex chat window).
- `.avatar` & `.activeBadge`: circular avatars with green active badge.
- `.bubbleMine`: `#0084ff`, `color: #fff`, `border-radius: 18px 18px 4px 18px`.
- `.bubbleOther`: `#f0f2f5`, `color: #050505`, `border-radius: 18px 18px 18px 4px`.
- `.quickPill`: rounded pill chips (`border-radius: 20px`).
- `.composerPill`: pill input wrapper (`border-radius: 24px`, background `#f0f2f5`).
- `.sendBtn`: circular blue button with send paper plane icon.

### 4.4 Contract Tests to Add in `frontend/tests/ui-contract.test.mjs`
```js
test('Doctor-Patient chat is separated in StaffDashboard and formatted in Messenger style', () => {
  const staffSource = readFileSync(new URL('../app/StaffDashboard.tsx', import.meta.url), 'utf8');
  assert.match(staffSource, /id:\s*["']chat["']/);
  assert.match(staffSource, /แชทแพทย์-ผู้ป่วย/);
  // Ensure CareChat is not in triage section
  assert.doesNotMatch(staffSource, /active === ['"]triage['"][^]*?<CareChat/);

  const careChatSource = readFileSync(new URL('../app/CareChat.tsx', import.meta.url), 'utf8');
  assert.match(careChatSource, /activeBadge/);
  assert.match(careChatSource, /bubbleMine/);
  assert.match(careChatSource, /bubbleOther/);
  assert.match(careChatSource, /composerPill/);
  assert.match(careChatSource, /ข้อความแชทด่วนสำหรับผู้ป่วย/);
  // Ensure strict exclusion of voice/video call controls
  assert.doesNotMatch(careChatSource, /video|call|เสียงเรียกเข้า|โทร|วิดีโอ/i);
});
```

---

## 5. Verification Method

1. **Backend Tests**:
   ```bash
   ./.venv/bin/python -m unittest discover -s backend/tests -p "test_monitor_portals.py" -v
   ```
   *Expected*: 39/39 tests pass.

2. **Frontend Type Check**:
   ```bash
   PATH="/opt/homebrew/bin:$PATH" npx tsc --noEmit
   ```
   *Expected*: 0 errors after resolving the `AskAgent` reference in `StaffDashboard.tsx`.

3. **Frontend Linter**:
   ```bash
   PATH="/opt/homebrew/bin:$PATH" npm run lint
   ```
   *Expected*: 0 ESLint errors.

4. **Frontend Unit & UI Contract Tests**:
   ```bash
   PATH="/opt/homebrew/bin:$PATH" npm test
   ```
   *Expected*: All tests pass, including `ui-contract.test.mjs`.

5. **Manual / Visual Verification Checklist**:
   - [ ] In Staff Dashboard, click sidebar item "แชทแพทย์-ผู้ป่วย": navigates to dedicated Messenger chat screen.
   - [ ] In Staff Dashboard, navigate to "ลำดับการดูแล" (Triage): confirms `CareChat` is absent and only triage/care messages remain.
   - [ ] In Overview tab, click "แชทแพทย์-ผู้ป่วยยังไม่อ่าน": directly opens the `chat` section.
   - [ ] Chat conversation list displays initials avatar, patient name, timestamp, and green active badge.
   - [ ] Chat bubbles render Messenger blue on the right (with read indicators) and light gray on the left.
   - [ ] Pill composer allows typing and sending with Enter or clicking the circular send button.
   - [ ] No voice or video buttons appear anywhere on the header or chat room.
