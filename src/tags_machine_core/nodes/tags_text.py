"""Read the editable prompt source without executing legacy directives."""

NEGATIVE_KEYS = frozenset({"uc", "origin_uc", "after_uc", "negative_prompt", "after_negative_prompt"})
EXTENSION_KEYS = NEGATIVE_KEYS | {"origin_clear", "gen_json", "gen_param"}


def split_tags_text(text: str) -> tuple[list[str], list[str], list[str]]:
    positive, types, extensions = [], [], []
    in_extension = False
    for raw in text.splitlines():
        line = raw.strip().lstrip("\ufeff")
        if not line or line.startswith("#"):
            continue
        if line.startswith("="):
            in_extension = True
            line = line[1:].strip(" ,")
            if line:
                extensions.append(line)
        elif in_extension or line.partition(",")[0].strip() in EXTENSION_KEYS:
            in_extension = True
            extensions.append(line)
        elif line.partition(",")[0].strip() == "type":
            types.append(line)
        else:
            positive.append(line)
    return positive, types, extensions


def negative_tags(extensions: list[str]) -> list[str]:
    result = []
    for line in extensions:
        key, _, value = line.partition(",")
        if key.strip() in NEGATIVE_KEYS and value.strip():
            result.append(value.strip())
    return result


def prompt_tags(lines: list[str]) -> list[str]:
    """Split only top-level commas, preserving weighted groups."""
    items = []
    for text in lines:
        current, stack = [], []
        closing = {")": "(", "]": "[", "}": "{"}
        for char in text:
            if char in "([{":
                stack.append(char)
            elif char in closing and stack and stack[-1] == closing[char]:
                stack.pop()
            if char == "," and not stack:
                item = "".join(current).strip()
                if item:
                    items.append(item)
                current = []
            else:
                current.append(char)
        item = "".join(current).strip()
        if item:
            items.append(item)
    return items
