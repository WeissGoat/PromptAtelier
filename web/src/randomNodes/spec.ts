import type { ClassifyFilter, NodePoolSpec } from "../workspace/types";

export const CLASSIFY_FIELDS: Array<keyof ClassifyFilter> = [
  "phase",
  "species",
  "cast",
  "domain",
  "subtype",
  "pose",
  "environment",
  "tone",
  "flags",
  "clothing",
];

export const CLASSIFY_OPTIONS: Record<keyof ClassifyFilter, string[]> = {
  phase: ["start", "pre", "core", "climax", "post"],
  species: ["human", "human_xeno", "human_tentacle"],
  cast: ["solo", "1boy1girl", "1boy2girls", "1boy3girls", "2girls", "3girls", "multi_boys1girl", "multi_boys2girls", "multi_boys3girls", "multi_boys_multi_girls"],
  domain: ["sex", "body", "foot", "mouth", "breast", "crotch", "yuri", "sfw"],
  subtype: ["penetration", "anal", "double_penetration", "group_sex", "masturbation", "missionary", "cowgirl", "doggystyle", "cum", "display", "closeup", "undressing", "touching", "footjob", "barefoot", "sole_focus", "foot_focus", "foot_interaction", "kiss", "oral", "mouth_focus", "breast_touch", "breast_focus", "paizuri", "crotch_focus", "ass_focus", "spread", "yuri_kiss", "yuri_touch", "tribadism", "portrait", "face_focus", "upper_body", "full_body"],
  pose: ["standing", "lying", "sitting", "kneeling", "all_fours", "side_lying", "lap_sitting", "against_wall", "suspended", "inverted", "bent_over"],
  environment: ["bed", "floor", "table", "sofa", "wall", "bathroom", "classroom", "vehicle", "outdoor", "water", "indoor"],
  tone: ["normal", "affectionate", "forced"],
  flags: ["bondage", "restraint", "hypnosis", "sleep", "voyeur", "recording", "ntr"],
  clothing: ["clothed", "nude", "specific_outfit"],
};

export function createEmptyClassifyFilter(): ClassifyFilter {
  return {
    phase: [],
    species: [],
    cast: [],
    domain: [],
    subtype: [],
    pose: [],
    environment: [],
    tone: [],
    flags: [],
    clothing: [],
  };
}

export function createDefaultNodePoolSpec(): NodePoolSpec {
  return {
    source: {
      type: "folder",
      value: "",
      recursive: false,
      include_names: [],
      exclude_names: [],
    },
    filters: { classify: createEmptyClassifyFilter() },
  };
}
