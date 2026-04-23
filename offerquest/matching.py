from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

TOKEN_RE = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class MatchableText:
    raw: str
    tokens: tuple[str, ...]
    token_set: frozenset[str]

    @property
    def normalized(self) -> str:
        return " ".join(self.tokens)


@lru_cache(maxsize=256)
def prepare_matchable_text(text: str) -> MatchableText:
    tokens = tuple(TOKEN_RE.findall(text.lower()))
    return MatchableText(
        raw=text,
        tokens=tokens,
        token_set=frozenset(tokens),
    )


def tokenize_text(text: str) -> list[str]:
    return list(TOKEN_RE.findall(text.lower()))


def contains_keyword(text: str | MatchableText, keyword: str) -> bool:
    prepared = text if isinstance(text, MatchableText) else prepare_matchable_text(text)
    needle = tuple(TOKEN_RE.findall(keyword.lower()))
    if not needle:
        return False
    if len(needle) == 1:
        return needle[0] in prepared.token_set
    return contains_token_sequence(prepared.tokens, needle)


def contains_any_keyword(text: str | MatchableText, keywords: list[str]) -> bool:
    return any(contains_keyword(text, keyword) for keyword in keywords)


def find_pattern_matches(text: str | MatchableText, patterns: dict[str, list[str]]) -> list[str]:
    return sorted(
        label
        for label, keywords in patterns.items()
        if contains_any_keyword(text, keywords)
    )


def contains_token_sequence(tokens: tuple[str, ...], needle: tuple[str, ...]) -> bool:
    if len(needle) > len(tokens):
        return False
    return any(tokens[index : index + len(needle)] == needle for index in range(len(tokens) - len(needle) + 1))
