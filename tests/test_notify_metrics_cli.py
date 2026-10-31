from __future__ import annotations

import io
import json
import sys
import urllib.error
from datetime import date
from pathlib import Path

import pytest

from sns_draft_queue.cli import main
from sns_draft_queue.config import Config
from sns_draft_queue.metrics import add, exit_code, judge
from sns_draft_queue.notify import notify, payloads
from sns_draft_queue.queue import create_draft


class Response:
    def __enter__(self) -> Response:
        return self

    def __exit__(self, *args: object) -> None:
        return None


def test_notify_file_and_webhook(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    draft = create_draft("cert", "2026-11-01", "x", ["投稿"], {})
    paths = notify(draft, None, tmp_path)
    assert len(paths) == 2
    assert "approve" in paths[0].read_text(encoding="utf-8")
    assert json.loads(paths[1].read_text(encoding="utf-8"))[0]["allowed_mentions"] == {"parse": []}
    calls = []

    def fake_urlopen(request: object, timeout: int) -> Response:
        calls.append(request)
        if len(calls) == 1:
            raise urllib.error.HTTPError(
                "https://secret.invalid/hook", 429, "rate", {}, io.BytesIO(b'{"retry_after":0}')
            )
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr("time.sleep", lambda _: None)
    notify(draft, "https://secret.invalid/hook", tmp_path)
    assert len(calls) == 2
    assert "secret.invalid" not in capsys.readouterr().err

    def failing_urlopen(request: object, timeout: int) -> Response:
        raise urllib.error.HTTPError("https://secret.invalid/hook", 500, "error", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", failing_urlopen)
    with pytest.raises(ValueError) as error:
        notify(draft, "https://secret.invalid/hook", tmp_path)
    assert "secret.invalid" not in str(error.value)


def test_discord_content_limit() -> None:
    draft = create_draft("cert", "2026-11-01", "long", ["あ" * 100] * 30, {})
    data = payloads(draft)
    assert len(data) > 1
    assert all(len(str(item["content"])) <= 2000 for item in data)


@pytest.mark.parametrize(
    ("plan", "impressions", "app_uu", "followers", "expected"),
    [
        ("B", 300, 200, "", "GO"),
        ("B", 299, 200, "", "NO-GO"),
        ("A", 0, 0, "150", "GO"),
        ("A", 300, 0, "", "GO"),
        ("A", 299, 0, "149", "NO-GO"),
    ],
)
def test_judge_branches(
    tmp_path: Path, plan: str, impressions: int, app_uu: int, followers: str, expected: str
) -> None:
    path = tmp_path / "metrics.csv"
    add(
        path,
        {
            "date": "2026-11-01",
            "plan": plan,
            "impressions": str(impressions),
            "app_uu": str(app_uu),
            "followers": followers,
            "bookmarks": "3",
        },
    )
    result = judge(path, plan, date(2026, 11, 1), 30, date(2026, 11, 30), Config())
    assert result["result"] == expected
    assert exit_code(result["result"]) == (0 if expected == "GO" else 1)
    pending = judge(path, plan, date(2026, 11, 1), 30, date(2026, 11, 2), Config())
    assert pending["result"] == "PENDING"
    assert exit_code(pending["result"]) == 2
    empty = judge(
        path, "A" if plan == "B" else "B", date(2026, 11, 1), 30, date(2026, 11, 30), Config()
    )
    assert empty["result"] == "NO_DATA"
    assert exit_code(empty["result"]) == 3


def test_cli_end_to_end(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
    source = Path(__file__).parent / "fixtures/cert-study"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "sns-queue",
            "cert",
            "daily",
            "--source",
            str(source),
            "--exam",
            "fe",
            "--date",
            "2026-11-01",
        ],
    )
    assert main() == 0
    draft_id = next((tmp_path / "queue").glob("*.json")).stem
    monkeypatch.setattr(sys, "argv", ["sns-queue", "notify", draft_id])
    assert main() == 0
    monkeypatch.setattr(sys, "argv", ["sns-queue", "queue", "approve", draft_id])
    assert main() == 0
    monkeypatch.setattr(sys, "argv", ["sns-queue", "publish", draft_id])
    assert main() == 0
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
            "300",
            "--app-uu",
            "200",
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
            "2026-11-30",
            "--json",
        ],
    )
    assert main() == 0
    assert '"result": "GO"' in capsys.readouterr().out
