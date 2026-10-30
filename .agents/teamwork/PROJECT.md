# Project: Smart Ward AI Patient Monitor UI & Workflow Refinement

## Architecture
- **Framework**: Next.js (React 18, TypeScript) frontend in `/Users/thuwanon/ai-patient-monitor/frontend`, Python backend in `/Users/thuwanon/ai-patient-monitor/backend`.
- **Frontend Architecture**:
  - `PatientPortal.tsx`: Patient portal view, hero section, live vitals, daily tasks, guides, care requests, and direct chat.
  - `StaffDashboard.tsx`: Clinical ward dashboard with navigation sidebar, live telemetry, triage, patient modal, alerts workflow, and dedicated chat section.
  - `CareChat.tsx`: Two-way real-time messaging between clinicians and patients (Facebook Messenger design language).
  - `AgentAssistant.tsx`: Global AI assistant modal launched via floating bottom-right button with centered dialog and controls.
  - `CareMessages.tsx`: Asynchronous patient care requests and ticketing (distinct from real-time chat).
- **Backend Architecture**:
  - `backend/care_chat.py`: Endpoints for chat conversations, messages, and read status tracking.
  - `backend/app.py`: Core Flask/FastAPI REST endpoints serving telemetry and portals.

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| F1 | Removal of `ก+ ตัวอักษรใหญ่` Toggle | Remove text enlargement button from Patient Portal hero header | M1 | Survey R1 |
| F2 | Removal of `.largeText` CSS Mode | Delete 28 `.largeText` override CSS rules from PatientPortal.module.css | M1 | Survey R1 |
| F3 | Refined Patient & Staff Typography | Clean default typography (16px base, >=44px touch targets, tabular numbers) | M1 | Survey R1 |
| F4 | Bottom-Right Floating AI Launcher | Fixed bottom-right launcher button for AgentAssistant across portals | M2 | Survey R2 |
| F5 | Centered AI Assistant Modal | Native `<dialog>` centered with `margin: auto; inset: 0;` and centered text/controls | M2 | Survey R2 |
| F6 | Removal of Inline `AskAgent` Buttons | Remove all inline `AskAgent` buttons from StaffDashboard and charts | M2 | Survey R2 |
| F7 | Removal of Per-Section `assistantPanel` | Eliminate AI sidebars and outer `.split` grids from StaffDashboard sections | M2 | Survey R2 |
| F8 | Staff Dashboard State Cleanup | Remove unused `summary` and `loadingSummary` state; refactor to `loadSnapshot` | M2 | Survey R2 |
| F9 | Dedicated Staff Chat Navigation | Add `'chat'` (`แชทแพทย์-ผู้ป่วย`) as top-level section in StaffDashboard nav and navGroups | M3 | Survey R3 |
| F10 | Separate Real-Time Chat from Triage | Remove `CareChat` from triage; keep triage focused strictly on clinical priority | M3 | Survey R3 |
| F11 | Distinguish Patient Chat from Care Requests | Explicit separation between real-time `CareChat` and asynchronous `CareMessages` | M3 | Survey R3 |
| F12 | Facebook Messenger-Inspired Layout | Avatars with initials, green active badges (`#31a24c`), conversation filter tabs | M3 | Survey R4 |
| F13 | Messenger Message Bubbles & Delivery Status | Right blue `#0084ff` bubbles with read status (`✓✓`), left gray `#f0f2f5` bubbles | M3 | Survey R4 |
| F14 | Messenger Composer & Quick Replies | Rounded pill composer (`border-radius: 24px`), circular send button, pill chips | M3 | Survey R4 |
| F15 | Strict Exclusion of Call Controls & Ringing | Zero voice/video call buttons, zero incoming call modals, zero ringing alarms | M3 | Survey R4 |
| F16 | UI Contract Test Suite Alignment | Comprehensive automated test assertions covering R1, R2, R3, R4 in `ui-contract.test.mjs` | M4 | Survey Tests |
| F17 | End-to-End System Verification | 100% passing for npm test, tsc typecheck, npm run lint, and python backend tests | M4 | Survey Tests |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Patient Portal Typography & Text-Enlargement Removal (R1) | F1, F2, F3 | none | DONE |
| M2 | AI Assistant Launcher, Centered Modal & Inline Removal (R2) | F4, F5, F6, F7, F8 | M1 | DONE |
| M3 | Doctor-Patient Chat Navigation & Messenger UI (R3, R4) | F9, F10, F11, F12, F13, F14, F15 | M2 | IN_PROGRESS |
| M4 | E2E Contract Testing & Full Suite Acceptance | F16, F17 | M3 | PLANNED |

## Interface Contracts
### `frontend/app/StaffDashboard.tsx` ↔ `frontend/app/CareChat.tsx`
- Prop signature: `<CareChat staff openPatient={openPatient} />`
- Nav section: `type Section = ... | "chat" | ...`
- Callback from OperationsPanel: `chat={() => setActive('chat')}`

### `frontend/app/StaffDashboard.tsx` ↔ `frontend/app/AgentAssistant.tsx`
- Default export: `export default function AgentAssistant({ section, patientId, staff }: Props)`
- Inline `AskAgent` removed completely; no named export.

### `frontend/app/CareChat.tsx` Messenger Interface
- Props: `{ staff?: boolean; openPatient?: (id: string) => void }`
- Left/right bubbles with sender initials, read indicator (`อ่านแล้ว ✓✓`), quick replies with `aria-label="ข้อความแชทด่วนสำหรับผู้ป่วย"`.
- Strictly no audio/video call buttons or incoming call dialogs.

## Code Layout
- `frontend/app/PatientPortal.tsx`: Patient portal entry point
- `frontend/app/PatientPortal.module.css`: Patient portal styles
- `frontend/app/StaffDashboard.tsx`: Staff clinician dashboard
- `frontend/app/Ward.module.css`: Staff dashboard layout styles
- `frontend/app/CareChat.tsx`: Doctor-Patient Messenger component
- `frontend/app/CareChat.module.css`: Messenger layout and bubble styles
- `frontend/app/AgentAssistant.tsx`: Global floating AI assistant modal
- `frontend/app/AgentAssistant.module.css`: Floating launcher and centered dialog styles
- `frontend/app/VitalCharts.tsx`: Patient vital charts
- `frontend/tests/ui-contract.test.mjs`: Automated UI contract test suite
