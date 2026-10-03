import re
from functools import lru_cache


# Characters that may form part of a handle. An alias only counts as
# present when it is not embedded in a longer handle, so "8chan" does
# not match "8chanho" or "my8chan".
HANDLE_CHARS = r"A-Za-z0-9_"


@lru_cache(maxsize=256)
def alias_pattern(alias: str) -> re.Pattern:
    return re.compile(
        rf"(?<![{HANDLE_CHARS}]){re.escape(alias.strip())}(?![{HANDLE_CHARS}])",
        re.IGNORECASE,
    )


def find_mentions(text: str, alias: str) -> list[tuple[int, int]]:
    """Return (start, end) spans of whole-handle mentions of the alias."""

    if not text or not alias.strip():
        return []

    return [match.span() for match in alias_pattern(alias).finditer(text)]


def mentions_alias(text: str, alias: str) -> bool:
    return bool(text and alias.strip() and alias_pattern(alias).search(text))


def context_windows(
    text: str,
    spans: list[tuple[int, int]],
    radius: int = 300,
) -> list[str]:
    """
    Text surrounding each mention, with overlapping windows merged.
    Indicators found here are the ones plausibly tied to the alias.
    """

    merged: list[list[int]] = []

    for start, end in spans:
        left = max(0, start - radius)
        right = min(len(text), end + radius)

        if merged and left <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], right)
        else:
            merged.append([left, right])

    return [text[left:right] for left, right in merged]
