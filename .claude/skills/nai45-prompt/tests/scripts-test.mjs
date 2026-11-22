import test from 'node:test';
import assert from 'node:assert/strict';

import { checkSpec, estimateTokens, gridCell, positiveTags, tags, textSection, unclosedWeights } from '../scripts/check-prompt.mjs';
import { describe, typedSpec } from '../scripts/read-prompt.mjs';

const messages = (result, level) => result.problems.filter((problem) => !level || problem.level === level).map((problem) => problem.message);
const has = (result, level, pattern) => messages(result, level).some((message) => pattern.test(message));

function chunk(type, data) {
  const length = Buffer.alloc(4);
  length.writeUInt32BE(data.length);
  return Buffer.concat([length, Buffer.from(type, 'latin1'), data, Buffer.alloc(4)]);
}

function novelAiPng(comment, source = 'NovelAI Diffusion V4.5 4BDE2A90') {
  const header = Buffer.alloc(13);
  header.writeUInt32BE(832, 0);
  header.writeUInt32BE(1216, 4);
  const text = (key, value) => chunk('tEXt', Buffer.from(`${key}\0${value}`, 'utf8'));
  return Buffer.concat([Buffer.from([0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a]), chunk('IHDR', header),
    text('Software', 'NovelAI'), text('Source', source), text('Comment', JSON.stringify(comment)), chunk('IEND', Buffer.alloc(0))]);
}

test('helpers parse tags, weights, grid cells and text', () => {
  assert.deepEqual(tags('1.2::artist:a::, {{red hair}}, -1::hat ::. She smiles. Text: Hi'), ['artist:a', 'red hair', 'hat', 'she smiles']);
  assert.deepEqual(positiveTags('red hair, -1::multiple views, hat::, smile'), ['red hair', 'smile']);
  assert.equal(unclosedWeights('1.2::a::, 0.8::b, c'), 1);
  assert.equal(unclosedWeights('1.5::rain, night ::, -1::hat::, {{{{rain ::'), 0);
  assert.equal(unclosedWeights('1.2::a, 0.8::b ::, c'), 0);
  assert.equal(gridCell('c3'), 'C3');
  assert.equal(gridCell([0.1, 0.9]), 'A5');
  assert.equal(gridCell([0.7, 0.5]), 'D3');
  assert.equal(gridCell('F1'), undefined);
  assert.equal(textSection('english text. She says "Hi". Text: Hi'), 'Hi');
  assert.equal(textSection('rating:general, context: none'), null);
  assert.ok(estimateTokens('1girl, solo, very aesthetic') > 5);
});

test('a well-formed two-character spec has no errors or warnings', () => {
  const result = checkSpec({
    model: 'V4.5 Full',
    size: [832, 1216],
    base: '2girls, 1.1::artist:example::, -3::artist collaboration::, year 2024, cowboy shot, location, park. The red-haired girl hugs the blue-haired girl.',
    characters: [
      { prompt: 'girl, red hair, green eyes, school uniform, source#hug, smile', negative: 'blue hair', position: 'B3' },
      { prompt: 'girl, blue hair, hoodie, target#hug, surprised', negative: 'red hair', position: 'D3' },
    ],
    negative: '',
    settings: { qualityTags: true, ucPreset: 'Heavy', aiChoosesPositions: false, steps: 28, scale: 5, cfgRescale: 0.2, sampler: 'k_euler_ancestral' },
  });
  assert.deepEqual(messages(result, 'error'), []);
  assert.deepEqual(messages(result, 'warn'), []);
  assert.deepEqual(result.cells, ['B3', 'D3']);
});

test('syntax from other tools is reported', () => {
  const result = checkSpec({ base: 'masterpiece, (1girl:1.2), <lora:style:0.8>, mika \\(blue archive\\), {{{smile}}}, top aesthetic, 1.3::red hair', characters: [] });
  assert.ok(has(result, 'error', /\(tag:1\.2\)/));
  assert.ok(has(result, 'error', /LoRA/));
  assert.ok(has(result, 'info', /backslash/));
  assert.ok(has(result, 'info', /bracket layers/));
  assert.ok(has(result, 'warn', /top aesthetic/));
  assert.ok(has(result, 'warn', /not closed/));
});

test('counts, solo, dataset tags, boxes and pipes are checked', () => {
  const result = checkSpec({
    base: 'solo, background dataset, 1girl, landscape | girl, red hair',
    characters: [{ prompt: '1girl, red hair' }, { prompt: 'red hair, boy' }, { prompt: 'girl, fur dataset' }],
  });
  assert.ok(has(result, 'error', /very first tag/));
  assert.ok(has(result, 'error', /"solo"/));
  assert.ok(has(result, 'error', /base \| character/));
  assert.ok(has(result, 'error', /not in a character box/));
  assert.ok(has(result, 'warn', /counts 1 people but there are 3/));
  assert.ok(has(result, 'warn', /Count tags/));
  assert.ok(has(result, 'warn', /Start the box with girl/));
  assert.ok(checkSpec({ base: '||a|b||, 1girl', characters: [{ prompt: 'girl' }] }).problems.every((problem) => !/base \| character/.test(problem.message)));
});

test('action tags and positions are paired', () => {
  const result = checkSpec({
    base: '1girl, 1boy, source#hug',
    characters: [
      { prompt: 'girl, source#punching, source#pointing at another', position: 'C3' },
      { prompt: 'boy, target#pointing', position: 'C3' },
    ],
    settings: { aiChoosesPositions: false },
  });
  assert.ok(has(result, 'warn', /belong in the character boxes/));
  assert.ok(has(result, 'warn', /source#punching has no target#punching/));
  assert.ok(has(result, 'info', /different word/));
  assert.ok(has(result, 'warn', /share a grid cell/));
});

test('lettering rules: Text: last, length, script, blocked by UC', () => {
  const tagsAfter = checkSpec({ base: '1girl, english text. Text: Hello, masterpiece, very aesthetic', characters: [] });
  assert.ok(has(tagsAfter, 'error', /Text: must come last/));
  const blocked = checkSpec({ base: '1girl, no text. She says "こんにちは". Text: こんにちは', characters: [], negative: 'text' });
  assert.ok(has(blocked, 'warn', /text, english text/));
  assert.ok(has(blocked, 'warn', /"no text"/));
  assert.ok(has(blocked, 'warn', /Only English/));
  assert.ok(has(blocked, 'warn', /blocks the text/));
  const long = checkSpec({ base: `1girl, text, english text. Text: ${'a'.repeat(130)}`, characters: [] });
  assert.ok(has(long, 'warn', /130 characters/));
  assert.ok(has(long, 'info', /Repeat the words/));
});

test('model, preset, conflicts, tokens and settings', () => {
  assert.ok(has(checkSpec({ model: 'V4.5 Curated', base: '1girl, nsfw', characters: [] }), 'error', /Curated cannot/));
  assert.ok(has(checkSpec({ model: 'V5 Full', base: '1girl', characters: [] }), 'error', /nai5-comic-prompt/));
  assert.ok(has(checkSpec({ model: 'V4.5 Curated', base: '1girl', characters: [], settings: { ucPreset: 'Furry Focus' } }), 'error', /does not exist/));
  const clash = checkSpec({ base: '1girl, chromatic aberration, -1::multiple views::', characters: [], settings: { ucPreset: 'Heavy' } });
  assert.ok(has(clash, 'warn', /chromatic aberration/));
  assert.ok(!has(clash, 'warn', /multiple views/));
  assert.ok(has(checkSpec({ base: '1girl, very aesthetic, masterpiece', characters: [] }), 'info', /already appends very aesthetic, masterpiece/));
  assert.ok(has(checkSpec({ base: Array.from({ length: 200 }, (_, i) => `tag number ${i}`).join(', '), characters: [] }), 'warn', /Roughly \d+ tokens/));
  const settings = checkSpec({ base: '1girl, location', characters: [], size: [830, 1216], settings: { steps: 40, scale: 8, sampler: 'ddim' } });
  assert.ok(has(settings, 'warn', /multiples of 64/));
  assert.ok(has(settings, 'info', /28 steps/));
  assert.ok(has(settings, 'warn', /Prompt Guidance 8/));
  assert.ok(has(settings, 'info', /recommended samplers/));
});

test('read-prompt turns a V4.5 PNG into a spec without the quality suffix', () => {
  const comment = {
    width: 832, height: 1216, steps: 28, scale: 5, cfg_rescale: 0.2, sampler: 'k_euler_ancestral', noise_schedule: 'karras', seed: 1,
    prompt: 'flat',
    v4_prompt: { use_coords: true, caption: { base_caption: '2girls, park, location, very aesthetic, masterpiece, no text', char_captions: [
      { char_caption: 'girl, red hair, source#hug', centers: [{ x: 0.3, y: 0.5 }] },
      { char_caption: 'girl, blue hair, target#hug', centers: [{ x: 0.7, y: 0.5 }] },
    ] } },
    v4_negative_prompt: { caption: { base_caption: 'lowres', char_captions: [{ char_caption: 'blue hair' }, { char_caption: 'red hair' }] } },
  };
  const record = describe('x.png', novelAiPng(comment));
  assert.deepEqual(record.characters.map((character) => character.position), ['B3', 'D3']);
  const spec = typedSpec(record);
  assert.equal(spec.base, '2girls, park');
  assert.equal(spec.model, 'V4.5 Full');
  assert.equal(spec.settings.qualityTags, true);
  assert.equal(spec.settings.aiChoosesPositions, false);
  assert.deepEqual(messages(checkSpec(spec), 'error'), []);

  const curated = typedSpec(describe('y.png', novelAiPng({ ...comment, v4_prompt: { use_coords: false, caption: { base_caption: '1girl, masterpiece, no text, -0.8::feet::, rating:general', char_captions: [] } } })));
  assert.equal(curated.model, 'V4.5 Curated');
  assert.equal(curated.base, '1girl');
  assert.equal(describe('z.png', Buffer.from('not a png')).error, 'not a PNG');
});
