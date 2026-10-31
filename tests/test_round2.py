from __future__ import annotations

import json
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from sns_draft_queue.cert import EXAMS, make_daily
from sns_draft_queue.cli import main
from sns_draft_queue.config import Config, load_config
from sns_draft_queue.notify import payloads
from sns_draft_queue.publish import publish
from sns_draft_queue.qa import Article, select_weekly
from sns_draft_queue.queue import (
    PLACEHOLDER,
    create_draft,
    import_drafts,
    load,
    save_new,
    transition,
)
from sns_draft_queue.xtext import pack_blocks, weighted_length

FIXTURE = Path(__file__).parent / "fixtures/cert-study"
JST = ZoneInfo("Asia/Tokyo")


def test_weighted_characters_and_greedy_packing() -> None:
    assert weighted_length("ABC") == 3
    assert weighted_length("全角") == 4
    assert weighted_length("🙂") == 2
    assert weighted_length("https://example.org/very/long/path") == 23
    assert weighted_length("前https://example.org/a 後") == 28
    assert pack_blocks(["A" * 140, "B" * 139, "C"]) == ["A" * 140 + "\n" + "B" * 139, "C"]
    assert pack_blocks(["短い問題", "A. はい\nB. いいえ", "#1日1問"]) == [
        "短い問題\nA. はい\nB. いいえ\n#1日1問"
    ]
    chunks = pack_blocks(["あ" * 100 + "。" + "い" * 100 + "。"])
    assert chunks == ["あ" * 100 + "。", "い" * 100 + "。"]
    long_sentence = "あ" * 150 + "。"
    assert "".join(pack_blocks([long_sentence])) == long_sentence
    assert all(weighted_length(post) <= 280 for post in pack_blocks([long_sentence]))


def test_cert_roles_hashtags_rotation_and_used_history(tmp_path: Path) -> None:
    day = date(2026, 11, 1)
    config = Config()
    for offset in range(3):
        current = day + timedelta(days=offset)
        draft = make_daily(FIXTURE, "all", current, tmp_path, config)
        exam = EXAMS[current.toordinal() % len(EXAMS)]
        assert draft["meta"]["exam"] == exam
        assert config.hashtags[exam][0] in "\n".join(draft["posts"])
        assert all("【解答】" not in post for post in draft["posts"])
        assert "【解答】" in "\n".join(draft["answer_posts"])
        assert all("※問題はAI" not in post for post in draft["posts"])
        assert draft["answer_posts"][-1] != config.ai_label
    first = make_daily(FIXTURE, "fe", day, tmp_path, config)
    assert len(first["posts"]) == 1
    save_new(tmp_path, first)
    second = make_daily(FIXTURE, "fe", day, tmp_path, config)
    assert second["meta"]["question_id"] != first["meta"]["question_id"]
    assert (
        make_daily(FIXTURE, "fe", day, tmp_path, config)["meta"]["question_id"]
        == second["meta"]["question_id"]
    )


@pytest.mark.parametrize(
    ("initial", "action"),
    [
        ("pending", "posted"),
        ("approved", "approved"),
        ("approved", "rejected"),
        ("rejected", "approved"),
        ("rejected", "posted"),
        ("posted", "approved"),
        ("posted", "rejected"),
        ("posted", "posted"),
    ],
)
def test_invalid_transitions(tmp_path: Path, initial: str, action: str) -> None:
    draft = create_draft("cert", "2026-11-01", "x", ["問題"], {}, ["解答"])
    draft["status"] = initial
    save_new(tmp_path, draft)
    with pytest.raises(ValueError):
        transition(tmp_path, str(draft["id"]), action, url="https://x.com/a/status/1")


def test_import_preserves_existing_and_checks_answer_placeholder(tmp_path: Path) -> None:
    source = tmp_path / "artifact"
    queue = tmp_path / "queue"
    draft = create_draft("cert", "2026-11-01", "x", ["問題"], {}, [PLACEHOLDER])
    save_new(source, draft)
    assert import_drafts(queue, source) == (1, 0)
    with pytest.raises(ValueError, match="プレースホルダ"):
        transition(queue, str(draft["id"]), "approved")
    existing = load(queue, str(draft["id"]))
    existing["posts"] = ["手動変更"]
    from sns_draft_queue.queue import save

    save(queue, existing)
    assert import_drafts(queue, source) == (0, 1)
    assert load(queue, str(draft["id"]))["posts"] == ["手動変更"]


def test_invalid_transition_inputs(tmp_path: Path) -> None:
    draft = create_draft("qa", "2026-11-01", "x", ["投稿"], {})
    save_new(tmp_path, draft)
    draft_id = str(draft["id"])
    with pytest.raises(ValueError, match="却下理由"):
        transition(tmp_path, draft_id, "rejected")
    with pytest.raises(ValueError, match="不正な操作"):
        transition(tmp_path, draft_id, "unknown")
    transition(tmp_path, draft_id, "approved")
    with pytest.raises(ValueError, match="投稿URL"):
        transition(tmp_path, draft_id, "posted", url="https://example.org/post/1")


def test_configurable_exam_hashtags(tmp_path: Path) -> None:
    path = tmp_path / "config.toml"
    path.write_text('[display]\nhashtags = { fe = ["#独自", "#共通"] }\n', encoding="utf-8")
    config = load_config(path)
    assert config.hashtags["fe"] == ("#独自", "#共通")
    assert config.hashtags["ap"] == Config().hashtags["ap"]


def test_publish_roles_encoding_and_html_escape(tmp_path: Path) -> None:
    draft = create_draft("cert", "2026-11-01", "x", ["<script>&あ"], {}, ["解答"])
    with pytest.raises(ValueError, match="承認済み"):
        publish(draft, tmp_path)
    draft["status"] = "approved"
    markdown, html = publish(draft, tmp_path)
    assert "問題を順に投稿し、解答は最初の問題投稿へのリプ欄" in markdown.read_text()
    assert "## 解答（リプ欄/翌日用）" in markdown.read_text()
    html_text = html.read_text()
    assert "&lt;script&gt;&amp;あ" in html_text
    assert "%3Cscript%3E%26%E3%81%82" in html_text


def test_notify_roles_and_limit() -> None:
    draft = create_draft("cert", "2026-11-01", "x", ["あ" * 140] * 20, {}, ["解答"])
    messages = payloads(draft)
    assert len(messages) >= 2
    assert all(len(str(message["content"])) <= 2000 for message in messages)
    assert all(message["allowed_mentions"] == {"parse": []} for message in messages)
    combined = "\n".join(str(message["content"]) for message in messages)
    assert "問題 1:" in combined
    assert "解答 1（リプ欄/翌日用）:" in combined


def test_qa_jst_boundaries_and_language_priority() -> None:
    start = datetime(2026, 10, 26, 0, 0, tzinfo=JST)
    end = datetime(2026, 11, 1, 23, 59, tzinfo=JST)
    articles = [
        Article("start", "開始", "https://example.org/1", "s1", start, "ja"),
        Article("end", "終了", "https://example.org/2", "s2", end, "ja"),
        Article("before", "前", "https://example.org/3", "s3", start - timedelta(minutes=1), "ja"),
        Article("after", "後", "https://example.org/4", "s4", end + timedelta(minutes=1), "ja"),
        Article("english", "English", "https://example.org/5", "s5", end, "en"),
    ]
    assert select_weekly(articles, date(2026, 11, 1), 1)[0].guid == "end"
    selected = select_weekly(articles, date(2026, 11, 1), 3)
    assert {article.guid for article in selected} == {"start", "end", "english"}
    assert selected == select_weekly(list(reversed(articles)), date(2026, 11, 1), 3)


def test_cli_import_and_missing_metric_text(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    source = tmp_path / "artifact"
    draft = create_draft("cert", "2026-11-01", "x", ["問題"], {}, ["解答"])
    save_new(source, draft)
    monkeypatch.setattr(sys, "argv", ["sns-queue", "queue", "import", str(source)])
    assert main() == 0
    assert "取込: 1件" in capsys.readouterr().out
    assert main() == 0
    assert "スキップ: 1件" in capsys.readouterr().out
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "sns-queue",
            "metrics",
            "add",
            "--plan",
            "B",
            "--date",
            "2026-11-01",
            "--impressions",
            "100",
        ],
    )
    assert main() == 0
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "sns-queue",
            "metrics",
            "judge",
            "--plan",
            "B",
            "--start",
            "2026-11-01",
            "--today",
            "2026-11-15",
        ],
    )
    assert main() == 2
    assert "未記録" in capsys.readouterr().out


def test_example_metrics_have_thirty_demo_days() -> None:
    path = Path(__file__).parents[1] / "examples/demo/metrics/metrics.csv"
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 61
    assert all("架空のデモ値" in line for line in lines[1:])
    for stem, result in (("b-go", "GO"), ("a-no-go", "NO-GO"), ("b-pending", "PENDING")):
        data = json.loads(path.with_name(stem + ".json").read_text())
        assert data["result"] == result
