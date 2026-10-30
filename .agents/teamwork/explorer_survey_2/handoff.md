# Investigation and Survey Report — Requirement R2: Single Bottom-Right AI Agentic Interface with Centered Text

## 1. Observation

### 1.1 Compilation Error and Current Git Status
Running `PATH="/opt/homebrew/bin:$PATH" npx tsc --noEmit` in `/Users/thuwanon/ai-patient-monitor/frontend` yields:
```
app/StaffDashboard.tsx:10:26 - error TS2614: Module '"./AgentAssistant"' has no exported member 'AskAgent'. Did you mean to use 'import AskAgent from "./AgentAssistant"' instead?

10 import AgentAssistant, { AskAgent } from './AgentAssistant';
                            ~~~~~~~~

Found 1 error in app/StaffDashboard.tsx:10
```
Running `git status` shows unstaged modifications in:
- `frontend/app/AgentAssistant.module.css`
- `frontend/app/AgentAssistant.tsx`
- `frontend/app/Icon.tsx`
- `frontend/app/OperationsPanel.tsx`
- `frontend/app/PatientPortal.module.css`
- `frontend/app/PatientPortal.tsx`
- `frontend/app/VitalCharts.tsx`
- `frontend/app/patientView.ts`

### 1.2 Inline `AskAgent` Buttons
Investigation of all source files shows `AskAgent` references remaining in:
1. **`frontend/app/StaffDashboard.tsx` Line 10**:
   ```typescript
   import AgentAssistant, { AskAgent } from './AgentAssistant';
   ```
2. **`frontend/app/StaffDashboard.tsx` Line 387**:
   ```tsx
   const assistantPanel = <aside className={styles.aiPanel}><AskAgent /><p className={styles.muted}>กดเพื่ออ่านข้อมูลผู้ป่วย แนวโน้ม และงานดูแล พร้อมตรวจสอบขั้นตอนที่ใช้</p><details><summary>สรุปภาพรวมหมวดนี้</summary><p className={styles.aiText}>{loadingSummary ? "กำลังเตรียมสรุป…" : summary}</p><button className={styles.secondary} disabled={loadingSummary} onClick={() => void loadSummary()}>สรุปใหม่</button></details><p className={styles.disclaimer}>ผู้ช่วยอ่านข้อมูล ไม่วินิจฉัยหรือสั่งการรักษา</p></aside>;
   ```
3. **`frontend/app/StaffDashboard.tsx` Line 495**:
   ```tsx
   <div className={styles.filters} role="group" aria-label="หมวดรายละเอียดผู้ป่วย">{[["summary", "ข้อมูลและผลโมเดล"], ["chat", "Gemini เพิ่มเติม"], ["timeline", "ประวัติและส่งต่อ"]].map(([value, label]) => <Choice key={value} label={label} active={tab === value} onClick={() => setTab(value)} />)}<AskAgent /></div>
   ```
4. **`frontend/app/VitalCharts.tsx` Line 34** (removed in unstaged diff):
   ```tsx
   - <AskAgent question="อธิบายกราฟแนวโน้มย้อนหลัง 24 ชั่วโมง และความครบถ้วนของข้อมูล" label="ถามเรื่องกราฟ" />
   ```
5. **`frontend/app/AgentAssistant.tsx`** (removed in unstaged diff):
   Previously exported `AskAgent` function which dispatched `'ward:ask-agent'` event to trigger the dialog.

### 1.3 Per-Section AI Agentic Sidebars
In `frontend/app/StaffDashboard.tsx`, `assistantPanel` is an `<aside className={styles.aiPanel}>` defined at line 387 and inserted into 5 section views:
- **`overview`** (lines 398–408):
  ```tsx
  <div className={styles.split}><div>
    ...
  </div>{assistantPanel}</div>
  ```
- **`triage`** (lines 410–416):
  ```tsx
  else if (active === "triage") content = <div className={styles.split}><div>
    ...
  </div>{assistantPanel}</div>;
  ```
- **`patients`** (lines 417–422):
  ```tsx
  else if (active === "patients") content = <div className={styles.split}><div>
    ...
  </div>{assistantPanel}</div>;
  ```
- **`alerts`** (lines 423–430):
  ```tsx
  else if (active === "alerts") content = <div className={styles.split}><div>
    ...
  </div>{assistantPanel}</div>;
  ```
- **`reports` / Handoff & Export** (line 436):
  ```tsx
  else content = <div className={styles.split}><div className={styles.panel}>
    ...
  </div>{assistantPanel}</div>;
  ```

In `frontend/app/Ward.module.css`, `.split` is defined as:
```css
.split { display: grid; grid-template-columns: minmax(0, 1fr) 290px; gap: 24px; align-items: start; }
```
Where the right column (`290px`) was specifically allocated for `{assistantPanel}`.
(Note: `NotificationPanel.tsx` line 140 also uses `.split` for push notifications setup/privacy info, but none of the 5 main StaffDashboard views need `.split` once `assistantPanel` is removed).

### 1.4 State Variables Tied to `assistantPanel`
In `frontend/app/StaffDashboard.tsx`:
- Line 115: `const [summary, setSummary] = useState("");`
- Line 116: `const [loadingSummary, setLoadingSummary] = useState(false);`
- Lines 199–209: `loadSummary` callback fetches `/api/dashboard/${active}` and sets `snapshot` and `summary`.
- Lines 264–265: Polling effects calling `loadSummary()`.
When `assistantPanel` is removed, `summary` and `loadingSummary` are completely unreferenced. `loadSummary` can be simplified to `loadSnapshot` to retain `snapshot` for `registeredCount`, `zoneCards`, and `SnapshotTable`.

### 1.5 Floating Bottom-Right Launcher
In `frontend/app/AgentAssistant.tsx`:
- Rendered in `StaffDashboard.tsx` line 447:
  ```tsx
  <AgentAssistant key={`${active}-${selected ?? ''}`} section={active} patientId={selected ?? undefined} staff />
  ```
- Rendered in `PatientPortal.tsx` line 42:
  ```tsx
  <AgentAssistant key={active} section={active} patientId={patient.patient_id} />
  ```
- In `frontend/app/AgentAssistant.module.css` (lines 1–4):
  ```css
  .launcher { position: fixed; z-index: 1100; bottom: max(20px, env(safe-area-inset-bottom)); right: 24px; display: inline-flex; align-items: center; justify-content: center; gap: 12px; padding: 14px 22px; border: 1px solid #ffffff55; border-radius: 999px; background: linear-gradient(135deg, #15594e, #0f3f38); box-shadow: 0 14px 36px #0f3d4340; color: white; font: inherit; cursor: pointer; text-align: center; }
  .launcher:hover { transform: translateY(-2px); box-shadow: 0 18px 42px #0f3d4355; }
  .launcher span { display: grid; text-align: center; font-weight: 700; line-height: 1.25; }
  .launcher small { font-size: 10.5px; font-weight: 500; color: #c6e5de; }
  ```
  On mobile (`@media (max-width: 600px)`):
  ```css
  .launcher { right: 14px; padding: 12px 16px; bottom: max(14px, env(safe-area-inset-bottom)); }
  ```

### 1.6 Modal Centering & Centered Text / Controls
In `frontend/app/AgentAssistant.module.css`:
- `.dialog`:
  ```css
  .dialog { margin: auto; position: fixed; inset: 0; padding: 0; width: min(560px, calc(100vw - 28px)); max-height: 86dvh; overflow-y: auto; border: 1px solid #d5e3df; border-radius: 26px; color: #173c36; box-shadow: 0 28px 100px #123c3945; background: #fff; text-align: center; }
  ```
  This applies `margin: auto; position: fixed; inset: 0;` ensuring vertical and horizontal centering.
- Header, body, form, input, buttons:
  - `.header`: `display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 10px; text-align: center;`
  - `.headerText`: `text-align: center;`
  - `.body`: `padding: 22px 26px 26px; text-align: center;`
  - `.context`: `display: inline-block; margin: 0 auto 8px; text-align: center;`
  - `.note`: `max-width: 440px; margin: 6px auto 16px; text-align: center;`
  - `.suggestions`: `display: flex; flex-wrap: wrap; justify-content: center; gap: 8px;`
  - `.suggestions button`: `text-align: center;`
  - `.form`: `display: grid; gap: 14px; text-align: center;`
  - `.form label`: `display: grid; gap: 7px; text-align: center;`
  - `.form input, .form textarea`: `text-align: center;`
  - `.send`: `display: flex; justify-content: center; align-items: center; text-align: center;`
  - `.answer`: `text-align: center;`
  - `.answer b`: `display: block; text-align: center;`
  - `.answer p`: `white-space: pre-wrap; text-align: center;`
  - `.error`: `text-align: center;`
- Observation on `.answer details` (line 27):
  ```css
  .answer details { border-top: 1px solid #d9e4de; padding-top: 12px; margin-top: 10px; text-align: left; }
  ```
  `.answer details` is currently set to `text-align: left;`, which causes the collapsible steps list to be left-aligned rather than centered. Changing this to `text-align: center;` with centered summary and centered/indented list items ensures complete compliance with the acceptance criteria.

### 1.7 Documentation References
Grep for `ถามเรื่องกราฟ` reveals:
- `docs/CONTEXT_ASSISTANT.md:3`: `เปิดจากไอคอนมุมล่างทุกหมวด หรือปุ่มถามเรื่องกราฟ/รายละเอียดผู้ป่วย`
- `docs/USER_MANUAL_TH.md:182`: `กดไอคอน **ถาม Agentic** มุมล่างของแต่ละหมวด หรือปุ่ม **ถามเรื่องกราฟ**`

---

## 2. Logic Chain

1. **Root cause of TS2614 compilation error**:
   - `AgentAssistant.tsx` removed `AskAgent` export as part of R2 redesign.
   - However, `StaffDashboard.tsx` still imports `AskAgent` on line 10 and renders it on lines 387 (`assistantPanel`) and 495 (`PatientModal`).
   - Removing `{ AskAgent }` import and usages from `StaffDashboard.tsx` directly resolves the compiler error TS2614.

2. **Removal of Per-Section Sidebars (`assistantPanel`)**:
   - Requirement R2 mandates removing all inline AI Agentic sidebars from individual sections.
   - `assistantPanel` in `StaffDashboard.tsx` is an `<aside className={styles.aiPanel}>` that displayed per-section AI summary and an inline `AskAgent` button.
   - It was placed in 5 views: `overview`, `triage`, `patients`, `alerts`, and `reports`.
   - Removing `{assistantPanel}` from these 5 views satisfies the requirement.
   - Because `{assistantPanel}` sat in a `grid-template-columns: minmax(0, 1fr) 290px` layout (`.split`), removing `{assistantPanel}` and the outer `.split` container allows each section to expand cleanly across the entire workspace, improving typography, whitespace, and clinical readability.

3. **State Cleanup**:
   - In `StaffDashboard.tsx`, `summary` and `loadingSummary` exist solely to feed `assistantPanel`'s `<details><summary>สรุปภาพรวมหมวดนี้</summary>`.
   - Once `assistantPanel` is removed, `summary` and `loadingSummary` are unused.
   - However, the API call to `/api/dashboard/${active}` also returns `data.snapshot`, which is actively consumed by `registeredCount`, `zoneCards`, and `SnapshotTable`.
   - Therefore, `loadSummary` should be retained and renamed to `loadSnapshot`, removing `setSummary` and `setLoadingSummary` while continuing to maintain `setSnapshot(data.snapshot)`.

4. **Floating Launcher & Modal Centering**:
   - Both `StaffDashboard.tsx` and `PatientPortal.tsx` render `<AgentAssistant ... />` at the root of their workspaces.
   - The launcher button in `AgentAssistant.module.css` is positioned `fixed` at `bottom: max(20px, env(safe-area-inset-bottom)); right: 24px; z-index: 1100;`.
   - The `<dialog>` has `margin: auto; position: fixed; inset: 0;` ensuring native browser top-layer viewport centering.
   - `.dialog` and its children (`.header`, `.body`, `.context`, `.note`, `.suggestions button`, `.form`, `.form input`, `.form textarea`, `.send`, `.answer`) specify `text-align: center;`.
   - To make centering 100% consistent across all states, `.answer details` should be updated from `text-align: left;` to `text-align: center;`, with summary centered and ordered list styled neatly.

5. **Test Strategy**:
   - Current `frontend/tests/ui-contract.test.mjs` checks accessibility and P2/P3 UI elements, but lacks automated contract assertions for R2.
   - A dedicated contract test in `ui-contract.test.mjs` should assert:
     - `assert.doesNotMatch(staffSource, /AskAgent/);`
     - `assert.doesNotMatch(chartsSource, /AskAgent/);`
     - `assert.doesNotMatch(staffSource, /assistantPanel/);`
     - `assert.match(assistantCss, /\.dialog\s*\{[^}]*margin:\s*auto;/);`
     - `assert.match(assistantCss, /\.dialog\s*\{[^}]*text-align:\s*center;/);`
     - `assert.match(assistantCss, /\.launcher\s*\{[^}]*position:\s*fixed;/);`
     - `assert.match(assistantCss, /\.launcher\s*\{[^}]*right:\s*24px;/);`

---

## 3. Caveats

1. **Active Unstaged Changes in Git**:
   - Certain R2 changes (in `VitalCharts.tsx`, `AgentAssistant.tsx`, and `AgentAssistant.module.css`) are already in the working directory as unstaged modifications. They must be preserved and committed together with the `StaffDashboard.tsx` changes.
2. **`ui-contract.test.mjs` Line 95 Failure**:
   - Currently, `npm test` fails at `ui-contract.test.mjs:95` (`assert.match(patientSource, /ก\+ ตัวอักษรใหญ่/);`) because Requirement R1 removes `ก+ ตัวอักษรใหญ่`. This is within Requirement R1's scope and should be coordinated with the R1 task.
3. **`Ward.module.css` `.split` and `.aiPanel` Reuse**:
   - `.split`, `.aiPanel`, and `.aiText` are also used by `NotificationPanel.tsx` (for the push notification setup panel and privacy notice). Do NOT delete `.split` or `.aiPanel` from `Ward.module.css`, as that would break `NotificationPanel.tsx`. Only remove the usage of `assistantPanel` and `.split` from `StaffDashboard.tsx`'s 5 dashboard views.

---

## 4. Conclusion & Proposed Implementation Plan

### 4.1 Changes Required in `frontend/app/StaffDashboard.tsx`
1. **Remove `AskAgent` import** on line 10:
   ```typescript
   // BEFORE:
   import AgentAssistant, { AskAgent } from './AgentAssistant';
   // AFTER:
   import AgentAssistant from './AgentAssistant';
   ```
2. **Remove unused summary state** on lines 115–116:
   ```typescript
   // REMOVE:
   const [summary, setSummary] = useState("");
   const [loadingSummary, setLoadingSummary] = useState(false);
   ```
3. **Refactor `loadSummary` to `loadSnapshot`** on lines 199–209:
   ```typescript
   const loadSnapshot = useCallback(async () => {
     const revision = ++summaryRequest.current;
     if (["research", "notifications", "evidence", "care"].includes(active)) return;
     try {
       const response = await fetch(url("/api/dashboard/" + active));
       if (!response.ok) throw new Error("snapshot unavailable");
       const data = await response.json() as { snapshot: Snapshot };
       if (revision === summaryRequest.current) { setSnapshot(data.snapshot); }
     } catch { /* retain current snapshot on transient error */ }
   }, [active]);
   ```
   Update `loadSummary` references in lines 264–265 to `loadSnapshot`.
4. **Remove `assistantPanel` declaration** on line 387:
   ```typescript
   // DELETE line 387:
   const assistantPanel = ...;
   ```
5. **Remove `{assistantPanel}` and `.split` from the 5 sections**:
   - **Overview** (lines 398–408): Remove `<div className={styles.split}>` and `{assistantPanel}</div>`.
   - **Triage** (lines 410–416): Remove `<div className={styles.split}>` and `{assistantPanel}</div>`.
   - **Patients** (lines 417–422): Remove `<div className={styles.split}>` and `{assistantPanel}</div>`.
   - **Alerts** (lines 423–430): Remove `<div className={styles.split}>` and `{assistantPanel}</div>`.
   - **Reports** (line 436): Change `else content = <div className={styles.split}><div className={styles.panel}>...</div>{assistantPanel}</div>;` to `else content = <div className={styles.panel}>...</div>;`.
6. **Remove `<AskAgent />` from `PatientModal`** on line 495:
   ```tsx
   // BEFORE:
   <div className={styles.filters} role="group" aria-label="หมวดรายละเอียดผู้ป่วย">{[["summary", "ข้อมูลและผลโมเดล"], ["chat", "Gemini เพิ่มเติม"], ["timeline", "ประวัติและส่งต่อ"]].map(([value, label]) => <Choice key={value} label={label} active={tab === value} onClick={() => setTab(value)} />)}<AskAgent /></div>

   // AFTER:
   <div className={styles.filters} role="group" aria-label="หมวดรายละเอียดผู้ป่วย">{[["summary", "ข้อมูลและผลโมเดล"], ["chat", "Gemini เพิ่มเติม"], ["timeline", "ประวัติและส่งต่อ"]].map(([value, label]) => <Choice key={value} label={label} active={tab === value} onClick={() => setTab(value)} />)}</div>
   ```

### 4.2 CSS Refinement in `frontend/app/AgentAssistant.module.css`
Update line 27 for `.answer details`:
```css
/* BEFORE: */
.answer details { border-top: 1px solid #d9e4de; padding-top: 12px; margin-top: 10px; text-align: left; }

/* AFTER: */
.answer details { border-top: 1px solid #d9e4de; padding-top: 12px; margin-top: 10px; text-align: center; }
.answer details summary { cursor: pointer; text-align: center; font-weight: 600; color: #176e53; }
.answer details ol { display: inline-block; text-align: left; margin: 8px auto; padding-left: 20px; }
```

### 4.3 Documentation Updates
- In `docs/CONTEXT_ASSISTANT.md:3`: Update text to note that the assistant is accessed exclusively via the single floating launcher in the bottom-right corner.
- In `docs/USER_MANUAL_TH.md:182`: Update text to describe the bottom-right floating launcher button.

### 4.4 Automated Contract Test in `frontend/tests/ui-contract.test.mjs`
Add a dedicated test verifying all R2 requirements:
```javascript
test('R2: AI Agentic assistant has single floating bottom-right launcher, centered modal, and no inline AskAgent or sidebars', () => {
  const staffSource = readFileSync(new URL('../app/StaffDashboard.tsx', import.meta.url), 'utf8');
  const chartsSource = readFileSync(new URL('../app/VitalCharts.tsx', import.meta.url), 'utf8');
  const patientSource = readFileSync(new URL('../app/PatientPortal.tsx', import.meta.url), 'utf8');
  const assistantSource = readFileSync(new URL('../app/AgentAssistant.tsx', import.meta.url), 'utf8');
  const assistantCss = readFileSync(new URL('../app/AgentAssistant.module.css', import.meta.url), 'utf8');

  // Verify complete removal of AskAgent
  assert.doesNotMatch(staffSource, /AskAgent/);
  assert.doesNotMatch(chartsSource, /AskAgent/);
  assert.doesNotMatch(patientSource, /AskAgent/);
  assert.doesNotMatch(assistantSource, /AskAgent/);

  // Verify removal of per-section assistantPanel from StaffDashboard
  assert.doesNotMatch(staffSource, /assistantPanel/);
  assert.doesNotMatch(staffSource, /สรุปภาพรวมหมวดนี้/);

  // Verify floating bottom-right launcher
  assert.match(assistantSource, /className=\{s\.launcher\}/);
  assert.match(assistantCss, /\.launcher\s*\{[^}]*position:\s*fixed;/);
  assert.match(assistantCss, /\.launcher\s*\{[^}]*right:\s*24px;/);

  // Verify centered modal dialog
  assert.match(assistantCss, /\.dialog\s*\{[^}]*margin:\s*auto;/);
  assert.match(assistantCss, /\.dialog\s*\{[^}]*text-align:\s*center;/);

  // Verify centered text and controls
  assert.match(assistantCss, /\.header\s*\{[^}]*text-align:\s*center;/);
  assert.match(assistantCss, /\.body\s*\{[^}]*text-align:\s*center;/);
  assert.match(assistantCss, /\.form\s*\{[^}]*text-align:\s*center;/);
});
```

---

## 5. Verification Method

1. **TypeScript Type Check**:
   ```bash
   PATH="/opt/homebrew/bin:$PATH" npx tsc --noEmit
   ```
   *Expected result*: Exits with code 0. TS2614 (`AskAgent` error) disappears completely.

2. **Linter Execution**:
   ```bash
   PATH="/opt/homebrew/bin:$PATH" npm run lint
   ```
   *Expected result*: Exits with code 0 without unused variable warnings (`summary`, `loadingSummary`, etc.).

3. **Frontend Automated Unit/Contract Tests**:
   ```bash
   PATH="/opt/homebrew/bin:$PATH" npm test
   ```
   *Expected result*: All contract assertions in `tests/ui-contract.test.mjs` pass.

4. **Visual & Source Inspection Checklist**:
   - Inspect `frontend/app/StaffDashboard.tsx`: No `AskAgent` or `assistantPanel`.
   - Inspect `frontend/app/VitalCharts.tsx`: No `AskAgent`.
   - Inspect `frontend/app/AgentAssistant.module.css`: `.dialog` has `margin: auto; text-align: center;`, `.launcher` has `position: fixed; right: 24px; bottom: max(20px, env(safe-area-inset-bottom));`.
   - Verify layout in Staff Portal: Views are full-width without the empty 290px right column.
   - Verify clicking the bottom-right `AgentAssistant` button displays the centered modal with centered text and controls.
