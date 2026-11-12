---
name: nai45-prompt
description: "Write, organize, fix or explain NovelAI Diffusion V4.5 (Curated or Full) image prompts — base prompt, character boxes and 5×5 positions, source#/target#/mutual# action tags, 1.2::tag:: and negative weights, artist strings (画师串), quality tags, Undesired Content presets, fur/background dataset tags, Text: lettering, and generation settings. "
---

# NovelAI V4.5 prompts

NovelAI Diffusion V4.5 (Curated from 2025-05-05, Full from 2025-05-29) reads
prompts with a T5 encoder. A prompt has a base prompt, up to six character
boxes (each with an optional grid position and its own negative), and
Undesired Content. Tags and plain English sentences can be mixed. This skill
turns what the user wants into those fields, checks them, and explains the
choices, so the user spends fewer Anlas on rerolls.

Read before writing:
- [references/syntax.md](references/syntax.md): official rules and the exact
  text of the Quality Tags and Undesired Content presets. Required.
- [references/practice.md](references/practice.md): what the community does
  (prompt order, multi-character, artist strings, quality and negatives,
  settings, Curated vs Full) and a troubleshooting table. Required.
- [references/examples.md](references/examples.md): real prompts, annotated.
  Read the one closest to the request.

`<skill-dir>` below is the directory containing this file.

## Workflow

1. **Brief.** Find out the subject, how many people, who they are (character
   and series names, or a fixed look), what they do to each other, the style
   (artist names, or a description such as "thick lineart, flat colours"),
   framing and setting, any English text in the image, and the model (Full or
   Curated). Ask only for what you cannot reasonably choose; pick the rest and
   say what you picked. Defaults: Full, 832×1216 portrait, Quality Tags on,
   Undesired Content preset Heavy, AI's Choice on.
2. **Pick the model first.** Curated is SFW only and knows fewer artists;
   adult content needs Full plus `nsfw`. Artist strings tuned on one model do
   not carry over to the other, so settle this before tuning style.
3. **Write the base prompt** in this order (practice.md explains each part):
   dataset tag if any → people count (`1girl, solo` or `2girls, 1boy`) → for a
   single named character, the character and series → artist string with
   numeric weights → `year 2024`-style tags → framing, camera, setting
   (`cowboy shot, from side, location, bedroom`) → one or two plain sentences
   for what tags cannot say → your own quality block, if Quality Tags is off →
   `text, english text`, a sentence that repeats the words, and `Text: …` last.
4. **Write a character box per person** when there are two or more people (or
   one person you want kept apart from the scene): start with `girl`, `boy` or
   `other` with no number, then name or identity, hair, eyes, outfit, action
   (with `source#`/`target#`/`mutual#` when they interact), expression. In each
   box's negative, put the other characters' distinguishing traits.
5. **Undesired Content**: a preset (Heavy, Light, Human Focus; Furry Focus on
   Full) or about ten words of your own with the preset set to None. Prefer a
   negative weight in the prompt (`-2::monochrome::`) to remove or reverse one
   specific thing.
6. **Check.** Write the prompt as a spec file (format below) and run
   `node <skill-dir>/scripts/check-prompt.mjs <spec.json>`. Fix every error and
   warning, or tell the user why a warning does not apply. Keep spec files in
   the user's project (for example `nai_prompts/`) or a scratch folder, not
   inside this skill.
7. **Deliver** in the user's language:
   - the paste blocks the script prints (Base, each Character with its grid
     cell and negative, Undesired Content);
   - settings: model, size, steps, Prompt Guidance, rescale, sampler, Quality
     Tags on or off, UC preset, AI's Choice or manual positions;
   - why the prompt is built this way, briefly, citing syntax.md or
     practice.md where a choice is not obvious;
   - two or three fixes to try first if it comes out wrong, from the
     troubleshooting table in practice.md.

Prompt text stays in English tags and sentences. Japanese or Chinese words are
mostly unknown to the T5 tokenizer and act like random noise, and lettering is
only promised in English.

When the user brings an existing prompt (from Stable Diffusion, NAI3, an LLM
or a friend), convert rather than rewrite: keep their tags, fix the syntax
(`(tag:1.2)` → `1.2::tag::`), move counts and dataset tags to where V4.5 wants
them, split people into character boxes, trim it under the token limit, and
list what you changed.

## Spec format

```json
{
  "model": "V4.5 Full",
  "size": [832, 1216],
  "base": "2girls, 1.1::artist:example::, year 2024, cowboy shot, location, park, …",
  "characters": [
    { "prompt": "girl, red hair, … source#hug", "negative": "blue hair", "position": "B3" },
    { "prompt": "girl, blue hair, … target#hug", "negative": "red hair", "position": "D3" }
  ],
  "negative": "",
  "settings": { "qualityTags": true, "ucPreset": "Heavy", "aiChoosesPositions": false,
                "steps": 28, "scale": 5, "cfgRescale": 0.2, "sampler": "k_euler_ancestral" }
}
```

`model` is `V4.5 Full` or `V4.5 Curated`. `position` is a 5×5 grid cell:
columns A–E left to right, rows 1–5 top to bottom, C3 the centre; `[x, y]`
fractions also work. `ucPreset` is `Heavy`, `Light`, `Human Focus`,
`Furry Focus` or `None`. The script adds the toggle's quality tags and the
preset's words when it estimates tokens and looks for conflicts.

## Reading an existing image

`node <skill-dir>/scripts/read-prompt.mjs <png|dir>` prints the base, every
box with its grid cell, the negatives and the settings stored in a NovelAI
PNG. `--spec` prints a spec for check-prompt.mjs with the Quality Tags suffix
removed (recorded as `settings.qualityTags`). Use it to explain why an image
looks the way it does, or to start from an image the user likes. Images that
were re-encoded (Telegram photos, screenshots, most social media) have no
metadata left; say so instead of guessing. The metadata does not say whether
the model was Curated or Full; infer it from the quality suffix only when one
is present.

## Honesty about evidence

- syntax.md is official documentation (archived before V5 replaced it).
  practice.md is community experience; several points are disputed or rest on
  one person's tests, and it marks them. Keep that distinction when you
  explain a rule, and do not present a community habit as an official rule.
- Multi-character prompts still swap actions and expressions between people
  often. Tell the user to expect rerolls rather than promising a fix.
- Do not invent artist names or claim an artist tag works; suggest the user
  checks it in the nax.moe V4.5 artist gallery or by a fixed-seed test.
- practice.md and examples.md cite private Discord servers and Telegram
  groups. Do not publish this skill, its references, or long excerpts.

## Updating this skill

The references come from a research run dated 2026-10-06 covering
2025-04-01 to 2026-08-20 (before V5): `research_reports/nai45-prompting/` in
this repository (report.md plus web.md, discord.md and telegram.md, which hold
the links for the `W`/`D`/`T` ids used in the references). To refresh, run the
discord-community-research and telegram-community-research skills on new
questions, update practice.md with the source ids, and run
`node --test <skill-dir>/tests/scripts-test.mjs` after changing the scripts.
