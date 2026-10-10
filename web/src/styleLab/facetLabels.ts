/** 动作 classify.yaml 分面的中文名；没收录的值原样显示。 */

export const PRIMARY_FACETS = ["cast", "domain", "pose", "clothing"] as const;
export const MORE_FACETS = ["subtype", "environment", "tone", "flags", "phase"] as const;

export const FACET_FIELD_LABELS: Record<string, string> = {
  cast: "人数",
  domain: "类型",
  subtype: "细分",
  pose: "姿势",
  environment: "场景",
  clothing: "服装",
  tone: "氛围",
  flags: "元素",
  phase: "阶段",
};

const VALUE_LABELS: Record<string, Record<string, string>> = {
  cast: {
    solo: "单人",
    "1boy1girl": "一男一女",
    "1boy2girls": "一男二女",
    "1boy3girls": "一男三女",
    "2girls": "二女",
    "3girls": "三女",
    multi_boys1girl: "多男一女",
    multi_boys2girls: "多男二女",
    multi_boys3girls: "多男三女",
    multi_boys_multi_girls: "多男多女",
  },
  domain: {
    sex: "性爱",
    body: "身体",
    mouth: "嘴",
    crotch: "下体",
    breast: "胸",
    foot: "足",
    sfw: "全年龄",
    yuri: "百合",
  },
  subtype: {
    penetration: "插入",
    group_sex: "群交",
    cum: "射精",
    display: "展示",
    oral: "口交",
    crotch_focus: "下体特写",
    doggystyle: "后入",
    missionary: "传教士",
    kiss: "接吻",
    spread: "张开",
    touching: "触摸",
    cowgirl: "女上",
    ass_focus: "臀部特写",
    barefoot: "赤足",
    breast_focus: "胸部特写",
    breast_touch: "摸胸",
    footjob: "足交",
    foot_focus: "足部特写",
    sole_focus: "足底特写",
    foot_interaction: "足部互动",
    undressing: "脱衣",
    portrait: "肖像",
    upper_body: "上半身",
    full_body: "全身",
    tribadism: "磨镜",
    yuri_kiss: "百合接吻",
    yuri_touch: "百合触摸",
    mouth_focus: "嘴部特写",
  },
  pose: {
    lying: "躺",
    sitting: "坐",
    standing: "站",
    all_fours: "趴跪",
    kneeling: "跪",
    side_lying: "侧躺",
    bent_over: "弯腰",
    suspended: "悬空",
    against_wall: "靠墙",
    lap_sitting: "坐腿上",
    inverted: "倒立",
  },
  environment: {
    indoor: "室内",
    bed: "床",
    outdoor: "室外",
    floor: "地板",
    sofa: "沙发",
    bathroom: "浴室",
    water: "水中",
    table: "桌子",
    vehicle: "车内",
    classroom: "教室",
    wall: "墙边",
  },
  clothing: { nude: "裸体", clothed: "穿衣", specific_outfit: "特定服装" },
  tone: { normal: "普通", forced: "强迫", affectionate: "亲密" },
  flags: {
    bondage: "捆绑",
    restraint: "束缚",
    recording: "拍摄",
    sleep: "睡眠",
    ntr: "NTR",
    hypnosis: "催眠",
    voyeur: "偷窥",
  },
  phase: { start: "开始", pre: "前戏", core: "正戏", climax: "高潮", post: "事后" },
};

export function facetValueLabel(field: string, value: string): string {
  return VALUE_LABELS[field]?.[value] ?? value;
}

/** 动作卡片上的一行分面摘要：人数 · 姿势 · 服装。 */
export function facetSummary(facets: Record<string, string[]>): string {
  return (["cast", "pose", "clothing"] as const)
    .flatMap((field) => (facets[field] ?? []).map((value) => facetValueLabel(field, value)))
    .join(" · ");
}
