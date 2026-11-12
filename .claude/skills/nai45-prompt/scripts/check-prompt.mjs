#!/usr/bin/env node
// Lints a NovelAI Diffusion V4.5 prompt spec and prints it as paste-ready blocks.
// The spec format matches read-prompt.mjs --spec, so an image's prompt can be
// checked, edited and re-checked.
import fs from 'node:fs';
import { parseArgs } from 'node:util';

const USAGE = `Usage: node scripts/check-prompt.mjs <spec.json> [--json]

Spec: { "model": "V4.5 Full" | "V4.5 Curated", "size": [832, 1216],
        "base": "...", "characters": [{ "prompt": "...", "negative": "...", "position": "C3" | [x, y] | null }],
        "negative": "...",
        "settings": { "qualityTags": true, "ucPreset": "Heavy" | "Light" | "Human Focus" | "Furry Focus" | "None",
                      "aiChoosesPositions": true, "steps": 28, "scale": 5, "cfgRescale": 0.2, "sampler": "k_euler_ancestral" } }
Prints problems (error / warn / info), then the prompt as blocks to paste into
NovelAI. Exit code 1 when there are errors.`;

// Official text (docs.novelai.net snapshots before V5, see references/syntax.md).
export const QUALITY_TAGS = {
  full: ', location, very aesthetic, masterpiece, no text',
  curated: ', location, masterpiece, no text, -0.8::feet::, rating:general',
};
export const UC_PRESETS = {
  full: {
    heavy: 'lowres, artistic error, film grain, scan artifacts, worst quality, bad quality, jpeg artifacts, very displeasing, chromatic aberration, dithering, halftone, screentone, multiple views, logo, too many watermarks, negative space, blank page',
    light: 'lowres, artistic error, scan artifacts, worst quality, bad quality, jpeg artifacts, multiple views, very displeasing, too many watermarks, negative space, blank page',
    'furry focus': '{worst quality}, distracting watermark, unfinished, bad quality, {widescreen}, upscale, {sequence}, {{grandfathered content}}, blurred foreground, chromatic aberration, sketch, everyone, [sketch background], simple, [flat colors], ych (character), outline, multiple scenes, [[horror (theme)]], comic',
    'human focus': 'lowres, artistic error, film grain, scan artifacts, worst quality, bad quality, jpeg artifacts, very displeasing, chromatic aberration, dithering, halftone, screentone, multiple views, logo, too many watermarks, negative space, blank page, @_@, mismatched pupils, glowing eyes, bad anatomy',
  },
  curated: {
    heavy: 'blurry, lowres, upscaled, artistic error, film grain, scan artifacts, worst quality, bad quality, jpeg artifacts, very displeasing, chromatic aberration, halftone, multiple views, logo, too many watermarks, negative space, blank page',
    light: 'blurry, lowres, upscaled, artistic error, scan artifacts, jpeg artifacts, logo, too many watermarks, negative space, blank page',
    'human focus': 'blurry, lowres, upscaled, artistic error, film grain, scan artifacts, bad anatomy, bad hands, worst quality, bad quality, jpeg artifacts, very displeasing, chromatic aberration, halftone, multiple views, logo, too many watermarks, @_@, mismatched pupils, glowing eyes, negative space, blank page',
  },
};
const MAX_CHARACTERS = 6;
const TEXT_LIMIT = 120;
const TOKEN_LIMIT = 512;
const COLUMNS = 'ABCDE';
const DATASET_TAGS = ['fur dataset', 'background dataset'];
const COUNT = /(?<![\p{L}\p{N}])(\d+)\+?\s*(girls?|boys?|others?)(?![\p{L}])/giu;

// "Text:" as NovelAI writes it; lowercase "text:" is left alone (rating:, context:).
export function textStart(field) {
  return field.search(/(?<![\p{L}\p{N}])Text:/u);
}

export function textSection(field) {
  const index = textStart(field);
  return index === -1 ? null : field.slice(index + 5).trim();
}

export function promptPart(field) {
  const index = textStart(field);
  return index === -1 ? field : field.slice(0, index);
}

// Plain tag names: weights, brackets and :: removed, lower case.
export function tags(field) {
  return promptPart(field)
    .split(/[,\n]|\.\s/)
    .map((tag) => tag.replace(/-?\d*\.?\d+::/g, '').replace(/::/g, '').replace(/[{}[\]]/g, '').trim().toLowerCase())
    .filter(Boolean);
}

// Tags that are not pushed away by a negative weight such as -1::multiple views::.
export function positiveTags(field) {
  return tags(field.replace(/-\d*\.?\d+::[\s\S]*?::/g, ''));
}

export function gridCell(position) {
  if (position == null) return null;
  if (typeof position === 'string') return /^[A-E][1-5]$/i.test(position.trim()) ? position.trim().toUpperCase() : undefined;
  if (Array.isArray(position) && position.length === 2 && position.every((n) => typeof n === 'number' && n >= 0 && n <= 1)) {
    const index = (n) => Math.min(4, Math.max(0, Math.round((n - 0.1) / 0.2)));
    return `${COLUMNS[index(position[0])]}${index(position[1]) + 1}`;
  }
  return undefined;
}

// Rough T5 estimate: a common word is one token, a long or rare one about one
// per 6 letters; each digit run and punctuation mark is one. The UI's Context Limit bar is authoritative.
export function estimateTokens(text) {
  let total = 0;
  for (const piece of text.match(/\p{L}+|\p{N}+|[^\s\p{L}\p{N}]/gu) ?? []) total += /\p{L}/u.test(piece) ? Math.ceil(piece.length / 6) : 1;
  return total;
}

// A numeric weight holds until the next weight or a bare "::", so only the last
// one can run on to the end of the field. Returns 1 when it does.
export function unclosedWeights(field) {
  const openers = [...field.matchAll(/-?\d*\.?\d+::/g)];
  if (!openers.length) return 0;
  const last = openers.at(-1);
  return field.slice(last.index + last[0].length).includes('::') ? 0 : 1;
}

function actionTags(field) {
  return [...promptPart(field).matchAll(/(source|target|mutual)#([^,:{}[\]\n]+)/gi)].map((match) => ({ role: match[1].toLowerCase(), action: match[2].trim().toLowerCase() }));
}

function modelOf(spec, add) {
  const model = spec.model ?? '';
  if (/v\s*5|diffusion\s*5|nai5/i.test(model)) add('error', 'model', 'This is a V5 spec. V5 differs (22 characters, longer lettering); use the nai5-comic-prompt skill.');
  else if (model && !/4\.5/.test(model)) add('warn', 'model', `"${model}" is not V4.5. Negative weights, masterpiece and background dataset are V4.5-only.`);
  if (!model) add('info', 'model', 'No model given; checked as V4.5 Full.');
  return /curated/i.test(model) ? 'curated' : 'full';
}

export function checkSpec(spec) {
  const problems = [];
  const add = (level, where, message) => problems.push({ level, where, message });
  const characters = spec.characters ?? [];
  const base = spec.base ?? '';
  const negative = spec.negative ?? '';
  const settings = spec.settings ?? {};
  const model = modelOf(spec, add);
  const qualityTags = settings.qualityTags !== false;
  const presetName = String(settings.ucPreset ?? 'Heavy').toLowerCase();
  const preset = presetName === 'none' ? '' : UC_PRESETS[model][presetName];
  if (preset === undefined) add('error', 'settings', `UC preset "${settings.ucPreset}" does not exist for ${model === 'curated' ? 'Curated' : 'Full'} (${Object.keys(UC_PRESETS[model]).join(', ')}, none).`);
  const fields = [['base', base], ...characters.map((character, index) => [`character ${index + 1}`, character.prompt ?? ''])];
  const everything = fields.map(([, field]) => field).join('\n');

  if (!base.trim()) add('error', 'base', 'The base prompt is empty.');
  if (characters.length > MAX_CHARACTERS) add('error', 'characters', `${characters.length} character boxes; V4.5 allows ${MAX_CHARACTERS}.`);

  // Syntax carried over from other tools.
  for (const [where, field] of [...fields, ['negative', negative]]) {
    if (/\([^()]*:\s*-?\d+(?:\.\d+)?\s*\)/.test(field)) add('error', where, 'Stable Diffusion weights such as (tag:1.2) do nothing on NovelAI. Write 1.2::tag:: instead.');
    if (/<lora:[^>]*>/i.test(field)) add('error', where, 'NovelAI has no LoRAs; remove <lora:…> and use artist tags or Vibe Transfer.');
    if (/\\[()]/.test(field)) add('info', where, 'Brackets need no backslash on NovelAI: write mika (blue archive).');
    if (/\{\{\{|\[\[\[/.test(field)) add('info', where, 'Three or more bracket layers are only ~1.16x; a numeric weight such as 1.3::tag:: is clearer.');
    const open = unclosedWeights(field);
    if (open) add('warn', where, 'The last numeric weight is not closed with "::", so it runs on to the end of the field.');
    if (/(?<![\p{L}])top aesthetic/iu.test(field)) add('warn', where, '"top aesthetic" is the V4 tag; V4.5 calls it masterpiece.');
  }

  // Dataset tags must lead the base prompt.
  const baseTags = tags(base);
  const datasets = DATASET_TAGS.filter((tag) => baseTags.includes(tag));
  if (datasets.length > 1) add('error', 'base', 'fur dataset and background dataset cannot both be first; keep one.');
  for (const tag of datasets) if (baseTags[0] !== tag && datasets.length === 1) add('error', 'base', `"${tag}" only works as the very first tag of the base prompt.`);
  characters.forEach((character, index) => {
    if (DATASET_TAGS.some((tag) => tags(character.prompt ?? '').includes(tag))) add('error', `character ${index + 1}`, 'Dataset tags belong at the start of the base prompt, not in a character box.');
  });

  // Counts, solo and character boxes.
  const counts = [...promptPart(base).matchAll(COUNT)].reduce((sum, match) => sum + Number(match[1]), 0);
  const people = Math.max(counts, characters.length);
  if (characters.length && !counts) add('warn', 'base', `Put the people count in the base prompt (for example ${characters.length === 2 ? '"1girl, 1boy" or "2girls"' : '"2girls, 1boy"'}); character boxes start with girl/boy/other only.`);
  else if (counts && counts < characters.length) add('warn', 'base', `The base counts ${counts} people but there are ${characters.length} character boxes.`);
  if (people >= 2 && baseTags.includes('solo')) add('error', 'base', '"solo" with several people makes them merge; remove it.');
  if (characters.length && /\|/.test(base.replace(/\|\|[\s\S]*?\|\|/g, ''))) add('error', 'base', 'The "base | character" form stops working once character boxes exist; move each part into its box.');
  if (!characters.length && /\|/.test(base.replace(/\|\|[\s\S]*?\|\|/g, ''))) add('info', 'base', 'The "base | character" form works, but character boxes give each person a position and a negative.');
  characters.forEach((character, index) => {
    const where = `character ${index + 1}`;
    const prompt = character.prompt ?? '';
    const first = tags(prompt)[0] ?? '';
    if (!prompt.trim()) add('error', where, 'Empty character box.');
    else if ([...promptPart(prompt).matchAll(COUNT)].length) add('warn', where, 'Count tags (1girl, 2boys) go in the base prompt; start the box with girl, boy or other.');
    else if (!/^(girl|boy|other)\b/.test(first)) add('warn', where, `Start the box with girl, boy or other (it starts with "${first}").`);
    if (/(?<![\p{L}])(very aesthetic|masterpiece|best quality|amazing quality)(?![\p{L}])/iu.test(prompt)) add('info', where, 'Quality tags belong in the base prompt or the toggle, not in a character box.');
    if (characters.length > 1 && !(character.negative ?? '').trim()) add('info', where, "No character negative: listing the other characters' hair or outfit here reduces trait bleed.");
  });

  // Action tags.
  if (actionTags(base).length) add('warn', 'base', 'source#/target#/mutual# tags belong in the character boxes of the people acting and receiving.');
  const actions = characters.map((character) => actionTags(character.prompt ?? ''));
  actions.forEach((list, index) => {
    const others = actions.filter((_, other) => other !== index).flat();
    for (const { role, action } of list) {
      const partner = role === 'source' ? 'target' : role === 'target' ? 'source' : 'mutual';
      if (others.some((item) => item.role === partner && item.action === action)) continue;
      // A partner tag that starts with the same word (pointing / pointing at another) pairs with this one.
      const head = action.split(/\s+/)[0];
      const loose = others.filter((item) => item.role === partner && item.action.split(/\s+/)[0] === head);
      if (loose.length) add('info', `character ${index + 1}`, `${role}#${action} has a ${partner}# partner with a different word; the same word on both sides swaps less often.`);
      else add('warn', `character ${index + 1}`, `${role}#${action} has no ${partner}#${action} in another box.`);
    }
  });
  if (characters.length === 1 && actions[0]?.length) add('warn', 'character 1', 'Action tags need two character boxes.');

  // Positions.
  const manual = settings.aiChoosesPositions === false;
  const cells = characters.map((character, index) => {
    const cell = gridCell(character.position);
    if (cell === undefined) add('error', `character ${index + 1}`, 'position must be a grid cell A1–E5 (column A–E left to right, row 1–5 top to bottom) or [x, y] fractions.');
    if (manual && characters.length > 1 && !cell) add('warn', `character ${index + 1}`, "AI's Choice is off but this box has no position.");
    return cell;
  });
  if (manual && characters.length > 1) {
    const seen = cells.filter(Boolean);
    if (new Set(seen).size < seen.length) add('warn', 'positions', 'Two boxes share a grid cell; they tend to merge. Give each a different cell.');
  }
  if (characters.length === 1 && cells[0]) add('info', 'positions', 'Positions only apply with two or more character boxes.');

  // Text.
  const textFields = fields.filter(([, field]) => textSection(field) != null);
  for (const [where, field] of textFields) {
    const section = textSection(field);
    if (/::|\b(1girl|1boy|masterpiece|very aesthetic|best quality)\b/i.test(section) || (section.match(/,/g) ?? []).length >= 4) add('error', where, 'What follows "Text:" looks like prompt tags. Everything after Text: may be drawn as lettering, so Text: must come last.');
    for (const piece of section.split(/\n\s*\n/)) {
      if (piece.trim().length > TEXT_LIMIT) add('warn', where, `A text piece is ${piece.trim().length} characters; keep each under about ${TEXT_LIMIT}.`);
    }
    if (/[^\p{Script=Latin}\p{N}\p{P}\p{S}\s]/u.test(section)) add('warn', where, 'Only English lettering is promised on V4.5; Japanese or Chinese is not drawn and acts like style noise.');
    if (!promptPart(field).toLowerCase().includes(section.split(/\n/)[0].trim().toLowerCase())) add('info', where, 'Repeat the words in a sentence before Text: (She is saying "…") for more reliable lettering.');
    if (where !== 'base') add('info', where, 'Text: in a character box can work, but the base prompt is the most reliable place.');
  }
  if (textFields.length) {
    if (!baseTags.some((tag) => /(^|\s)text$/.test(tag) && tag !== 'no text')) add('warn', 'base', 'Add "text, english text" to the base prompt when the image needs lettering.');
    if (baseTags.includes('no text')) add('warn', 'base', '"no text" in the base works against the lettering; remove it if the text does not appear.');
    if (qualityTags) add('info', 'settings', 'Quality Tags adds "no text"; if short text does not appear, turn it off.');
    if (tags(`${negative}, ${preset ?? ''}`).some((tag) => ['text', 'english text', 'speech bubble'].includes(tag))) add('warn', 'negative', 'Undesired Content blocks the text or bubbles the image needs.');
  }

  // Quality tags, UC and conflicts.
  const appended = qualityTags ? QUALITY_TAGS[model] : '';
  if (qualityTags) {
    const doubled = positiveTags(QUALITY_TAGS[model]).filter((tag) => baseTags.includes(tag) && tag !== 'no text');
    if (doubled.length) add('info', 'base', `Quality Tags already appends ${doubled.join(', ')}; typing them again costs tokens.`);
  }
  if (model === 'full' && qualityTags && !baseTags.some((tag) => ['location', 'indoors', 'outdoors', 'scenery', 'simple background', 'white background'].includes(tag) || /background|room|street|park|outdoor|indoor|city|forest|beach/.test(tag))) {
    add('info', 'base', 'Users report the Full toggle no longer adds "location"; write it, or a setting, if you want a background.');
  }
  const wanted = new Set(fields.flatMap(([, field]) => positiveTags(field)));
  const negativeTags = tags(`${negative}, ${preset ?? ''}`);
  const clashes = [...new Set(negativeTags.filter((tag) => wanted.has(tag)))];
  if (clashes.length) add('warn', 'negative', `In both the prompt and Undesired Content${preset ? ' (with the preset)' : ''}: ${clashes.join(', ')}.`);
  if (presetName !== 'none' && negative && tags(negative).length >= 8) add('info', 'negative', 'A long own UC on top of a preset stacks both; consider preset None.');

  // Model rules.
  if (model === 'curated' && /(?<![\p{L}])(nsfw|rating:(explicit|questionable|sensitive))(?![\p{L}])/iu.test(everything)) add('error', 'model', 'Curated cannot make adult content; use Full.');

  // Tokens.
  const promptTokens = estimateTokens(everything + appended);
  const negativeTokens = estimateTokens([negative, preset ?? '', ...characters.map((character) => character.negative ?? '')].join(', '));
  if (promptTokens > TOKEN_LIMIT * 0.9) add('warn', 'tokens', `Roughly ${promptTokens} tokens including Quality Tags (limit ~${TOKEN_LIMIT}); past the limit the tail, often the artist string or text, is dropped.`);

  // Settings.
  const [width, height] = spec.size ?? [];
  if (width && height) {
    if (width % 64 || height % 64) add('warn', 'size', 'Width and height should be multiples of 64.');
    if (width * height > 1024 * 1024) add('info', 'size', 'Larger than the normal sizes, so it costs Anlas even on Opus.');
  }
  if (settings.steps > 28) add('info', 'settings', 'Over 28 steps costs Anlas on Opus; 28 is the usual value.');
  if (settings.scale > 7) add('warn', 'settings', `Prompt Guidance ${settings.scale} is high for V4.5 (docs 5–6; Full users report artifacts at 7).`);
  if (settings.sampler && !/euler_ancestral|euler a|dpmpp_2m|dpm\+\+ 2m/i.test(settings.sampler)) add('info', 'settings', 'Euler Ancestral and DPM++ 2M are the recommended samplers.');

  return { problems, model, promptTokens, negativeTokens, appended, preset: preset ?? '', cells };
}

export function blocks(spec, result = checkSpec(spec)) {
  const lines = [`[Base Prompt]${result.appended ? `  (+ Quality Tags appends "${result.appended.slice(2)}")` : ''}\n${spec.base}`];
  (spec.characters ?? []).forEach((character, index) => {
    const cell = result.cells[index];
    lines.push(`[Character ${index + 1}]${cell ? `  (position ${cell})` : ''}\n${character.prompt}`);
    if (character.negative) lines.push(`[Character ${index + 1} Undesired Content]\n${character.negative}`);
  });
  const preset = spec.settings?.ucPreset ?? 'Heavy';
  lines.push(`[Undesired Content]  (preset: ${preset})\n${spec.negative ?? ''}`);
  return lines.join('\n\n');
}

if (process.argv[1]?.endsWith('check-prompt.mjs')) {
  const { values, positionals } = parseArgs({ options: { json: { type: 'boolean', default: false }, help: { type: 'boolean', short: 'h', default: false } }, allowPositionals: true });
  if (values.help || positionals.length !== 1) {
    console.log(USAGE);
    process.exit(values.help ? 0 : 2);
  }
  const spec = JSON.parse(fs.readFileSync(positionals[0], 'utf8'));
  const result = checkSpec(spec);
  if (values.json) {
    console.log(JSON.stringify(result, null, 2));
  } else {
    for (const problem of result.problems) console.log(`${problem.level.toUpperCase().padEnd(5)} ${problem.where}: ${problem.message}`);
    const s = spec.settings ?? {};
    console.log(`\n${result.model === 'curated' ? 'V4.5 Curated' : 'V4.5 Full'} | ${spec.size?.join('x') ?? 'size ?'} | ~${result.promptTokens}/${TOKEN_LIMIT} prompt tokens (rough) | UC ~${result.negativeTokens} | ${s.aiChoosesPositions === false ? 'manual positions' : "AI's Choice"}\n`);
    console.log(blocks(spec, result));
  }
  process.exitCode = result.problems.some((problem) => problem.level === 'error') ? 1 : 0;
}
