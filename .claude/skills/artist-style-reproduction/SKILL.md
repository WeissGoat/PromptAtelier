---
name: artist-style-reproduction
description: Use when a user provides an artist image corpus and asks to analyze style versions, classify vibe/style groups, recover NovelAI metadata, extract a style preset, reproduce with run_action, or build compare packages.
---

# Artist Style Reproduction

## Purpose

Use this skill when a user brings in an artist corpus under `artist_parse/YYYYMMDD/author_id` and wants to analyze the artist's style evolution, classify style variants, extract a reusable style preset, or iterate toward a close reproduction with `run_action`.

## Workflow

Follow the user's requested scope. If the user asks only for analysis, stop after the analysis report and do not create style presets or run reproduction. Start extraction and `run_action` reproduction only when the user explicitly asks to process, extract, reproduce, test, or compare a selected style.

1. Prepare the workspace.
   - Standard layout is `artist_parse/YYYYMMDD/author_id/origin/<post_directory>/`.
   - If the source corpus already lives in a large external image library and copying it into `artist_parse` would waste disk, use Windows junctions when the user allows source writes. Keep `origin` itself as a real directory, and create one junction per post directory under it.
   - Example shape:

     ```text
     artist_parse/YYYYMMDD/author_id/
       origin/
         2026-06-11_145880004_title/  -> junction to G:\...\2026-06-11_145880004_title
         2026-06-12_145917885_title/  -> junction to G:\...\2026-06-12_145917885_title
       group/
       repro_tests/
     ```

   - Treat junction-backed `origin` posts as live source files. Hidden-watermark restore, metadata repair, and other write operations will affect the external library target.
   - Never make `origin` itself a junction to one post. If that happens, remove only the junction reparse point, recreate `origin` as a normal directory, then add child post junctions.
   - On Windows, prefer native PowerShell end to end for inspection. For removing a junction reparse point, use a junction-safe removal such as `cmd /c rmdir "<junction_path>"` or a verified PowerShell equivalent; never recursively delete through the junction target.
   - After creating junctions, verify `origin` is not a junction, every child post directory is a junction, all targets exist, and each post exposes image files through the workspace path.

2. Restore metadata first.
   - Prefer PNG `Comment`.
   - If PNG `Comment` or equivalent visible metadata is missing, check the hidden watermark.
   - When hidden watermark metadata is found, restore it directly onto the original image with the project helper pattern `image.get_ai_image_prompt(file_path, transfer_origin=True)`, then re-read the image metadata and continue from the restored PNG `Comment`.
   - Record this as a hidden-watermark-to-origin restore, not merely a transient read.
   - Do not read nearby `metadata.json`, ancestor `nai_metadata_cache/images.jsonl`, or other sidecar/cache metadata for classification.
   - For speed, use a local image-metadata cache derived only from direct image reads during the current or previous skill run. Cache entries must be invalidated by file path, byte size, and `mtime_ns`; stale entries must be re-read from the image.
   - If Celsys Studio Tool export is detected, prefer `image.get_ai_image_prompt(file_path, transfer_origin=True)`.
   - Mark special cases after metadata restore: missing vibe reference, suspected vibe without recoverable vibe params, inpaint, img2img/add_original, or unrecoverable source metadata.
   - If every image in a post uses vibe but lacks embedded reference data, mark the post as `all_vibe_missing_embedded`. Keep this under the inferred style family in a `missing` second-level folder when style can be justified.
   - If every image in a post is img2img/inpaint/add_original and there is no normal `PromptGenerateRequest`, first check whether the images have recoverable embedded vibe references. If an embedded vibe group is present, classify by style family and embedded `vibe_<hash>` first, and record the whole-post img2img/inpaint status as a reproducibility warning. Only copy the whole post into top-level `99_all_img2img_or_inpaint` when there is no recoverable embedded vibe group.
   - Do not discard mixed posts wholesale. If a post contains any normal `PromptGenerateRequest`, classify the normal prompt images and keep img2img/inpaint/add_original as variants or flags.
   - When reviewing `missing` folders or posts with missing vibe data, salvage recoverable normal no-vibe images only when a direct image read shows `request_type = PromptGenerateRequest`, `reference_image_multiple` is empty or absent, and no vibe params such as `reference_strength_multiple` or `reference_information_extracted_multiple` are present. Copy that image into the inferred style family's `no_vibe/<post_name>/` folder. Keep the original `missing` copy in place, copy only image files unless the user asks otherwise, and write an audit row with source path, destination path, request type, vibe ref count, vibe-param absence, and key parameters.
   - Treat `98_unknown_style` as a review queue, not a final style. Before leaving anything there, re-read the original image metadata directly, inspect the recovered prompt stack, and attempt style-family inference from artist/style tags. Only keep a post in `98_unknown_style/missing` when the prompt and recovered parameters truly cannot justify a style family.

3. Group by post, not by image count.
   - Count one submission/post as one unit.
   - Do not let multi-image posts skew style frequency.
   - Track date ranges and post frequency per style family.

4. Group by style combination, not single-token frequency.
   - Use this primary split order: style family first, then second-level status (`no_vibe`, embedded `vibe_<hash>`, `missing` for missing embedded vibe), then model family.
   - The top-level folder should answer "which style family is this?".
   - The second-level folder should answer "which vibe/missing-reference state is this?".
   - Only second-level folders with embedded vibe should include `vibe_<hash>`. Use `no_vibe` only as a second-level status, not in the top-level style folder name.
   - Treat quality words, lighting words, and generic technique words such as `anime coloring` or `cel shading` as variants unless they are paired with a different artist stack or parameter family.
   - Do not create a separate main class for generic rendering/coloring differences such as `realistic`, `anime coloring`, `cel shading`, soft/painterly shading, or lighting mood when the stronger artist stack is unchanged.
   - Compare the whole prompt stack, but do not promote minor prompt seasoning into a separate main class.
   - Ignore resolution when clustering parameter variants.
   - Do not split vertical and horizontal images into separate style classes unless the prompt/parameter family truly changes.

5. Classify the style family.
   - Identify the main stable version.
   - Identify internal variants that differ only by quality words, lighting, shading language, or generic technique tags.
   - Split a new main style class when the artist stack/features or model family changes. Keep vibe and special archive states as second-level folders inside that style class.
   - Split manga/monochrome/orion/rance/yabuki-style variants only when they form a stable post-level artist/style stack in normal prompt images. Keep one-off manga/orion seasoning, content/action tags, or mostly img2img-only evidence under the parent style as variants.
   - Treat `all_vibe_missing_embedded` as a style-level `missing` second-level folder. Copy it under the inferred style family, but do not split it further unless the user explicitly asks.
   - Treat `all_img2img_or_inpaint` without recoverable embedded vibe as a top-level archive folder `99_all_img2img_or_inpaint`, not as a style child. When a whole-post img2img/inpaint group has recoverable embedded vibe references, vibe classification takes priority over this archive status.
   - If an archive-status post cannot be assigned to a style family from recovered image metadata or a confirmed prior style classification, place it under `unknown_style/<archive-status>` and call out the uncertainty.
   - If a post is currently in `98_unknown_style` but the prompt contains a recognizable style stack, move it back under the inferred style folder, usually as `missing` when the issue is missing embedded vibe. Record the matched evidence in the report or a TSV audit file.
   - If a mixed post has some images missing embedded vibe data but other images in the same post expose the vibe group, keep the whole post under that shared vibe group and record the missing-embedded cases only as notes.
   - When salvaging normal images from posts that had vibe elsewhere, copy only recoverable no-vibe normal images into the style family's `no_vibe/<post_name>/` folder and label them in reports as `normal_from_had_vibe_post` or `normal_from_missing`. Do not copy images that still have vibe params but lack embedded reference images.
   - Treat sampler, steps, scale, schedule, numeric strengths, and feature switches as variants. Model family is the only parameter-family main split unless the user asks otherwise.
   - Record each class's post share and time span.
   - Prefer the newest stable version inside the dominant class for reproduction.

6. Extract a reusable style folder.
   - Skip this step for analysis-only requests.
   - Write the chosen style to the project's style preset directory.
   - Keep the style folder focused on the stable reproduction target.
   - Store the chosen `tags.txt`, parameter notes, and sample source references there.
   - Name new style preset folders as `<author_id>_<EnglishStyleName>`, for example `104994507_Crisp_Flat_Anime`.
   - Build `EnglishStyleName` from two to four short visual/style words, with title-cased words separated by underscores. The name should read like a recognizable preset title.
   - Keep vibe hashes, model names, CFG values, vibe strengths, steps, scale, dates, source post ids, and labels such as `latest_stable` out of the folder name. Record them in `notes.md` and `gen_json` instead.
   - Add a visual suffix such as `_Soft`, `_Monochrome`, or `_Dark` only when it identifies a genuinely distinct reusable style variant.
   - Apply this naming rule prospectively. Do not rename existing style preset folders unless the user explicitly requests migration.
   - If the user explicitly asks for a new stable version of an existing preset, create a sibling copy instead of overwriting the existing folder. Preserve the source image and prompt files, document the base preset and the reason for the new version in `notes.md`, and use a concise suffix such as `_random_resolution` only when the behavior actually differs.
   - A random-resolution stable copy may retain the recovered source metadata for audit purposes, but normal artist loading must not force the source canvas size. Do not create a style variant solely because the source metadata contains `width` and `height`.

7. Reproduce with `run_action`.
   - Skip this step unless the user explicitly asks for reproduction or compare testing.
   - Default to `prompt_preset_service.py -> run_action`.
   - Keep preset enabled; do not bypass it.
   - Use the current `gen_json` parameter format for reproduction runs. Do not use the old `gen_param` workflow or files when preparing, running, or comparing style reproductions.
   - Use the current prompt composition rule unless the user overrides it:
     `artist line 1 + preset character + artist line 2 + action + artist line 3`
   - Extract the action prompt from the source image when possible.
   - Match the source parameters as closely as possible.
   - Treat `width` and `height` as runtime canvas settings, not style parameters. The normal artist-loading path removes them after merging artist parameters so Blackboard can choose its configured square/landscape/portrait behavior. If an exact source-size compare is requested, pass the source dimensions explicitly through the compare/generation runtime override; do not restore fixed resolution into the reusable style definition.
   - When the user asks for reproduction, treat compare testing as part of the default workflow. After generating, automatically build the compare package unless the user explicitly says to skip testing.

8. Build a flat compare package.
   - This step is mandatory after reproduction unless the user explicitly disables it.
   - Put source and generated images in one compare folder.
   - Export prompt, uc, comment, slim JSON, PNG text, and diff summary files.
   - Keep the package easy for external diff tools.
   - Prefer placing the compare folder beside the generated image unless the user asks otherwise.

9. Validate grouping artifacts.
   - After any grouping or reclassification, run `scripts/validate_grouping.py <group_root>` unless the user explicitly asks to skip validation.
   - Treat validator hard errors as blockers for the grouping result. Fix the grouping or report the blocker before continuing to reproduction.
   - Include `validation_report.md` and `validation_report.json` in the grouping root when validation is run.
   - After any grouping or reclassification, verify post-level consistency: source post count equals map rows equals grouped post directories, excluding only explicitly documented archives.
   - Rebuild `classification_map`, `classification_manifest`, and `group_summary` from the current source-of-truth data when they drift. Do not trust stale CSVs over the actual image metadata and grouping folders.
   - Check that `new_dst_post_path` is populated for every mapped row and points to an existing post folder.
   - Check that no `98_unknown_style` rows remain unless each unresolved post has a written reason.
   - Do not fabricate `no_vibe` or style labels to fill missing map rows. If provenance is missing, re-read image metadata or report the inconsistency.
   - Verify `no_vibe` at post-group granularity: a `no_vibe/<post>` group may contain img2img/inpaint variants, but it must include at least one recoverable `PromptGenerateRequest` image with zero vibe refs and no image in that group may use vibe.
   - Verify `vibe_<hash>/<post>` at post-group granularity: at least one image in the post group must expose embedded vibe refs matching the folder hash. Other images in the same post may lack embedded refs and should be treated as following the post-level vibe evidence.
   - Do not let salvaged copies inflate post-frequency totals; count the original submission once per applicable report scope.
   - Report metadata cache hits, misses, stale entries, and hidden-watermark restores when a cache was used.

10. Iterate.
   - Compare prompt diffs first, then parameter diffs, then image appearance.
   - If the source used vibe but the reference is missing, mark it as not exactly reproducible.
   - If the post is all inpaint/add_original, treat the base artwork as the real style carrier.
   - Re-run only when the style class or parameter family actually changes.

## Decision Rules

- Use post-level analysis before token-level analysis.
- Treat analysis and reproduction as separate phases; do not generate images for analysis-only requests.
- For large external corpora, prefer a junction-backed `origin` when the user accepts writing through to the source library. The required shape is a real `origin` directory containing per-post junctions, not one `origin` junction to a post.
- Treat junction-backed posts as originals for all metadata reads/writes; warn in reports when hidden-watermark restore or metadata repair modified files through a junction.
- Treat resolution as non-structural for style grouping.
- Prefer coarse main classes. Main class priority is `style family -> second-level vibe/missing status -> model family`, with top-level `99_all_img2img_or_inpaint` reserved for whole-post img2img/inpaint/add_original only when recoverable embedded vibe references are absent.
- Do not create top-level `no_vibe` folder names. If there is no embedded vibe, use `no_vibe` only as the second-level status under the style folder.
- Treat quality words, lighting, and generic rendering/coloring tags as variants unless they travel with a stronger primary split. Do not promote a `realistic`/`anime coloring`/`cel shading` cluster into a main style class by itself.
- Require stable post-level evidence before splitting manga/monochrome/orion/rance/yabuki variants. One-off manga/orion seasoning stays under the parent style.
- For main classification, split parameters only by model family. Sampler, steps, scale, scheduler, numeric strengths, and feature switches are parameter variants unless a whole post is special-only.
- Resolution is never a style/version discriminator. `width` and `height` may be preserved in recovered source records for exact comparison, but must be removed from the merged artist parameters during ordinary loading.
- Keep `preset` in the reproduction path.
- Use `gen_json` for reproduction parameters; do not fall back to old `gen_param`.
- Name newly extracted style presets as `<author_id>_<EnglishStyleName>` and keep technical parameters in `notes.md`/`gen_json`. Preserve existing preset folder names unless migration is explicitly requested.
- When reproduction is requested, automatically run the compare-package test flow after generation unless the user explicitly opts out.
- For every reproduction request, use the selected source image's action prompt and create the compare package in the same turn. Do not silently substitute a generic action or stop after image generation.
- If a new stable preset is requested from an existing preset, create a sibling copy and record its derivation; do not mutate the previous stable preset unless the user explicitly asks for an in-place update.
- Prioritize the latest stable member of the dominant style class.
- Treat whole-post missing embedded vibe as a style-level archive status. Copy those posts under the inferred style folder as `missing`, but do not subdivide that folder further.
- Treat whole-post img2img/inpaint/add_original with no recoverable embedded vibe references as a top-level archive category. Copy those posts to `99_all_img2img_or_inpaint`. If embedded vibe references are recoverable, classify under the inferred style family's `vibe_<hash>` folder and note that exact reproduction still depends on the source image/base canvas.
- Treat `98_unknown_style` as temporary. Reclassify it from direct image metadata whenever prompt evidence exists; leave only genuinely unresolved posts there, with evidence for why they could not be inferred.
- Use metadata caching for large corpora, but only when cache rows are derived from direct image reads and validated by path, size, and `mtime_ns`. Never trust sidecar metadata as the classification source.
- Run `scripts/validate_grouping.py <group_root>` after classification changes. The validator is read-only for source images and checks directory shape, post-level no-vibe/vibe/missing/99 metadata semantics, cross-style post duplicates, and salvage duplicates.
- In normal groups, if a post has any recoverable embedded vibe group, keep all images from that post under the same vibe group and only note the missing-embedded members in the report.
- In `missing` groups, actively look for recoverable normal no-vibe images. A salvageable no-vibe image must be `PromptGenerateRequest`, have zero embedded vibe refs, and have no vibe params. Copy only those image files into the inferred style family's `no_vibe/<post_name>/`, leave the original `missing` material intact, and audit the salvage. These copies are reproduction samples, not extra posts for frequency math.
- Top-level folder names should be concise style folders numbered like `01_official_typemoon_main`, `03_manga_monochrome_variant`; do not put model or vibe in the top-level folder title. Keep detailed reference hashes, model, and parameter variants in the report instead of the folder name.
- After correcting classification, regenerate or verify all summary artifacts and report the final post distribution.

## Outputs

- Style analysis report with classes, differences, frequency, and time span.
- Project style preset folder.
- Reproduction compare package with paired source/generated artifacts.

## Resources

- See [grouping-rules.md](references/grouping-rules.md) for grouping, versioning, and priority rules.
- See [compare-package-format.md](references/compare-package-format.md) for compare folder layout and file naming.
- See [run-action-repro.md](references/run-action-repro.md) for reproduction workflow and prompt composition rules.
- Use [scripts/image_metadata_cache.py](scripts/image_metadata_cache.py) to build or refresh a direct-image metadata cache for large artist corpora.
- Use [scripts/validate_grouping.py](scripts/validate_grouping.py) after grouping or reclassification to produce `validation_report.md` and `validation_report.json`.
- Use [scripts/sendto_make_compare.py](scripts/sendto_make_compare.py) to generate a local compare package from two selected images.
