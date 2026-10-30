# Dispatch Assignment — Worker M2 (Requirement R2)

You are Worker M2 (teamwork_preview_worker).
Your Working Directory: /Users/thuwanon/ai-patient-monitor/.agents/teamwork/worker_m2
Authoritative Request: /Users/thuwanon/ai-patient-monitor/.agents/teamwork/ORIGINAL_REQUEST.md
Survey Report: /Users/thuwanon/ai-patient-monitor/.agents/teamwork/explorer_survey_2/handoff.md
Project Scope: /Users/thuwanon/ai-patient-monitor/PROJECT.md

## Exclusive File Ownership
You own:
- `frontend/app/StaffDashboard.tsx`
- `frontend/app/AgentAssistant.module.css`
- `docs/CONTEXT_ASSISTANT.md`
- `docs/USER_MANUAL_TH.md`

## Task
Implement all changes for Milestone M2 (Requirement R2: AI Assistant Launcher, Centered Modal & Inline Removal):
1. In `frontend/app/StaffDashboard.tsx`:
   - Remove `AskAgent` import from `./AgentAssistant`.
   - Remove `summary` and `loadingSummary` state.
   - Refactor `loadSummary` to `loadSnapshot` (preserve `setSnapshot(data.snapshot)` from `/api/dashboard/${active}`).
   - Update `useEffect` polling references from `loadSummary` to `loadSnapshot`.
   - Remove `assistantPanel` declaration (`<aside className={styles.aiPanel}>...`).
   - In the 5 sections (`overview`, `triage`, `patients`, `alerts`, `reports`): remove the outer `<div className={styles.split}>` and `{assistantPanel}</div>`, allowing sections to render full-width.
   - In `PatientModal` (around line 495): remove `<AskAgent />` from the filters row.
2. In `frontend/app/AgentAssistant.module.css`:
   - Update `.answer details` to `text-align: center;`.
   - Center `.answer details summary` with `cursor: pointer; text-align: center; font-weight: 600; color: #176e53;`.
   - Style `.answer details ol` as `display: inline-block; text-align: left; margin: 8px auto; padding-left: 20px;`.
   - Ensure `.dialog` maintains `margin: auto; position: fixed; inset: 0; text-align: center;` and `.launcher` maintains `position: fixed; right: 24px; bottom: max(20px, env(safe-area-inset-bottom));`.
3. In documentation (`docs/CONTEXT_ASSISTANT.md` and `docs/USER_MANUAL_TH.md`):
   - Update references to describe the single floating launcher in the bottom-right corner rather than inline per-section buttons.
4. Verification:
   - Run `PATH="/opt/homebrew/bin:$PATH" npx tsc --noEmit` in `/Users/thuwanon/ai-patient-monitor/frontend` (must have 0 errors, TS2614 must be resolved).
   - Run `PATH="/opt/homebrew/bin:$PATH" npm run lint` in `/Users/thuwanon/ai-patient-monitor/frontend` (must have 0 errors).

DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Output:
Write your completion report to /Users/thuwanon/ai-patient-monitor/.agents/teamwork/worker_m2/handoff.md and notify the orchestrator.


## 2026-10-24T09:01:30Z
You are Worker M2. Read /Users/thuwanon/ai-patient-monitor/.agents/teamwork/ORIGINAL_REQUEST.md, /Users/thuwanon/ai-patient-monitor/PROJECT.md, /Users/thuwanon/ai-patient-monitor/.agents/teamwork/explorer_survey_2/handoff.md, and /Users/thuwanon/ai-patient-monitor/.agents/teamwork/worker_m2/DISPATCH.md.
Your working directory is /Users/thuwanon/ai-patient-monitor/.agents/teamwork/worker_m2.

DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Implement Milestone M2 (Requirement R2):
- Remove AskAgent import, assistantPanel, summary state from frontend/app/StaffDashboard.tsx, refactor to loadSnapshot, and remove .split wrappers around the 5 sections.
- Remove AskAgent from PatientModal in StaffDashboard.tsx.
- Center .answer details in frontend/app/AgentAssistant.module.css.
- Update docs/CONTEXT_ASSISTANT.md and docs/USER_MANUAL_TH.md.
- Run `PATH="/opt/homebrew/bin:$PATH" npx tsc --noEmit` and `PATH="/opt/homebrew/bin:$PATH" npm run lint` in frontend.
Write your handoff report to /Users/thuwanon/ai-patient-monitor/.agents/teamwork/worker_m2/handoff.md and send a completion message back to parent.
