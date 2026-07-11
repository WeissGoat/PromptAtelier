# Task 3 Report: Custom Studio Temporary Node Integration

## Status

Completed and committed.

## Files

- `web/src/pages/CustomStudio.tsx`
- `web/src/pages/CustomStudio.test.tsx`
- `src/tags_machine_core/web/routes/nodes.py`
- `tests/test_web_nodes.py`
- `web/src/components/NodeEditorDrawer.tsx` (minimal preview API envelope compatibility update)

## Commit

- `3d6dab2 feat: use temporary nodes in custom generation`

## Test Evidence

```powershell
uv run python -m unittest tests.test_web_nodes tests.test_web_compose -v
# PASS: 7 tests

cd web
npm run test -- src/pages/CustomStudio.test.tsx src/nodes/temporaryNodes.test.ts src/components/NodeEditorDrawer.test.tsx
# PASS: 3 test files, 18 tests

npm run build
# PASS: TypeScript and Vite production build
```

Additional renderer-context check passed with an inline modified Artist and no `render.artist` source ref:

```text
1girl, draft_artist
```

## Self-check

- Preview and Generate use the same revision snapshot; a slot or render parameter update makes the prior preview stale, so Generate re-runs `/compose-preview` before posting `/generate`.
- `useTemporaryNodes`, `NodeSlot`, and `NodeEditorDrawer` now form the Custom Studio node flow. Modified and blank-origin nodes serialize inline; Preview and Generate never call `/nodes/save`.
- Character or Action is required. Temporary or modified slots require a non-empty positive prompt, with the failing slot identified in a visible Chinese alert. Original nodes remain exempt from this client-side prompt check for legacy normalization.
- Modified or temporary Artists are sent inline and do not retain a competing `render.artist` source ref, so the copied renderer context uses the draft. Original Artists continue to use their source ref.
- `/nodes/preview` now requires `{ "node": {...} }`, normalizes valid nodes, and maps validation failures to `invalid_node`. `/nodes/save` uses the same validation error code.
- `git diff --check` passed before staging. Task-external working tree changes were retained.

## Concerns

- The working tree remains intentionally dirty with concurrent changes outside this task; they were not reverted.
- The report is written after the implementation commit and is not included in it, consistent with the preceding task reports.

## Preview Race Fix

- Commit: `194287c fix: ignore stale compose previews`
- `CustomStudio` now assigns every compose preview a monotonically increasing request id plus a JSON input signature. Only the latest request with the current signature can write preview data, preview revision, status, or request errors.
- A signature change invalidates an active preview. A stale manual preview shows `Preview stale`; a stale automatic preview aborts before `/generate` and shows `输入已变化，请重新生成。`.
- Added focused coverage for one render-parameter revision (`Negative`), delayed stale Preview response handling, and stale automatic preview generation suppression.

### Preview Race Verification

```powershell
uv run python -m unittest tests.test_web_nodes tests.test_web_compose -v
# PASS: 7 tests

cd web
npm run test -- src/pages/CustomStudio.test.tsx src/nodes/temporaryNodes.test.ts src/components/NodeEditorDrawer.test.tsx
# PASS: 3 test files, 21 tests

npm run build
# PASS: TypeScript and Vite production build
```

## Task 3 Final Test Reinforcement

- Added delayed reject coverage for manual Preview. After input changes invalidate the request, the old rejection cannot replace `Preview stale`, create an old-error alert, or leave Preview/Generate disabled.
- Added delayed reject coverage for automatic Preview started by Generate. After input changes, the state remains `Generate blocked`, the current-input alert remains intact, and `/generate` is not called.
- Added parameterized Generate coverage for `width`, `height`, and `nt`; each change causes a second `/compose-preview` with the changed value before `/generate`.

### Final Verification

```powershell
cd web
npm run test -- src/pages/CustomStudio.test.tsx
# PASS: 1 test file, 15 tests

npm run build
# PASS: TypeScript and Vite production build
```
