# Investigation and Survey Report — Requirement R1: Patient Portal Typography, Removal of Text Enlargement & Clinical Review Workflow

**Agent**: Explorer Survey 1 (Replacement) (`teamwork_preview_explorer`)  
**Working Directory**: `/Users/thuwanon/ai-patient-monitor/.agents/teamwork/explorer_survey_1_repl`  
**Parent Conversation ID**: `2af93610-4a29-43c8-bcdc-29f45eb79fe3`  
**Authoritative Scope**: Requirement R1 from `/Users/thuwanon/ai-patient-monitor/.agents/teamwork/ORIGINAL_REQUEST.md` and `/Users/thuwanon/ai-patient-monitor/.agents/teamwork/explorer_survey_1_repl/DISPATCH.md`

---

## 1. Observation

### 1.1 Patient Text-Enlargement Toggle and `.largeText` Mode in `PatientPortal.tsx` and `PatientPortal.module.css`

Direct inspection of `frontend/app/PatientPortal.tsx` and `git diff frontend/app/PatientPortal.tsx` reveals the complete anatomy of the text enlargement feature:

1. **Local Storage Key and Component State**:
   In the pre-modification version of `frontend/app/PatientPortal.tsx`:
   ```tsx
   const LARGE_TEXT_KEY = 'smart-ward-large-text';

   export default function PatientPortal() {
     const live = usePatientResource<PatientRecord>('/api/me', 3000, true);
     const [largeText, setLargeText] = useState(() => {
       try { return typeof window !== 'undefined' && localStorage.getItem(LARGE_TEXT_KEY) === '1'; } catch { return false; }
     });
     function toggleLargeText() {
       setLargeText((prev) => {
         const next = !prev;
         try { localStorage.setItem(LARGE_TEXT_KEY, next ? '1' : '0'); } catch { /* ignore */ }
         return next;
       });
     }
     return <main id="main-content" tabIndex={-1} className={`${s.page} ${largeText ? s.largeText : ''}`}>
       ...
       : <PatientWorkspace key={live.data.patient_id} patient={live.data} refresh={live.refresh} loading={live.loading} largeText={largeText} toggleLargeText={toggleLargeText} />}
       ...
   ```

2. **Toggle Button Rendering in Hero Section**:
   In `PatientWorkspace`:
   ```tsx
   <div className={s.heroActions}>
     <button type="button" aria-pressed={largeText} onClick={toggleLargeText} aria-label="ปรับขนาดตัวอักษรสำหรับผู้ป่วย">
       {largeText ? 'ก+ ตัวอักษรใหญ่: เปิด' : 'ก+ ตัวอักษรใหญ่'}
     </button>
     <span className={s.badge}>{fresh ? 'ได้รับข้อมูลการวัดล่าสุด' : 'รอข้อมูลการวัดใหม่'}</span>
   </div>
   ```

3. **Current Unstaged Modifications in `PatientPortal.tsx`**:
   The working copy has cleanly removed:
   - `LARGE_TEXT_KEY` constant
   - `largeText` state variable and `toggleLargeText` handler
   - `largeText` and `toggleLargeText` prop drilling to `PatientWorkspace`
   - Dynamic class `${largeText ? s.largeText : ''}` on `<main>` (now cleanly `className={s.page}`)
   - The toggle button `<button type="button" ...>{largeText ? 'ก+ ตัวอักษรใหญ่: เปิด' : 'ก+ ตัวอักษรใหญ่'}</button>`
   In its place in `heroActions` (line 43), the hero now renders a prominent primary action button for direct Doctor–Patient communication:
   ```tsx
   <header className={s.hero}>
     <div className={s.identity}>
       <div className={s.avatar}><Icon name="patients" size={28} /></div>
       <div>
         <span className={s.eyebrow}>MY CARE · {patient.patient_id}</span>
         <h1>การดูแลของฉัน</h1>
         <p>โซน {patient.profile.zone} · ห้อง {patient.profile.room_number}</p>
       </div>
     </div>
     <div className={s.heroActions}>
       <button type="button" className={s.primary} onClick={() => setActive('chat')}>
         <Icon name="chat" size={18} />
         แชทกับแพทย์และทีมดูแล
         {Boolean(chatStatus.data?.unread) && <span className={s.unread} aria-label={`ข้อความใหม่ ${chatStatus.data?.unread}`}>{chatStatus.data?.unread}</span>}
       </button>
       <span className={s.badge}>{fresh ? 'ได้รับข้อมูลการวัดล่าสุด' : 'รอข้อมูลการวัดใหม่'}</span>
     </div>
   </header>
   ```

4. **CSS Rules in `frontend/app/PatientPortal.module.css`**:
   In `frontend/app/PatientPortal.module.css`, lines 30–57 originally declared 28 CSS rules under `.largeText`:
   ```css
   .largeText { font-size: 19px; line-height: 1.85; }
   .largeText h1 { font-size: clamp(32px, 4.5vw, 44px); }
   .largeText h2 { font-size: 27px; }
   .largeText h3 { font-size: 22px; }
   .largeText small { font-size: 15px; }
   .largeText button, .largeText .link, .largeText input, .largeText select { font-size: 18px; min-height: 52px; padding: 12px 20px; }
   .largeText .badge { font-size: 15px; padding: 6px 14px; }
   .largeText .table table { font-size: 17px; min-width: 480px; }
   .largeText .table th, .largeText .table td { padding: 16px 14px; }
   .largeText .table caption { font-size: 16px; padding: 12px 10px; }
   .largeText .task { padding: 22px 0; font-size: 18px; }
   .largeText .taskHeading strong { font-size: 21px; }
   .largeText .task p { font-size: 18px; line-height: 1.8; margin: 10px 0; }
   .largeText .task small { font-size: 15px; margin-top: 6px; }
   .largeText .card { padding: 28px; }
   .largeText .warning, .largeText .error, .largeText .note, .largeText .summaryGuide, .largeText .careStateGuide { font-size: 18px; line-height: 1.85; padding: 18px 22px; }
   .largeText .summaryGuide > strong, .largeText .careStateGuide > strong { font-size: 19px; margin-bottom: 12px; }
   .largeText .summaryGuideGrid b, .largeText .careStateGrid .badge { font-size: 16px; }
   .largeText .summaryGuideGrid p, .largeText .careStateGrid p { font-size: 16px; line-height: 1.75; }
   .largeText .guideGrid > div { padding: 18px; font-size: 17px; }
   .largeText .guideGrid strong { font-size: 19px; }
   .largeText details summary { font-size: 19px; padding: 8px 0; cursor: pointer; }
   .largeText .stat { padding: 22px; }
   .largeText .stat span { font-size: 16px; }
   .largeText .stat strong { font-size: 32px; }
   .largeText .fieldGrid dt { font-size: 15px; }
   .largeText .fieldGrid dd { font-size: 18px; }
   .largeText .narrative { font-size: 18px; line-height: 2; }
   ```
   All 28 `.largeText` rules have been removed in the current working copy of `frontend/app/PatientPortal.module.css`, eliminating CSS bloat and responsive layout breakage caused by oversized text modes.

---

### 1.2 Inspection of `frontend/app/patientView.ts`

Inspection of `frontend/app/patientView.ts` shows:
- Lines 3–11: Defines `PatientSection` union type (`'overview' | 'trends' | 'care' | 'chat' | 'reports' | 'profile'`) and the `patientSections` metadata array:
  ```ts
  export type PatientSection = 'overview' | 'trends' | 'care' | 'chat' | 'reports' | 'profile';
  export const patientSections: { key: PatientSection; title: string; description: string; icon: string }[] = [
    { key: 'overview', title: 'ภาพรวม', description: 'ค่าล่าสุดและสิ่งที่ควรติดตาม', icon: 'overview' },
    { key: 'trends', title: 'แนวโน้มย้อนหลัง', description: 'เปรียบเทียบข้อมูล 1 ชั่วโมงถึง 7 วัน', icon: 'evidence' },
    { key: 'care', title: 'แผนดูแลของฉัน', description: 'งานที่ทีมดูแลยืนยันและสถานะล่าสุด', icon: 'care' },
    { key: 'chat', title: 'แชททีมดูแล', description: 'แชทข้อความกับแพทย์และทีมดูแล (Messenger)', icon: 'chat' },
    { key: 'reports', title: 'สรุปประจำวัน', description: 'เลือกวัน ดูสรุป และดาวน์โหลด', icon: 'reports' },
    { key: 'profile', title: 'ข้อมูลของฉัน', description: 'แยกประวัติที่ยืนยันจากข้อมูลสาธิต', icon: 'patients' },
  ];
  ```
- Lines 12–20: Contains data formatting and validation helpers: `sourceLabel`, `careStateLabel`, `displayValue`, and `safeAnalysis`.
- **Finding**: There are zero references to text enlargement, `largeText`, font scaling, or toggle functions in `patientView.ts`.

---

### 1.3 Test Suite Impact in `frontend/tests/ui-contract.test.mjs`

Executing `PATH="/opt/homebrew/bin:$PATH" node --test frontend/tests/ui-contract.test.mjs` outputs:
```
✖ clinician dashboard and patient portal expose P2/P3 accessibility and triage controls (2.19325ms)
  AssertionError [ERR_ASSERTION]: The input did not match the regular expression /ก\+ ตัวอักษรใหญ่/.
      at TestContext.<anonymous> (file:///Users/thuwanon/ai-patient-monitor/frontend/tests/ui-contract.test.mjs:95:10)
      ...
    actual: '"use client";\n\nimport { useEffect, useState } from \'react\';\n...',
    expected: /ก\+ ตัวอักษรใหญ่/,
    operator: 'match'
```

In `frontend/tests/ui-contract.test.mjs`, lines 88–103 state:
```javascript
test('clinician dashboard and patient portal expose P2/P3 accessibility and triage controls', () => {
  const staffSource = readFileSync(new URL('../app/StaffDashboard.tsx', import.meta.url), 'utf8');
  assert.match(staffSource, /playCriticalChime/);
  assert.match(staffSource, /เสียงเตือนวิกฤต/);
  assert.match(staffSource, /กรองระดับความเร่งด่วนหน้าภาพรวม/);

  const patientSource = readFileSync(new URL('../app/PatientPortal.tsx', import.meta.url), 'utf8');
  assert.match(patientSource, /ก\+ ตัวอักษรใหญ่/);
  assert.match(patientSource, /คำอธิบายค่าสัญญาณชีพเบื้องต้น/);

  const careMessagesSource = readFileSync(new URL('../app/CareMessages.tsx', import.meta.url), 'utf8');
  assert.match(careMessagesSource, /ข้อความด่วนสำหรับผู้ป่วย/);

  const careChatSource = readFileSync(new URL('../app/CareChat.tsx', import.meta.url), 'utf8');
  assert.match(careChatSource, /ข้อความแชทด่วนสำหรับผู้ป่วย/);
});
```

Line 95 explicitly tests for the legacy toggle text `/ก\+ ตัวอักษรใหญ่/`. Because `PatientPortal.tsx` has correctly removed this toggle per Requirement R1, the test fails.  
Under Requirement R1 and the Acceptance Criteria:
> "The Patient Portal no longer renders the `ก+ ตัวอักษรใหญ่` text enlargement button or `.largeText` style toggle."

The test contract in `ui-contract.test.mjs` must be updated from:
```javascript
assert.match(patientSource, /ก\+ ตัวอักษรใหญ่/);
```
to:
```javascript
assert.doesNotMatch(patientSource, /ก\+ ตัวอักษรใหญ่/);
assert.doesNotMatch(patientSource, /largeText/);
```
while maintaining `assert.match(patientSource, /คำอธิบายค่าสัญญาณชีพเบื้องต้น/);`.

---

### 1.4 Visual Appearance and Default Typography in Patient Portal

Investigation of `PatientPortal.module.css` and related components (`PatientPortal.tsx`, `PatientSections.tsx`, `VitalCharts.tsx`) shows the default typography and layout without `.largeText`:

| Element | Default Size / Style in `.page` | Line Height | Touch Target / Spacing | Accessibility & Readability Assessment |
|---|---|---|---|---|
| **Page Base** (`.page`) | `16px` | `1.7` | `max-width: 1180px; padding: 32px 28px 70px;` | Baseline 16px is larger than typical 14px dashboards, highly legible for patients of all ages without artificial enlargement. |
| **Hero Title** (`h1`) | `clamp(28px, 4vw, 38px)` | `1.42` | `font-weight: 750; margin: 4px 0 6px;` | Strong visual hierarchy, scales dynamically across desktop, tablet, and mobile. |
| **Section Headings** (`h2`) | `23px` | `1.42` | `font-weight: 700; margin: 0 0 8px;` | Clearly delineates functional zones (e.g. "วันนี้มีอะไรให้ติดตาม", "แนวโน้มสัญญาณชีพย้อนหลัง"). |
| **Card Headings** (`h3`) | `18px` | `1.42` | `font-weight: 700; margin: 0 0 8px;` | Readable sub-section anchors. |
| **Buttons & Links** | `font-size: 16px; font-weight: 650;` | `1.5` | `min-height: 46px; padding: 10px 16px; border-radius: 10px;` | Exceeds WCAG 2.1 AAA minimum touch target of 44×44px; ample padding prevents mis-taps. |
| **Form Inputs & Selects** | `font-size: 16px;` | `1.5` | `min-height: 46px; padding: 10px; border-radius: 9px;` | iOS-compliant font size (>= 16px prevents automatic browser zooming when focusing inputs). |
| **Badges & Status Tags** | `font-size: 13px; font-weight: 700;` | `1.4` | `padding: 5px 11px; border-radius: 30px;` | High contrast (`#246146` on `#eef6ee`, `#b43d4a` on `#fff`), clear pill shape. |
| **Vitals Metrics** (`.stat strong`) | `font-size: 27px;` | `1.2` | `font-variant-numeric: tabular-nums;` | Monospaced numeric alignment prevents horizontal jitter during live streaming updates. |
| **Accessible Guides** (`.guideGrid`, `.summaryGuide`, `.careStateGuide`) | `13px - 15px; font-size` | `1.6 - 1.75` | `border-radius: 12px - 14px; padding: 14px - 18px;` | Card containers with distinct green accents (`#176e53`) providing plain-language explanations. |

**Responsive Breakpoint Behavior**:
- `@media (max-width: 850px)`: Converts 3-column `.guideGrid`, `.summaryGuideGrid`, and `.careStateGrid` into single-column layouts; collapses 6-item navigation to 3-column grid.
- `@media (max-width: 600px)`: Page padding adjusts to `22px 16px 40px`; navigation transforms into touch-friendly cards with stacked icon and label; cards padding becomes `18px`.

---

### 1.5 Visual Appearance and Clinical Review Workflow in Staff Dashboard

Investigation of `frontend/app/StaffDashboard.tsx`, `frontend/app/Ward.module.css`, and `frontend/app/AlertWorkflow.tsx` reveals:

1. **Global Typography System (`frontend/app/globals.css`)**:
   - Font stack: `-apple-system, BlinkMacSystemFont, "Noto Sans Thai", Thonburi, "Leelawadee UI", Tahoma, sans-serif`
   - Base text rendering: `font-kerning: normal; text-rendering: optimizeLegibility; -webkit-tap-highlight-color: transparent;`
   - Focus outline: `:focus-visible { outline: 3px solid #268765; outline-offset: 3px; }` ensuring full keyboard navigation compliance.

2. **Clinical Review Workflow Across Staff Dashboard Sections**:
   - **Triage & Priority Review (`active === 'triage'`)**:
     - Evaluates ward patients by clinical priority: `CRITICAL` (`#ad394b`), `ATTENTION` (`#936511`), `ROUTINE` (`#247354`).
     - Explicit clinical headline: `"ใครควรได้รับการตรวจสอบก่อน? รวมค่าสัญญาณชีพล่าสุดกับรายการแจ้งเตือนที่ยังไม่ปิด ไม่ใช่การวินิจฉัยของ AI"`
     - Each triage card displays: room number, patient ID, condition, mobility, priority reason, live vital numbers (HR, SpO2, RR), and open alert badge.
   - **Alert Lifecycle Management (`AlertWorkflow.tsx`)**:
     - Strict 4-stage clinical protocol:
       1. `NEW` (รอรับทราบ) — Unacknowledged alarm with audio/visual notification.
       2. `ACKNOWLEDGED` (รับทราบแล้ว) — Clinician confirms receipt of alarm.
       3. `ESCALATED` (ส่งต่อประเมิน) — Alarm escalated to physician/rapid response team with mandatory notes.
       4. `RESOLVED` (ปิดงานแล้ว) — Closed with mandatory minimum 5-character audit note (`"บันทึกสิ่งที่ตรวจพบและการดำเนินการ"`).
   - **Bedside Device & Turn Schedule (`BedsidePanel.tsx`, `PosturePanel.tsx`)**:
     - Visual turn reminder countdown (`.turnProgressBar`) with color-coded states: `normal` (green, >30m remaining), `warning` (amber, <=30m remaining), `due` (red border/background, turn overdue).
     - Quick clinical note chips (`.quickNoteChip`): 1-click documentation for `"พลิกตัวเรียบร้อย"`, `"ท่านอนหงาย"`, `"นอนตะแคงซ้าย"`, `"นอนตะแคงขวา"`.
     - Sensor quality metrics: battery percentage, sensor lead contact, pulse strength, signal-to-noise ratio.
   - **Shift Operations & Handoff (`OperationsPanel.tsx`)**:
     - Shift handoff reminder checklist (`Shift Handoff Reminder`) summarizing active critical alerts, unacknowledged care tasks, and unread patient communications.
   - **AI Model Transparency & Safety Guardrails (`EvidencePanel.tsx`, `ResearchPanel.tsx`)**:
     - Explicit grounding on PhysioNet BIDMC 1Hz benchmark with 30s forecast horizon and persistence baseline comparison.
     - Strict abstention indicator (`งดพยากรณ์` / `Abstain`) when input signal is stale, missing, or irregular.
     - Zero data leakage confirmation between training, validation, and test sets.

---

### 1.6 Current Verification State Across Codebase

Running the official verification commands yields:

1. **Backend Unit Tests**:
   `./.venv/bin/python -m unittest discover -s backend/tests -p "test_monitor_portals.py" -v`
   - **Result**: `Ran 39 tests in 3.211s. OK.` (100% passing).

2. **Frontend Linter**:
   `PATH="/opt/homebrew/bin:$PATH" npm run lint`
   - **Result**: `0 errors, 0 warnings.` (Passes cleanly).

3. **Frontend Non-Contract Unit Tests**:
   `PATH="/opt/homebrew/bin:$PATH" node --test frontend/tests/care.test.mjs frontend/tests/evidence.test.mjs frontend/tests/patient.test.mjs frontend/tests/request.test.mjs frontend/tests/vitalView.test.mjs`
   - **Result**: `18 tests passed, 0 failed.` (100% passing).

4. **Frontend TypeScript Check**:
   `PATH="/opt/homebrew/bin:$PATH" npx tsc --noEmit`
   - **Result**: 1 error in `app/StaffDashboard.tsx:10:26` (`AskAgent` import from R2 scope). Zero errors in `PatientPortal.tsx`, `patientView.ts`, or `PatientSections.tsx`.

5. **Frontend UI Contract Test**:
   `PATH="/opt/homebrew/bin:$PATH" node --test frontend/tests/ui-contract.test.mjs`
   - **Result**: 1 failure in `clinician dashboard and patient portal expose P2/P3 accessibility and triage controls` exclusively caused by line 95 expecting `/ก\+ ตัวอักษรใหญ่/`.

---

## 2. Logic Chain

1. **From Observation 1.1**: The patient text-enlargement toggle previously relied on `largeText` state stored in `localStorage` under key `'smart-ward-large-text'`, applied via a `.largeText` CSS class on `<main>`, and toggled via a hero button labeled `ก+ ตัวอักษรใหญ่`.
2. **From Observation 1.1 & 1.4**: In `PatientPortal.module.css`, the default base font size is already `16px` with a generous line height of `1.7`, headings up to `38px`, and button/input touch targets of `46px`. The `.largeText` rules increased font sizes to 19px–28px, causing visual distortion, element collisions, and horizontal overflow on smaller screens.
3. **From Observation 1.1 & 1.2**: Removal of the `ก+ ตัวอักษรใหญ่` toggle and `.largeText` mode from `PatientPortal.tsx` and `PatientPortal.module.css` eliminates UI fragmentation and simplifies the DOM hierarchy. No other component (such as `patientView.ts` or `PatientSections.tsx`) depends on `largeText`.
4. **From Observation 1.3**: The automated test suite in `frontend/tests/ui-contract.test.mjs` line 95 asserts `assert.match(patientSource, /ก\+ ตัวอักษรใหญ่/);`. Because the toggle was removed, this assertion fails.
5. **From Requirement R1 & Acceptance Criteria**: Acceptance criteria explicitly mandates that the Patient Portal no longer renders `ก+ ตัวอักษรใหญ่` or `.largeText`. Therefore, updating `ui-contract.test.mjs` to `assert.doesNotMatch(patientSource, /ก\+ ตัวอักษรใหญ่/);` and `assert.doesNotMatch(patientSource, /largeText/);` brings the test suite into exact alignment with Requirement R1.
6. **From Observation 1.4 & 1.5**: The visual appearance across both portals has strong typographic hierarchy, high-contrast accessible color tokens, WCAG-compliant touch targets (>= 44px), tabular numbers for live vitals, and structured clinical workflows (triage board, alert progression, turn reminder, AI abstention).

---

## 3. Caveats

- **Scope Boundaries**: This investigation focused exclusively on Requirement R1 (Patient Portal typography, removal of text enlargement toggle and `.largeText`, and clinical review workflow refinement). The TypeScript compiler error in `StaffDashboard.tsx:10` (`AskAgent`) belongs to Requirement R2 (surveyed by Explorer 2). Doctor–Patient chat navigation separation and Messenger UI styling belong to Requirements R3 and R4 (surveyed by Explorer 3).
- **Working Copy State**: The current working directory already contains unstaged edits for `PatientPortal.tsx` and `PatientPortal.module.css` removing `largeText`. These changes were verified and found to be complete and clean for R1.
- **Browser-Level Accessibility**: Removing the in-app `.largeText` toggle does not impair patient accessibility; modern mobile and desktop browsers natively support pinch-to-zoom and OS-level dynamic type scaling. The 16px base font size and flexible rem/clamp layouts adhere to modern web accessibility best practices without requiring proprietary in-app toggles.

---

## 4. Conclusion

Requirement R1 is clearly defined and nearly fully realized in the codebase. To complete Requirement R1:

1. **Confirm Removal in Source Files**:
   - `frontend/app/PatientPortal.tsx`: Confirm removal of `LARGE_TEXT_KEY`, `largeText` state, `toggleLargeText` function, `<main className={s.page}>` without `${s.largeText}`, and removal of the `ก+ ตัวอักษรใหญ่` button. (Already present in unstaged working copy).
   - `frontend/app/PatientPortal.module.css`: Confirm deletion of the 28 `.largeText` override rules. (Already present in unstaged working copy).
   - `frontend/app/patientView.ts`: Confirmed no changes needed for text enlargement; navigation and labels are clean.

2. **Update Test Contract in `frontend/tests/ui-contract.test.mjs`**:
   In `frontend/tests/ui-contract.test.mjs` lines 94–97:
   ```javascript
   // Before:
   const patientSource = readFileSync(new URL('../app/PatientPortal.tsx', import.meta.url), 'utf8');
   assert.match(patientSource, /ก\+ ตัวอักษรใหญ่/);
   assert.match(patientSource, /คำอธิบายค่าสัญญาณชีพเบื้องต้น/);

   // After:
   const patientSource = readFileSync(new URL('../app/PatientPortal.tsx', import.meta.url), 'utf8');
   assert.doesNotMatch(patientSource, /ก\+ ตัวอักษรใหญ่/);
   assert.doesNotMatch(patientSource, /largeText/);
   assert.match(patientSource, /คำอธิบายค่าสัญญาณชีพเบื้องต้น/);
   ```

3. **Visual Appearance and Clinical Workflow**:
   - The default typography across both portals is clean, high-contrast, and responsive.
   - The clinical review workflow in the Staff Dashboard (Triage board, Alert progression, Bedside turn management, Patient detail modal, and AI explainability) provides clear clinical context without visual clutter.

---

## 5. Verification Method

To independently verify Requirement R1:

1. **Verify Patient Portal Source Code**:
   ```bash
   grep -E "ก\+ ตัวอักษรใหญ่|largeText|LARGE_TEXT" /Users/thuwanon/ai-patient-monitor/frontend/app/PatientPortal.tsx
   ```
   *Expected result*: No matches found (exit code 1).

2. **Verify CSS Module Rules**:
   ```bash
   grep -E "\.largeText" /Users/thuwanon/ai-patient-monitor/frontend/app/PatientPortal.module.css
   ```
   *Expected result*: No matches found (exit code 1).

3. **Run Frontend Contract Test Suite**:
   ```bash
   PATH="/opt/homebrew/bin:$PATH" node --test frontend/tests/ui-contract.test.mjs
   ```
   *Expected result*: Exits with code 0 once line 95 is updated to `assert.doesNotMatch`.

4. **Run Full Frontend Unit Tests**:
   ```bash
   PATH="/opt/homebrew/bin:$PATH" node --test frontend/tests/care.test.mjs frontend/tests/evidence.test.mjs frontend/tests/patient.test.mjs frontend/tests/request.test.mjs frontend/tests/vitalView.test.mjs
   ```
   *Expected result*: All 18 tests pass.

5. **Run Frontend Linter**:
   ```bash
   PATH="/opt/homebrew/bin:$PATH" npm run lint
   ```
   *Expected result*: Exits with code 0 (no lint errors).

6. **Run Backend Test Suite**:
   ```bash
   ./.venv/bin/python -m unittest discover -s backend/tests -p "test_monitor_portals.py" -v
   ```
   *Expected result*: Ran 39 tests; all OK.

**Invalidation Conditions**:
- Any re-introduction of the `ก+ ตัวอักษรใหญ่` button or `.largeText` CSS rules in `PatientPortal.tsx` or `PatientPortal.module.css`.
- Any regression breaking the 18 frontend unit tests or 39 backend tests.
