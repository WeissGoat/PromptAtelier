from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal

from tags_machine_core.logging_config import get_logger
from tags_machine_core.nodes.models import NodeDocument
from tags_machine_core.policies.context import PromptRuleContext
from tags_machine_core.policies.tokens import PromptToken, canonicalize_tag, parse_prompt_token


logger = get_logger(__name__)

TriggerMode = Literal["fixed", "fixed_plus_legacy", "legacy"]


@dataclass(frozen=True)
class ExtensionSlot:
    slot: str
    legacy_rule_names: tuple[str, ...]
    declaration_names: tuple[str, ...]
    triggers: tuple[str, ...]


@dataclass(frozen=True)
class ExtensionDeclaration:
    slot: str
    materials: tuple[str, ...]


@dataclass(frozen=True)
class ExtensionOperation:
    name: str
    args: tuple[str, ...]


@dataclass(frozen=True)
class ExtensionRuleLine:
    slot: str
    legacy_name: str
    legacy_triggers: tuple[str, ...]
    operations: tuple[ExtensionOperation, ...]


SLOTS: dict[str, ExtensionSlot] = {
    "legwear": ExtensionSlot(
        slot="legwear",
        legacy_rule_names=("leg_wear", "barefoot"),
        declaration_names=("ext_legwear",),
        triggers=(
            "ankle socks",
            "argyle_legwear",
            "bare feet",
            "barefoot",
            "black socks",
            "black thighhighs",
            "black_pantyhose",
            "kneehighs",
            "legwear",
            "pantyhose",
            "single_thighhigh",
            "socks",
            "stirrup legwear",
            "thighhighs",
            "toeless legwear",
            "white kneehighs",
            "white socks",
            "white_pantyhose",
            "white_socks",
        ),
    ),
    "shoes": ExtensionSlot(
        slot="shoes",
        legacy_rule_names=("shoes",),
        declaration_names=("ext_shoes",),
        triggers=(
            "armored shoes",
            "armored_boots",
            "barefoot",
            "boots",
            "footwear",
            "high heels",
            "high_heels",
            "loafers",
            "mary janes",
            "mary_janes",
            "shoes",
            "sneakers",
        ),
    ),
    "weapon": ExtensionSlot(
        slot="weapon",
        legacy_rule_names=("weapon",),
        declaration_names=("ext_weapon", "ext_item"),
        triggers=("sword", "weapon", "gun"),
    ),
    "pant": ExtensionSlot(
        slot="pant",
        legacy_rule_names=("extend_func_pant",),
        declaration_names=(),
        triggers=(
            "breasts out",
            "lactation",
            "leg_wear",
            "pant_pull",
            "panties",
            "panty_pull",
            "underwear",
        ),
    ),
    "pantyhose": ExtensionSlot(
        slot="pantyhose",
        legacy_rule_names=("extend_func_pantyhose",),
        declaration_names=(),
        triggers=("pantyhose",),
    ),
    "barefoot": ExtensionSlot(
        slot="barefoot",
        legacy_rule_names=("extend_func_barefoot",),
        declaration_names=(),
        triggers=("barefoot",),
    ),
    "nipple": ExtensionSlot(
        slot="nipple",
        legacy_rule_names=("extend_func_nipple",),
        declaration_names=(),
        triggers=("nipple", "nipples"),
    ),
    "boy": ExtensionSlot(
        slot="boy",
        legacy_rule_names=("extend_func_boy",),
        declaration_names=(),
        triggers=("1boy", "boy", "male"),
    ),
}

DECLARATION_TO_SLOT = {
    name: slot.slot
    for slot in SLOTS.values()
    for name in slot.declaration_names
}
RULE_NAME_TO_SLOT = {
    name: slot.slot
    for slot in SLOTS.values()
    for name in slot.legacy_rule_names
}
SUPPORTED_OPERATIONS = {
    "include_replace",
    "replace",
    "fuzzy_replace",
    "add",
    "add_after",
    "add_if_not_exist",
}


class CharacterExtensionPolicyRule:
    id = "character_extension"
    version = "v1"
    phase = "compose_selection"
    default_enabled = False

    def apply(self, context: PromptRuleContext) -> PromptRuleContext:
        if context.target != "script":
            return context
        characters = _resolved_characters(context)
        if not characters:
            return context

        options = context.config.options_for(self.id)
        trigger_mode = _trigger_mode(options.get("trigger_mode"))
        include_materials = bool(options.get("include_declaration_materials", True))
        ignore_disabled = bool(options.get("ignore_disabled_lines", True))
        enabled_slots = _enabled_slots(options.get("enabled_slots"))

        for character in characters:
            parsed = _parse_character_extensions(character, ignore_disabled=ignore_disabled)
            triggered_slots = self._triggered_slots(
                context.positive_tokens,
                parsed.rules,
                trigger_mode=trigger_mode,
                enabled_slots=enabled_slots,
            )
            if not triggered_slots:
                continue
            logger.info(
                "CharacterExtensionPolicyRule applying character=%s slots=%s",
                character.id,
                sorted(triggered_slots),
            )
            if include_materials:
                self._apply_materials(context, parsed.declarations, triggered_slots, character)
            for rule in parsed.rules:
                if rule.slot not in triggered_slots:
                    continue
                for operation in rule.operations:
                    self._apply_operation(context, operation, rule, character)
        return context

    def _triggered_slots(
        self,
        tokens: list[PromptToken],
        rules: list[ExtensionRuleLine],
        *,
        trigger_mode: TriggerMode,
        enabled_slots: set[str],
    ) -> set[str]:
        active: set[str] = set()
        for slot_name, slot in SLOTS.items():
            if slot_name not in enabled_slots:
                continue
            fixed_hit = trigger_mode in {"fixed", "fixed_plus_legacy"} and _any_present(
                tokens, slot.triggers
            )
            legacy_hit = False
            if trigger_mode in {"fixed_plus_legacy", "legacy"}:
                legacy_hit = any(
                    rule.slot == slot_name and _legacy_triggers_hit(tokens, rule.legacy_triggers)
                    for rule in rules
                )
            if fixed_hit or legacy_hit:
                active.add(slot_name)
        return active

    def _apply_materials(
        self,
        context: PromptRuleContext,
        declarations: list[ExtensionDeclaration],
        triggered_slots: set[str],
        character: NodeDocument,
    ) -> None:
        for declaration in declarations:
            if declaration.slot not in triggered_slots:
                continue
            for material in declaration.materials:
                if _append_if_missing(context.positive_tokens, material):
                    context.add_trace(
                        rule=f"{self.id}@{self.version}",
                        action="add_material",
                        token=canonicalize_tag(material),
                        reason=f"{character.id}:{declaration.slot}",
                        mode="declaration",
                    )

    def _apply_operation(
        self,
        context: PromptRuleContext,
        operation: ExtensionOperation,
        rule: ExtensionRuleLine,
        character: NodeDocument,
    ) -> None:
        if operation.name == "include_replace":
            self._include_replace(context, operation, rule, character)
        elif operation.name == "replace":
            self._replace(context, operation, rule, character, mode="replace", fuzzy=False)
        elif operation.name == "fuzzy_replace":
            self._fuzzy_replace(context, operation, rule, character)
        elif operation.name == "add":
            self._add(context, operation.args, rule, character)
        elif operation.name == "add_after":
            self._add_after(context, operation, rule, character)
        elif operation.name == "add_if_not_exist":
            self._add_if_not_exist(context, operation, rule, character)
        else:
            context.add_trace(
                rule=f"{self.id}@{self.version}",
                action="skip_operation",
                token=operation.name,
                reason=f"{character.id}:{rule.legacy_name}",
            )

    def _include_replace(
        self,
        context: PromptRuleContext,
        operation: ExtensionOperation,
        rule: ExtensionRuleLine,
        character: NodeDocument,
    ) -> None:
        if len(operation.args) < 2:
            return
        target = operation.args[-1]
        target_key = canonicalize_tag(target)
        if not target_key:
            return
        matchers = [
            canonicalize_tag(value)
            for value in operation.args[:-1]
            if canonicalize_tag(value) not in {"stirrup_legwear", "toeless_legwear"}
        ]
        if not matchers:
            return

        changed = False
        new_tokens: list[PromptToken] = []
        for token in context.positive_tokens:
            new_body = token.canonical
            for matcher in matchers:
                if matcher and matcher in new_body:
                    new_body = new_body.replace(matcher, target_key)
            if new_body != token.canonical:
                new_tokens.append(token.with_body(new_body))
                changed = True
                context.add_trace(
                    rule=f"{self.id}@{self.version}",
                    action="include_replace",
                    from_value=token.render("underscore"),
                    to_value=new_body,
                    reason=f"{character.id}:{rule.legacy_name}",
                    mode=rule.slot,
                )
            else:
                new_tokens.append(token)
        if changed:
            context.positive_tokens = new_tokens

    def _replace(
        self,
        context: PromptRuleContext,
        operation: ExtensionOperation,
        rule: ExtensionRuleLine,
        character: NodeDocument,
        *,
        mode: str,
        fuzzy: bool,
    ) -> None:
        if len(operation.args) < 2:
            return
        target = operation.args[-1]
        matchers = operation.args[:-1]
        if not target.strip():
            return
        target_key = canonicalize_tag(target)
        replaced = False
        new_tokens: list[PromptToken] = []
        for token in context.positive_tokens:
            if _token_matches_any(token, matchers, fuzzy=fuzzy):
                if not any(existing.canonical == target_key for existing in new_tokens):
                    new_tokens.append(parse_prompt_token(target))
                context.add_trace(
                    rule=f"{self.id}@{self.version}",
                    action=mode,
                    from_value=token.render("underscore"),
                    to_value=target_key,
                    reason=f"{character.id}:{rule.legacy_name}",
                    mode=rule.slot,
                )
                replaced = True
                continue
            new_tokens.append(token)
        if replaced:
            context.positive_tokens = new_tokens

    def _fuzzy_replace(
        self,
        context: PromptRuleContext,
        operation: ExtensionOperation,
        rule: ExtensionRuleLine,
        character: NodeDocument,
    ) -> None:
        if len(operation.args) < 2:
            return
        target = operation.args[-1]
        matchers = operation.args[:-1]
        target_key = canonicalize_tag(target)
        if not target_key:
            return
        result: list[PromptToken] = []
        matched = False
        for token in context.positive_tokens:
            result.append(token)
            if matched or not _token_matches_any(token, matchers, fuzzy=True):
                continue
            if not _has_canonical(result, target):
                result.append(parse_prompt_token(target))
                context.add_trace(
                    rule=f"{self.id}@{self.version}",
                    action="fuzzy_replace",
                    from_value=token.render("underscore"),
                    to_value=target_key,
                    reason=f"{character.id}:{rule.legacy_name}",
                    mode=rule.slot,
                )
            matched = True
        if matched:
            context.positive_tokens = result

    def _add(
        self,
        context: PromptRuleContext,
        values: Iterable[str],
        rule: ExtensionRuleLine,
        character: NodeDocument,
    ) -> None:
        for value in values:
            if _append_if_missing(context.positive_tokens, value):
                context.add_trace(
                    rule=f"{self.id}@{self.version}",
                    action="add",
                    token=canonicalize_tag(value),
                    reason=f"{character.id}:{rule.legacy_name}",
                    mode=rule.slot,
                )

    def _add_after(
        self,
        context: PromptRuleContext,
        operation: ExtensionOperation,
        rule: ExtensionRuleLine,
        character: NodeDocument,
    ) -> None:
        if len(operation.args) < 2:
            return
        additions = [value for value in operation.args[:-1] if value.strip()]
        anchor = operation.args[-1]
        anchor_key = canonicalize_tag(anchor)
        result: list[PromptToken] = []
        inserted = False
        for token in context.positive_tokens:
            result.append(token)
            if token.canonical != anchor_key:
                continue
            for addition in additions:
                if _has_canonical(result, addition) or _has_canonical(context.positive_tokens, addition):
                    continue
                result.append(parse_prompt_token(addition))
                inserted = True
                context.add_trace(
                    rule=f"{self.id}@{self.version}",
                    action="add_after",
                    token=canonicalize_tag(addition),
                    from_value=anchor_key,
                    reason=f"{character.id}:{rule.legacy_name}",
                    mode=rule.slot,
                )
        if inserted:
            context.positive_tokens = result

    def _add_if_not_exist(
        self,
        context: PromptRuleContext,
        operation: ExtensionOperation,
        rule: ExtensionRuleLine,
        character: NodeDocument,
    ) -> None:
        if not operation.args:
            return
        target = operation.args[0]
        blocked = operation.args[1:]
        if _has_canonical(context.positive_tokens, target):
            return
        if blocked and _any_present(context.positive_tokens, blocked):
            return
        if _append_if_missing(context.positive_tokens, target):
            context.add_trace(
                rule=f"{self.id}@{self.version}",
                action="add_if_not_exist",
                token=canonicalize_tag(target),
                reason=f"{character.id}:{rule.legacy_name}",
                mode=rule.slot,
            )


@dataclass(frozen=True)
class ParsedCharacterExtensions:
    declarations: list[ExtensionDeclaration]
    rules: list[ExtensionRuleLine]


def _parse_character_extensions(
    node: NodeDocument,
    *,
    ignore_disabled: bool,
) -> ParsedCharacterExtensions:
    declarations: list[ExtensionDeclaration] = []
    rules: list[ExtensionRuleLine] = []
    for raw_line in node.legacy.raw_sections.get("extension", []):
        line = raw_line.strip()
        if not line:
            continue
        if ignore_disabled and line.startswith(("#", "-", "--")):
            continue
        parts = [part.strip() for part in line.split(",")]
        parts = [part for part in parts if part]
        if not parts:
            continue
        name = parts[0]
        if name in DECLARATION_TO_SLOT:
            declarations.append(
                ExtensionDeclaration(
                    slot=DECLARATION_TO_SLOT[name],
                    materials=tuple(parts[1:]),
                )
            )
            continue
        slot = RULE_NAME_TO_SLOT.get(name)
        if not slot:
            logger.trace(
                "CharacterExtensionPolicyRule skipped loose extension line character=%s line=%s",
                node.id,
                raw_line,
            )
            continue
        operations = tuple(_parse_operation(part) for part in parts[2:])
        operations = tuple(operation for operation in operations if operation is not None)
        rules.append(
            ExtensionRuleLine(
                slot=slot,
                legacy_name=name,
                legacy_triggers=tuple(_split_pipe(parts[1] if len(parts) > 1 else "")),
                operations=operations,
            )
        )
    return ParsedCharacterExtensions(declarations=declarations, rules=rules)


def _parse_operation(value: str) -> ExtensionOperation | None:
    parts = _split_pipe(value)
    if not parts:
        return None
    name = parts[0]
    if name not in SUPPORTED_OPERATIONS:
        return None
    return ExtensionOperation(name=name, args=tuple(parts[1:]))


def _split_pipe(value: str) -> list[str]:
    return [part.strip() for part in str(value).split("|") if part.strip()]


def _resolved_characters(context: PromptRuleContext) -> list[NodeDocument]:
    if context.resolved_nodes is None:
        return []
    return [item.node for item in context.resolved_nodes.characters()]


def _trigger_mode(value: object) -> TriggerMode:
    text = str(value or "fixed").strip()
    if text in {"fixed", "fixed_plus_legacy", "legacy"}:
        return text  # type: ignore[return-value]
    return "fixed"


def _enabled_slots(value: object) -> set[str]:
    if value is None:
        return {"legwear", "shoes", "weapon", "pant", "pantyhose", "barefoot", "nipple", "boy"}
    if isinstance(value, str):
        items = [item.strip() for item in value.split(",")]
    elif isinstance(value, list):
        items = [str(item).strip() for item in value]
    else:
        items = [str(value).strip()]
    enabled = {item for item in items if item in SLOTS}
    return enabled or set(SLOTS)


def _legacy_triggers_hit(tokens: list[PromptToken], triggers: Iterable[str]) -> bool:
    positive = False
    for trigger in triggers:
        if trigger.startswith("!"):
            if _any_present(tokens, [trigger[1:]]):
                return False
            continue
        if _any_present(tokens, [trigger]):
            positive = True
    return positive


def _any_present(tokens: list[PromptToken], values: Iterable[str]) -> bool:
    return any(_has_prompt_key(tokens, value) for value in values if str(value).strip())


def _has_prompt_key(tokens: list[PromptToken], value: str) -> bool:
    key = canonicalize_tag(value)
    if not key:
        return False
    negative_key = f"no_{key}"
    for token in tokens:
        if token.canonical == negative_key:
            return False
    return any(_canonical_contains(token.canonical, key) for token in tokens)


def _canonical_contains(token_key: str, key: str) -> bool:
    return token_key == key or token_key.endswith(f"_{key}") or key in token_key.split("_")


def _token_matches_any(token: PromptToken, values: Iterable[str], *, fuzzy: bool) -> bool:
    for value in values:
        key = canonicalize_tag(value)
        if not key:
            continue
        if token.canonical == key:
            return True
        if fuzzy and _canonical_contains(token.canonical, key):
            return True
    return False


def _append_if_missing(tokens: list[PromptToken], value: str) -> bool:
    text = value.strip(" ,")
    if not text:
        return False
    if _has_canonical(tokens, text):
        return False
    tokens.append(parse_prompt_token(text))
    return True


def _has_canonical(tokens: list[PromptToken], value: str) -> bool:
    key = canonicalize_tag(value)
    return any(token.canonical == key for token in tokens)
