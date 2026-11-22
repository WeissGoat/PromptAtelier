# V4.5 syntax: official facts

Everything here comes from NovelAI's own documentation and announcements. The
live docs have been rewritten for V5, so the links are archive.org snapshots
taken before V5 (2026-06-21 to 2026-07-24). Where the community found the
product behaving differently from the docs, the note says so.

## Contents
- Models
- Prompt structure and limits
- Weights
- Multiple characters
- Special tags
- Text
- Quality Tags toggle
- Undesired Content presets
- Settings
- Vibe Transfer and Precise Reference

## Models

- **Curated** (2025-05-05) is trained on a smaller, cleaner dataset: safe for
  streaming, no adult content. **Full** (2025-05-29) has the broader dataset;
  NovelAI suggests trying Full when Curated cannot draw something.
  ([Models](https://web.archive.org/web/20260621141343/https://docs.novelai.net/en/image/models/),
  [Curated announcement](https://journal.novelai.net/novelai-diffusion-v4-5-curated-is-here-9e5ba1f628f3/),
  [Full announcement](https://journal.novelai.net/novelai-diffusion-v4-5-full-release-678318c86205/))
- Both have `fur dataset` and `background dataset`. Their Quality Tags and
  Undesired Content presets differ (below); Full also has a Furry Focus preset.
- Opus subscribers generate for free at 28 steps or fewer, one image at a
  time, at normal sizes, on V4.5 and older models.

## Prompt structure and limits

- About **512 T5 tokens**, counting the base prompt and all character boxes
  together. Watch the Context Limit bar in the UI. The Quality Tags toggle uses
  some of this budget. Emoji and most Japanese or Chinese characters are not
  supported by the tokenizer.
  ([Models](https://web.archive.org/web/20260621141343/https://docs.novelai.net/en/image/models/),
  [Quality Tags](https://web.archive.org/web/20260624040802/https://docs.novelai.net/en/image/qualitytags/))
- Prompts can be all tags, all sentences, or both; the official examples mix
  tags with sentences.
  ([Basics](https://web.archive.org/web/20260624040803/https://docs.novelai.net/en/image/basics/))
- Suggested order: `1boy, 1girl, characters, series, everything else in any
  order`. Put what matters in the first half; avoid redundant, overlong tag
  lists. Only V3 and older are documented as "earlier tags are stronger".
  ([Tagging](https://web.archive.org/web/20260624040803/https://docs.novelai.net/en/image/tags/))
- Tag suggestions show a dot whose opacity says how well the model knows the
  tag. A word missing from the suggestions can still work; the model also
  trained on prose.

## Weights

([Strengthening & Weakening](https://web.archive.org/web/20260624040803/https://docs.novelai.net/en/image/strengthening-weakening/))

- `{tag}` multiplies by 1.05 per layer, `[tag]` divides by 1.05. `{{{tag}}}`
  is only about 1.16.
- Numeric: `1.5::rain, night ::` weights everything up to the next `::`
  without a number. Below 1 weakens (`0.5::coat ::`). Both `tag ::` and
  `tag::` appear in official examples.
- **Negative weights (V4.5 and later):** `-1::hat ::` removes a hat, `-3::hat ::`
  more strongly; `-1::monochrome ::` brings colour back; `-2.5::flat color ::`
  or `-6::simple illustration ::` add detail; `-1::simple background ::,
  location` moves a character off a blank background.
- Official rule of thumb: negative weights remove or reverse one concept;
  Undesired Content holds a long list of things you do not want. They do not
  replace each other.
- Weights up to about 10 stay fairly stable on V4.5.
- `::` on its own also closes every open bracket: `{{{{{rain ::`.
- Stable Diffusion's `(tag:1.2)` and V3's prompt mixing (`a | b`, `:0.5`) do
  not work on V4 or later.

## Multiple characters

([Multi-Character Prompting](https://web.archive.org/web/20260724204059/https://docs.novelai.net/en/image/multiplecharacters/))

- One base prompt for the scene and style, plus up to **six** character boxes
  (**+ Add Character**). V5 allows 22; that does not apply to V4.5.
- **Counts go in the base prompt** (`2girls, 1boy`, `3others`). Each box starts
  with `girl`, `boy` or `other`, without a number.
- Order the boxes with the arrows. The model usually places characters top to
  bottom, left to right: with `side-by-side`, the first box is usually on the
  left.
- **Position:** with two or more boxes, turn off **AI's Choice** and pick a
  cell in each box's **5×5 grid**. NovelAI calls this a gentle nudge: do not
  fight the box order, and back it up with a sentence.
- Each box has its own **Undesired Content**, for "information leakage"
  between characters.
- **Action tags:** `source#hug` for the one acting, `target#hug` for the one
  receiving, `mutual#hug` when both do it. NovelAI says they are not always
  reliable. The official example pairs `source#pointing at another` with
  `target#pointing`.
- The older `base | character 1 | character 2` form stops working as soon as
  any character box exists; do not mix them. A single `|` inside a prompt
  chunk also switches on this mode.

## Special tags

([Tagging](https://web.archive.org/web/20260624040803/https://docs.novelai.net/en/image/tags/))

- Dataset tags **must be first in the base prompt.** `fur dataset` (V4+) for
  furry art; Furry mode in the UI just adds it. `background dataset` (V4.5+)
  for landscapes, animal portraits and still life in a photographic style,
  without people.
- Quality: `best quality`, `amazing quality`, `great quality`,
  `normal quality`, `bad quality`, `worst quality`.
- Aesthetic: `masterpiece` (V4.5 only; V4 called it `top aesthetic`),
  `very aesthetic`, `aesthetic`, `displeasing`, `very displeasing`.
- `location` (new in V4.5): "there is a setting", without choosing indoors or
  outdoors.
- `year 2014` and so on: any year should work, with varying effect.
- `rating:general` is part of Curated's Quality Tags. The full list of
  `rating:` values is not documented.
- Renamed because `|` is a separator: `v` → `peace sign`, `double v` →
  `double peace`, `|_|` → `bar eyes`, `:|` → `neutral face`,
  `eyepatch bikini` → `square bikini`, `tachi-e` → `character image`.

## Text

([Text Rendering](https://web.archive.org/web/20260624040803/https://docs.novelai.net/en/image/textrendering/))

- Add `text, english text`, then put `Text: …` at the **very end** of the base
  prompt. Anything after `Text:` may be drawn as lettering.
- Separate several pieces of text with an empty line (Shift+Enter).
- Keep each piece to about **120 characters** including spaces. Only English
  is promised. V4.5 no longer needs all caps.
- Repeating the words in a sentence (`She is saying "Stop that!"`) makes it
  more reliable. Describe colour or placement in words (`in yellow text`).
- The base prompt is the most reliable place for `Text:`; character boxes
  work in theory.
- If short text does not appear, turn off Quality Tags: it adds `no text`.
- Official example: `2girls, text, english text, location, park, cowboy shot,
  -1::speech bubble::, looking at another, masterpiece, best quality,
  rating:general. The blonde girl is excitedly asking "…" in yellow text and
  the purple haired girl is responding "…" in green text … Text: …`

## Quality Tags toggle

([Add Quality Tags](https://web.archive.org/web/20260624040802/https://docs.novelai.net/en/image/qualitytags/))

On by default (gear icon of the prompt box). Hidden from the prompt, appended
at the end, and counted against the token limit.

| Model | Appended text |
| --- | --- |
| V4.5 Full | `, location, very aesthetic, masterpiece, no text` |
| V4.5 Curated | `, location, masterpiece, no text, -0.8::feet::, rating:general` |

- It can pull results toward an anime look. For a specific art style, turn it
  off or put `[]` around `very aesthetic`.
  ([Artstyles tutorial](https://web.archive.org/web/20260624040804/https://docs.novelai.net/en/image/tutorial-artstyles/))
- **Docs vs product:** Discord users who captured the real Full request saw no
  `location`, and one reported it was dropped on 2025-06-05 (D97–D99). Images
  in this repo's collection show both endings. Write `location` yourself when
  you want a setting.

## Undesired Content presets

([Undesired Content](https://web.archive.org/web/20260724204059/https://docs.novelai.net/en/image/undesiredcontent/))

Chosen from the gear icon; your own UC is added on top.

**V4.5 Full**
- Heavy: `lowres, artistic error, film grain, scan artifacts, worst quality, bad quality, jpeg artifacts, very displeasing, chromatic aberration, dithering, halftone, screentone, multiple views, logo, too many watermarks, negative space, blank page`
- Light: `lowres, artistic error, scan artifacts, worst quality, bad quality, jpeg artifacts, multiple views, very displeasing, too many watermarks, negative space, blank page`
- Furry Focus: `{worst quality}, distracting watermark, unfinished, bad quality, {widescreen}, upscale, {sequence}, {{grandfathered content}}, blurred foreground, chromatic aberration, sketch, everyone, [sketch background], simple, [flat colors], ych (character), outline, multiple scenes, [[horror (theme)]], comic`
- Human Focus: `lowres, artistic error, film grain, scan artifacts, worst quality, bad quality, jpeg artifacts, very displeasing, chromatic aberration, dithering, halftone, screentone, multiple views, logo, too many watermarks, negative space, blank page, @_@, mismatched pupils, glowing eyes, bad anatomy`

**V4.5 Curated**
- Heavy: `blurry, lowres, upscaled, artistic error, film grain, scan artifacts, worst quality, bad quality, jpeg artifacts, very displeasing, chromatic aberration, halftone, multiple views, logo, too many watermarks, negative space, blank page`
- Light: `blurry, lowres, upscaled, artistic error, scan artifacts, jpeg artifacts, logo, too many watermarks, negative space, blank page`
- Human Focus: `blurry, lowres, upscaled, artistic error, film grain, scan artifacts, bad anatomy, bad hands, worst quality, bad quality, jpeg artifacts, very displeasing, chromatic aberration, halftone, multiple views, logo, too many watermarks, @_@, mismatched pupils, glowing eyes, negative space, blank page`

Heavy includes `chromatic aberration`; avoid it when you want that effect.
Official tip: when `freckles` gives odd artifacts, `{{tattoo, facial mark}}`
in UC keeps the freckles and drops the artifacts.

## Settings

([Sampling](https://web.archive.org/web/20260624040804/https://docs.novelai.net/en/image/sampling/),
[Steps & Guidance](https://web.archive.org/web/20260624040803/https://docs.novelai.net/en/image/stepsguidance/))

- Samplers: Euler Ancestral and DPM++ 2M recommended.
- Prompt Guidance: about 5–6 for V3 and later. Lower is softer and more
  painterly; higher is sharper, with side effects if too high.
- Rescale exists to curb oversaturation at high guidance. No official V4.5
  value.
- No official V4.5 resolution or noise schedule. 832×1216 is the default
  portrait size; 1216×832 landscape.
- Find a composition at low steps first, then Enhance.

## Vibe Transfer and Precise Reference

([Vibe Transfer](https://web.archive.org/web/20260624040803/https://docs.novelai.net/en/image/vibetransfer/),
[Precise Reference](https://web.archive.org/web/20260624040803/https://docs.novelai.net/en/image/precisereference/))

- Higher Vibe Transfer strength ignores more of the prompt. Keep the summed
  strength at 1.0 or less. Tag what you want kept from the reference; put
  what you want gone in UC. Lower "Information Extracted" keeps composition
  and drops texture and style.
- Precise Reference is **V4.5 only** and cannot be combined with Vibe
  Transfer. Several Character References blend into one character rather than
  becoming separate people. Clean, full-body, neutral-pose references on a
  simple background work best; if an outfit does not carry over, add tags for
  it.
