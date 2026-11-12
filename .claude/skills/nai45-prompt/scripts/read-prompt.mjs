#!/usr/bin/env node
// Prints the prompt structure stored in NovelAI V4/V4.5 PNGs: base prompt,
// character boxes with grid cells, negatives and settings, ready to copy or to
// turn into a spec for check-prompt.mjs.
import fs from 'node:fs';
import path from 'node:path';
import { inflateSync } from 'node:zlib';
import { parseArgs } from 'node:util';

import { gridCell } from './check-prompt.mjs';

const USAGE = `Usage: node scripts/read-prompt.mjs <image.png|dir> ... [--json] [--spec]

  --json   one JSON record per image instead of text
  --spec   print a check-prompt.mjs spec for the (first) image
Reads PNG text chunks only. Images re-encoded by Telegram photos, Twitter or
screenshots have lost their metadata; NovelAI's pixel-hidden copy is not read.`;

export function pngText(buffer) {
  const text = {};
  if (!buffer.subarray(0, 8).equals(Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]))) return null;
  for (let offset = 8; offset + 12 <= buffer.length;) {
    const length = buffer.readUInt32BE(offset);
    const type = buffer.toString('latin1', offset + 4, offset + 8);
    const data = buffer.subarray(offset + 8, offset + 8 + length);
    if (type === 'IEND' || offset + 8 + length > buffer.length) break;
    const nul = data.indexOf(0);
    if (nul > 0 && type === 'tEXt') text[data.toString('latin1', 0, nul)] = data.subarray(nul + 1).toString('utf8');
    if (nul > 0 && type === 'zTXt') text[data.toString('latin1', 0, nul)] = inflateSync(data.subarray(nul + 2)).toString('utf8');
    if (nul > 0 && type === 'iTXt') {
      const compressed = data[nul + 1] === 1;
      let rest = data.subarray(nul + 3);
      rest = rest.subarray(rest.indexOf(0) + 1);
      rest = rest.subarray(rest.indexOf(0) + 1);
      text[data.toString('latin1', 0, nul)] = (compressed ? inflateSync(rest) : rest).toString('utf8');
    }
    offset += 12 + length;
  }
  return text;
}

export function describe(file, buffer = fs.readFileSync(file)) {
  const text = pngText(buffer);
  if (!text) return { file, error: 'not a PNG' };
  let comment = null;
  try {
    comment = JSON.parse(text.Comment ?? 'null');
  } catch {}
  if (!comment) return { file, error: 'no NovelAI Comment metadata' };
  const negatives = comment.v4_negative_prompt?.caption?.char_captions ?? [];
  const useCoords = comment.v4_prompt?.use_coords ?? false;
  return {
    file,
    model: (text.Source ?? comment.model_name ?? '').trim() || null,
    size: [comment.width, comment.height],
    base: comment.v4_prompt?.caption?.base_caption ?? comment.prompt ?? '',
    characters: (comment.v4_prompt?.caption?.char_captions ?? []).map((character, index) => ({
      prompt: character.char_caption ?? '',
      negative: negatives[index]?.char_caption ?? '',
      position: useCoords && character.centers?.[0] ? gridCell([character.centers[0].x, character.centers[0].y]) ?? null : null,
    })),
    negative: comment.v4_negative_prompt?.caption?.base_caption ?? comment.uc ?? '',
    settings: {
      steps: comment.steps,
      scale: comment.scale,
      cfgRescale: comment.cfg_rescale,
      sampler: comment.sampler,
      noiseSchedule: comment.noise_schedule,
      seed: comment.seed,
      aiChoosesPositions: !useCoords,
    },
  };
}

// The Quality Tags toggle appends one of these at the end of the base prompt.
// Full images show it with and without "location" (see references/syntax.md).
const QUALITY_SUFFIXES = [
  { model: 'curated', pattern: /,\s*(?:location, )?masterpiece, no text, -0\.8::feet::, rating:general\s*$/ },
  { model: 'full', pattern: /,\s*(?:location, )?very aesthetic, masterpiece, no text\s*$/ },
];

// What the user typed: the base without the toggle's suffix. A suffix the user
// typed by hand looks the same, so qualityTags is a best guess.
export function typedSpec(record) {
  const { file, ...spec } = record;
  const match = QUALITY_SUFFIXES.find(({ pattern }) => pattern.test(spec.base));
  const base = match ? spec.base.replace(match.pattern, '') : spec.base;
  const model = match && /4\.5/.test(spec.model ?? '') ? `V4.5 ${match.model === 'curated' ? 'Curated' : 'Full'}` : spec.model;
  // The UC preset is not stored by name; the full negative is kept as typed text.
  return { ...spec, model, base, settings: { ...spec.settings, qualityTags: Boolean(match), ucPreset: 'None' } };
}

if (process.argv[1]?.endsWith('read-prompt.mjs')) {
  const { values, positionals } = parseArgs({
    options: { json: { type: 'boolean', default: false }, spec: { type: 'boolean', default: false }, help: { type: 'boolean', short: 'h', default: false } },
    allowPositionals: true,
  });
  if (values.help || !positionals.length) {
    console.log(USAGE);
    process.exit(values.help ? 0 : 2);
  }

  const files = positionals.flatMap((input) => (fs.statSync(input).isDirectory()
    ? fs.readdirSync(input).filter((name) => /\.png$/i.test(name)).map((name) => path.join(input, name))
    : [input]));
  const records = files.map((file) => describe(file));

  if (values.spec) {
    const record = records.find((item) => !item.error);
    if (!record) throw new Error('No readable NovelAI image');
    console.log(JSON.stringify({ source: path.basename(record.file), ...typedSpec(record) }, null, 2));
  } else if (values.json) {
    for (const record of records) console.log(JSON.stringify(record));
  } else {
    for (const record of records) {
      console.log(`=== ${path.basename(record.file)}`);
      if (record.error) {
        console.log(`(${record.error})\n`);
        continue;
      }
      const s = record.settings;
      console.log(`${record.model} | ${record.size.join('x')} | steps ${s.steps} | scale ${s.scale} | rescale ${s.cfgRescale} | ${s.sampler} ${s.noiseSchedule} | seed ${s.seed} | ${s.aiChoosesPositions ? "AI's Choice" : 'manual positions'}`);
      console.log(`\n[Base]\n${record.base}`);
      record.characters.forEach((character, index) => {
        console.log(`\n[Character ${index + 1}${character.position ? ` @ ${character.position}` : ''}]\n${character.prompt}`);
        if (character.negative) console.log(`[Character ${index + 1} negative]\n${character.negative}`);
      });
      console.log(`\n[Undesired Content]\n${record.negative}\n`);
    }
  }
}
