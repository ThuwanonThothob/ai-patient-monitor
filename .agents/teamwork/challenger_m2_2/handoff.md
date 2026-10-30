# Milestone M2 Adversarial Challenge Report — Requirement R2

**Verdict**: **APPROVE**  
**Challenger**: Challenger M2-2 (`teamwork_preview_challenger`)  
**Timestamp**: 2026-10-24T09:21:00Z  
**Overall Risk Assessment**: **LOW**

---

## 1. Observation

1. **Inline `AskAgent` and Assistant Sidebars in `StaffDashboard.tsx`**:
   - `grep -rn "AskAgent" frontend/app/StaffDashboard.tsx` returns 0 matches.
   - `grep -rn "AskAgent" frontend/app/` returns 0 matches across the entire frontend directory.
   - Line 10 of `StaffDashboard.tsx`: `import AgentAssistant from './AgentAssistant';` (clean default import; named `{ AskAgent }` import completely removed).
   - `grep -rn "assistantPanel" frontend/app/StaffDashboard.tsx` returns 0 matches.
   - `grep -rn "styles.split" frontend/app/StaffDashboard.tsx` returns 0 matches.
   - `grep -rn "styles.aiPanel" frontend/app/StaffDashboard.tsx` returns 0 matches.
   - Lines 385–430: Section views `overview`, `triage`, `patients`, `alerts`, `ai`, `research`, `evidence`, `care`, `notifications`, and `reports` are rendered directly without `.split` wrapping, allowing full-width presentation without reserving an empty 290px column.
   - Line 441: Single floating launcher rendered at root: `<AgentAssistant key={`${active}-${selected ?? ''}`} section={active} patientId={selected ?? undefined} staff />`.
   - Lines 487–501: `PatientModal` no longer renders `<AskAgent />` in filters or modal headers.

2. **State Cleanup & `loadSnapshot` in `StaffDashboard.tsx`**:
   - `grep -rn "loadingSummary" frontend/app/StaffDashboard.tsx` returns 0 matches.
   - `grep -rn "setSummary" frontend/app/StaffDashboard.tsx` returns 0 matches.
   - Lines 197–206: `loadSnapshot` is defined with revision guard `summaryRequest.current` to prevent race conditions:
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
   - Polling is maintained cleanly at line 262: `useEffect(() => { const timer = window.setInterval(() => { void loadSnapshot(); ... }, 15000); ... }, ...)`.

3. **Bottom-Right Launcher & Centered Modal Styling in `AgentAssistant.module.css`**:
   - `.launcher`:
     - Line 1: `position: fixed; z-index: 1100; bottom: max(20px, env(safe-area-inset-bottom)); right: 24px; display: inline-flex; align-items: center; justify-content: center; text-align: center;`
     - Line 33: `@media(max-width:600px) { .launcher { right: 14px; padding: 12px 16px; bottom: max(14px, env(safe-area-inset-bottom)); } ... }`
   - `.dialog`:
     - Line 5: `margin: auto; position: fixed; inset: 0; padding: 0; width: min(560px, calc(100vw - 28px)); max-height: 86dvh; overflow-y: auto; text-align: center;`
     - Line 6: `.dialog::backdrop { background: #0b252866; backdrop-filter: blur(5px); }`
   - Modal text and child element centering:
     - Header: `.header { align-items: center; justify-content: center; text-align: center; }`, `.headerText { text-align: center; }`
     - Body: `.body { text-align: center; }`
     - Context tag: `.context { display: inline-block; margin: 0 auto 8px; text-align: center; }`
     - Note: `.note { margin: 6px auto 16px; text-align: center; }`
     - Suggestions: `.suggestions { justify-content: center; }`, `.suggestions button { text-align: center; }`
     - Form: `.form { text-align: center; }`, `.form label { text-align: center; }`, `.form input, .form textarea { text-align: center; }`
     - Answer box: `.answer { text-align: center; }`, `.answer p { text-align: center; }`
     - Details collapsible: `.answer details { text-align: center; }`, `.answer details summary { text-align: center; }`
     - Details ordered list: `.answer details ol { display: inline-block; text-align: left; margin: 8px auto; padding-left: 20px; }` (centers block while preserving standard numerical list formatting).
     - Timestamp and error: `.answer small { text-align: center; }`, `.error { text-align: center; }`

4. **Component API and Behavioral Guardrails in `AgentAssistant.tsx`**:
   - Line 11: Single default export `export default function AgentAssistant({ patientId, section, staff = false }: { patientId?: string; section: string; staff?: boolean })`.
   - Line 9: Comprehensive `sections` dictionary mapping 13 section keys: `overview`, `patients`, `triage`, `chat`, `alerts`, `ai`, `research`, `reports`, `notifications`, `evidence`, `care`, `trends`, `profile`.
   - Lines 22–26: Input guardrails — empty/whitespace queries early return: `if (!question.trim() || busy) return;`.
   - In-flight request cancellation via `AbortController` at submit (`controller.current?.abort()`) and on unmount (`useEffect(() => () => controller.current?.abort(), [])`).
   - Line 48: Textarea bound by `maxLength={1000}`.
   - Line 47: Staff target patient input bound by `maxLength={20}` with `.toUpperCase()`.
   - Line 49: Send button disabled when empty or missing target: `disabled={busy || !question.trim() || (staff && !target.trim())}`.

5. **Empirical Adversarial Test Suite Execution**:
   - Executed newly authored empirical test suite `frontend/tests/m2-adversarial.mjs`:
     ```
     ✔ M2-ADVERSARIAL-1: StaffDashboard.tsx completely eliminates AskAgent and assistantPanel (1.07ms)
     ✔ M2-ADVERSARIAL-2: StaffDashboard.tsx has zero occurrences of styles.split or empty 290px column (0.69ms)
     ✔ M2-ADVERSARIAL-3: StaffDashboard.tsx cleanly manages loadSnapshot without summary leaks (0.06ms)
     ✔ M2-ADVERSARIAL-4: AgentAssistant.tsx has single default export and zero AskAgent exports (0.08ms)
     ✔ M2-ADVERSARIAL-5: AgentAssistant.tsx markup contracts (launcher, dialog, accessibility) (0.07ms)
     ✔ M2-ADVERSARIAL-6: AgentAssistant.tsx stress-tests input bounds, validation, and cancellation (0.05ms)
     ✔ M2-ADVERSARIAL-7: AgentAssistant.module.css enforces fixed bottom-right launcher and viewport-centered modal (0.32ms)
     ✔ M2-ADVERSARIAL-8: AgentAssistant.module.css enforces centered typography across all modal children (0.53ms)
     ✔ M2-ADVERSARIAL-9: Mobile responsive positioning rules for AgentAssistant (0.15ms)
     ✔ M2-ADVERSARIAL-10: Whole frontend codebase verification: zero stray AskAgent in any component (0.67ms)
     ✔ M2-ADVERSARIAL-11: Sections coverage: all sections in StaffDashboard and PatientPortal map to labels (0.17ms)
     ✔ M2-ADVERSARIAL-12: Runtime timestamp parsing and Bangkok locale simulation (38.39ms)
     ℹ tests 12 | pass 12 | fail 0
     ```

6. **Static Analysis & Build Verification**:
   - `npx tsc --noEmit` -> Exited with code 0 (TS2614 completely resolved).
   - `npm run lint` -> Exited with code 0 (0 ESLint errors/warnings).
   - `npm run build` (WARD_PORTAL=staff next build --webpack) -> Exited with code 0 (production build succeeded).
   - `npm run build:patient` (WARD_PORTAL=patient next build --webpack) -> Exited with code 0 (patient portal build succeeded).
   - Unit tests (`care.test.mjs`, `evidence.test.mjs`, `patient.test.mjs`, `request.test.mjs`, `vitalView.test.mjs`) -> 18/18 passed.
   - Python backend tests (`test_monitor_portals.py`) -> 39/39 passed.

---

## 2. Logic Chain

1. **Elimination of Inline AskAgent and Unused Sidebars**:
   - Requirement R2 dictates: *"Redesign the AI Agentic assistant interface so that only the floating launcher button in the bottom-right corner of the screen is present, removing inline AI Agentic buttons and sidebars from individual sections."*
   - Observation 1.1 proves that `AskAgent` has zero imports, definitions, or usages across `StaffDashboard.tsx`, `PatientPortal.tsx`, `VitalCharts.tsx`, and all other frontend files.
   - Observation 1.1 also confirms that `assistantPanel` and `styles.split` are entirely absent from `StaffDashboard.tsx`. No section reserves an empty 290px right column.

2. **Full-Width Section Layout and State Refactoring**:
   - In prior revisions, `styles.split` allocated `minmax(0, 1fr) 290px` for the side panel. Unwrapping `.split` across `overview`, `triage`, `patients`, `alerts`, and `reports` enables the clinical tables and telemetry widgets to expand to the full container width.
   - The state variables `summary` and `loadingSummary` were used only by the retired sidebar. Refactoring to `loadSnapshot` preserves telemetry fetching (`/api/dashboard/${active}`) for snapshot cards without retaining dead summary state (Observation 1.2).

3. **Centering and Floating Launcher Conformance**:
   - Requirement R2 mandates: *"When the user clicks the bottom-right button, the assistant modal must open centered on the screen with its text and controls centered."*
   - As verified in Observation 1.3, `.launcher` is fixed at `bottom: max(20px, env(safe-area-inset-bottom)); right: 24px;` with high z-index (1100).
   - The native `<dialog>` element utilizes standard CSS centering via `margin: auto; position: fixed; inset: 0;` which guarantees viewport centering in all browsers.
   - All text within `.dialog` is centered by default via `.dialog { text-align: center; }`, and reinforced on `.header`, `.body`, `.context`, `.note`, `.suggestions`, `.form`, `.answer`, `.answer details summary`, and `.answer details ol` (which uses `margin: 8px auto` to center the list block).

4. **Empirical Robustness and Zero Regressions**:
   - The 12 automated empirical adversarial tests in `m2-adversarial.mjs` verify AST structure, CSS declarations, accessibility attributes, input boundaries, and locale formatting.
   - Zero compilation errors (`tsc`), zero lint issues (`eslint`), and successful production compilation of both portal targets confirm the absence of regressions.

---

## 3. Caveats

1. **M4 UI Contract Alignment**:
   - `frontend/tests/ui-contract.test.mjs` line 95 asserts on `/ก\+ ตัวอักษรใหญ่/`, which failed because Milestone M1 intentionally removed the text-enlargement toggle from `PatientPortal.tsx`.
   - As defined in `PROJECT.md` Feature F16, `ui-contract.test.mjs` is scheduled for end-to-end alignment during Milestone M4. This failure is an expected intermediate artifact of earlier milestone work and does not invalidate Milestone M2.
2. **Ward.module.css `.split` Definition**:
   - `.split` and `.aiPanel` remain in `Ward.module.css` because they are utilized by `NotificationPanel.tsx` (for device push setup and privacy disclosures). Their retention in CSS is harmless and intentional; they are completely removed from `StaffDashboard.tsx`'s main clinical views.

---

## 4. Conclusion

**Verdict: APPROVE**

Milestone M2 strictly satisfies all requirements of Requirement R2:
- All inline `AskAgent` buttons and per-section `assistantPanel` sidebars have been removed.
- `StaffDashboard.tsx` sections no longer allocate a 290px split column, utilizing full workspace width.
- `AgentAssistant.tsx` is mounted as a single global floating launcher at the bottom-right.
- The assistant `<dialog>` opens centered on screen with centered typography and centered controls.
- All static type checks, linters, production builds, backend tests, and adversarial test checks pass without error.

---

## 5. Verification Method

To independently verify this evaluation, execute the following commands in `/Users/thuwanon/ai-patient-monitor/frontend`:

```bash
# 1. Run the M2 empirical adversarial test suite (12 tests)
PATH="/opt/homebrew/bin:$PATH" node tests/m2-adversarial.mjs

# 2. Run TypeScript type check
PATH="/opt/homebrew/bin:$PATH" npx tsc --noEmit

# 3. Run ESLint
PATH="/opt/homebrew/bin:$PATH" npm run lint

# 4. Verify staff and patient production builds
PATH="/opt/homebrew/bin:$PATH" npm run build
PATH="/opt/homebrew/bin:$PATH" npm run build:patient

# 5. Run frontend unit tests
PATH="/opt/homebrew/bin:$PATH" node tests/care.test.mjs && \
PATH="/opt/homebrew/bin:$PATH" node tests/evidence.test.mjs && \
PATH="/opt/homebrew/bin:$PATH" node tests/patient.test.mjs && \
PATH="/opt/homebrew/bin:$PATH" node tests/request.test.mjs && \
PATH="/opt/homebrew/bin:$PATH" node tests/vitalView.test.mjs

# 6. Run backend test suite (from repo root)
./.venv/bin/python -m unittest discover -s backend/tests -p "test_monitor_portals.py" -v
```
