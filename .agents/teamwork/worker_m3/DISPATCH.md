# Dispatch Assignment — Worker M3 (Requirements R3 & R4)

You are Worker M3 (teamwork_preview_worker).
Your Working Directory: /Users/thuwanon/ai-patient-monitor/.agents/teamwork/worker_m3
Authoritative Request: /Users/thuwanon/ai-patient-monitor/.agents/teamwork/ORIGINAL_REQUEST.md
Survey Report: /Users/thuwanon/ai-patient-monitor/.agents/teamwork/explorer_survey_3/handoff.md
Project Scope: /Users/thuwanon/ai-patient-monitor/PROJECT.md

## Exclusive File Ownership
You own:
- `frontend/app/StaffDashboard.tsx`
- `frontend/app/CareChat.tsx`
- `frontend/app/CareChat.module.css`
- `frontend/app/OperationsPanel.tsx` (if needed for chat callback)

## Task
Implement all changes for Milestone M3 (Requirements R3 & R4: Doctor-Patient Chat Navigation & Facebook Messenger UI):

1. **In `frontend/app/StaffDashboard.tsx`**:
   - Add `"chat"` to `Section` union type:
     `type Section = "overview" | "chat" | "triage" | "patients" | "alerts" | "ai" | "research" | "reports" | "notifications" | "evidence" | "care";`
   - Add `{ id: "chat", icon: "chat", label: "แชทแพทย์-ผู้ป่วย", detail: "แชทข้อความสองทางแบบเรียลไทม์ระหว่างแพทย์และผู้ป่วย" }` to `nav` array.
   - Add `{ label: 'แชทแพทย์-ผู้ป่วย', icon: 'chat', sections: ['chat'] }` to `navGroups` array.
   - Connect `OperationsPanel`'s `chat` prop: `chat={() => setActive('chat')}`.
   - In `active === "triage"`, REMOVE the `<details><summary>แชทระหว่างแพทย์และผู้ป่วย</summary><CareChat staff openPatient={openPatient} /></details>` block completely. Keep only `CareMessages` and triage board.
   - Add dedicated `else if (active === "chat") content = <CareChat staff openPatient={openPatient} />;`.

2. **In `frontend/app/CareChat.tsx` and `frontend/app/CareChat.module.css`**:
   - Modern Facebook Messenger design system:
     - Multi-contact sidebar (for staff):
       - User avatars with initials and deterministic color palette (`getInitials`, `getAvatarColor`).
       - Green active status badge (`#31a24c`).
       - Conversation filter tabs ("ทั้งหมด" / "ยังไม่อ่าน").
       - Snippet preview and unread counters.
     - Messenger room header:
       - Contact initials avatar with active status badge.
       - Display name and status indicator ("พร้อมติดต่อ / ใช้งานอยู่").
       - STRICTLY NO voice or video call buttons (no phone, no camera icon).
     - Message thread:
       - Right bubbles (`mine`): Messenger blue (`#0084ff`), white text, rounded corners (`border-radius: 18px 18px 4px 18px`), delivery/read receipts (`อ่านแล้ว ✓✓` / `ส่งแล้ว ✓`).
       - Left bubbles (`other`): Light gray (`#f0f2f5`), dark text (`#050505`), rounded corners (`border-radius: 18px 18px 18px 4px`), accompanied by sender initials avatar.
     - Quick replies (for patients):
       - Rounded pill chips (`border-radius: 20px`) with `aria-label="ข้อความแชทด่วนสำหรับผู้ป่วย"`.
     - Rounded pill composer:
       - Pill wrapper (`border-radius: 24px`, background `#f0f2f5`).
       - Auto-resizing textarea / input with Enter-to-send support (Shift+Enter for newline).
       - Circular blue Messenger send button with paper plane icon.
     - Zero incoming call notifications, ringtones, or call modals.

3. **Verification**:
   - Run `PATH="/opt/homebrew/bin:$PATH" npx tsc --noEmit` in `frontend` (0 errors).
   - Run `PATH="/opt/homebrew/bin:$PATH" npm run lint` in `frontend` (0 errors).
   - Run `PATH="/opt/homebrew/bin:$PATH" npm run build` and `npm run build:patient` in `frontend`.
   - Run `PATH="/opt/homebrew/bin:$PATH" node tests/care.test.mjs && node tests/evidence.test.mjs && node tests/patient.test.mjs && node tests/request.test.mjs && node tests/vitalView.test.mjs`.
   - Run `./.venv/bin/python -m unittest discover -s backend/tests -p "test_monitor_portals.py" -v`.

DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Output:
Write your handoff report to /Users/thuwanon/ai-patient-monitor/.agents/teamwork/worker_m3/handoff.md and notify the orchestrator.


## 2026-10-24T09:22:04Z
[Message] sender=2af93610-4a29-43c8-bcdc-29f45eb79fe3
You are Worker M3. Read /Users/thuwanon/ai-patient-monitor/.agents/teamwork/ORIGINAL_REQUEST.md, /Users/thuwanon/ai-patient-monitor/PROJECT.md, /Users/thuwanon/ai-patient-monitor/.agents/teamwork/explorer_survey_3/handoff.md, and /Users/thuwanon/ai-patient-monitor/.agents/teamwork/worker_m3/DISPATCH.md.
Your working directory is /Users/thuwanon/ai-patient-monitor/.agents/teamwork/worker_m3.

Implement Milestone M3 (Requirements R3 & R4):
1. In frontend/app/StaffDashboard.tsx:
   - Add 'chat' to Section union type, nav, and navGroups with label 'แชทแพทย์-ผู้ป่วย'.
   - Connect OperationsPanel chat callback.
   - Remove CareChat from triage view; render dedicated 'chat' section for CareChat.
2. In frontend/app/CareChat.tsx and frontend/app/CareChat.module.css:
   - Implement Facebook Messenger layout:
     - Multi-contact sidebar with initials avatars, green active status badges (#31a24c), and unread filter tabs.
     - Messenger profile header with initials avatar, active status, and zero voice/video buttons.
     - Left/right bubbles: right blue (#0084ff) with read receipts (อ่านแล้ว ✓✓ / ส่งแล้ว ✓); left gray (#f0f2f5) with sender avatar.
     - Quick replies with aria-label="ข้อความแชทด่วนสำหรับผู้ป่วย".
     - Rounded pill composer (border-radius: 24px, background #f0f2f5, circular blue send button).
     - Strict exclusion of voice/video call buttons and incoming call/ringing notifications.
3. Verification:
   - Run `PATH="/opt/homebrew/bin:$PATH" npx tsc --noEmit` and `npm run lint` in frontend.
   - Run `PATH="/opt/homebrew/bin:$PATH" npm run build` and `npm run build:patient`.
   - Run frontend unit tests and backend unittest discover.
