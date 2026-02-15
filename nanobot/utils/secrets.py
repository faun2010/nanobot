"""Secret extraction and redaction helpers."""

from __future__ import annotations

import re
from typing import Any, Sequence

_SENSITIVE_KEY_HINTS = (
    "password",
    "passwd",
    "secret",
    "token",
    "api_key",
    "apikey",
    "access_key",
    "private_key",
)

_PLACEHOLDER_VALUES = {
    "",
    "***",
    "none",
    "null",
    "dummy",
    "changeme",
    "change-me",
    "replace-me",
    "your-api-key",
    "your-token",
    "your-password",
}

_SENSITIVE_KEY_PATTERN = (
    r"[A-Za-z0-9_.-]*(?:password|passwd|secret|token|api[_-]?key|access[_-]?key|private[_-]?key)[A-Za-z0-9_.-]*"
)

_JSON_DOUBLE_QUOTED = re.compile(
    rf'(?i)(?P<prefix>"(?P<key>{_SENSITIVE_KEY_PATTERN})"\s*:\s*")(?P<value>[^"\n]*)(?P<suffix>")'
)

_JSON_SINGLE_QUOTED = re.compile(
    rf"(?i)(?P<prefix>'(?P<key>{_SENSITIVE_KEY_PATTERN})'\s*:\s*')(?P<value>[^'\n]*)(?P<suffix>')"
)

_YAML_KEY_VALUE = re.compile(
    rf"(?im)^(?P<prefix>\s*(?P<key>{_SENSITIVE_KEY_PATTERN})\s*:\s*)(?P<value>[^#\r\n]+?)(?P<suffix>\s*(?:#.*)?)$"
)

_ENV_KEY_VALUE = re.compile(
    r"(?im)^(?P<prefix>\s*(?:export\s+)?"
    r"(?P<key>[A-Za-z0-9_]*(?:PASSWORD|PASSWD|SECRET|TOKEN|API_KEY|APIKEY|ACCESS_KEY|PRIVATE_KEY)[A-Za-z0-9_]*)"
    r"\s*=\s*)(?P<value>[^\r\n]+)$"
)


def _is_sensitive_key(key: str) -> bool:
    normalized = re.sub(r"[^a-z0-9]+", "_", key.lower()).strip("_")
    return any(hint in normalized for hint in _SENSITIVE_KEY_HINTS)


def _normalize_secret(value: str) -> str | None:
    candidate = value.strip()
    if not candidate:
        return None
    if candidate.lower() in _PLACEHOLDER_VALUES:
        return None
    if len(candidate) < 6:
        return None
    return candidate


def extract_secret_values(data: Any) -> list[str]:
    """Extract likely secret values from a nested object."""
    found: set[str] = set()

    def walk(node: Any, key_hint: str | None = None) -> None:
        if isinstance(node, dict):
            for key, value in node.items():
                walk(value, str(key))
            return
        if isinstance(node, list):
            for item in node:
                walk(item, key_hint)
            return
        if isinstance(node, str) and key_hint and _is_sensitive_key(key_hint):
            if secret := _normalize_secret(node):
                found.add(secret)

    walk(data)
    return sorted(found, key=len, reverse=True)


def _should_mask_value(raw: str, mask: str) -> bool:
    candidate = raw.strip()
    if not candidate or candidate == mask:
        return False
    if candidate.lower() in {"true", "false", "null", "none"}:
        return False
    return True


def _mask_preserving_quote(raw: str, mask: str) -> str:
    value = raw.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        inner = value[1:-1]
        if _should_mask_value(inner, mask):
            return f"{value[0]}{mask}{value[0]}"
    return mask if _should_mask_value(value, mask) else raw


def redact_sensitive_text(
    text: str,
    known_secrets: Sequence[str] | None = None,
    mask: str = "***",
) -> str:
    """Redact common secret shapes and known secret values from text."""
    if not text:
        return text

    redacted = text

    if known_secrets:
        normalized = [
            secret.strip()
            for secret in known_secrets
            if isinstance(secret, str) and _normalize_secret(secret)
        ]
        for secret in sorted(set(normalized), key=len, reverse=True):
            redacted = redacted.replace(secret, mask)

    def _replace_json(match: re.Match[str]) -> str:
        value = match.group("value")
        if not _should_mask_value(value, mask):
            return match.group(0)
        return f"{match.group('prefix')}{mask}{match.group('suffix')}"

    def _replace_yaml(match: re.Match[str]) -> str:
        value = match.group("value")
        if not _should_mask_value(value, mask):
            return match.group(0)
        masked = _mask_preserving_quote(value, mask)
        return f"{match.group('prefix')}{masked}{match.group('suffix')}"

    def _replace_env(match: re.Match[str]) -> str:
        value = match.group("value")
        if not _should_mask_value(value, mask):
            return match.group(0)
        masked = _mask_preserving_quote(value, mask)
        return f"{match.group('prefix')}{masked}"

    redacted = _JSON_DOUBLE_QUOTED.sub(_replace_json, redacted)
    redacted = _JSON_SINGLE_QUOTED.sub(_replace_json, redacted)
    redacted = _YAML_KEY_VALUE.sub(_replace_yaml, redacted)
    redacted = _ENV_KEY_VALUE.sub(_replace_env, redacted)

    return redacted
