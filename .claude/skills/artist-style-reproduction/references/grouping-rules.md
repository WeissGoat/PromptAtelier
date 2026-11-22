# Grouping Rules

## Unit of Analysis

Use submissions/posts as the primary unit. Count a multi-image post once when computing frequency and share. Image-level details are still useful for prompt recovery and examples, but should not dominate the classification.

## Metadata Recovery

Restore metadata before grouping:

1. PNG text `Comment`
2. Hidden watermark restored onto the original image when PNG text is missing
3. Celsys Studio Tool fallback through `image.get_ai_image_prompt(file_path, transfer_origin=True)`

For images that look parameterless because PNG `Comment` is absent or unusable, check hidden watermark. If hidden watermark metadata is available, call the project helper in the write-back mode, following `image.get_ai_image_prompt(file_path, transfer_origin=True)`, so the recovered NAI prompt/parameters are written back to the original file. Re-read the PNG text afterward and use the restored `Comment` as the source of truth. Record the recovery source as hidden-watermark restored to origin.

Do not read nearby `metadata.json`, ancestor `nai_metadata_cache/images.jsonl`, or other sidecar/cache metadata for classification. Classification must come directly from the image metadata or hidden-watermark data restored onto the image. If repeated image reads are slow, write a cache derived only from image metadata read directly by the skill.

Cache rules:

- Cache direct PNG metadata in a local file such as `.artist_metadata_cache/image_metadata.jsonl` under the analyzed corpus or output folder.
- Key each row by normalized absolute path, file byte size, and `mtime_ns`.
- Reuse cached rows only when path, size, and `mtime_ns` still match.
- Treat mismatches as stale and re-read the image.
- Store PNG `info`, raw `Comment`, parsed NAI JSON fields, parse errors, and recovery source.
- Do not import sidecar `metadata.json`, old `nai_metadata_cache`, or previous classifier outputs into this cache.
- If hidden watermark restore writes metadata back to the image, refresh that image's cache row after the write because `mtime_ns` should change.
- Report cache hits, misses, stale rows, unreadable images, and hidden-watermark restores in the analysis summary.

Record the source of recovered metadata. Separate these cases:

- `vibe` with missing reference image
- suspected vibe usage but no recoverable vibe parameters
- `inpaint`
- img2img or `add_original_image`
- unrecoverable metadata

Do not discard mixed posts as a whole. First isolate special images for reporting, then classify any images inside the post that still have normal recoverable text-to-image metadata.

Use this handling:

- If an image has explicit vibe parameters and the reference image is missing, put that image in a vibe-missing-reference category. Do not use it as a primary reproduction source.
- If every image in a post uses vibe but lacks embedded reference data, copy the whole post into a second-level `missing` folder under the inferred style family. Do not split this missing-reference status by residual `reference_strength_multiple`, prompt seasoning, model, or other missing-ref parameters.
- If a mixed post contains at least one recoverable embedded vibe image and other images in the same post are vibe-missing, keep the whole post under the same shared vibe group. Record the missing-embedded members as notes only; do not create a separate `vibe_missing_mixed` normal class.
- If an image visibly or structurally appears to have used vibe but recovered metadata lacks vibe parameters, put it in a suspected-vibe-without-params category. Treat exact reproduction as uncertain.
- If a whole post has no `PromptGenerateRequest`, first check for recoverable embedded vibe references before using a special-only archive category. Do not treat the visible style as prompt-only evidence.
- If every image in a post is img2img/inpaint/add_original and there is a recoverable embedded vibe group, classify the post under the inferred style family's `vibe_<hash...>` folder and record an img2img/inpaint reproducibility warning. Only copy the whole post into top-level `99_all_img2img_or_inpaint` when there is no recoverable embedded vibe group. Do not split this archive by model, prompt seasoning, or missing-reference details unless the user asks for forensic analysis.
- If a post contains at least one `PromptGenerateRequest`, classify the prompt images normally and keep inpaint/img2img/`add_original_image` as variants or flags, not as separate main groups.
- If a post contains both special images and normal text-to-image images, suffix or flag the post as mixed, but continue classifying the normal recoverable images in the regular style groups.
- If all images in a post are inpaint/img2img/add_original, do not assume the visible style is reproducible from text prompt alone. Report the post as special-only.
- If a post has vibe somewhere but a specific image has no vibe usage and normal recoverable metadata, classify that image normally while keeping a post-level flag such as `had_vibe` or `normal_from_had_vibe_post`. Do not treat an image as no-vibe if it still has vibe params such as `reference_strength_multiple` or `reference_information_extracted_multiple`.

### Salvaging Normal Images From Missing Groups

When a post or folder is under `missing`, `all_vibe_missing_embedded`, or another missing-vibe review state, still inspect each image directly. Copy recoverable no-vibe normal images out for reproduction analysis:

- Source must be the image's own PNG metadata or hidden watermark restored onto the original image, not `metadata.json` or prior CSV rows.
- The image must have `request_type = PromptGenerateRequest`.
- `reference_image_multiple` must be empty, absent, or parsed as zero embedded vibe references.
- Vibe params such as `reference_strength_multiple` and `reference_information_extracted_multiple` must also be empty or absent. If those params exist, the image belongs in missing-vibe handling, not `no_vibe`.
- Copy only the qualifying image files into `<style-family>/no_vibe/<post_name>/`. Preserve the post name. Do not copy sidecar `metadata.json` unless the user explicitly asks.
- Leave the original `missing` folder material in place so the missing-vibe status remains auditable.
- Write an audit file such as `normal_from_missing_audit.md` or `.jsonl` with source path, destination path, sampled image name, request type, vibe ref count, prompt snippet, model, sampler, steps, scale, and recovery source.
- Label these samples as `normal_from_missing` or `normal_from_had_vibe_post` in reports.
- Count the original submission once when computing post frequency. Salvaged copies are usable reproduction samples, not additional posts.

## Style Clustering

Use coarse main classes first, then record smaller prompt changes as variants. Main class priority:

1. style family: artist stack/features and weighted artist names
2. second-level status: `no_vibe`, embedded `vibe_<hash>`, `missing` for all-vibe-missing-reference posts
3. model family

This priority is strict. The top-level style folder answers "which style family is this?". The second-level folder answers "which vibe/missing-reference state is this?". Do not make `vibe`, `no_vibe`, or `missing` top-level folders. Keep whole-post img2img/inpaint/add_original in top-level `99_all_img2img_or_inpaint` only when no recoverable embedded vibe group exists.

Posts without embedded vibe are still normal groups when they have recoverable `PromptGenerateRequest`, but `no_vibe` belongs only in the second-level folder under the style family.

For whole-post missing-vibe-reference posts, infer the style family from recoverable image metadata when possible. If metadata does not expose enough style evidence, use a confirmed previous style classification for that same post only when the user has approved that classification source. If no style family can be justified, place the post under `unknown_style/missing` and report the uncertainty.

`98_unknown_style` / `unknown_style` is a temporary review bucket, not a style family. Before finalizing a grouping:

- Re-read the original image metadata directly; do not rely on stale CSV rows or sidecar metadata.
- Inspect the recovered prompt stack for decisive artist/style evidence such as artist names, official style tags, studio/style-family tags, or stable weighted artist stacks.
- If evidence exists, move the post under the inferred style family. For all-vibe-missing-reference posts, use that style's `missing` second-level folder.
- Write an audit note or TSV row with post name, sampled image, inferred style, matched keyword/phrase, and a short prompt snippet.
- Leave a post in `unknown_style/missing` only when direct image metadata and restored hidden watermark data still cannot justify a style family.
- Do not create a numbered top-level style folder for unknowns. Use `98_unknown_style/missing` only as the unresolved review bucket.

For group folder names, prefer a two-level layout:

```text
<NN>_<feature-description>/<status>
```

Use short sorted reference hashes for the second-level vibe status, following the spirit of `group_by_reference_image.py`'s `group_<hash...>` naming. Add the `vibe_<hash>` marker only for second-level groups with embedded vibe. Number style folders in timeline/stability order with `01`, `02`, `03`, ... and do not put model or vibe into the top-level folder title. Put full reference hashes, strengths, model, and parameter variants in the JSON/report.

Examples:

```text
01_official_typemoon_main/no_vibe
01_official_typemoon_main/vibe_06fdcab3_c45ccc0b
01_official_typemoon_main/missing
03_manga_monochrome_variant/missing
99_all_img2img_or_inpaint
unknown_style/missing
```

Only after those are stable, compare the rest of the whole prompt stack:

- linework words, rough/sketch/graphite terms
- shading/color language
- quality/type/default quality words
- lighting/mood/cinematic terms
- negative prompt family

Treat quality words, lighting words, and generic technique words such as `realistic`, `anime coloring`, `cel shading`, `soft shading`, or `cinematic lighting` as variants by default. They should not create a separate main class unless they consistently travel with a different artist stack or model family. If they only travel with a different vibe status, keep them under the same style family and separate by second-level status.

Do not create a main class such as `02_realistic_coloring_main` when the only evidence is generic coloring/rendering language layered over the same stronger artist stack. Merge that group into the parent style and report the coloring/rendering language as an internal variant.

Split a manga/monochrome/orion/rance/yabuki branch only when the evidence forms a stable post-level style stack in normal prompt images. Good split evidence includes repeated combinations such as `monochrome`, `line art`/`lineart`, `manga art`, `art yabuki`/`yabuki`, screentone, or a stable weighted manga artist stack across multiple posts. Do not split when `manga`, `orion`, or `rance` appears as one-off seasoning, action/content language, or mostly inside img2img/inpaint-only variants.

Avoid classifying by isolated token frequency. A rare token may be decisive when it participates in a stable combination.

Separate style tokens from content/action tokens before extracting a preset. Subject count, rating, body state, pose, expression, clothing, scene objects, and sexual/action terms should usually remain in the action prompt even if they appear often in one source subset. Do not put tokens such as `1girl`, `solo`, `nsfw`, `sweat`, or `{{{sweatdrop}}}` into the reusable style block unless the user explicitly wants a content-locked preset.

When using salvaged normal images from mixed vibe posts, keep their special context visible in reports with the label `normal_from_had_vibe_post`.

## Artifact Consistency

After moving or copying grouped posts, regenerate or verify the grouping artifacts from the current source of truth. Treat image metadata and real grouping folders as stronger evidence than old CSVs.

Run `scripts/validate_grouping.py <group_root>` after grouping changes. Treat hard errors as blockers for the grouping result. Keep the generated `validation_report.md` and `validation_report.json` in the grouping root or the chosen output directory. The validator checks `no_vibe` and `vibe_<hash>` at post-group granularity: `no_vibe/<post>` may contain img2img/inpaint variants if at least one normal no-vibe image is recoverable and no image uses vibe params or embedded refs; `vibe_<hash>/<post>` is valid when at least one image in the post exposes embedded refs matching the folder hash.

Required checks:

- Source post count equals the number of post-level classification rows.
- Grouped post-directory count equals the classification rows, with top-level archives counted once per post.
- `classification_manifest` totals match the actual folder layout.
- `classification_map` has one row per post, no blank destination paths, and every `new_dst_post_path` exists.
- `98_unknown_style` is empty or contains only unresolved posts with written reasons.
- `99_all_img2img_or_inpaint` remains top-level for whole-post img2img/inpaint/add_original posts without recoverable embedded vibe, and is not absorbed into a style class during repair.

When repairing drift:

- Do not invent `no_vibe`, style names, request types, or parameters to fill gaps.
- Re-read image metadata or restored hidden watermark data to rebuild missing rows.
- If a row and folder disagree, resolve the disagreement from direct image metadata and the current directory state, then rewrite map, manifest, and summary together.
- Preserve already-isolated top-level archives unless direct metadata proves they were misclassified.

## Parameter Clustering

Ignore resolution for grouping unless the user explicitly asks about canvas format. Parameters are a main-class split only by model family. Sampler, steps, scale, scheduler, numeric strengths, and feature switches are variants unless the whole post has no normal `PromptGenerateRequest`, in which case it is a special-only archive post.

Record these fields as variants for reporting:

- `request_type`
- `sampler`
- `steps`
- `scale`
- `cfg_rescale`
- `uncond_scale`
- `dynamic_thresholding`
- `noise_schedule`
- `sm`
- `sm_dyn`
- `skip_cfg_above_sigma`
- `skip_cfg_below_sigma`
- `legacy_v3_extend`
- `add_original_image`

Seed is useful for compare reproducibility, but not a style class criterion.

Use this interpretation:

- Main parameter class: model family only.
- Parameter variant: sampler algorithm, scheduler/noise schedule, `sm`/`sm_dyn`, dynamic thresholding, legacy switches, `steps`, `scale`, `cfg_rescale`, `skip_cfg_above_sigma`, and similar numeric strengths.
- Post-level special-only archive: inpaint/img2img/add_original when every image in the post lacks `PromptGenerateRequest`; keep it as one archive group by default.
- Non-structural: seed and resolution.

## Version Priority

Recommend reproduction priority by combining:

- post share
- date range and recency
- post frequency over time
- parameter stability
- prompt stability
- recoverability without missing vibe references
- whether the visible image depends on inpaint/add_original
- how many recoverable normal images remain after special-case filtering

Prefer the newest stable version inside the dominant class. If a late variant is newer but rare, report it as an external variant rather than replacing the main target.

## Report Shape

For each style version, report:

- class name
- post count and share
- date range
- approximate posts per 30 days
- main prompt traits
- main parameter family
- internal variants
- reproduction priority and caveats
