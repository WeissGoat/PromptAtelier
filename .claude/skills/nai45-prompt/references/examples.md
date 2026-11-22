# V4.5 example prompts

Real prompts, quoted as collected and shortened with `…`. SFW only. Ids point
to the source lists in `research_reports/nai45-prompting/` (see practice.md).
Read the example closest to the request; borrow structure, not artist names.

| # | Shows | Source |
| --- | --- | --- |
| E1 | Base + one character box, sentence for placement | Anlatan, D10 |
| E2 | Lettering in a speech bubble | Anlatan, D141 |
| E3 | Three boxes with source#/target# and a negative weight | Telegram bot export, T8 |
| E4 | Official text example with two speakers | NovelAI docs, W11 |
| E5 | Official action-tag pair with different words | NovelAI docs, W13 |
| E6 | Artist string with negative-weight quality block | Anlatan, D84 |
| E7 | Quality and negative-weight block | Telegram, T72 |
| E8 | `background dataset` landscape | Anlatan, D172 |
| E9 | Minimal start | Anlatan, D13 |
| E10 | Converting an SD prompt (illustration, not collected) | — |

## E1 Base + character box (Raezuto, Anlatan) [D10]

Base:
```
1boy, solo, rating:general, from side, daytime, lights on, bedroom interior, window, cinematic, … best quality, amazing quality, simple background, -0.5::absurdly detailed composition::, In the back corner of the bedroom, Character is sitting on the floor…
```
Character 1: `boy, adult male, mature male, clothed,`
UC preset: Human Focus. The author suggests comparing Quality Tags on and off.

Notes: count and `solo` first; tags for the setting, then one sentence for
where he is. The box holds only identity tags; the scene stays in the base.
A small negative weight trims one quality tag's side effect.

## E2 Lettering (Uchariko, Anlatan) [D141]

```
1girl, solo, very long hair, purple hair, … speech bubble, crossed arms, annoyed, english text, location, very aesthetic, masterpiece, no text. She is saying "Don't you ever think?". Text:Don't you ever think?
```

Notes: `speech bubble` and `english text` as tags; the line repeated in a
sentence; `Text:` last after a full stop. The quality block here carries
`no text` and the text still rendered; if yours does not, remove it.

## E3 Three characters with action tags (galaxytagger export, Telegram) [T8]

Base:
```
2girls, 1boy, 1.1::TorinoAqua, kazunehaka::, 0.6::toosaka asagi::, distracted boyfriend (meme), … very aesthetic, masterpiece, no text
```
Character 1: `girl, 1.5::mika (blue archive)::, …, source#angry, anger vein, …`
Character 2: `boy, doodle sensei (blue archive), …, target#angry, …`
Character 3: `girl, 1.5::kisaki (blue archive)::, …, -2:: anger vein::, head out of frame`

Notes: counts only in the base; each box starts with `girl`/`boy`; the same
action word on both sides; a negative weight in the third box keeps the anger
vein from bleeding onto her. A meme tag sets the composition in one word.

## E4 Official text example (NovelAI docs) [W11]

```
2girls, text, english text, location, park, cowboy shot, -1::speech bubble::, looking at another, masterpiece, best quality, rating:general. The blonde girl is excitedly asking "…" in yellow text and the purple haired girl is responding "…" in green text … Text: …
```

Notes: tags, then sentences that say who says what and in which colour, then
`Text:`. `-1::speech bubble::` keeps the words as free-floating text.

## E5 Official action-tag pair (NovelAI docs) [W13]

The pointing character's box has `source#pointing at another`; the other has
`target#pointing`, and its box ends with `Text: Stop that!`. Officially the
words may differ; community experience says identical words swap less often
(practice.md, Multiple characters).

## E6 Artist string with quality block (Anlatan) [D84]

```
1.2::artist:daram (shappydude),:: 1.8::artist:japtangtang2,:: … year 2024, year 2025, -6::artist collaboration::, 1.5::realistic::, best illustration, best quality, amazing quality, very aesthetic, highres, … -1::multiple views::, -1::simple illustration:: -2::upscaled, blurry::
```

Notes: every artist weighted and closed; `-6::artist collaboration::` against
style splitting; negative weights instead of UC entries for a few targeted
problems. Brackets and numeric weights are mixed in the elided part; prefer
numeric.

## E7 Quality and negative-weight block (Telegram) [T72]

```
year 2025, year 2024, 1.3::best quality, amazing quality, very aesthetic, highres, incredibly absurdres, ::, cinematic, …, -3::simple illustration ::, -6.0::artist collaboration ::,
```

Notes: one weight over a whole group of quality tags, closed by `::`. A common
Chinese-community ending.

## E8 `background dataset` (Strawberry Mk.VI, Anlatan) [D172]

```
background dataset, realistic, landscape only, day, soviet union, apartment blocks, snow, 1.5::dark, dark atmosphere::, snow storm, street view, photo (medium),
```

Notes: dataset tag first; no people; photographic medium tag; one weighted
mood group.

## E9 Minimal start (Anlatan) [D13]

Base begins `digital media (artwork), absurdres, year 2023`; UC preset None
with the author's own `blurry, lowres, error, jpeg artifacts, scan artifacts,
chromatic aberration, bad anatomy, unfocused, unfinished`.

Notes: a short base to find a style before adding content; own UC instead of
a preset, so they do not stack.

## E10 Converting a Stable Diffusion prompt (illustration)

Not collected; shows the usual edits.

Before (SD):
```
masterpiece, best quality, (1girl:1.2), 1boy, (red hair:1.3), (blue hair), girl hugging boy, \(genshin impact\), <lora:style:0.8>, (worst quality:1.4)
```
After (V4.5 Full, Quality Tags on, UC preset Heavy):
- Base: `1girl, 1boy, year 2024, upper body, location, garden. The red-haired girl hugs the blue-haired boy from behind.`
- Character 1: `girl, 1.3::red hair::, source#hug, smile` — negative `blue hair`
- Character 2: `boy, blue hair, target#hug, surprised` — negative `red hair`
- UC: preset only.

Changes: `(tag:1.2)` → `1.2::tag::`; counts to the base, people into boxes;
LoRA syntax dropped (NovelAI has no LoRAs; use artist tags or Vibe Transfer);
the escaped series tag dropped because neither character is named (keep it,
unescaped, as `genshin impact` when they are); `masterpiece, best quality`
left to the toggle;
`(worst quality:1.4)` left to the preset.
