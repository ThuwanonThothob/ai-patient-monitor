# Original User Request

## Initial Request — 2026-10-24T08:31:30Z

Improve the Smart Ward AI Patient Monitor web application's visual appearance and clinical review workflow by removing the patient text-enlargement toggle, consolidating the AI Agentic assistant into a single bottom-right launcher button that opens a centered interface with centered text, and separating Doctor–Patient communication into a dedicated Facebook Messenger-style chat interface without incoming call notifications.

Working directory: /Users/thuwanon/ai-patient-monitor
Integrity mode: development

## Requirements

### R1. Website Appearance, Review Workflow & Removal of Text Enlargement
Remove the text enlargement (`ก+ ตัวอักษรใหญ่`) toggle and its associated large-text mode from the Patient Portal, and refine the visual appearance and review workflow across both the Staff and Patient portals so the default typography and layout are clean, legible, and easy to review.

### R2. Single Bottom-Right AI Agentic Interface with Centered Text
Redesign the AI Agentic assistant interface so that only the floating launcher button in the bottom-right corner of the screen is present, removing inline AI Agentic buttons and sidebars from individual sections. When the user clicks the bottom-right button, the assistant modal must open centered on the screen with its text and controls centered.

### R3. Separated Doctor–Patient Chat Navigation
Clarify and separate the real-time Doctor–Patient chat function from general triage and asynchronous care requests so that doctors, care teams, and patients have a dedicated, clearly labeled chat section for direct two-way text communication.

### R4. Facebook Messenger-Style Chat Without Incoming Call Notifications
Present the Doctor–Patient chat interface in a layout and visual style similar to Facebook Messenger (including conversation list with avatars/initials, active status badges, rounded left/right message bubbles, delivery/read indicators, and a rounded pill composer with quick replies), while strictly excluding voice/video call controls and incoming call or ringing notifications.

## Verification Resources

- Frontend test suite: `PATH="/opt/homebrew/bin:$PATH" npm test` in `/Users/thuwanon/ai-patient-monitor/frontend`
- Frontend TypeScript check: `PATH="/opt/homebrew/bin:$PATH" npx tsc --noEmit` in `/Users/thuwanon/ai-patient-monitor/frontend`
- Frontend linter: `PATH="/opt/homebrew/bin:$PATH" npm run lint` in `/Users/thuwanon/ai-patient-monitor/frontend`
- Backend unit tests: `./.venv/bin/python -m unittest discover -s backend/tests -p "test_monitor_portals.py" -v` in `/Users/thuwanon/ai-patient-monitor`

## Acceptance Criteria

### UI & Functional Criteria
- [ ] The Patient Portal no longer renders the `ก+ ตัวอักษรใหญ่` text enlargement button or `.largeText` style toggle.
- [ ] Inline `AskAgent` buttons and per-section AI Agentic sidebars are removed from individual dashboard sections and charts; only the floating `AgentAssistant` button in the bottom-right corner remains.
- [ ] Clicking the bottom-right `AgentAssistant` button opens a viewport-centered modal (`margin: auto`) with centered text (`text-align: center`).
- [ ] Doctor–Patient chat is separated into its own dedicated navigation section in the Staff Dashboard (`แชทแพทย์-ผู้ป่วย`) and clearly distinguished from general care requests in the Patient Portal.
- [ ] The chat interface renders in a Facebook Messenger-inspired layout (conversation sidebar with avatars and unread filters, Messenger-style header, left/right chat bubbles with read status, and rounded composer) with zero incoming call notifications or voice/video call buttons.

### Automated Verification
- [ ] All frontend unit and UI contract tests pass (`npm test` exits with code 0).
- [ ] TypeScript compilation (`npx tsc --noEmit`) and ESLint (`npm run lint`) pass with 0 errors.
