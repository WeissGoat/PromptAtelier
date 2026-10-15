"""按画风栈自动分组。

和 skill 的口径一致：一个投稿算一个单位；先按画师（没有画师 tag 时用风格 tag）集合聚类，
再按 vibe 状态和模型细分。质量词、光影词、分辨率不参与分组。
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from .classify import token_category
from .metadata import ImageRecord
from .tokens import inner_tags, tokenize


CLUSTER_THRESHOLD = 0.5
CORE_RATIO = 0.5
NAME_TAGS = 3
VARIANT_MIN_RATIO = 0.1


@dataclass
class _Post:
    key: str
    date: str | None
    images: list[ImageRecord]
    signature: frozenset[str] = frozenset()
    vibe: str = "no_vibe"
    model: str | None = None


@dataclass
class _Cluster:
    posts: list[_Post] = field(default_factory=list)
    counts: Counter = field(default_factory=Counter)

    def core(self) -> set[str]:
        if len(self.posts) == 1:
            return set(self.counts)
        threshold = CORE_RATIO * len(self.posts)
        return {tag for tag, count in self.counts.items() if count >= threshold}

    def add(self, post: _Post) -> None:
        self.posts.append(post)
        self.counts.update(post.signature)


def image_signature(image: ImageRecord, categories: dict[str, str]) -> tuple[set[str], set[str]]:
    """(画师 tag 集合, 风格 tag 集合)。"""
    artists: set[str] = set()
    styles: set[str] = set()
    for token in tokenize(image.prompt).tokens:
        category = token_category(token.text, categories)
        if category == "artist":
            artists.update(tag for tag in inner_tags(token.text) if categories.get(tag, "artist") == "artist")
        elif category == "style":
            styles.update(inner_tags(token.text))
    return artists, styles


def _vibe_key(images: list[ImageRecord]) -> str:
    hashes = sorted({hash_ for image in images for hash_ in image.vibe.hashes})
    if hashes:
        return "vibe_" + "_".join(hash_[:4] for hash_ in hashes)
    if any("vibe_missing" in image.flags for image in images):
        return "missing"
    return "no_vibe"


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def build_groups(images: list[ImageRecord], categories: dict[str, str]) -> list[dict[str, Any]]:
    posts: dict[str, _Post] = {}
    for image in images:
        key = image.post.dir_name if image.post else image.id
        post = posts.setdefault(key, _Post(key=key, date=image.post.date if image.post else None, images=[]))
        post.images.append(image)

    for post in posts.values():
        artists: set[str] = set()
        styles: set[str] = set()
        for image in post.images:
            if image.has_metadata:
                image_artists, image_styles = image_signature(image, categories)
                artists |= image_artists
                styles |= image_styles
        post.signature = frozenset(artists or {f"style:{tag}" for tag in styles})
        post.vibe = _vibe_key(post.images)
        models = Counter(image.model for image in post.images if image.model)
        post.model = models.most_common(1)[0][0] if models else None

    clusters: list[_Cluster] = []
    unassigned: list[_Post] = []
    for post in sorted(posts.values(), key=lambda item: item.date or "", reverse=True):
        if not post.signature:
            unassigned.append(post)
            continue
        scored = [(_jaccard(set(post.signature), cluster.core()), cluster) for cluster in clusters]
        best_score, best = max(scored, key=lambda item: item[0], default=(0.0, None))
        if best is not None and best_score >= CLUSTER_THRESHOLD:
            best.add(post)
        else:
            cluster = _Cluster()
            cluster.add(post)
            clusters.append(cluster)

    clusters.sort(key=lambda cluster: len(cluster.posts), reverse=True)
    groups = [_group_payload(f"g{index + 1}", cluster.posts, cluster.counts) for index, cluster in enumerate(clusters)]
    if unassigned:
        groups.append(_group_payload("unassigned", unassigned, Counter(), name="未识别画风栈"))
    return groups


def _variants(posts: list[_Post]) -> list[tuple[str, list[_Post]]]:
    """同一画风家族里的稳定变体：相对基础栈（所有投稿共有的 tag）多出/缺少的 tag 组合。

    少于 max(2, 10%) 个投稿的组合并到最接近的稳定变体，避免一次性的调味词拆出一堆小组。
    """
    base = frozenset.intersection(*(post.signature for post in posts)) if posts else frozenset()
    by_signature: dict[frozenset[str], list[_Post]] = {}
    for post in posts:
        by_signature.setdefault(post.signature, []).append(post)
    minimum = max(2, round(len(posts) * VARIANT_MIN_RATIO))
    stable = {sig: items for sig, items in by_signature.items() if len(items) >= minimum}
    if not stable:
        return [("", posts)]
    for sig, items in by_signature.items():
        if sig in stable:
            continue
        nearest = max(stable, key=lambda candidate: (_jaccard(set(sig), set(candidate)), len(stable[candidate])))
        stable[nearest].extend(items)
    variants = []
    for sig, items in stable.items():
        extra = sorted(tag.removeprefix("style:") for tag in sig - base)
        variants.append((" ".join(f"+{tag}" for tag in extra), items))
    return sorted(variants, key=lambda item: len(item[1]), reverse=True)


def _group_payload(group_id: str, posts: list[_Post], counts: Counter, *, name: str | None = None) -> dict[str, Any]:
    top = counts.most_common()
    if name is None:
        name = " · ".join(tag.removeprefix("style:") for tag, _ in top[:NAME_TAGS]) or group_id
    variants = _variants(posts) if counts else [("", posts)]
    children = []
    for variant_index, (variant, variant_posts) in enumerate(variants):
        subgroups: dict[tuple[str, str | None], list[_Post]] = {}
        for post in variant_posts:
            subgroups.setdefault((post.vibe, post.model), []).append(post)
        for (vibe, model), items in sorted(subgroups.items(), key=lambda item: len(item[1]), reverse=True):
            children.append(
                {
                    "id": f"{group_id}/v{variant_index + 1}/{vibe}/{model or 'unknown'}",
                    "variant": variant or ("基础栈" if len(variants) > 1 else ""),
                    "vibe": vibe,
                    "model": model,
                    **_counts(items),
                }
            )
    return {
        "id": group_id,
        "name": name,
        "signature": [{"tag": tag.removeprefix("style:"), "posts": count} for tag, count in top[:12]],
        "signature_kind": "style" if top and top[0][0].startswith("style:") else "artist",
        **_counts(posts),
        "children": children,
    }


def _counts(posts: list[_Post]) -> dict[str, Any]:
    dates = sorted(post.date for post in posts if post.date)
    return {
        "post_count": len(posts),
        "image_count": sum(len(post.images) for post in posts),
        "date_from": dates[0] if dates else None,
        "date_to": dates[-1] if dates else None,
        "image_ids": [image.id for post in posts for image in post.images],
    }


def workspace_tags(images: list[ImageRecord]) -> tuple[list[str], list[str]]:
    """(要翻译的 token 原文, 要分类的规范化 tag)。负面只翻译不分类。"""
    token_texts: list[str] = []
    tags: list[str] = []
    for image in images:
        positives = [image.prompt, *(caption.positive for caption in image.char_captions)]
        negatives = [image.negative_prompt, *(caption.negative for caption in image.char_captions)]
        for text in positives:
            for token in tokenize(text).tokens:
                token_texts.append(token.text)
                tags.extend(inner_tags(token.text))
        for text in negatives:
            token_texts.extend(token.text for token in tokenize(text).tokens)
    return list(dict.fromkeys(token_texts)), list(dict.fromkeys(tags))
