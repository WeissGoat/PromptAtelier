# Compare Package Format

Create a flat folder that can be inspected by image viewers and diff tools.

## Preferred Files

```text
source_*.png
generated_current_tags.png
source_prompt.txt
generated_prompt.txt
source_uc.txt
generated_uc.txt
source_comment.json
generated_comment.json
source_slim.json
generated_slim.json
source_png_text.json
generated_png_text.json
prompt_unified.diff
diff_summary.txt
tags_used.txt
```

## Folder Placement

When comparing manually selected images, put the compare folder beside the generated image. Use a name like:

```text
manual_compare_<source_stem>_vs_<generated_stem>_<YYYYMMDD_HHMMSS>
```

For planned reproduction tests, a stable folder under the artist `repro_tests` directory is also acceptable when the user asks for it.

When the user asked for reproduction and did not opt out of testing, always create one compare folder for the run. Do not wait for a second user message to package the artifacts.

## Diff Summary

Always include:

- source path
- generated path
- source metadata recovery method
- generated metadata recovery method
- `PARAM_DIFF`
- `PARAM_DIFF_NO_RESOLUTION`
- prompt token counts
- common tokens
- source-only tokens
- generated-only tokens

`PARAM_DIFF_NO_RESOLUTION - none` is the important grouping signal. Full `PARAM_DIFF - none` is the stronger exact-compare signal.

Resolution handling:

- `PARAM_DIFF_NO_RESOLUTION` is the primary parameter result for style reproduction.
- A difference in `width` or `height` alone must not be reported as a style mismatch.
- If the run intentionally uses the source canvas size, record that as an explicit runtime override in the summary.
- Do not edit the reusable artist preset just to make a compare package match source dimensions.

## Existing Tool

Use `scripts/sendto_make_compare.py` when two image paths are available. It should:

- infer source and generated roles by path/name heuristics
- read PNG text and hidden watermark only
- copy both images into the compare folder
- write prompt, uc, comment JSON, slim JSON, PNG text JSON, unified diff, and summary
