from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
import os
from pathlib import Path
import re
import shutil
from typing import Any

import yaml

try:
    from .migration import (
        _collect_legacy_negative_prompt,
        _resolve_tags_path,
        _split_legacy_prompt_tags,
        _split_legacy_tags_lines,
    )
except ImportError:
    from migration import (
        _collect_legacy_negative_prompt,
        _resolve_tags_path,
        _split_legacy_prompt_tags,
        _split_legacy_tags_lines,
    )

# ---------------------------------------------------------------------------
# 0. 明确元标签与情趣玩具预过滤黑名单 (Pre-Filter Drop: Avoid False Match in Props)
# ---------------------------------------------------------------------------

PRE_FILTER_PATTERNS = [
    re.compile(r".*\b(screenshot|screencap|fake screenshot|cellphone photo|fake phone screenshot)\b.*"),
    re.compile(r".*\b(hitachi magic wand|sex toy)\b.*"),
]

# ---------------------------------------------------------------------------
# 1. 动作与服装交互黑名单 (Clothing Actions / Manipulations to Drop)
# ---------------------------------------------------------------------------

CLOTHING_ACTION_PATTERNS = [
    re.compile(r".*\b(lift|pull|aside|pulling|lifting|strip|stripping|undress|undressing|tear|tearing|unbutton|unbuttoned|unzip|unzipped|slip|slipping|flashing|adjusting|removing)\b.*"),
    re.compile(r"^(open|torn)\s+(clothes|shirt|jacket|coat|dress|blouse|sweater|vest|bra|panties|skirt)$"),
    re.compile(r".*\bclothed\s+.*nude\b.*"),
    re.compile(r"^no\s+(panties|bra|shoes|socks|sleeves)$"),
    re.compile(r".*\bpantie?s?\s+around\s+.*"),
    re.compile(r".*\b(cum\s+(on|in)|filled\s+with|cream\s+in|unworn|holding\s+(clothes|skirt|shirt|dress|panties|bra|hem|collar|hands?|person|another)|under\s+clothes|over\s+clothes)\b.*"),
    re.compile(r".*\b(upskirt|downblouse|wardrobe malfunction|wedgie|panty peek|open fly|shoe dangle|upshirt|curtain grab|neckwear grab)\b.*"),
    re.compile(r".*\b(partially undressed|dressing|undressing|smelling sleeve|smelling clothes|smelling panties|removed|pulled\s+open|unfastened)\b.*"),
    re.compile(r"^visible\s+pant(y|ies)$"),
    re.compile(r"^脱衣$"),
]

# ---------------------------------------------------------------------------
# 2. 裸露与无服装状态标签 (全裸与私处暴露/遮挡状态 - 局部身体裸露如露肩/露背/露腹/露腿/赤脚已归入服饰设计属性)
# ---------------------------------------------------------------------------

NUDITY_AND_ABSENCE = {
    "nude", "completely nude", "naked", "bottomless", "topless", "breasts out",
    "one breast out", "covered nipples", "no bra", "no panties", "nude male",
    "nude female", "nude man", "partially unclothed", "hanging breasts",
    "covered navel", "covered eyes", "covering face", "covering own eyes",
    "covering privates", "covering crotch", "covering breasts", "covering genitals",
    "covering vagina", "covering ass", "covering nipples", "tanlines", "tan lines",
    "ass visible", "exposed breasts", "exposed ass", "naked towel", "nude towelette",
    "ass visible through thighs", "skindentation",
}

# ---------------------------------------------------------------------------
# 3. 通用杂词黑名单 (Drop Tags & Patterns)
# ---------------------------------------------------------------------------

EXACT_DROP_TAGS = {
    # 单字符/符号残余
    "d", "o", "v", "3", "x", "p", "c", "?", "!", "+", "-", "@",

    # 人数与角色主体
    "1girl", "2girls", "3girls", "4girls", "5girls", "multiple girls", "1 girl",
    "1boy", "2boys", "3boys", "multiple boys", "1 boy", "2 boys",
    "1other", "2others", "multiple others", "solo", "duo", "group", "crowd",
    "nobody", "monochrome", "greyscale", "loli", "shota", "faceless male",
    "faceless", "dark-skinned male", "fat man", "fat", "ugly man", "goblin",
    "aged down", "age difference", "pedophile", "crossdresser", "femboy",
    "monster", "animal", "creature", "demon", "angel", "elf", "dark elf",
    "bald", "bald man", "old man", "old", "sisters", "siblings", "twins",
    "virtual youtuber", "boy in front of girl", "girl in front of boy",
    "2 boys in front of her", "crossdressing", "gender bender", "slave",

    # 画质与元标签
    "masterpiece", "best quality", "amazing quality", "highres", "absurdres",
    "very aesthetic", "aesthetic", "low quality", "worst quality", "lowres",
    "jpeg artifacts", "bad quality", "normal quality", "unfinished", "displeasing",
    "error", "bad anatomy", "bad hands", "bad feet", "bad eyes", "bad face",
    "extra fingers", "extra digits", "extra limbs", "missing limbs", "mutation",
    "scan", "abstract", "watermark", "signature", "username", "artist name",
    "weibo username", "weibo_username", "patreon username", "twitter username",
    "comic", "manga", "sample", "logo", "copyright", "dated", "year 2023",
    "year 2024", "year 2022", "year 2021", "no text", "text", "speech bubble",
    "sound effects", "motion lines", "motion blur", "timestamp", "fake screenshot",
    "heads-up display", "heart", "spoken heart", "sparkles", "glowing", "glow",
    "viewfinder", "take your pick", "scene", "recording", "screencap",
    "cinematic lighting", "perfect anatomy", "highly detailed", "reflection",
    "light particles", "sfw", "selfie", "battery indicator", "mirror",
    "lens flare", "blurry foreground", "sharpened", "wallpaper", "curated",
    "volumetric lighting", "retouched", "smooth lines", "excellent color",
    "incredibly absurdres", "fine art parody", "parody", "ray tracing",
    "x-ray", "wlop", "chiaroscuro", "anime coloring", "official art",
    "english text", "ultra-detailed", "beautiful detailed glow", "text messaging",

    # 审查标签
    "censored", "censor", "bar censor", "censor bar", "mosaic", "mosaic censoring",
    "character censor", "novelty censor", "light censor", "convenient censoring",
    "leafa", "nsfw", "uncensored",

    # 镜头、构图与视角
    "close-up", "close up", "portrait", "cowboy shot", "full body", "upper body",
    "lower body", "wide shot", "dutch angle", "dynamic angle", "from above",
    "from below", "from behind", "from side", "profile", "back", "pov",
    "first-person view", "facing viewer", "facing away", "looking at viewer",
    "looking away", "looking back", "looking down", "looking up",
    "looking to the side", "looking at another", "looking at partner",
    "looking ahead", "looking at mirror", "depth of field", "blurry",
    "blurry background", "bokeh", "focus", "solo focus", "cropped",
    "out of frame", "head out of frame", "foot out of frame", "feet out of frame",
    "pov hands", "pov crotch", "female pov", "straight-on", "close to viewer",
    "multiple views", "split screen", "foreshortening", "backlighting",
    "downblouse", "midriff peek", "cross-section", "top-down bottom-up",
    "pantyshot", "eye contact", "sideways glance", "upside-down", "split",

    # 身体特征与解剖
    "breasts", "small breasts", "medium breasts", "large breasts", "huge breasts",
    "gigantic breasts", "flat chest", "cleavage", "navel", "collarbone",
    "ass", "butt", "buttocks", "hips", "wide hips", "thighs", "thick thighs",
    "thigh gap", "slender thighs", "groin", "pubic hair", "female pubic hair",
    "male pubic hair", "pussy", "spread pussy", "clitoris", "penis",
    "large penis", "huge penis", "erection", "veiny penis", "testicles",
    "scrotum", "anus", "puckered anus", "cleft of venus", "muscular", "abs",
    "skin", "shiny skin", "pale skin", "dark skin", "tan", "tanned", "sweat",
    "sweaty", "steaming body", "steam", "oily skin", "oiled", "wet",
    "wet body", "wet skin", "nipples", "nipple", "areola", "mole", "freckles",
    "scar", "injury", "blood", "cuts", "bruise", "veins", "teeth", "tongue",
    "toes", "toenails", "tiptoes", "feet", "good feet", "soles", "soles detailed",
    "legs", "armpits", "stomach", "stomach bulge", "midriff", "narrow waist",
    "nail polish", "toenail polish", "underboob", "sideboob", "belly",
    "clenched teeth", "upper teeth only", "forehead", "slap mark", "cameltoe",
    "kneepits", "skinny", "tattoo", "human skin", "humid skin", "glossy skin",
    "extreme detailed skin", "wrinkled skin", "shiny", "spread ass", "bulge",
    "cat paws", "rabbit ears", "pointy ears", "animal ear fluff", "animal hands",
    "brain", "flying brain", "oversized brain",

    # 发型、面部特征与表情
    "hair", "short hair", "long hair", "medium hair", "very long hair", "wet hair",
    "ponytail", "twintails", "side ponytail", "braid", "twin braids",
    "messy hair", "bangs", "blunt bangs", "parted bangs", "sidelocks",
    "ahoge", "hair between eyes", "eyes", "blue eyes", "red eyes", "green eyes",
    "brown eyes", "black eyes", "purple eyes", "yellow eyes", "amber eyes",
    "heterochromia", "closed eyes", "half-closed eyes", "half closed eyes",
    "wide eyes", "wide-eyed", "empty eyes", "wink", "one eye closed", "cross-eyed",
    "heart-shaped pupils", "symbol-shaped pupils", "slit pupils", "detailed eyes",
    "bags under eyes", "v-shaped eyebrows", "mouth", "open mouth", "closed mouth",
    "parted lips", "pursed lips", "wavy mouth", "fang", "fangs", "smile",
    "light smile", "grin", "smirk", "laughing", "pout", "frown", "blush",
    "flushed", "full-face blush", "blush stickers", "nose blush", "ear blush",
    "tears", "crying", "crying with eyes open", "tearing up", "streaming tears",
    "cry", "sad", "angry", "screaming", "gasp", "expressionless", "drool",
    "drooling", "saliva", "saliva trail", "tongue out", "sweatdrop", "scared",
    "embarrassed", "surprised", "shy", "sleepy", "ahegao", ":d", ":o", ":3",
    ";)", "@ @", "^^^", "disgust", "shaded face", "rolling eyes", "breath",
    "breathing", "defeat", "seductive smile", "naughty face", "glaring",
    "scowl", "totally drained",

    # 动作与姿势
    "standing", "sitting", "lying", "on back", "on stomach", "on side",
    "all fours", "kneeling", "squatting", "crawling", "leaning forward",
    "leaning back", "arched back", "crossed legs", "straddling", "spread legs",
    "wide spread legs", "legs up", "legs apart", "m legs", "knees up", "leg up",
    "feet up", "wariza", "bent over", "arm at side", "arms at sides",
    "arms behind back", "arms behind head", "arm behind head", "arms up",
    "arm up", "hands up", "hand up", "arm behind back", "arm support",
    "hand on hip", "hands on hips", "hand to mouth", "hand on head",
    "hand on cheek", "hand on another's head", "hand on another's face",
    "hand on another's chin", "pointing", "reaching", "waving", "salute",
    "peace sign", "v", "paw pose", "tail raised", "walking", "running",
    "jumping", "flying", "falling", "dancing", "sleeping", "stretching",
    "shivering", "trembling", "holding", "holding hands", "holding phone",
    "grabbing", "grabbing from behind", "grabbing another's breast",
    "grabbing another's hair", "grabbing another's ass", "grabbing breasts from behind",
    "head grab", "her head grab", "arm grab", "leg grab", "torso grab",
    "ass grab", "thigh grab", "groping", "hug", "lifted by self", "pulled by self",
    "head tilt", "head up", "head back", "sheet grab", "folded", "spanked",
    "drooping", "bouncing", "taking picture", "knees together feet apart",
    "spread knees", "against wall", "carrying person", "open stance", "grinding",

    # 性爱、性动作与体液
    "sex", "implied sex", "hetero", "yuri", "group sex", "threesome",
    "ffm threesome", "mmf threesome", "gangbang", "orgy", "rape", "imminent rape",
    "after rape", "sex crime", "netorare", "ntr", "clothed sex", "standing sex",
    "missionary", "doggystyle", "cowgirl position", "girl on top", "boy on top",
    "reverse upright straddle", "upright straddle", "prone bone", "mating press",
    "reverse suspended congress", "sex from behind", "interracial",
    "bisexual female", "oral", "fellatio", "cunnilingus", "deepthroat",
    "deepthroatl", "irrumatio", "kiss", "french kiss", "after kiss",
    "penetration", "vaginal", "vaginal sex", "anal", "imminent penetration",
    "imminent vaginal", "double penetration", "defloration", "masturbation",
    "female masturbation", "fingering", "handjob", "footjob", "two-footed footjob",
    "dildo", "vibrator", "remote control vibrator", "sex toy", "condom",
    "used condom", "condom wrapper", "cum", "cum on body", "cum on breasts",
    "cum in mouth", "cum on face", "cum on hair", "cum in pussy", "cum on feet",
    "cum on ass", "cum in ass", "cum overflow", "cum pool", "excessive cum",
    "precum", "pojecile cum", "cum string", "bukkake", "internal cumshot",
    "ejaculation", "female ejaculation", "cumdrip", "pussy juice",
    "pussy juice stain", "pussy juice trail", "suggestive fluid", "lactation",
    "milk", "breast milk", "pee", "urination", "after sex", "after vaginal",
    "after fellatio", "heavy breathing", "orgasm", "female orgasm", "forced orgasm",
    "nipple stimulation", "nipple tweak", "breast sucking", "breast press",
    "licking", "licking another's face", "licking penis", "object insertion",
    "anal object insertion", "butt plug", "sexual coaching", "facial",
    "reverse fellatio", "fucked silly", "rough sex", "spitroast", "ryona",
    "moaning", "election",

    # 束缚与 BDSM 动作
    "bondage", "tied up", "bound", "bound together", "bound arms", "bound wrists",
    "bound legs", "bound ankles", "rope", "red rope", "shackles", "trapped",
    "stuck", "restraint", "restrained", "hypnosis", "mind control", "bdsm",
    "shibari", "gag", "gagged", "ball gag", "improvised gag", "cloth gag",
    "tape gag", "chained", "strangling", "tape", "suspension", "crotch rope",
    "frogtie",

    # 背景、环境与道具
    "indoors", "indoor", "outdoors", "outdoor", "simple background",
    "white background", "monochrome background", "grey background",
    "black background", "transparent background", "room", "bedroom", "bed room",
    "locker room", "prison", "bed", "on bed", "on white bed", "bed sheet",
    "white sheets", "stained sheets", "sheets", "pillow", "couch", "on couch",
    "sofa", "chair", "on chair", "school chair", "table", "desk", "school desk",
    "floor", "on floor", "wooden floor", "tatami", "mat", "carpet",
    "window", "curtains", "door", "wall", "grey stone wall", "stone wall",
    "through wall", "bathroom", "in bath room", "shower", "bathtub", "onsen",
    "hot spring", "pool", "beach", "beach towel", "beach umbrella", "ocean",
    "sea", "sky", "clouds", "cloud", "blue sky", "night", "night sky",
    "stars", "moon", "full moon", "sunset", "sunlight", "sunbeams", "light rays",
    "shadow", "day", "forest", "trees", "tree", "flowers", "flower", "field",
    "flower field", "grass", "on green lawn", "park", "street", "city",
    "classroom", "in school", "beautiful japanese school", "car", "car interior",
    "phone", "cellphone", "smartphone", "nintendo switch", "book", "water",
    "food", "chips (food", "cup", "animal ears", "cat ears", "fake animal ears",
    "tail", "fake tail", "cat tail", "anal tail", "tentacles", "plant",
    "lamp", "uterus", "blanket", "towel", "stuffed toy",

    # 扩充通用杂词
    "anus peek", "overflow", "1 man's hand", "her legs grab", "tiles", "petals",
    "body writing", "rose", "pet play", "interlocked fingers", "sand", "presenting foot",
    "candy", "handheld game console", "clitoral stimulation", "exhibitionism", "weak",
    "flying sweatdrops", "muscular male", "legs together", "buttjob", "femdom", "ribs",
    "crime prevention buzzer", "wings", "demon wings", "harem", "molestation",
    "sleep molestation", "paizuri", "knee up", "gaping", "cat girl", "potato chips",
    "leaf", "arm held back", "after anal", "chocolate", "weapon", "oily", "slender",
    "flustered", "nfsw", "color grading", "hug from behind", ">=", "daylight",
    "white flower", "fake phone screenshot", "cellphone photo", "pointless condom",
    "bookshelf", "under covers", "fruit", "eating", "hairy", "cervix", "zzz",
    "reverse cowgirl position", "doorway", "drinking glass", "tally", "public indecency",
    "heart hands", "imminent anal", "dark", "dark skinned male", "introvert", "juice",
    "from front", "oil body", "warm colors", "overall detail", "8k", "exhausted",
    "pov hand", "imminent", "fertilization", "dripping", "missionary position", "road",
    "cover", "cover page", "controller", "drinking straw", "suspended congress",
    "hair spread out", "box", "anal beads", "cat", "emphasis lines", "chikan",
    "from back", "slim legs", "ningen mame", "light", "motion line", "grasslands",
    "intricate", "cropped legs", "in box", "head down", "twitching", "large insertion",
    "presenting", "wince", "spoken question mark", "in container", "valentine", "wind",
    "dancer", "perspective", "asymmetrical docking", "drugged", "hand between legs",
    "public use", "crossed ankles", "remote control", "drink", "vaginal object insertion",
    "chalkboard", "hitachi magic wand", "rain", "dorsiflexion", "motor vehicle",
    "umbrella", "picture frame", "shoulder blades", "bokura wa ima no naka de",
    "assertive female", "!?", "anal hair", "disembodied limb", "dark-skinned female",
    "6+boys", "voyeurism", "very sweaty", "kissing", "incest", "vaulting horse",
    "gift box", "arm hair", "パイズリ", "胸揉み", "脱衣",
}

DROP_REGEXES = [
    # 人数
    re.compile(r"^\d+\+?\s*(girls?|boys?|others?|people)$"),
    re.compile(r"^multiple\s+(girls?|boys?|others?)$"),
    # 单字母/标点残余/纯符号
    re.compile(r"^[a-zA-Z0-9]$"),
    re.compile(r"^[!?@#\$%^&*()_\-+=\[\]{}|\\:;\"'<>,./?`~]+$"),
    re.compile(r"^spoken\s+.*"),
    re.compile(r"^\d+k\b"),
    # 画师与作品元标签
    re.compile(r"^artist:.*"),
    re.compile(r".*\b(sho lwlw|askzy|ciloranko|ningen mame|morikura en|kantoku|hiten|tiv|krenz|wlop|mika pikazo|sudou tomonori|shisantian|yyb|ogipote|nekoda|as109|reoen)\b.*"),
    # 面部器官与五官
    re.compile(r".*\b(eyes?|pupils?|eyebrows?|cheeks?|face|chin|mouth|lips?|teeth|tongue|ears?|eyelashes?|nose)\b.*"),
    # 发型发色
    re.compile(r".*\b(hair|braids?|twintails?|ponytail|bangs?|updo|sidelocks?|ahoge)\b.*"),
    # 身体特征与解剖 (仅在非服饰规则之后触发)
    re.compile(r".*\b(skin|breasts?|nipples?|butt|buttocks?|ass|thighs?|hips?|waist|stomach|belly|navel|penis|pussy|vagina|vulva|clitoris|scrotum|testicles?|pubic|groin|muscles?|veins?|feet|foot|soles?|toes?|toenails?|nails?|painted nails|fingernails?)\b.*"),
    re.compile(r".*\b(ribs|shoulder blades?|collarbones?|shoulders?|spine|furrow|median furrow|dimples?|arm hair|anal hair|body hair|hairy|armpits?|backboob|mons|labia|crease|throat|legs?|arms?|chest|back|hands?|crotch|areolae?)\b.*"),
    # 动作姿态
    re.compile(r".*\b(pose|holding|standing|sitting|lying|kneeling|walking|running|squatting|straddling|crawling|leaning|grabbing|touching|pressing|pulling|lifting|carrying|reaching|facing|pointing|hugging|wading|yawning|fanning)\b.*"),
    re.compile(r".*\b(interlocked fingers|crossed ankles|legs together|knee up|head down|dorsiflexion|plantar flexion|body writing|heart hands|hands together|arms around|crossed arms|self hug|contrapposto|leg lock|closed legs|tail grab|choke hold)\b.*"),
    # 性爱体液重口
    re.compile(r".*\b(sex|paizuri|buttjob|footjob|handjob|blowjob|fellatio|cunnilingus|deepthroat|fingering|masturbation|tribadism|gokkun|spanking|hickey)\b.*"),
    re.compile(r".*\b(penetration|insertion|insertions|gaping|orgasm|ejaculation|cum|cumshot|cumming|cumdump|creampie|bukkake|precum|squirt|lactation|pee|urination|virgin blood)\b.*"),
    re.compile(r".*\b(femdom|chikan|molestation|rape|voyeurism|exhibitionism|pet play|public indecency|public use|incest|drugged|hypnosis|ntr|netorare|bdsm|bondage|shibari|tied up|bound|gag|gagged|blindfold|restraints?|chained|pinned)\b.*"),
    re.compile(r".*\b(dildo|vibrator|butt plug|sex toy|beads|anal beads|magic wand|strap-on|condom|condoms)\b.*"),
    re.compile(r".*\b(cowgirl|missionary|doggystyle|straddle|suspended congress|mating press|docking|prone bone|spooning)\b.*"),
    re.compile(r".*\b(imminent|fertilization|cervix|uterus|overflow|impregnation|torogao|futa|futanari|asphyxiation|ovum|interspecies|urethra|shimaidon|onee-shota|just the tip|girls on top|child on child)\b.*"),
    re.compile(r".*\b(sweat|sweaty|sweatdrop|sweatdrops|drool|drooling|saliva|tears|crying|wince|twitching|flustered|exhausted|drained|trembling|shivering|spasm|tremblingheavy)\b.*"),
    # 角色类型与人数
    re.compile(r".*\b(faceless|dark-skinned|minigirl|child|android|cyborg|demon|angel|monster|creature|foursome)\b.*"),
    # 场景环境家具与自然
    re.compile(r"^on\s+(bed|floor|couch|chair|table|desk|grass|lawn|tatami|futon|sofa|ground|bench).*$"),
    re.compile(r".*\b(background|room|indoor|outdoor|wall|floor|ceiling|window|door|table|chair|desk|bed|sheet|pillow|street|classroom|classrom|school|stairs|bench|locker|building|cityscape|library)\b.*"),
    re.compile(r".*\b(flowers?|rose|sunflower|petals?|leaves|leaf|grass|grasslands?|lawn|trees?|branch|forest|sand|beach|water|ocean|sea|sky|clouds?|sunlight|daylight|moon|stars?|night|sunbeam|nature|rock|snow|ice|fireworks)\b.*"),
    re.compile(r".*\b(tiles?|road|sidewalk|bookshelf|books?|doors?|doorway|windows?|bedroom|bath|bathroom|tub|bathtub|onsen|pool|kitchen|shouji)\b.*"),
    re.compile(r".*\b(box|container|umbrella|frames?|picture frame|couch|sofa|shelf|lattice|pole)\b.*"),
    # 道具与食物
    re.compile(r".*\b(food|candy|chips|potato chips|chocolate|fruit|apple|strawberry|cookie|ice cream|drink|drinking|juice|mug|bottle|bowl|pill|drugs|cake|popsicle|ball|beachball)\b.*"),
    re.compile(r".*\b(weapon|sword|blade|knife|gun|pistol|rifle|shield|bow|arrow|wand|staff|spikes)\b.*"),
    re.compile(r".*\b(cat|dog|bird|horse|rabbit|bunny|animal|creature|monster|fish|butterfly|wings?|feathers?|horns?|tails?|tentacles?|fern|vines?|potted plant)\b.*"),
    re.compile(r".*\b(gamepad|controller|console|smartphone|phone|cellphone|laptop|computer|screen|monitor|buzzer|television|tv|fan|clock|coin|card|cards|pen|pencil|paper|tissue|lock)\b.*"),
    re.compile(r".*\b(vehicle|car|train|bus|bicycle|bike|motorcycle|steering wheel|seatbelt)\b.*"),
    # 情绪、状态与微表情
    re.compile(r".*\b(smug|sexy|cute|elegant|messy|despair|annoyed|hot|serious|dirty|curvy|droop|laster|tearful|glare|confused|shouting|humiliation|unconscious|vulgarity|manly|instant loss|caught|mind break)\b.*"),
    # 构图画质元数据与风格
    re.compile(r".*\b(quality|res|angle|view|shot|focus|lighting|out of frame|shadows?|silhouette|reflection|caustics|chromatic aberration|contrast|bloom|hdr|grain|illustration|artstyle|photorealism|cross[\s\-]section|transparency|underlighting|layer|close to viewer|wallpaper)\b.*"),
    re.compile(r".*\b(screenshot|screencap|livestream|chat log|web address|sound effects?|emphasis lines?|motion lines?|dialogue|subtitle|tally|zzz|speed lines|2koma|doujin|comments|bubble)\b.*"),
    re.compile(r".*\b(years? old|y/o|detail|high resolution)\b.*"),
    re.compile(r"^wet\s+(body|hair|skin|face).*$"),
    re.compile(r".*[\{\}\)\(\+@\?]{2,}.*|^[\?_,\.\+]+$"),
    re.compile(r"^.{50,}$"),
    re.compile(r".*\b(nopan|exposure|suggestive|undressed|in motion|oily body|in heat)\b.*"),
    re.compile(r"^[\^;:\-_\s\+dDpPoO]{2,4}$"),
    re.compile(r"^-\d+::.*"),
    re.compile(r".*\b(photo|marker|painting|spade|chips)\s*\([a-z0-9_\s\-]+$"),
    re.compile(r"^\d+\s*girls?\s+and\s+\d+\s*boys?$"),
    re.compile(r".*\b(facial mark|bite mark|head rest|size difference|height difference|human stacking|playing games|washing machine|wind chime|ice cube|sweating profusely|barcode tattoo|heart tattoo|robot joints|mechanical parts|steam body|broken violated victim|identity censor|spread anus|dilation tape|doggy style|character doll|gym storeroom|heavy atmosphere|oripathy lesion|clean smooth texture|invisible man|uncommon stimulation|princess carry|borrowed character|summer festival|orange slice|shower head|father and daughter|kissing neck|clef of venus|missing upper body|steam work|stone walls|uncensored censoring|cargo racks|heavy breath|stemaing body|cream on body|whipped cream|evil smile|meaningful smile|dragon tattoo|tall strong black man|mature female|amazing colors|album cover|wine glass|full scream|light spot|light censoring|good perspective|lemon slice|abandoned house|grab below|yellow light|implied sexual crime|boy on behind|brasts grab|anime colored|male body|sit astride|love hotel|shut up and endure|wet all over the body|in hotel|boy kneeing behind her|on all fours|elbow rest|double bun|body blush|blue fire|teddy bear|stab wounds)\b.*"),
    re.compile(r".*\b(huwari|dnwls3010|sanbonzakura|kari|monika weisswind|fumihiko|fu mihi ko|misaki kurehito|wanke|novelance|rhasta|minagi kou|mirudakemann|ama mitsuki|goldowl|torino aqua|mochizuki kei|sayappa|henreader|tsurime|onineko|modare|sy4|marumoru|kowiru|dinoartforame|pieat|maeda hiroyuki|tempupupu|yuran|akeyama kitsune|tianliang duohe fangdongye)\b.*"),
    re.compile(r".*\b(colorful|delicate|bright|darkness|abuse|teamwork|multitasking|waking up|border|dual persona|walk-in|gift|invisible|gauze|bandaid|bedhighres|furrowed brow|white theme|mugshot|overexposure|camletoe|fgoblined oral|cinematic light|portlait|shushing|petite|emaciated|lolidom|bleeding|bread|piano|instrument|ninja|hogtie|fairy|subtitled|grimace|futon|mountain|piggyback|toilet|torture|alley|milk carton|wisteria|police|cushion|lollipop|church|skyscraper|toothbrush|notebook|eraser|pond|vase|hairjob|camera|cuddling|fire|armchair|outside border|gradient|pinching|selfcest|yandere|hallway|sadism|noise|paintbrush|nosebleed|whispering|peeing|imagining|idol|wife and wife|yarn|railing|lemon|contrail|splashing|balloon|dakimakura|digital media player|cd|snot|parfait|cherry|showering|dove|biting|slime|spill|headless|ripples|crosswalk|puddle|letterboxed|toddler|entrance|doubts|overflowing|headback|look down|siting|sunshine|pain|honey|siiting|drunk|bar|newest|lineart|overhang|floating|lantern|wires|behind another|otoko no ko|barcode|skeleton|wine glass|teacup|teapot|steaming|3d|fisheye|coffee|seaside|lie down|top-up|breathe|leisure|sunny|indroos|massage|celebrity|perspired|death|corpse|gore|necrophilia|experienceless|teardrop|jail|horrified|tearindoors|pregnant|resistance|violent|limp|sit down|basement|from outside|kabedon|doorstep|supermarkets|backlight|clavicle|vore|poolside|frawn|stabbed|disappointed|boys|swallow|lament|taut|evening|neckwear grab|lotion|christmas|summer|festival|index finger raised|double v|sparkle|light leaks|multiple penises|fetal position|headlock|kissing his dick|bend over|succubus|oral cavity|masturbate|asshole|nyotaimori|milking machine|tsundere|pubic tattoo)\b.*"),
    re.compile(r".*\b(game cg|movie light|panorama|photo stickerphoto|color trace|movie tonal|maximalism|thick lines|general|questionable|sensitive|content rating|explicit|traditional media)\b.*"),
    re.compile(r".*\b(perspective composition|threepoint perspective|belowlighting|upside down|look at side|looking above|medium close-up|portrait \(object|close-up|notice lines|heart effects|question mark)\b.*"),
    re.compile(r".*\b(resenting|timid|disappointed|pigeon-toed|twister|2pole|side by side|symmetry|black vs white|girls sandwitch|tiger paws|missing head|liquid metal girl|whole body|ancient city|sun light|ice ceam cone)\b.*"),
    re.compile(r".*\b(cyberpunk|futuristic|high-tech|robotic|sci-fi|battle ready|heroic stance|sleek design|advanced technology|detailed scenery|hovering|mechanized|mecha|jungle|dim|moonlight|sidelighting|bodypaint|crowded|squat|smlie)\b.*"),
    re.compile(r".*\b(mignon|liduke|yamasan|gweda|mamyouda|radial engine|ramdayo|white datura|omone hokoma agm|tokkyu|kidmo|muv-luv|kedama milk|rella|kouyafu|natsume koji|nakamura takeshi|haruri|uminokaisen|da mao banlangen)\b.*"),
    re.compile(r".*\b(viewed form below|cowboy shoot|leading forward|twisted torso|shocked)\b.*"),
    # 更多画师与社团
    re.compile(r".*\b(sakamata chloe|reoe|xilmo|fkey|minowa sukyaru|beudelb|asou|mitsumomo mamu|shiro9jira|eufoniuz|fukuro daizi|kz oji|naga u|aki99|nekojira|noeru|atdan|starshadowmagician|tyakomes|misaka|shinkai makoto|monety|chyoel|happoubi jin|yukie|kahlua|hyouuma|kase daiki|gurande|ishikei|piromizu|kanzaki hiro|asahina hikage|oniilus|superpig|ipuu|kyoto animation|xo|midori|inaeda kei|haguhagu|alp style|sonoda chiyoko|asakuraf)\b.*"),
    # 更多场景、食物与物品杂词
    re.compile(r".*\b(pancake|syrup|blueberry|fork|butter|bamboo|smoke|runes|cupboard|shrine|hospital corridor|fence|waterdrops|wave|chick|glint|rice|icepop|eyeball|lake|wine|throne|swing|energy drinks|air purifier|oil|restroom|pillory|magic circle|cave|landscape|glassland|sperm cell|east asian architecture|bedsheets|claws|fireplace|rug|casino|envelope|poker chip)\b.*"),
    # 更多微动作与状态姿态
    re.compile(r".*\b(stepped on|sittig|curled up|groping|fist|punching|defeated woman|soul kiss|gangbang|doggstyle|buckstyle|lie on sides|sob|turn pale|dispair|dispear|tilt head|breastfeeding|firing at viewer|on fours|top down|spit take|dimly lit|peeping|two-handed|reclining|choking|squeezing|untying|dangle|dangling|seiza|look at the display|reading|cast spell|sideways|sideway|stealthy|deep sleep|weakness|clothed girl|intercourse|male on bottom|man of top|girl on the top)\b.*"),
    # 更多表情、微情绪与画质元数据
    re.compile(r".*\b(frown|surpised|coherent|evil grin|dsmile|dark persona|emotionless|disdain|vulgar smile|mysterious gaze|false smile|hatred|sanpaku|teadrop|screaming for help|apply motion blur|distinct image|hyper-detailed|suitable texture|kessoku band|outline|super cell|pcpcpc|kankaku shadan|bottomlesses|zygocactus|kemonomimi mode|contemporary|silm girl|correct ratio|inflation|tanabata|drak|feelings of hatred|mysterious gaze|disdain|innocent|nervous|forced smile)\b.*"),
    # 男性、人数与特殊标签
    re.compile(r".*\b(1male|1guy|1 guy|1 man|1 old man|1onther|1girl\.1boy|couple|black men|clothed girl|naked man|drooping female|girl look front|male pov|female pervert|ghost pervert|dominatrix|female|male|69|6 9)\b.*"),
    # 日语/全角字符与乱码残余
    re.compile(r".*[\u3040-\u30ff\u4e00-\u9fff\uff00-\uffef\ufffd].*"),
    # 纹身、印记与特殊体征
    re.compile(r".*\b(tattoos?|marks?|amputee|stump|gash|incision|waste on body)\b.*"),
    # 科幻、机械与电子元件
    re.compile(r".*\b(circuit|wire|screw|battery|robot|mechanical|charging|plug|current|exoskeleton|dissection|cable)\b.*"),
    # 厨房、烹饪与商业生活环境
    re.compile(r".*\b(cooking|stove|cutting board|checkout counter|convenience store|cash|streetlights|wet pavement|casket|closed environment|okashi|sanshoku dango|ruins|wreckage|rubbish dump|trash can)\b.*"),
    # 解剖细部、错拼与身体微观特征
    re.compile(r".*\b(areole|nippl|tose|grion|nape|knees?|calves|abs|open moth|openmouth|jitome|eyeball|sanpaku|teadrop|blood drip|fist)\b.*"),
    # 微表情与情绪状态
    re.compile(r".*\b(serene|peaceful|curious expression|optimistic smile|gentle smile|naughty smile|scared expression|intense expression|embarrassed smile|anxious|frown|dispair|dispear|hatred|painful)\b.*"),
    # 时间、自然与场所环境
    re.compile(r".*\b(morning|morning glory|dusk|sunrise|nightclub|pier|hospital|shrine|office|casino|ground|prison|cave|mountainous horizon|spray|lake|throne|swing|underwater|outside)\b.*"),
    # 光影、氛围与特效
    re.compile(r".*\b(light|lights|glow|glint|mist|smoke|shadows?|hight|fog|flame theme|ambient light)\b.*"),
    # 动作姿态与交互
    re.compile(r".*\b(reaching|blinking|pouring|finger writing|submerged|licking|posture|attacking|attacked|struggles|begs|screaming|retouch|untied|bathing|dropping|sittig|curled up|groping|firing|peeping|two-handed|reclining|choking|squeezing|untying|dangle|dangling|seiza|one knee down|from front below|from front above|looking at object|staring at viewer|look at viewer|slooking at viewer|looking at veiewer|looking at viewers|heel pop|sheets grab|leashing pov)\b.*"),
    # 节庆、年代、修饰形容与元数据
    re.compile(r".*\b(xmas|chinese new year|happy new year|happy valentine|pumpkinspice|gold|silver|pink|drak|erotic and sensual|relax|solo foucus|3cameltoe|cameltoes|spread vaginal|hymen|asphyxia|vibration rod|smell|smelling|amazing|slim|slender body|thin|small|primitive|native american|fantasy|watercolor|oil|corruption|designed|dutch|spoken|exposed|close to|hard|matgangbang|white liquid|white hire|feathes|7010|year 2025|year 20231girl|mash kyrielight|lolita channel|hoshi \(snacherubi|fake video|minillustration|trefoil|bug|constellation|saturn \(planet|dust|scales|wh|milf)\b.*"),
    # 杂质符号
    re.compile(r".*(= =|=3|3j dangan|ribao|pcpcpc).*"),
    # 终极长尾环境、残余动作与杂词
    re.compile(r".*\b(body|upperbody|head|joints?|ankle|tiptoes?|bare|x-ray|mind|liquid|glass|cream|parody|record|squiggle|broken|scratches|stain|photo|tiling|artifacts|threesome|bukkke|character name|dynamic|underlight|very|kiss|detailed|details|highlights|sweat|sweating|profusely|plant texture|theme|reach-around|paying the bill|hints|condensation|covering|wrapping|puppet|in air|ask|cg|science fiction|looking afar|icing|furniture|infiltration|stret|half from side|straight on|form below|gaming display|chiaroscuro|classroon|pov head|half indoors|kyoto|speed line|look up|boy|girl|imp|style|hidari|roses|can|open|sleep|nsfw|handsgrabbing|lifted|grocery racks|grocery|confident)\b.*"),
    re.compile(r".*\b(sun|nudity|pry about|foreshortening|sweathat|hanging up|tight|heart effects?)\b.*"),
    re.compile(r"^\d+\+?\s*(girls?|boys?|others?|people).*$"),
]

# ---------------------------------------------------------------------------
# 4. 服饰词根与 Section 路由规则 (Word Roots & Keywords)
# ---------------------------------------------------------------------------

# 优先级顺序检查：shoes -> legwear -> full_body_clothes -> lower_clothes -> upper_clothes -> headwear -> hair -> props -> accessories -> clothes
SECTION_RULES: list[tuple[str, list[str]]] = [
    (
        "shoes",
        [
            "shoes", "shoe", "loafers", "boots", "sneakers", "sandals", "slippers",
            "flip-flops", "flip flops", "uwabaki", "heels", "pumps", "stiletto",
            "mules", "clogs", "geta", "zori", "waraji", "footwear", "mary janes",
            "high heels", "combat boots", "ankle boots", "knee boots", "thigh boots",
            "riding boots", "platform boots", "cross-laced footwear", "boots remove",
            "sandals remove", "paw shoes", "single shoe", "highheels", "high-heels",
            # 局部裸露/鞋履状态：赤脚/光脚
            "barefoot", "bare soles", "bare foot",
        ],
    ),
    (
        "legwear",
        [
            "socks", "thighhighs", "thigh-highs", "thigh highs", "kneehighs",
            "knee-highs", "knee highs", "tights", "pantyhose", "stockings",
            "fishnets", "fishnet pantyhose", "fishnet tights", "garter",
            "garter belt", "garter straps", "leg garter", "thigh strap",
            "leg warmers", "anklet", "anklets", "stirrup socks", "tabi",
            "loose socks", "black socks", "white socks", "black pantyhose",
            "black thighhighs", "white thighhighs", "striped thighhighs",
            "black thighights", "thighband", "thighbands", "thigh band", "leg ribbon",
            "toeless legwear", "stirrup legwear", "legwear", "torn pantyhose",
            "fishnet", "single thighhigh", "single sock", "single stocking",
            "leg wrap", "foot ribbon", "thighlet", "thighhigh", "white thighthighs",
            # 局部裸露/腿部造型：光腿/露腿/绝对领域
            "bare legs", "barelegs", "bare thighs", "zettai ryouiki",
        ],
    ),
    (
        "full_body_clothes",
        [
            "dress", "sundress", "summer dress", "maid dress", "wedding dress",
            "cocktail dress", "evening gown", "gown", "cheongsam", "qipao",
            "hanfu", "kimono", "yukata", "furisode", "haori", "hakama", "sarong",
            "uniform", "school uniform", "sailor uniform", "serafuku", "military uniform",
            "police uniform", "nurse uniform", "cheerleader", "tracksuit", "track suit",
            "gym uniform", "buruma", "swimsuit", "one-piece swimsuit", "school swimsuit",
            "competition swimsuit", "bikini", "slingshot bikini", "micro bikini",
            "front-tie bikini", "side-tie bikini", "string bikini", "frilled bikini",
            "bodysuit", "leotard", "catsuit", "latex suit", "bunny suit", "bunnysuit",
            "reverse bunnysuit", "plugsuit", "unitard", "zentai", "overalls", "jumpsuit",
            "romper", "dungarees", "robe", "bathrobe", "pajamas", "pajama", "nightgown", "negligee",
            "babydoll", "lingerie", "corset dress", "apron", "maid apron", "naked apron",
            "sailor dress", "suit", "formal wear", "costume", "alternate costume",
            "sleeveless dress", "sleepwear", "nightwear", "loungewear", "playboy bunny",
            "miko", "enmaided", "bodystocking", "microdress", "raincoat", "tunic",
            "chemise", "nun", "bride", "magical girl", "office lady", "toga",
            "nurse", "white nurse", "brown aporn", "mismatched b1ikini",
        ],
    ),
    (
        "lower_clothes",
        [
            "skirt", "miniskirt", "microskirt", "micro skirt", "pleated skirt",
            "long skirt", "pencil skirt", "bubble skirt", "slit skirt", "plaid skirt",
            "denim skirt", "pants", "shorts", "jeans", "trousers", "denim shorts",
            "short shorts", "hotpants", "bloomers", "cargo pants", "sweatpants",
            "leggings", "culottes", "track pants", "spats", "bell-bottoms",
            "panties", "pantie", "panty", "pantsu", "thong", "g-string", "string panties",
            "side-tie panties", "striped panties", "white panties", "black panties",
            "lace panties", "bow panties", "pink panties", "briefs", "boxers",
            "boxer shorts", "boyshorts", "underpants", "drawers", "fundoshi",
            "underwear", "underware", "underwear only", "bike shorts", "undergarment",
            "pelvic curtain", "crotchless", "highleg", "lowleg", "side slit",
            "loincloth",
        ],
    ),
    (
        "upper_clothes",
        [
            "shirt", "t-shirt", "tee", "blouse", "sweater", "hoodie", "jacket",
            "coat", "vest", "tank top", "crop top", "cropped top", "halterneck",
            "halter", "tube top", "camisole", "corset", "cardigan", "parka",
            "turtleneck", "pullover", "windbreaker", "bolero", "blazer",
            "suit jacket", "tuxedo", "bra", "sports bra", "strapless bra",
            "bandeau", "cupless bra", "black bra", "white bra", "lace bra",
            "white blue bra", "sleeves", "sleeve", "short sleeves", "long sleeves",
            "sleeveless", "detached sleeves", "detached sleeve", "puffy sleeves",
            "wide sleeves", "flared sleeves", "bell sleeves",
            "sleeves past fingers", "sleeves past wrists",
            "sailor collar", "mandarin collar", "standing collar", "detached collar",
            "shirt collar", "fur collar", "wing collar", "neckline", "armhole",
            "cleavage cutout", "chest cutout", "capelet", "cape", "poncho",
            "shawl", "cardigan", "shrug", "off shoulder", "off-shoulder",
            "single off shoulder", "off shouler", "shoulder cutout",
            "collared", "naked shirt", "collared shirt", "spaghetti strap", "shoulder straps",
            "strapless", "hood", "hood up", "hood down", "underbust",
            "cloak", "hooded cloak", "naked cloak", "labcoat", "naked labcoat",
            "tabard", "naked tabard", "sarashi", "bralooking",
            # 局部裸露/剪裁设计：露肩/露背/露胸/露臂/露腹/深V
            "bare shoulders", "single bare shoulder", "bare back", "backless",
            "bare arms", "bare midriff", "cleavage", "cleavage peek", "underboob",
            "under boob", "sideboob", "sideboobs", "underboobs", "midriff peek", "plunging", "bustier",
            "v-neck",
        ],
    ),
    (
        "headwear",
        [
            "hat", "cap", "beret", "beanie", "witch hat", "straw hat", "cowboy hat",
            "santa hat", "top hat", "bowler hat", "baseball cap", "sun hat",
            "hairband", "headband", "alice band", "maid headdress", "headdress",
            "tiara", "crown", "circlet", "veil", "bridal veil", "mouth veil",
            "hair ornament", "hair ribbon", "hair bow", "hair clip", "hairclip",
            "hairpin", "hair flower", "scrunchie", "kanzashi", "hair bell",
            "hair bobbles", "hair ring", "hair beads", "halo", "headwear",
            "goggles", "head wreath", "helmet", "helmets", "wreath", "laurel wreath",
            "forehead protector", "fake antlers", "antlers", "object on head",
            "head-mounted display",
        ],
    ),
    (
        "hair",
        [
            # 发型与发式 (Hairstyles & Arrangements)
            "twintails", "short twintails", "low twintails", "asymmetrical twintails",
            "ponytail", "side ponytail", "short ponytail", "high ponytail", "folded ponytail",
            "split ponytail",
            "braid", "braids", "twin braids", "single braid", "french braid", "crown braid",
            "side braid", "braid over shoulder",
            "hair bun", "double bun", "triple bun", "side bun", "single side bun",
            "doughnut bun", "buns", "half updo", "updo", "topknot", "chignon", "odango",
            "two side up", "one side up", "short one side up",
            "short hair", "long hair", "medium hair", "very long hair", "absurdly long hair",
            "bob cut", "hime cut", "pixie cut", "buzz cut", "undercut",
            "bangs", "blunt bangs", "parted bangs", "swept bangs", "crossed bangs",
            "fringe", "hair between eyes", "sidelocks",
            "ahoge", "antenna hair", "heart ahoge", "huge ahoge",
            "drill hair", "twin drills", "hair drills",
            "messy hair", "spiky hair", "straight hair", "wavy hair", "curly hair",
            "floating hair", "asymmetrical hair", "hair over one eye", "hair over eyes",
            "hair behind ear", "alternate hairstyle", "comb", "hair comb",
        ],
    ),
    (
        "props",
        [
            # 道具与手持物品 (Props, Weapons & Handhelds)
            "umbrella", "parasol", "paper umbrella", "wagasa",
            "fan", "folding fan", "paper fan", "hand fan", "holding fan", "sensu", "uchiwa",
            "wand", "magic wand", "staff", "scepter",
            "sword", "blade", "katana", "knife", "dagger", "gun", "pistol", "rifle",
            "shield", "weapon", "weapons", "holding weapon",
            "book", "notebook", "scroll", "hanging scroll", "scrolls", "open book",
            "lantern", "paper lantern", "lamp", "torch",
            "cane", "walking stick", "broom", "basket", "tray", "holding tray", "syringe",
            "musical instrument", "instrument", "guitar", "violin", "flute",
            "microphone", "studio microphone",
            "camera", "smartphone", "phone", "holding phone", "gamepad", "controller",
            "game controller", "playstation controller", "handheld game console",
            "holding controller", "holding game controller",
            "plushie", "stuffed toy", "teddy bear", "doll", "character doll",
            "teacup", "wine glass", "cup", "milk cup", "bottle", "water bottle",
            "holding bottle", "mug", "coffee mug", "chopsticks", "pipe",
            "smoking pipe", "cigarette", "bouquet", "lightsaber", "towel", "wet towel",
            "writing brush", "brush", "candle", "envelope", "saucer", "rubber duck",
            "bucket", "wooden bucket", "hose", "innertube", "vials",
        ],
    ),
    (
        "accessories",
        [
            "ribbon", "bow", "bowtie", "necktie", "tie", "ascot", "scarf", "muffler",
            "gloves", "fingerless gloves", "white gloves", "black gloves", "elbow gloves",
            "opera gloves", "mittens", "monoglove", "wristband", "wrist cuffs", "cuffs",
            "arm warmers", "armband", "choker", "collar", "leather collar", "bell collar",
            "animal collar", "red collar", "belt collar", "spiked collar", "necklace",
            "pendant", "chain", "chains", "locket", "belt", "belts", "waist belt", "corset belt",
            "sash", "obi", "obiage", "glasses", "sunglasses", "spectacles", "monocle",
            "eyepatch", "mask", "surgical mask", "earrings", "earring", "piercing",
            "piercings", "bracelet", "bangle", "ring", "rings", "brooch", "badge", "bag", "shoulder bag",
            "backpack", "randoseru", "satchel", "tote bag", "handbag", "purse",
            "leash", "handcuffs", "bell", "neck bell", "cowbell", "jingle bell",
            "jewelry", "cross pasties", "pasties", "maebari", "blindfold", "blindfolded",
            "black blindfold", "armlet", "wristlet", "neckerchief", "gauntlets",
            "bridal gauntlets", "wrist wrap", "hand wrap", "arm strap", "leg strap",
            "bracer", "bandages", "bandage", "bandaged arm", "tassel", "rei no himo",
            "earphones", "earphone", "headphones", "headphone", "headset", "headsets", "eyewear on head",
            "eyewear", "tail ornament", "suspenders", "id card", "lanyard", "stethoscope",
            "chestplate", "chinese knot", "eyeliner", "emblem", "charm", "eyeshadow",
            "makeup", "harness", "swharness", "oven mitts", "lipstick", "gem", "brown rope", "naked tape",
            "suspendernavel",
        ],
    ),
    (
        "clothes",
        [
            "clothes", "clothing", "outfit", "wear", "attire", "garment", "fabric",
            "see-through", "see through", "transparent", "translucent", "frills", "ruffles",
            "frilled", "frill", "lace", "ribbons", "pleated", "plaid", "checkered", "striped",
            "polka dot", "maid", "gothic lolita", "cosplay", "revealing clothes",
            "oversized clothes", "clothing cutout", "cutout", "cutouts", "center opening",
            "cross-laced slit", "torn", "body curtains", "wet clothes", "latex",
            "chiffon", "velvet", "spandex", "mesh", "leather", "silk", "satin",
            "denim", "trim", "fur trim", "gold trim", "black fur", "animal print",
            "floral print", "cow print", "leopard print", "zebra print", "print",
            "buttons", "button", "zipper", "buckle", "armor", "white armor",
            "tribal", "egyptian", "modern fashionable", "techwear", "tulle",
            "lolita fashion", "sheer", "vertical stripes", "pinstripe pattern",
            "lacing", "exoskeleton", "body armer", "see-though", "ee-through", "strap gap",
        ],
    ),
]

_COMPILED_SECTION_RULES = [
    (
        sec,
        re.compile(r"\b(" + "|".join(re.escape(k) for k in sorted(kws, key=len, reverse=True)) + r")\b"),
    )
    for sec, kws in SECTION_RULES
]


def normalize_tag(raw: str) -> str:
    """清理外围符号权重等，转成标准小写规范 tag。"""
    cleaned = raw.replace("\xa0", " ").replace("\ufffd", " ")
    cleaned = cleaned.strip()
    # 递归去除首尾所有的权重符号如 {, }, [, ], (, ) 以及空白与符号
    cleaned = re.sub(r"^[{\[\(\s\+]+", "", cleaned)
    cleaned = re.sub(r"[}\]\)\s\+]+$", "", cleaned)
    cleaned = re.sub(r"^\d+(\.\d+)?::", "", cleaned)
    cleaned = re.sub(r"::\d+(\.\d+)?$", "", cleaned)
    cleaned = re.sub(r":\d+(\.\d+)?$", "", cleaned)
    cleaned = re.sub(r"^:+", "", cleaned)
    cleaned = re.sub(r":+$", "", cleaned)
    cleaned = re.sub(r"^[{\[\(\s]+", "", cleaned)
    cleaned = re.sub(r"[}\]\)\s]+$", "", cleaned)
    cleaned = cleaned.strip().lower()
    cleaned = cleaned.replace("_", " ")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def is_pre_filter_drop(tag: str) -> bool:
    """判断是否属于必须提前过滤的元标签或成人情趣玩具（避免误匹配入 props）。"""
    return any(p.match(tag) for p in PRE_FILTER_PATTERNS)


def is_clothing_action(tag: str) -> bool:
    """判断是否为操作/改变服装状态的动作。"""
    return any(p.match(tag) for p in CLOTHING_ACTION_PATTERNS)


def is_nudity_or_absence(tag: str) -> bool:
    """判断是否为裸露或无衣物状态。"""
    return tag in NUDITY_AND_ABSENCE


def is_drop_tag(tag: str) -> bool:
    """判断是否为通用杂词。"""
    if tag in EXACT_DROP_TAGS:
        return True
    return any(pattern.match(tag) for pattern in DROP_REGEXES)


def classify_tag_to_section(tag: str) -> str | None:
    """根据关键词与词根将服装标签路由到对应 section。"""
    for section, pattern in _COMPILED_SECTION_RULES:
        if pattern.search(tag):
            return section
    return None


# ---------------------------------------------------------------------------
# 3. 候选 Action 节点发现 (Discovery)
# ---------------------------------------------------------------------------

def is_st_clothes_dir(path: Path) -> bool:
    """检查是否属于 st_clothes_* 专用服装目录。"""
    parts = path.parts
    return any(p.startswith("st_clothes") for p in parts)


def check_action_outfit(root_str: str, file_set: set[str]) -> bool:
    """检查 tags.txt 是否带有 type,dress 标记。"""
    if "tags.txt" in file_set:
        try:
            with open(os.path.join(root_str, "tags.txt"), "r", encoding="utf-8", errors="ignore") as fp:
                for line in fp:
                    if line.startswith("type,"):
                        lower = line.lower()
                        if "dress" in lower and "no" not in lower:
                            return True
                        break
        except Exception:
            pass

    return False


def discover_clothing_candidate_dirs(action_root: Path) -> list[tuple[str, Path]]:
    """扫描 action 根目录下符合条件的服装候选目录。

    返回: list of (source_category, node_dir)
    source_category 为 "st_clothes" 或 "action_outfit"
    """
    candidates: list[tuple[str, Path]] = []
    seen = set()

    for root_str, _, filenames in os.walk(action_root):
        file_set = set(filenames)
        if "tags.txt" not in file_set and "meta.yaml" not in file_set:
            continue
        item = Path(root_str)
        if item in seen:
            continue

        if is_st_clothes_dir(item):
            seen.add(item)
            candidates.append(("st_clothes", item))
        elif check_action_outfit(root_str, file_set):
            seen.add(item)
            candidates.append(("action_outfit", item))

    return sorted(candidates, key=lambda x: str(x[1]))


# ---------------------------------------------------------------------------
# 4. 节点数据解析与标签清洗 (Node Tag Extraction & Cleaning)
# ---------------------------------------------------------------------------

def extract_node_raw_tags(node_dir: Path) -> tuple[list[str], list[str]]:
    """从 node 目录中提取原始 tags 和 negative_prompt。"""
    meta_path = node_dir / "meta.yaml"
    if meta_path.exists():
        try:
            data = yaml.safe_load(meta_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                tags_dict = data.get("tags") or {}
                raw_tags: list[str] = []
                if isinstance(tags_dict, dict):
                    for v in tags_dict.values():
                        if isinstance(v, list):
                            raw_tags.extend(str(x) for x in v)
                elif isinstance(tags_dict, list):
                    raw_tags.extend(str(x) for x in tags_dict)
                neg = data.get("negative_prompt") or []
                neg_list = [str(x) for x in neg] if isinstance(neg, list) else [str(neg)]
                return raw_tags, neg_list
        except Exception:
            pass

    tags_path = node_dir / "tags.txt"
    if tags_path.exists():
        try:
            prompt_lines, ext_lines = _split_legacy_tags_lines(tags_path)
            raw_tags = _split_legacy_prompt_tags(prompt_lines)
            neg_list = _collect_legacy_negative_prompt(ext_lines)
            return raw_tags, neg_list
        except Exception:
            pass

    return [], []


ACTION_BASE_GARMENTS: dict[str, str] = {
    "skirt lift": "skirt",
    "skirt pull": "skirt",
    "torn skirt": "skirt",
    "shirt lift": "shirt",
    "open shirt": "shirt",
    "torn shirt": "shirt",
    "dress lift": "dress",
    "dress pull": "dress",
    "open jacket": "jacket",
    "kimono pull": "kimono",
    "bikini pull": "bikini",
    "bra lift": "bra",
    "bra pull": "bra",
    "panties aside": "panties",
    "pantyhose pull": "pantyhose",
}


def clean_and_route_tags(raw_tags: list[str]) -> dict[str, Any]:
    """对原始 tags 进行清洗、过滤杂词、路由到 sections。"""
    dropped_tags: list[str] = []
    section_tags: dict[str, list[str]] = defaultdict(list)
    unclassified_tags: list[str] = []

    # 1. 展开多标签（例如某些 legacy meta 或 tags 中用逗号或 AND 连接的多标签字符串）
    expanded_tags: list[str] = []
    for raw in raw_tags:
        parts = [raw]
        if " AND " in raw:
            parts = [sub for p in parts for sub in p.split(" AND ")]
        for p in parts:
            if "," in p:
                for part in p.split(","):
                    item = part.strip()
                    if item:
                        expanded_tags.append(item)
            else:
                item = p.strip()
                if item:
                    expanded_tags.append(item)

    seen = set()
    for raw in expanded_tags:
        norm = normalize_tag(raw)
        if not norm or norm in seen:
            continue
        seen.add(norm)

        # Stage 0: 明确元标签与情趣玩具先行过滤（防止误匹配到 phone / wand 等道具）
        if is_pre_filter_drop(norm):
            dropped_tags.append(norm)
            continue

        # Stage 1: 服饰动作交互（脱衣/掀衣/扯衣等动作）
        if is_clothing_action(norm):
            dropped_tags.append(norm)
            base_garment = ACTION_BASE_GARMENTS.get(norm)
            if base_garment and base_garment not in seen:
                sec = classify_tag_to_section(base_garment)
                if sec:
                    section_tags[sec].append(base_garment)
                    seen.add(base_garment)
            continue

        # Stage 2: 裸露/无服饰状态
        if is_nudity_or_absence(norm):
            dropped_tags.append(norm)
            continue

        # Stage 3: 服饰 Section 路由 (按鞋->袜->全身->下装->上装->头饰->饰品->材质优先匹配)
        section = classify_tag_to_section(norm)
        if section:
            section_tags[section].append(norm)
            continue

        # Stage 4: 通用杂词黑名单与正则过滤
        if is_drop_tag(norm):
            dropped_tags.append(norm)
            continue

        unclassified_tags.append(norm)

    return {
        "dropped": dropped_tags,
        "sections": dict(section_tags),
        "unclassified": unclassified_tags,
    }


# ---------------------------------------------------------------------------
# 5. Dry-Run 运行与全面报表分析 (Analysis & Dry-run Report)
# ---------------------------------------------------------------------------

def run_dryrun_analysis(action_root: Path, *, min_tags: int = 4, sample_limit: int = 5) -> dict[str, Any]:
    """执行完整的 Dry-run 扫描并生成统计分析报告。"""
    candidates = discover_clothing_candidate_dirs(action_root)

    total_candidates = len(candidates)
    by_category_counts: Counter[str] = Counter()

    total_raw_tags_count = 0
    total_dropped_count = 0
    total_routed_count = 0
    total_unclassified_count = 0

    dropped_counter: Counter[str] = Counter()
    routed_counter: Counter[str] = Counter()
    section_counter: Counter[str] = Counter()
    unclassified_counter: Counter[str] = Counter()

    processed_items: list[dict[str, Any]] = []
    nodes_with_clothing = 0
    nodes_empty_clothing = 0

    for cat, node_dir in candidates:
        by_category_counts[cat] += 1
        raw_tags, neg = extract_node_raw_tags(node_dir)
        total_raw_tags_count += len(raw_tags)

        res = clean_and_route_tags(raw_tags)
        dropped = res["dropped"]
        sections = res["sections"]
        unclassified = res["unclassified"]

        routed_in_node = sum(len(v) for v in sections.values())
        if routed_in_node >= min_tags:
            nodes_with_clothing += 1
            for sec, tags in sections.items():
                total_routed_count += len(tags)
                section_counter[sec] += len(tags)
                routed_counter.update(tags)
        else:
            nodes_empty_clothing += 1

        total_dropped_count += len(dropped)
        dropped_counter.update(dropped)

        total_unclassified_count += len(unclassified)
        unclassified_counter.update(unclassified)

        processed_items.append({
            "category": cat,
            "path": str(node_dir.relative_to(action_root)),
            "id": node_dir.name,
            "raw_count": len(raw_tags),
            "dropped_count": len(dropped),
            "routed_count": routed_in_node,
            "unclassified_count": len(unclassified),
            "sections": sections,
            "unclassified": unclassified,
            "dropped_sample": dropped[:6],
        })

    # 计算清洗覆盖率
    processed_tags = total_dropped_count + total_routed_count
    coverage_rate = (processed_tags / (processed_tags + total_unclassified_count) * 100) if (processed_tags + total_unclassified_count) else 100.0

    return {
        "summary": {
            "total_nodes_found": total_candidates,
            "nodes_with_clothing": nodes_with_clothing,
            "nodes_empty_clothing": nodes_empty_clothing,
            "category_counts": dict(by_category_counts),
            "total_raw_tags": total_raw_tags_count,
            "total_processed_tags": processed_tags + total_unclassified_count,
            "total_dropped_tags": total_dropped_count,
            "total_routed_tags": total_routed_count,
            "total_unclassified_tags": total_unclassified_count,
            "coverage_rate_percent": round(coverage_rate, 2),
            "section_distribution": dict(section_counter),
        },
        "top_dropped_tags": dropped_counter.most_common(40),
        "top_routed_tags": routed_counter.most_common(40),
        "top_unclassified_tags": unclassified_counter.most_common(40),
        "samples": processed_items[:sample_limit],
    }


# ---------------------------------------------------------------------------
# 6. 服装节点导出落盘 (Clothing Node Export)
# ---------------------------------------------------------------------------

SECTION_ORDER = [
    "role",
    "upper_clothes",
    "lower_clothes",
    "full_body_clothes",
    "legwear",
    "shoes",
    "clothes",
    "headwear",
    "accessories",
    "hair",
    "props",
]


def _clothing_prompt_signature(sections: dict[str, list[str]], neg_list: list[str]) -> tuple[Any, ...]:
    """生成服装节点的提示词特征指纹，用于去重。"""
    role_tags = tuple(
        sorted(
            set(
                str(t).strip().lower()
                for t in sections.get("role", [])
                if str(t).strip() and str(t).strip().lower() != "{{alternative_clothing}}"
            )
        )
    )
    sec_items = []
    for sec, tags in sorted(sections.items()):
        if sec == "role":
            continue
        cleaned_tags = tuple(sorted(set(str(t).strip().lower() for t in tags if str(t).strip())))
        if cleaned_tags:
            sec_items.append((sec, cleaned_tags))
    neg_tags = tuple(sorted(set(str(t).strip().lower() for t in neg_list if str(t).strip())))
    return (tuple(sec_items), role_tags, neg_tags)


def _node_name_quality(name: str) -> tuple[int, int, str]:
    """评估目录命名作为服装节点名称的质量，用于重复组中选出最优代表。
    
    1. 优先无阶段前缀的干净命名 (如 '20260502_女仆野餐' 优于 '02_core_20260502_女仆野餐')
    2. 次优 00_start_ 前缀
    3. 再次 01_pre_ / 02_core_ / 03_finish_
    4. 长度更短者优先
    """
    has_stage = bool(re.match(r"^\d+_(start|pre|core|finish)_", name))
    is_start = bool(re.match(r"^\d+_start_", name))
    score = 0 if not has_stage else (1 if is_start else 2)
    return (score, len(name), name)


def export_clothing_nodes(
    action_root: Path,
    export_root: Path,
    *,
    force: bool = False,
    min_tags: int = 4,
    dedup: bool = True,
) -> dict[str, Any]:
    """将清洗出的有效服装节点导出到指定服装目录 (例如 design/服装/)。"""
    candidates = discover_clothing_candidate_dirs(action_root)
    export_root.mkdir(parents=True, exist_ok=True)

    exported_count = 0
    skipped_empty_count = 0
    skipped_existing_count = 0
    skipped_duplicate_count = 0
    exported_nodes: list[dict[str, Any]] = []

    # 1. 扫描提取并清洗候选节点
    valid_candidates: list[dict[str, Any]] = []
    for cat, node_dir in candidates:
        raw_tags, neg_list = extract_node_raw_tags(node_dir)
        res = clean_and_route_tags(raw_tags)
        sections = res["sections"]
        routed_in_node = sum(len(v) for v in sections.values())
        if routed_in_node < min_tags:
            skipped_empty_count += 1
            continue

        sig = _clothing_prompt_signature(sections, neg_list)
        valid_candidates.append({
            "cat": cat,
            "node_dir": node_dir,
            "raw_tags": raw_tags,
            "neg_list": neg_list,
            "sections": sections,
            "routed_in_node": routed_in_node,
            "sig": sig,
        })

    # 2. 提示词内容去重（默认开启）
    selected_candidates: list[dict[str, Any]] = []
    if dedup:
        grouped_by_sig: dict[tuple, list[dict[str, Any]]] = defaultdict(list)
        for item in valid_candidates:
            grouped_by_sig[item["sig"]].append(item)
        for sig, group in grouped_by_sig.items():
            best = min(group, key=lambda x: _node_name_quality(x["node_dir"].name))
            selected_candidates.append(best)
            skipped_duplicate_count += len(group) - 1
    else:
        selected_candidates = valid_candidates

    selected_candidates.sort(key=lambda x: str(x["node_dir"]))

    seen_rel_paths: set[Path] = set()

    for item in selected_candidates:
        cat = item["cat"]
        node_dir = item["node_dir"]
        neg_list = item["neg_list"]
        sections = item["sections"]
        routed_in_node = item["routed_in_node"]

        rel_path = node_dir.relative_to(action_root)
        clothing_id = node_dir.name

        # 同批次重名检查：若已有相同相对路径且未指定 force，跳过
        if rel_path in seen_rel_paths and not force:
            continue
        seen_rel_paths.add(rel_path)

        target_dir = export_root / rel_path
        meta_file = target_dir / "meta.yaml"

        if meta_file.exists() and not force:
            skipped_existing_count += 1
            continue

        target_dir.mkdir(parents=True, exist_ok=True)

        node_name = node_dir.name
        orig_meta = node_dir / "meta.yaml"
        if orig_meta.exists():
            try:
                meta_data = yaml.safe_load(orig_meta.read_text(encoding="utf-8"))
                if isinstance(meta_data, dict) and meta_data.get("name"):
                    node_name = str(meta_data["name"])
            except Exception:
                pass

        # 按照标准 Section 顺序整理 tags，所有服装节点均携带 role: ["{{alternative_clothing}}"]
        role_tags = ["{{alternative_clothing}}"]
        if "role" in sections and sections["role"]:
            for r in sections["role"]:
                if r not in role_tags:
                    role_tags.append(r)

        ordered_tags: dict[str, list[str]] = {
            "role": role_tags,
        }
        for sec in SECTION_ORDER:
            if sec == "role":
                continue
            if sec in sections and sections[sec]:
                ordered_tags[sec] = sections[sec]
        for sec, tags in sections.items():
            if sec not in ordered_tags and tags:
                ordered_tags[sec] = tags

        doc: dict[str, Any] = {
            "schema": "tags-machine.clothing/v1",
            "kind": "clothing",
            "id": clothing_id,
            "name": node_name,
            "description": f"Extracted from {cat} action: {node_dir.name}",
            "tags": ordered_tags,
        }
        if neg_list:
            doc["negative_prompt"] = neg_list

        meta_file.write_text(
            yaml.safe_dump(doc, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )

        # 迁移关联预览图
        for img_ext in (".png", ".jpg", ".jpeg", ".webp"):
            for img_file in node_dir.glob(f"*{img_ext}"):
                try:
                    shutil.copy2(img_file, target_dir / img_file.name)
                except Exception:
                    pass

        exported_count += 1
        exported_nodes.append({
            "id": clothing_id,
            "path": str(target_dir),
            "relative_path": str(rel_path).replace("\\", "/"),
            "sections": list(ordered_tags.keys()),
            "tag_count": routed_in_node,
        })

    return {
        "summary": {
            "total_candidates": len(candidates),
            "exported_count": exported_count,
            "skipped_empty_count": skipped_empty_count,
            "skipped_duplicate_count": skipped_duplicate_count,
            "skipped_existing_count": skipped_existing_count,
            "export_dir": str(export_root),
        },
        "exported_nodes": exported_nodes,
    }


def main():
    parser = argparse.ArgumentParser(description="Scan action directory for clothing nodes and analyze tag cleaning.")
    parser.add_argument("--root", default="F:/my_project/new/tags_machine/design/动作改2", help="Action root dir")
    parser.add_argument("--json", action="store_true", help="Output full JSON report")
    parser.add_argument("--save-report", help="Save report to path")
    parser.add_argument("--export", action="store_true", help="Execute export to design/服装 (default dry-run)")
    parser.add_argument("--export-dir", default="F:/my_project/new/tags_machine/design/服装", help="Directory to export clothing nodes to")
    parser.add_argument("--force", action="store_true", help="Force overwrite existing clothing node directories")
    parser.add_argument("--clear", action="store_true", help="Clear existing export dir before exporting")
    parser.add_argument("--min-tags", type=int, default=4, help="Minimum routed clothing tags required to export (default: 4)")
    parser.add_argument("--no-dedup", action="store_true", help="Disable prompt tag content deduplication")
    args = parser.parse_args()

    action_root = Path(args.root)
    if not action_root.exists():
        print(f"Error: Action root {action_root} does not exist.")
        return 1

    if args.export:
        export_dir = Path(args.export_dir)
        if args.clear and export_dir.exists():
            print(f"Clearing export directory {export_dir}...")
            shutil.rmtree(export_dir)
        print("=" * 60)
        print("  Exporting Action Clothing Nodes")
        print("=" * 60)
        print(f"Action Source: {action_root}")
        print(f"Export Target: {export_dir}")
        print(f"Force Overwrite: {args.force}")
        print(f"Min Tags: {args.min_tags}")
        print(f"Deduplication: {not args.no_dedup}")
        print("-" * 60)
        res = export_clothing_nodes(
            action_root,
            export_dir,
            force=args.force,
            min_tags=args.min_tags,
            dedup=not args.no_dedup,
        )
        sm = res["summary"]
        print(f"Total Candidates Scanned : {sm['total_candidates']}")
        print(f"Exported Clothing Nodes  : {sm['exported_count']}")
        print(f"Skipped Below Threshold  : {sm['skipped_empty_count']}")
        print(f"Skipped Duplicate Content: {sm['skipped_duplicate_count']}")
        print(f"Skipped Already Existing : {sm['skipped_existing_count']}")
        print("=" * 60)
        print(f"Export completed successfully to {export_dir}!")
        if args.save_report:
            Path(args.save_report).write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"Export report saved to {args.save_report}")
        return 0

    report = run_dryrun_analysis(action_root, min_tags=args.min_tags)

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        summary = report["summary"]
        total_p = summary["total_processed_tags"]
        print("=" * 60)
        print("  Action Clothing Extraction - Dry-Run Report")
        print("=" * 60)
        print(f"匹配到的候选节点总数: {summary['total_nodes_found']}")
        for cat, cnt in summary['category_counts'].items():
            print(f"  - {cat}: {cnt} 个节点")
        print(f"有效服装节点 (包含>=1件服饰): {summary['nodes_with_clothing']} 个")
        print(f"空服装节点 (全为动作/0服饰标签): {summary['nodes_empty_clothing']} 个")
        print("-" * 60)
        print(f"展开处理后总标签数: {total_p} (原始标签: {summary['total_raw_tags']})")
        print(f"已过滤通用杂词: {summary['total_dropped_tags']} ({round(summary['total_dropped_tags']/total_p*100, 1)}%)")
        print(f"已精准路由到 Section: {summary['total_routed_tags']} ({round(summary['total_routed_tags']/total_p*100, 1)}%)")
        print(f"待确认/未分类词: {summary['total_unclassified_tags']} ({round(summary['total_unclassified_tags']/total_p*100, 1)}%)")
        print(f"清洗与路由总覆盖率: {summary['coverage_rate_percent']}%")
        print("-" * 60)
        print("Section 标签分布:")
        for sec, cnt in summary["section_distribution"].items():
            print(f"  {sec:<18}: {cnt:>5} tags")
        print("-" * 60)
        print("Top 15 被过滤杂词:")
        for tag, cnt in report["top_dropped_tags"][:15]:
            print(f"  {tag:<25} ({cnt} 次)")
        print("-" * 60)
        print("Top 15 路由服饰词:")
        for tag, cnt in report["top_routed_tags"][:15]:
            print(f"  {tag:<25} ({cnt} 次)")
        print("-" * 60)
        print("Top 15 待确认词 (Unclassified):")
        for tag, cnt in report["top_unclassified_tags"][:15]:
            print(f"  {tag:<25} ({cnt} 次)")
        print("=" * 60)

    if args.save_report:
        Path(args.save_report).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"Report saved to {args.save_report}")

    return 0


if __name__ == "__main__":
    main()
