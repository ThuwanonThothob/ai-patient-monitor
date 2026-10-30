# Dispatch Assignment — Test Writer M4 (E2E Contract Testing & Acceptance)

You are Test Writer M4 (`teamwork_preview_test_writer`).
Your Working Directory: /Users/thuwanon/ai-patient-monitor/.agents/teamwork/test_writer_m4
Authoritative Request: /Users/thuwanon/ai-patient-monitor/.agents/teamwork/ORIGINAL_REQUEST.md
Project Scope: /Users/thuwanon/ai-patient-monitor/PROJECT.md

## Exclusive File Ownership
You own:
- `frontend/tests/ui-contract.test.mjs`

## Task
Update `frontend/tests/ui-contract.test.mjs` so that the entire automated test suite reflects the updated UI contracts for Requirements R1, R2, R3, and R4:

1. **R1: Removal of Text Enlargement & Typography**:
   - Assert `assert.doesNotMatch(patientSource, /ก\+ ตัวอักษรใหญ่/);`
   - Assert `assert.doesNotMatch(patientSource, /largeText/);`
   - Maintain `assert.match(patientSource, /คำอธิบายค่าสัญญาณชีพเบื้องต้น/);`

2. **R2: Single Bottom-Right AI Assistant Launcher & Centered Modal**:
   - Assert `assert.doesNotMatch(staffSource, /AskAgent/);`
   - Assert `assert.doesNotMatch(staffSource, /assistantPanel/);`
   - Assert `assert.match(assistantCss, /\.launcher\s*\{[^}]*position:\s*fixed;/);`
   - Assert `assert.match(assistantCss, /\.launcher\s*\{[^}]*right:\s*24px;/);`
   - Assert `assert.match(assistantCss, /\.dialog\s*\{[^}]*margin:\s*auto;/);`
   - Assert `assert.match(assistantCss, /\.dialog\s*\{[^}]*text-align:\s*center;/);`

3. **R3: Dedicated Doctor-Patient Chat Navigation & Triage Separation**:
   - Assert `assert.match(staffSource, /id:\s*["']chat["']/);`
   - Assert `assert.match(staffSource, /แชทแพทย์-ผู้ป่วย/);`
   - Assert `CareChat` is NOT rendered inside `active === "triage"`.
   - Assert `OperationsPanel` in `StaffDashboard.tsx` wires `chat={() => setActive('chat')}`.
   - Assert `PatientPortal.tsx` separates `CareChat` (`active === 'chat'`) from `CareMessages` (`active === 'care'`).

4. **R4: Facebook Messenger Layout & Strict Call Prohibition**:
   - Assert presence of Messenger elements in `CareChat.tsx` and `CareChat.module.css`:
     - `.activeBadge` or active indicator `#31a24c`.
     - `.bubbleMine` with delivery receipts `อ่านแล้ว` / `ส่งแล้ว`.
     - `.bubbleOther`.
     - `.composerPill` or rounded composer.
     - `.quickPill` and `aria-label="ข้อความแชทด่วนสำหรับผู้ป่วย"`.
   - Assert strict absence of call controls:
     - `assert.doesNotMatch(careChatSource, /video|call|เสียงเรียกเข้า|โทร|วิดีโอ/i);`

5. **Verification**:
   - Run `PATH="/opt/homebrew/bin:$PATH" npm test` in `frontend` (must pass 100% with exit code 0).
   - Run `PATH="/opt/homebrew/bin:$PATH" npx tsc --noEmit` in `frontend` (0 errors).
   - Run `PATH="/opt/homebrew/bin:$PATH" npm run lint` in `frontend` (0 errors).
   - Run `./.venv/bin/python -m unittest discover -s backend/tests -p "test_monitor_portals.py" -v` in project root (39/39 pass).

DO NOT CHEAT. All test implementations must be genuine. DO NOT skip or mock tests.

Output:
Write your handoff report to /Users/thuwanon/ai-patient-monitor/.agents/teamwork/test_writer_m4/handoff.md and notify the orchestrator.


## 2026-10-24T09:51:48Z
You are Test Writer M4. Read /Users/thuwanon/ai-patient-monitor/.agents/teamwork/ORIGINAL_REQUEST.md, /Users/thuwanon/ai-patient-monitor/PROJECT.md, and /Users/thuwanon/ai-patient-monitor/.agents/teamwork/test_writer_m4/DISPATCH.md.
Your working directory is /Users/thuwanon/ai-patient-monitor/.agents/teamwork/test_writer_m4.

DO NOT CHEAT. All test implementations must be genuine.

Implement Milestone M4:
- Update frontend/tests/ui-contract.test.mjs to assert the updated contracts for R1 (absence of ก+ ตัวอักษรใหญ่ and largeText), R2 (bottom-right launcher and centered modal), R3 (chat navigation and triage separation), and R4 (Facebook Messenger layout and strict call control prohibition).
- Execute `PATH="/opt/homebrew/bin:$PATH" npm test` in frontend.
- Execute `PATH="/opt/homebrew/bin:$PATH" npx tsc --noEmit` and `npm run lint` in frontend.
- Execute `./.venv/bin/python -m unittest discover -s backend/tests -p "test_monitor_portals.py" -v` in project root.
Write your report to /Users/thuwanon/ai-patient-monitor/.agents/teamwork/test_writer_m4/handoff.md and send a completion message back to parent.
