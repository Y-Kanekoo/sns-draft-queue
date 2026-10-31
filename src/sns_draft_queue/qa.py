"""qa-radar の RSS / SQLite から週刊下書きを作る。"""

from __future__ import annotations

import json
import sqlite3
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from .config import Config
from .queue import PLACEHOLDER, Draft, create_draft
from .xtext import weighted_length

JST = ZoneInfo("Asia/Tokyo")


@dataclass(frozen=True)
class Article:
    guid: str
    title: str
    url: str
    source: str
    published: datetime
    language: str = ""
    tags: tuple[str, ...] = ()


def read_rss(feed: str) -> list[Article]:
    parsed = urlparse(feed)
    if parsed.scheme in {"http", "https"}:
        with urllib.request.urlopen(feed, timeout=20) as response:
            content = response.read()
    elif parsed.scheme == "":
        content = Path(feed).read_bytes()
    else:
        raise ValueError("フィードは HTTP(S) URL またはローカルファイルを指定してください")
    root = ET.fromstring(content)
    articles = []
    for item in root.findall("./channel/item"):
        description = item.findtext("description", "")
        source = next(
            (
                line.removeprefix("出所:").strip()
                for line in reversed(description.splitlines())
                if line.strip().startswith("出所:")
            ),
            "不明",
        )
        published = parsedate_to_datetime(item.findtext("pubDate", ""))
        if published.tzinfo is None:
            published = published.replace(tzinfo=JST)
        title = item.findtext("title", "")
        articles.append(
            Article(
                item.findtext("guid", "") or item.findtext("link", ""),
                title,
                item.findtext("link", ""),
                source,
                published,
                "ja" if any("\u3040" <= char <= "\u9fff" for char in title) else "en",
                tuple(category.text or "" for category in item.findall("category")),
            )
        )
    return articles


def read_db(path: Path) -> list[Article]:
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as connection:
        rows = connection.execute(
            "SELECT a.guid, a.title, a.url, s.name, a.published_at, s.language, a.tags_json FROM articles a JOIN sources s ON a.source_id = s.id"
        ).fetchall()
    return [
        Article(
            str(guid),
            str(title),
            str(url),
            str(source),
            datetime.fromtimestamp(int(timestamp), JST),
            str(language),
            tuple(json.loads(str(tags))),
        )
        for guid, title, url, source, timestamp, language, tags in rows
    ]


def select_weekly(articles: list[Article], week_end: date, top: int) -> list[Article]:
    if top < 1:
        raise ValueError("--top は1以上にしてください")
    start = week_end - timedelta(days=6)
    eligible = [
        article
        for article in articles
        if start <= article.published.astimezone(JST).date() <= week_end
    ]
    eligible.sort(key=lambda a: (a.published, a.guid), reverse=True)
    selected: list[Article] = []
    source_counts: dict[str, int] = {}
    tag_counts: dict[str, int] = {}
    while eligible and len(selected) < top:
        candidates = [a for a in eligible if source_counts.get(a.source, 0) < 2]
        if not candidates:
            break

        def score(article: Article) -> tuple[int, int, int, str]:
            language_bonus = 2 if article.language == "ja" else 0
            if (
                article.language != "ja"
                and selected
                and all(item.language == "ja" for item in selected)
            ):
                language_bonus = 3
            tag_penalty = sum(tag_counts.get(tag, 0) for tag in article.tags)
            return (
                language_bonus,
                -source_counts.get(article.source, 0) - tag_penalty,
                int(article.published.timestamp()),
                article.guid,
            )

        chosen = max(candidates, key=score)
        selected.append(chosen)
        source_counts[chosen.source] = source_counts.get(chosen.source, 0) + 1
        for tag in chosen.tags:
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
        eligible.remove(chosen)
    return selected


def make_weekly(articles: list[Article], week_end: date, top: int, config: Config) -> Draft:
    selected = select_weekly(articles, week_end, top)
    if not selected:
        raise ValueError("指定週に記事がありません")
    prefix = "PR\n" if config.sponsored else ""
    topics = list(dict.fromkeys(tag for article in selected for tag in article.tags if tag))
    focus = "・".join(topics[:2]) if topics else selected[0].title
    intro = (
        prefix
        + f"【QA週刊ダイジェスト】{week_end.isoformat()}までの7日間。"
        + f"注目記事{len(selected)}件。主な話題: {focus}。"
    )
    if weighted_length(intro) > 280:
        intro = (
            prefix
            + f"【QA週刊ダイジェスト】{week_end.isoformat()}までの7日間。注目記事{len(selected)}件。主な話題: QAの新着記事。"
        )
    posts = [intro]
    for article in selected:
        suffix = f"\n出所: {article.source}\n{article.url}\nひとこと:{PLACEHOLDER}"
        title = article.title
        if weighted_length(title + suffix) > 280:
            budget = 280 - weighted_length(suffix) - weighted_length("…")
            title = ""
            for char in article.title:
                if weighted_length(title + char) > budget:
                    break
                title += char
            title += "…"
        post = title + suffix
        if weighted_length(post) > 280:
            raise ValueError(f"出所とリンクが1投稿に収まりません: {article.guid}")
        posts.append(post)
    posts.append(f"qa-radar の RSS: {config.rss_url}")
    metadata: Draft = {
        "article_guids": [article.guid for article in selected],
        "note_markdown": "# QA週刊ダイジェスト\n\n"
        + "\n\n".join(
            f"## {article.title}\n\n出所: {article.source}\n\n{article.url}\n\nひとこと:{PLACEHOLDER}"
            for article in selected
        )
        + f"\n\nRSS: {config.rss_url}\n",
    }
    return create_draft(
        "qa", week_end.isoformat(), "|".join(article.guid for article in selected), posts, metadata
    )
