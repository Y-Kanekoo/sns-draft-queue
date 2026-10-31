from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from typing import cast
from urllib.parse import parse_qs, urlparse

import pytest

from sns_draft_queue.cert import choose_question, load_questions, make_daily
from sns_draft_queue.config import Config
from sns_draft_queue.publish import intent_url, publish
from sns_draft_queue.queue import create_draft, edit, load, save, save_new, transition
from sns_draft_queue.xtext import split_text, weighted_length

FIXTURE = Path(__file__).parent / "fixtures/cert-study"


def test_weighted_length_and_split() -> None:
    assert weighted_length("ABCあ🙂") == 7
    assert weighted_length("https://example.com/long/path") == 23
    text = "問" * 300
    chunks = split_text(text)
    assert "".join(chunks) == text
    assert all(weighted_length(chunk) <= 280 for chunk in chunks)


def test_cert_selection_and_format(tmp_path: Path) -> None:
    _, questions = load_questions(FIXTURE, "fe")
    day = date(2026, 11, 1)
    first = choose_question(questions, day, set())
    assert choose_question(questions, day, set())["id"] == first["id"]
    assert choose_question(questions, day, {str(first["id"])})["id"] != first["id"]
    assert choose_question(questions, day, {str(q["id"]) for q in questions})["id"] == first["id"]
    draft = make_daily(FIXTURE, "fe", day, tmp_path, Config())
    posts = draft["posts"]
    assert isinstance(posts, list)
    assert any("A." in post for post in posts)
    assert any("【解答】" in post for post in draft["answer_posts"])
    assert all("【解答】" not in post for post in posts)
    assert "diagram_text" in draft["meta"]
    url = next(url for post in posts for url in post.split() if url.startswith("https://"))
    assert parse_qs(urlparse(url).query)["utm_content"] == [first["id"]]
    assert all(weighted_length(post) <= 280 for post in posts)


def test_multi_and_self_exclusion(tmp_path: Path) -> None:
    _, questions = load_questions(FIXTURE, "jstqb")
    multi = next(q for q in questions if q["type"] == "multi")
    _, ap_questions = load_questions(FIXTURE, "ap")
    assert all(q["type"] != "self" for q in ap_questions)
    assert any(
        q["type"] == "self"
        for q in json.loads(
            (FIXTURE / "content/ap/questions/sample.json").read_text(encoding="utf-8")
        )
    )
    original = FIXTURE / "content/jstqb/questions/sample.json"
    data = json.loads(original.read_text(encoding="utf-8"))
    data = [multi]
    root = tmp_path / "content/jstqb"
    (root / "questions").mkdir(parents=True)
    (root / "exam.json").write_text('{"shortName":"JSTQB FL"}', encoding="utf-8")
    (root / "questions/sample.json").write_text(
        json.dumps(data, ensure_ascii=False), encoding="utf-8"
    )
    draft = make_daily(tmp_path, "jstqb", date(2026, 11, 1), tmp_path / "queue", Config())
    expected = "・".join("ABCDE"[index] for index in multi["answers"])
    assert any(f"【解答】{expected}" in post for post in draft["answer_posts"])
    assert "2つ選べ" in "\n".join(draft["posts"])
    assert draft["meta"]["question_id"] == multi["id"]


def test_transitions_placeholder_edit_and_publish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    draft = create_draft(
        "qa",
        "2026-11-01",
        "a",
        ["序文", "ひとこと:（ここに自分の見解を書く）", "RSS"],
        {"note_markdown": "# QA\n\nひとこと:（ここに自分の見解を書く）"},
    )
    save(tmp_path / "queue", draft)
    draft_id = str(draft["id"])
    with pytest.raises(ValueError, match="プレースホルダ"):
        transition(tmp_path / "queue", draft_id, "approved")
    with pytest.raises(ValueError, match="承認済み"):
        publish(draft, tmp_path / "out")
    editor = tmp_path / "editor.py"
    editor.write_text(
        'import pathlib,sys\npathlib.Path(sys.argv[1]).write_text(\'["序文", "ひとこと: 良い記事です", "RSS"]\')\n',
        encoding="utf-8",
    )
    monkeypatch.setenv("EDITOR", f"python {editor}")
    edit(tmp_path / "queue", draft_id)
    assert "良い記事" in load(tmp_path / "queue", draft_id)["meta"]["note_markdown"]
    approved = transition(tmp_path / "queue", draft_id, "approved")
    with pytest.raises(ValueError, match="pending"):
        transition(tmp_path / "queue", draft_id, "approved")
    md, html = publish(approved, tmp_path / "out")
    assert "intent/post" in md.read_text(encoding="utf-8")
    assert "textarea" in html.read_text(encoding="utf-8")
    transition(tmp_path / "queue", draft_id, "posted", url="https://x.com/a/status/1")
    assert load(tmp_path / "queue", draft_id)["status"] == "posted"


def test_intent_encoding() -> None:
    url = intent_url("A&B あ\n次")
    assert "A%26B%20%E3%81%82%0A" in url


def test_allow_placeholder_warns(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    draft = create_draft("qa", "2026-11-01", "warn", ["ひとこと:（ここに自分の見解を書く）"], {})
    save(tmp_path, draft)
    transition(tmp_path, str(draft["id"]), "approved", allow_placeholder=True)
    assert "警告" in capsys.readouterr().err


def test_existing_draft_is_not_overwritten(tmp_path: Path) -> None:
    draft = create_draft("qa", "2026-11-01", "same", ["投稿"], {})
    save_new(tmp_path, draft)
    transition(tmp_path, str(draft["id"]), "approved")
    with pytest.raises(ValueError, match="既に存在"):
        save_new(tmp_path, draft)
    assert load(tmp_path, str(draft["id"]))["status"] == "approved"


def test_choices_stay_in_one_post_when_they_fit(tmp_path: Path) -> None:
    for exam in ("fe", "ap", "jstqb"):
        draft = make_daily(FIXTURE, exam, date(2026, 11, 1), tmp_path / exam, Config())
        posts = cast(list[str], draft["posts"])
        holders = [post for post in posts if "A. " in post]
        assert len(holders) == 1
        choice_lines = [
            line for line in holders[0].splitlines() if line[:3] in {"A. ", "B. ", "C. ", "D. "}
        ]
        assert len(choice_lines) >= 4
