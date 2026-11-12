# V4.5 in practice: what the community does

Community experience from the NovelAI Discord (Anlatan) and other Discord
servers, Chinese Telegram groups, and tutorials, 2025-04 to 2026-08. Ids in
brackets (`D81`, `T119`, `W29`) point to the source messages listed in
`research_reports/nai45-prompting/discord.md`, `telegram.md` and `web.md` in
this repository. "(one person)" marks something only one user reported;
"disputed" marks points where sources disagree. Treat both as things to test,
not rules.

## Contents
- Organizing a prompt
- Tags and sentences
- Multiple characters
- Weights
- Artist strings
- Quality tags and Undesired Content
- Dataset tags, year, rating
- Text
- Settings
- Curated vs Full
- Troubleshooting
- Disputed points

## Organizing a prompt

This template combines the sources; only "dataset tag first, counts in the
base, `Text:` last" is official.

```
[Base]
(dataset tag, optional: fur dataset / background dataset)
people count and solo: 1girl, solo   or   2girls, 1boy
(single character) character name (series), series
artist string: 1.2::artist:a::, 0.8::artist:b::, …, -3::artist collaboration::
year 2024, year 2025
framing / camera / setting: cowboy shot, from side, location, bedroom, …
one or two sentences: In the back corner of the room, she is …
(own quality block, or leave it to the Quality Tags toggle)
(with text) text, english text … She says "Hello!". Text: Hello!

[Character 1]  girl, name or identity, hair, eyes, outfit, action (source#…), expression
[Character 1 negative]  the other character's hair colour, outfit, …
[Character 2]  boy, …, target#…

[Undesired Content]  a preset, or about ten words of your own
```

- **Count and `solo` first.** Recommended by Anlatan regulars, attributed to
  Anlatan staff [D11][D12]. Do not write `solo` with several people [D67].
  If faces appear in the background, add `1girl, solo` [T16]. When a
  character name already carries its series in brackets, a separate series tag
  is not needed [T21].
- **Order matters less than on V3 — disputed.** A developer says V4/V4.5's T5
  encoder is bidirectional and order should not matter [D2]. Users keep
  reporting that the *last* artist in a string shows the most [D15][D16].
  Working rule: put the base artists first and the one you want to dominate
  later, slightly weighted [D16].
- **Length.** The ~512-token budget is shared by base and boxes, and users say
  the UC preset counts too [D17]. Over-long LLM-written prompts silently drop
  the artist string; capping at about 60 tags fixed it [D21][D19]. One
  tutorial author stays under 400 tokens [W26].

## Tags and sentences

- Use a tag when one exists: `white hair` beats a sentence about white hair
  [D7][D8]. Add one or two sentences for what tags cannot express: where
  people are relative to each other, details of an action [D10][T26].
- A developer calls V4.5's natural-language understanding "not strong yet"
  [D5]; Telegram users range from "stronger than tags" to "barely helps,
  cannot tell left from right" [T28][T33]. Expect sentences to nudge, not to
  control exact limb placement [T34].
- Commas between tags and full stops between sentences blur less when mixed
  (one person) [D14].

## Multiple characters

- Base prompt: counts (`2girls, 1boy`), scene, style. Each box: `girl`/`boy`
  without a number [W13][D6].
- **Positions** appear only with two or more boxes. Either leave AI's Choice
  on, or give each person a *different* cell; two boxes in one cell merge
  [D30][D31][D32]. The first box tends to land on the left either way [D33].
  Opinions on manual positions range from "never worked as intended" to
  "helps about half the time" [D34][D35][D36].
- **Action tags:** use the *same* action word on both sides
  (`source#punching` / `target#punching`); with three people, both actors get
  `source#` [D44][D47]. One action tag per character unless `mutual#` [W26].
- **Swapped actions and expressions** are the most common complaint in the
  English, Japanese and Chinese communities [D51][D54][D56][T60][T62][T65].
  No reliable fix exists. What helps:
  - real action tags rather than prose for the interaction [D48];
  - one sentence in the base stating who does what to whom [D57];
  - for two people, plain tags such as `hugging` / `hugged` instead of
    action tags [D49][D50];
  - rerolls: one user gets one or two usable images in four for three-person
    scenes [D58].
- **Trait bleed** (hair colour, outfit moving to the other person): put the
  other characters' traits in each box's negative, weight the traits that tell
  them apart, and keep each action in its own box [W13][D41]. Chinese prompt
  tools almost always add `background characters, fused bodies` to each box's
  negative [D40].
- **Each character in a different art style** with several artists is a known
  V4.5 behaviour [D64][T69]. Fix: `-3::artist collaboration::` (or -5, -6) in
  the positive prompt, and drop the `artist:` prefix on Full [D65]. This is why
  most Chinese artist strings end with `-N::artist collaboration::` [D84][T72].
- Keep quality tags out of character boxes, and describe characters only in
  their boxes, not in the base [W25].

## Weights

- Use numeric weights. Brackets are fixed 1.05 steps and need many layers on
  V4.5 [W10][D69][D71].
- `(tag:1.2)` does nothing on NovelAI; write `1.2::tag::` [D72]. Some Japanese
  tutorials and Chinese notes get this wrong [W29][W34], and AI chat bots on
  two Chinese servers claim "NAI only understands `{}`" — also wrong
  [D174][D175]. NAI3-era bracket strings reproduce poorly on V4.5 [T113].
- Range: a NovelAI developer calls 3.0 a reasonable weight on V4.5 [D68];
  concept tags at 2–5 are common [T85][T86]. Heavy weight on a series name
  brings in its side traits: `2::blue archive` adds halos [T88].
- Negative weight vs UC: one user found `-2::upside-down::` in the prompt
  worked where a 5× weight in UC did not (one person) [T91][T92]; no consensus
  [T95].

## Artist strings

- **Tuning loop** [D81]: start from one artist you like; fix a seed; add one
  artist at a time at `1::artist:name::` and move its weight up or down; keep
  4–9 artists; check the result on a few different prompts. Others tested
  weights from 1.8 down to 0.6 and kept 6–7 artists [D83].
- One artist usually dominates, even at a lower weight [D80].
- Strings do not transfer between models: V4 to 4.5 Curated changed most
  strings [T116], and a Curated string looks "completely different" on Full
  [T119]. Choose the model first.
- `artist:` prefix — disputed: one user finds artists unstable without it
  [D74]; others drop it on Full to reduce style splitting [D75][D65].
- Finding artists: the nax.moe "danbooru-artist-tags-v4.5" gallery [D76][T130];
  zele.st's artist library [T129]. Single artists are strong on Full; NAI3-style
  blending needs different strings [T107].
- Sharing: Discord turns `::artist:` into emoji; share strings in a code block
  [D90]. In Telegram groups people post the original file and reply `kkp` so a
  bot extracts the prompt; compressed photos lose it [T122][T124].

## Quality tags and Undesired Content

- The Quality Tags toggle and the default UC preset both push a style. For a
  consistent custom style, turn them off and write your own [W19][D102][D103].
- **Whether to write quality tags — disputed.** One regular says
  `very aesthetic` and `absurdres` often hurt on 4.5 (oversaturation, clutter)
  [D105]; another says 4.5 needs half the quality tags of V4 [D107]; Chinese
  strings nearly always carry `very aesthetic, masterpiece, no text`, often
  weighted [D86][T72]; one Telegram user lost quality by deleting "extra"
  quality tags [T141], another deleted them all with no loss [T145].
  Recommendation: start with the toggle's defaults, settle the style, then
  remove tags one at a time and compare.
- **UC:**
  - keep it to about ten words [D12]; a minimal one: `blurry, lowres, error,
    jpeg artifacts, scan artifacts, chromatic aberration, bad anatomy,
    unfocused, unfinished` [D13];
  - when you write your own, set the preset to None so they do not stack [D110];
  - UC changes the style noticeably; check it [T164];
  - add for a specific problem, for example `overexposure` when washed out
    [D109].
- Curated's toggle includes `-0.8::feet::`, which users say biases foot
  framing [T90].

## Dataset tags, year, rating

- `background dataset` must be first or it does nothing [D115]. It turns the
  image photographic and is poor for people; use it for landscapes, animals,
  still life [D117][D118][D119]. Vibe Transfer can tame it [D120].
- `fur dataset` is what Furry mode adds [D123]; it cannot share first place
  with `background dataset` [D126]; it lowers quality for non-furry content
  [D131]. Do not type it when Furry mode is on: it doubles [D168].
- `year 2024, year 2025` is nearly standard [D84][T104] and some use a year to
  steady one artist's style [T110]; others doubt it does much [T173].
- `rating:general` on Full tones down suggestive content [D100][D137].

## Text

- Pattern: `speech bubble, english text … She is saying "Don't you ever
  think?". Text: Don't you ever think?` [D141]. Repeat the words in a
  sentence, put `Text:` last, separated from what comes before by a full stop
  [D6][W11].
- Keep it under 120 characters; a developer later said 125 [D139][D140].
- Japanese and Chinese are not drawn; they act like a random style seed
  [D143][D145]. Several bubbles and complex layouts mostly fail [D147][D148].
- If text does not appear, turn off Quality Tags (it adds `no text`)
  [W11][D146].

## Settings

| Setting | Common values | Sources |
| --- | --- | --- |
| Sampler | Euler Ancestral most common; DPM++ 2M next; DPM++ 2M SDE for realistic images | [W21][D149][T193] |
| Steps | 28 (free for Opus); some find 14 usable for drafts | [W22][D149][T195] |
| Prompt Guidance | Docs 5–6; Anlatan regulars 5–5.5; a developer about 5 | [W22][D149][D150] |
| Rescale | Anlatan 0–0.2, a developer uses none; Telegram: Full unstable at 0, use ≥0.4 with low guidance — disputed | [D149][D150][T198][T204] |
| Size | 832×1216 portrait; 1216×832 or 1152×896 landscape | [W7] |

Telegram users say guidance 7 "blows up" on Full and 2–4 looks better [T198].
Start at guidance 5 and rescale 0.2; if the image is too bright or saturated,
lower guidance or raise rescale [D151][D153].

## Curated vs Full

- Curated is SFW only; adult content needs Full plus `nsfw` [D135][T224].
  Many "it ignores my prompt" posts were Curated by accident; the mobile
  site defaults to it [D166][T228].
- The models differ a lot; prompts need adjusting [D25]. They recognise
  different artists and characters [T234].
- NovelAI changed the inference backend in 2026-03 and 2026-06; old seeds may
  not reproduce [D160][D161][T243].

## Troubleshooting

| Symptom | Try first | Sources |
| --- | --- | --- |
| Censored, no adult content | Switch to Full and add `nsfw` | [D135] |
| People merge into one | No `solo`; `1boy, 1girl`; different grid cells or AI's Choice; trim UC | [D67] |
| Actions or expressions swapped | Same action word on both sides; one sentence on who does what; reroll | [D57][T65] |
| Each character in its own style | `-3::artist collaboration::`; drop `artist:` prefix | [D65] |
| Artist string ignored | Over the token limit (count the UC preset too); emoji-converted when copied from Discord | [D17][D21][D90] |
| `background dataset` / `fur dataset` no effect | Make it the first tag | [D115] |
| No text, or garbled text | English only, under 120 characters, `Text:` last; Quality Tags off | [W11][D139] |
| Too bright, oversaturated | Lower guidance or add rescale; `overexposure` in UC | [D153][D109] |
| Flat style, looks like 2010s anime | Add artist tags; turn off Quality Tags and the UC preset, write your own | [D102] |
| `(tag:1.2)` does nothing | Write `1.2::tag::` | [D72][W10] |
| String tuned on Curated breaks on Full | Pick the model, then tune | [T119] |
| Faces or small people in the background | `1girl, solo`; drop a redundant series tag | [T16][T21] |
| Halo, uniform or other series traits leak in | Lower the series or character weight | [T88] |
| Old seed gives a different image | Backend changed in 2026-03/06; not a prompt problem | [D160][T243] |

## Disputed points

- Does order matter? Developer: no. Users: the last artist dominates. [D2][D15]
- Quality tags: harmful, half needed, or essential? [D105][D107][T141][T145]
- `artist:` prefix on or off. [D74][D75]
- Manual positions useful or not. [D34][D35][D36]
- Rescale 0–0.2 (Anlatan) vs ≥0.4 (Telegram). [D149][T204]
- Does the Full toggle add `location`? Docs yes, captured requests no. [W15][D97]
- Negative weight vs UC: which removes a concept better. [T91][T95]
