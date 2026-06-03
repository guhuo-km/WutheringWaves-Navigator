from dataclasses import dataclass
from typing import Iterable, Mapping


SUPPORTED_MODIFIERS = {"ctrl", "alt", "shift"}


@dataclass(frozen=True)
class ParsedHotkey:
    modifiers: frozenset[str]
    primary: str


def normalize_primary(primary: str) -> str:
    primary = primary.strip().lower()
    aliases = {
        "middle": "middle",
        "x1": "x1",
        "x2": "x2",
        "back": "x1",
        "forward": "x2",
        "esc": "esc",
        "escape": "esc",
    }
    return aliases.get(primary, primary)


def parse_hotkey(hotkey: str) -> ParsedHotkey:
    modifiers: set[str] = set()
    primary = ""
    has_plus_primary = hotkey.strip().endswith("+")

    for raw_part in hotkey.split("+"):
        part = raw_part.strip().lower()
        if not part:
            continue
        if part in SUPPORTED_MODIFIERS:
            modifiers.add(part)
        elif part in {"win", "meta", "cmd", "command"}:
            continue
        else:
            primary = normalize_primary(part)

    if has_plus_primary:
        primary = "+"

    return ParsedHotkey(frozenset(modifiers), primary)


def normalize_modifiers(modifiers: Iterable[str]) -> frozenset[str]:
    return frozenset(
        modifier.strip().lower()
        for modifier in modifiers
        if modifier.strip().lower() in SUPPORTED_MODIFIERS
    )


def resolve_hotkey_action(
    bindings: Mapping[str, str],
    current_modifiers: Iterable[str],
    primary: str,
) -> str | None:
    active_modifiers = normalize_modifiers(current_modifiers)
    active_primary = normalize_primary(primary)
    candidates: list[tuple[int, str]] = []

    for action_name, hotkey in bindings.items():
        parsed = parse_hotkey(hotkey)
        if not parsed.primary or parsed.primary != active_primary:
            continue
        if not parsed.modifiers.issubset(active_modifiers):
            continue
        candidates.append((len(parsed.modifiers), action_name))

    if not candidates:
        return None

    max_specificity = max(score for score, _ in candidates)
    best = [action_name for score, action_name in candidates if score == max_specificity]
    if len(best) != 1:
        return None
    return best[0]
