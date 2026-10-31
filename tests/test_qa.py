from __future__ import annotations

import io
import sqlite3
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sns_draft_queue.config import Config
from sns_draft_queue.qa import Article, make_weekly, read_db, read_rss, select_weekly
from sns_draft_queue.queue import PLACEHOLDER

FEED = Path(__file__).parent / "fixtures/qa-feed.xml"
JST = ZoneInfo("Asia/Tokyo")


def test_rss_and_weekly_selection() -> None:
    articles = read_rss(str(FEED))
    assert len(articles) == 4
    assert articles[0].source == "QA Japan"
    chosen = select_weekly(articles, date(2026, 11, 1), 5)
    assert len(chosen) == 3
    assert {a.guid for a in chosen} == {"a1", "a2", "a3"}
    assert chosen == select_weekly(list(reversed(articles)), date(2026, 11, 1), 5)
    draft = make_weekly(articles, date(2026, 11, 1), 5, Config())
    assert len(draft["posts"]) == 5
    assert "主な話題:" in draft["posts"][0]
    assert PLACEHOLDER in draft["posts"][1]
    assert "note_markdown" in draft["meta"]


def test_rss_url_is_mocked(monkeypatch) -> None:
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda url, timeout: io.BytesIO(FEED.read_bytes()),
    )
    assert len(read_rss("https://example.org/feed.xml")) == 4


def test_source_cap_and_tags() -> None:
    articles = [
        Article(
            str(i),
            f"記事{i}",
            f"https://example.org/{i}",
            "同じソース" if i < 4 else "別ソース",
            datetime(2026, 10, 31, 12, tzinfo=JST),
            "ja",
            ("testing",),
        )
        for i in range(5)
    ]
    chosen = select_weekly(articles, date(2026, 11, 1), 5)
    assert sum(a.source == "同じソース" for a in chosen) == 2


def test_sqlite_input(tmp_path: Path) -> None:
    path = tmp_path / "articles.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE sources (id INTEGER, name TEXT, language TEXT)")
        connection.execute(
            "CREATE TABLE articles (guid TEXT, title TEXT, url TEXT, source_id INTEGER, published_at INTEGER, tags_json TEXT)"
        )
        connection.execute("INSERT INTO sources VALUES (1, 'QA Japan', 'ja')")
        connection.execute(
            "INSERT INTO articles VALUES (?, ?, ?, ?, ?, ?)",
            (
                "a",
                "記事",
                "https://example.org/a",
                1,
                int(datetime(2026, 10, 31, tzinfo=JST).timestamp()),
                '["testing"]',
            ),
        )
    articles = read_db(path)
    assert len(articles) == 1
    assert articles[0].language == "ja"
    assert select_weekly(articles, date(2026, 11, 1), 5)[0].guid == "a"
