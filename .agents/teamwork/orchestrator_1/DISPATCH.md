## 2026-10-24T08:32:27Z
You are the Project Orchestrator for this task.

Working Directory: /Users/thuwanon/ai-patient-monitor/.agents/teamwork/orchestrator_1
Project Root: /Users/thuwanon/ai-patient-monitor
Authoritative Request: /Users/thuwanon/ai-patient-monitor/.agents/teamwork/ORIGINAL_REQUEST.md

Task Summary:
Improve the Smart Ward AI Patient Monitor web application's visual appearance and clinical review workflow by:
1. R1: Removing the patient text-enlargement toggle (`ก+ ตัวอักษรใหญ่`) and associated `.largeText` style mode from the Patient Portal, and refining visual appearance/review workflow across Staff and Patient portals so default typography and layout are clean, legible, and easy to review.
2. R2: Redesigning the AI Agentic assistant interface into a single floating launcher button in the bottom-right corner of the screen, removing inline AI Agentic buttons and sidebars from individual sections. When clicked, the modal must open centered on the screen (`margin: auto`) with its text and controls centered (`text-align: center`).
3. R3: Clarifying and separating real-time Doctor-Patient chat navigation in the Staff Dashboard (`แชทแพทย์-ผู้ป่วย`) and clearly distinguishing it from general triage and asynchronous care requests in the Patient Portal.
4. R4: Presenting the Doctor-Patient chat interface in a Facebook Messenger-inspired layout (conversation sidebar with avatars/initials, active status badges, rounded left/right bubbles, delivery/read indicators, rounded pill composer with quick replies) while strictly excluding voice/video call controls and incoming call/ringing notifications.

Verification resources:
- Frontend test suite: `PATH="/opt/homebrew/bin:$PATH" npm test` in `/Users/thuwanon/ai-patient-monitor/frontend`
- Frontend TypeScript check: `PATH="/opt/homebrew/bin:$PATH" npx tsc --noEmit` in `/Users/thuwanon/ai-patient-monitor/frontend`
- Frontend linter: `PATH="/opt/homebrew/bin:$PATH" npm run lint` in `/Users/thuwanon/ai-patient-monitor/frontend`
- Backend unit tests: `./.venv/bin/python -m unittest discover -s backend/tests -p "test_monitor_portals.py" -v` in `/Users/thuwanon/ai-patient-monitor`

Maintain your progress.md and BRIEFING.md in your working directory. When complete and all verifications pass, send a message back claiming project completion.
