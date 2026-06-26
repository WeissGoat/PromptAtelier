# Action Selected Keys Business Test 2026-06-26

## Case

- composer: `script`
- backend: `novelai`
- artist: `20260412`
- model: `nai-diffusion-4-5-full`
- action: `F:/my_project/new/tags_machine/design/动作改2/new/20260506_3P后入趴卧`
- characters:
  - `danbooru_akemi_homura_暁美ほむら _魔法少女`
  - `danbooru_kaname_madoka_鹿目まどか_魔法少女`
  - `ultimate_madoka`

## Outputs

- image: `F:/my_project/new/tags_machine/refactor/outputs/action_selected_keys_business_20260626/2fb05bcf_0_01.png`
- executor status: `succeeded`

## PromptBundle Check

- character_selection source: `run-prompt-prompt.md`
- character 0 used_sections: `character`, `copyright`, `hair`
- character 1 used_sections: `character`, `copyright`, `hair`
- character 2 used_sections: `character`, `copyright`, `hair`
- AgentComposer involved: no

## PNG Parameter Check

- PNG params readable: yes
- selected_keys applied: yes
- action tags present: yes
- artist params present: yes
- model: `nai-diffusion-4-5-full`
- sampler: `k_euler_ancestral`
- steps: `28`
- scale: `5.0`
- seed: `3394452476`
- size: `1024x1024`
- reference_image_multiple present: yes

## Final PNG Prompt Evidence

The PNG prompt contains the selected character sections:

```text
akemi_homura, mahou_shoujo_madoka_magica, black_hair, kaname_madoka, mahou_shoujo_madoka_magica, pink_hair, ultimate_madoka, mahou_shoujo_madoka_magica:_hangyaku_no_monogatari, pink_hair, two_side_up
```

The PNG prompt also contains action tags from the action node:

```text
hetero, multiple girls, nude, 1boy, cum, cum on ass, completely nude, 3girls, sex, after sex, ass, lying, closed eyes, sex from behind, breasts, indoors, open mouth, on stomach, cumdrip, sweat, on side, cum in pussy, doggystyle, barefoot, smile, blush, cum in ass, harem, after vaginal, cum on body, prone bone, nipples, on bed, penis, back
```

Excluded character sections such as `eyes`, `upper_clothes`, `lower_clothes`, `feet`, and `weapons` were not included from the character nodes.

## Visual Check

- image generated: yes
- manual visual review: pending user review
