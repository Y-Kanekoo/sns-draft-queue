"""X の重み付き文字数と投稿分割。"""

from __future__ import annotations

import re
import unicodedata

URL_RE = re.compile(r"https?://[^\s]+")
LIMIT = 280


def weighted_length(value: str) -> int:
    def plain_length(part: str) -> int:
        return sum(
            1 if ord(char) < 128 or unicodedata.east_asian_width(char) == "H" else 2
            for char in part
        )

    total = 0
    cursor = 0
    for match in URL_RE.finditer(value):
        total += plain_length(value[cursor : match.start()]) + 23
        cursor = match.end()
    return total + plain_length(value[cursor:])


def split_text(value: str, limit: int = LIMIT) -> list[str]:
    """長い文だけを URL を保ったまま文字境界で分割する。"""
    if weighted_length(value) <= limit:
        return [value]
    result: list[str] = []
    current = ""
    for token in re.findall(r"https?://[^\s]+|[\s\S]", value):
        if weighted_length(token) > limit:
            raise ValueError("分割できない要素が文字数上限を超えています")
        if current and weighted_length(current + token) > limit:
            result.append(current)
            current = token
        else:
            current += token
    if current:
        result.append(current)
    return result


def pack_blocks(blocks: list[str], limit: int = LIMIT) -> list[str]:
    """段落を順番に詰め、長い段落だけ文単位で分割する。"""
    units: list[str] = []
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        if weighted_length(block) <= limit:
            units.append(block)
            continue
        sentences = re.findall(r"[^。]*。|[^。]+$", block)
        current_sentence = ""
        for sentence in sentences:
            if weighted_length(sentence) > limit:
                if current_sentence:
                    units.append(current_sentence)
                    current_sentence = ""
                units.extend(split_text(sentence, limit))
            elif current_sentence and weighted_length(current_sentence + sentence) > limit:
                units.append(current_sentence)
                current_sentence = sentence
            else:
                current_sentence += sentence
        if current_sentence:
            units.append(current_sentence)
    posts: list[str] = []
    current = ""
    for unit in units:
        candidate = f"{current}\n{unit}" if current else unit
        if weighted_length(candidate) <= limit:
            current = candidate
        else:
            posts.append(current)
            current = unit
    if current:
        posts.append(current)
    return posts


def validate_posts(posts: list[str]) -> None:
    if not posts or any(not post.strip() for post in posts):
        raise ValueError("投稿が空です")
    for index, post in enumerate(posts, 1):
        if weighted_length(post) > LIMIT:
            raise ValueError(f"{index}件目の投稿が280字を超えています")
