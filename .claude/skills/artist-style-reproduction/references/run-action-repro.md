# Run Action Reproduction

## Default Path

Use `prompt_preset_service.py -> run_action` as the default reproduction path. Do not disable preset characters unless the user explicitly requests it. Preset behavior is part of the target workflow.

Use the current `gen_json` parameter format for all reproduction runs and compare tests. Do not use the legacy `gen_param` workflow or files when preparing parameters, invoking `run_action`, or exporting comparison artifacts.

## Prompt Composition

Use the current project rule unless the user says otherwise:

```text
artist tags line 1 + preset character + artist tags line 2 + action prompt + artist tags line 3
```

This rule exists because source images often place action/content between the main style block and trailing quality/output tags. Keep `tags.txt` structured so line 1 is the pre-character prefix, line 2 is the main style block, and line 3 is the post-action tail such as `no text, best quality, very aesthetic, absurdres`.

Do not promote content/action tokens into the reusable style block just because they are frequent in a source group. Keep subject count, scene rating, body state, expression, pose, and effect tokens in the action prompt unless they are demonstrably part of the artist style across many unrelated actions. Examples that usually belong to action/content rather than style: `1girl`, `solo`, `nsfw`, `sweat`, `{{{sweatdrop}}}`, sex acts, clothing, pose, camera framing, and character-specific items.

## Source Selection

Choose a source image from the target style class that is:

- metadata-recoverable
- not missing a required vibe reference
- not suspected vibe-without-params when exact reproduction is expected
- not primarily inpaint/img2img/add_original
- representative of the latest stable parameter family
- visually typical of the target style class

Extract the action prompt from the selected source and reuse it in generation. Do not substitute a generic action when the user expects a source-matched compare.

Images salvaged from mixed special-case posts may be used only when the specific image has normal recoverable text-to-image metadata. Keep the post-level special flag in the report so the user understands the source context.

## Parameter Matching

Match source parameters first, ignoring width/height for class analysis. Preserve source width/height only in the compare record or an explicit runtime override when the goal is exact source-vs-generated diffing.

When translating recovered source metadata into runnable generation settings, write and pass `gen_json`. Treat old `gen_param` artifacts as stale reference material only; do not run from them.

For ordinary artist loading, `formula.py` removes `width` and `height` after merging the artist's legacy and canonical parameter blocks. This keeps source canvas dimensions from becoming hidden style parameters and lets Blackboard use its normal random canvas policy. Do not compensate by adding fixed dimensions back into `tags.txt`, `gen_json`, or a new stable preset.

When the user asks for a new stable version of an existing preset, copy the preset to a sibling directory, preserve the original, and record the derivation in `notes.md`. A suffix such as `_random_resolution` describes this loading behavior; it does not describe a different visual style.

Important fields:

- sampler
- steps
- scale
- cfg_rescale
- noise schedule
- sm and sm_dyn
- uc
- request type
- seed for reproducible test runs
- width/height only when explicitly supplied as a runtime compare override

## Iteration

After each generation:

1. Create a compare package.
2. Inspect prompt diff.
3. Inspect parameter diff.
4. Compare visible style.
5. Adjust `tags.txt` only when the issue is style language.
6. Adjust generation params only when the issue is parameter mismatch.

If `PARAM_DIFF - none` but the image is visibly off, focus on style tags, preset interaction, and source-specific action/content leakage.

## Default Testing Requirement

When the user asks for reproduction, do not stop after `run_action` succeeds. Treat the compare package as part of the reproduction deliverable:

1. run generation
2. build the compare folder automatically
3. inspect prompt diff and parameter diff
4. report the result or continue iterating

Skip the compare package only when the user explicitly says this run does not need testing or compare output.
