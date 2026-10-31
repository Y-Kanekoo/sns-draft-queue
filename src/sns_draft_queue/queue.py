"""JSON キューと承認状態。"""

from __future__ import annotations

import hashlib
import json
import os
import shlex
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import cast
from zoneinfo import ZoneInfo

from .xtext import validate_posts

JST = ZoneInfo("Asia/Tokyo")
Draft = dict[str, object]
PLACEHOLDER = "（ここに自分の見解を書く）"


def now() -> str:
    return datetime.now(JST).isoformat(timespec="seconds")


def create_id(kind: str, date: str, key: str) -> str:
    digest = hashlib.sha256(key.encode()).hexdigest()[:10]
    return f"{kind}-{date}-{digest}"


def create_draft(
    kind: str,
    date: str,
    key: str,
    posts: list[str],
    meta: Draft,
    answer_posts: list[str] | None = None,
) -> Draft:
    validate_posts(posts)
    if answer_posts is not None:
        validate_posts(answer_posts)
    draft_id = create_id(kind, date, key)
    draft: Draft = {
        "id": draft_id,
        "kind": kind,
        "date": date,
        "status": "pending",
        "posts": posts,
        "meta": meta,
        "created_at": now(),
        "history": [{"at": now(), "action": "created", "note": ""}],
    }
    if answer_posts is not None:
        draft["answer_posts"] = answer_posts
    return draft


def save(queue_dir: Path, draft: Draft) -> Path:
    queue_dir.mkdir(parents=True, exist_ok=True)
    draft_id = str(draft["id"])
    if Path(draft_id).name != draft_id:
        raise ValueError("不正な下書きIDです")
    path = queue_dir / f"{draft_id}.json"
    path.write_text(json.dumps(draft, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def save_new(queue_dir: Path, draft: Draft) -> Path:
    queue_dir.mkdir(parents=True, exist_ok=True)
    draft_id = str(draft["id"])
    if Path(draft_id).name != draft_id:
        raise ValueError("不正な下書きIDです")
    path = queue_dir / f"{draft_id}.json"
    try:
        with path.open("x", encoding="utf-8") as stream:
            stream.write(json.dumps(draft, ensure_ascii=False, indent=2) + "\n")
    except FileExistsError:
        raise ValueError(f"同じ下書きが既に存在します: {draft_id}") from None
    return path


def load(queue_dir: Path, draft_id: str) -> Draft:
    if Path(draft_id).name != draft_id:
        raise ValueError("不正な下書きIDです")
    path = queue_dir / f"{draft_id}.json"
    if not path.is_file():
        raise ValueError(f"下書きが見つかりません: {draft_id}")
    return cast(Draft, json.loads(path.read_text(encoding="utf-8")))


def list_drafts(queue_dir: Path, status: str | None = None) -> list[Draft]:
    drafts = [
        cast(Draft, json.loads(path.read_text(encoding="utf-8")))
        for path in sorted(queue_dir.glob("*.json"))
    ]
    return [draft for draft in drafts if status is None or draft.get("status") == status]


def posts_of(draft: Draft) -> list[str]:
    posts = draft.get("posts")
    if not isinstance(posts, list) or not all(isinstance(post, str) for post in posts):
        raise ValueError("投稿データが不正です")
    return cast(list[str], posts)


def answer_posts_of(draft: Draft) -> list[str]:
    posts = draft.get("answer_posts", [])
    if not isinstance(posts, list) or not all(isinstance(post, str) for post in posts):
        raise ValueError("解答投稿データが不正です")
    return cast(list[str], posts)


def import_drafts(queue_dir: Path, source_dir: Path) -> tuple[int, int]:
    if not source_dir.is_dir():
        raise ValueError(f"取込元ディレクトリが見つかりません: {source_dir}")
    imported = skipped = 0
    for path in sorted(source_dir.glob("*.json")):
        draft = cast(Draft, json.loads(path.read_text(encoding="utf-8")))
        if not isinstance(draft, dict) or draft.get("id") != path.stem:
            raise ValueError(f"下書きIDとファイル名が一致しません: {path.name}")
        if draft.get("status") not in {"pending", "approved", "rejected", "posted"}:
            raise ValueError(f"下書き状態が不正です: {path.name}")
        validate_posts(posts_of(draft))
        if "answer_posts" in draft:
            validate_posts(answer_posts_of(draft))
        if (queue_dir / path.name).exists():
            skipped += 1
            continue
        save_new(queue_dir, draft)
        imported += 1
    return imported, skipped


def transition(
    queue_dir: Path,
    draft_id: str,
    action: str,
    note: str = "",
    allow_placeholder: bool = False,
    url: str = "",
) -> Draft:
    draft = load(queue_dir, draft_id)
    expected = "approved" if action == "posted" else "pending"
    if draft["status"] != expected:
        raise ValueError(f"{action} は {expected} の下書きだけに実行できます")
    meta = cast(Draft, draft.get("meta", {}))
    has_placeholder = any(
        PLACEHOLDER in post for post in posts_of(draft) + answer_posts_of(draft)
    ) or PLACEHOLDER in str(meta.get("note_markdown", ""))
    if action == "approved" and has_placeholder:
        if not allow_placeholder:
            raise ValueError(
                "見解のプレースホルダが残っています。編集するか --allow-placeholder を指定してください"
            )
        print("警告: 見解のプレースホルダを残して承認します", file=sys.stderr)
    if action == "posted":
        if not url.startswith("https://x.com/") and not url.startswith("https://twitter.com/"):
            raise ValueError("X の投稿URLを指定してください")
        draft["post_url"] = url
    if action == "rejected" and not note.strip():
        raise ValueError("却下理由を入力してください")
    if action not in {"approved", "rejected", "posted"}:
        raise ValueError("不正な操作です")
    draft["status"] = action
    history = cast(list[Draft], draft["history"])
    history.append({"at": now(), "action": action, "note": note})
    save(queue_dir, draft)
    return draft


def edit(queue_dir: Path, draft_id: str) -> Draft:
    draft = load(queue_dir, draft_id)
    if draft["status"] != "pending":
        raise ValueError("編集できるのは pending の下書きだけです")
    editor = os.environ.get("EDITOR", "vi")
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(temporary) / "posts.json"
        editable: object = (
            {"posts": posts_of(draft), "answer_posts": answer_posts_of(draft)}
            if "answer_posts" in draft
            else posts_of(draft)
        )
        path.write_text(json.dumps(editable, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        subprocess.run([*shlex.split(editor), str(path)], check=True)
        edited = json.loads(path.read_text(encoding="utf-8"))
    if "answer_posts" in draft:
        if not isinstance(edited, dict) or set(edited) != {"posts", "answer_posts"}:
            raise ValueError(
                "編集結果は posts と answer_posts を含むJSONオブジェクトにしてください"
            )
        candidate = cast(dict[str, object], edited)
        answers = candidate["answer_posts"]
        if not isinstance(answers, list) or not all(isinstance(post, str) for post in answers):
            raise ValueError("answer_posts は文字列のJSON配列にしてください")
        validate_posts(cast(list[str], answers))
        draft["answer_posts"] = answers
        edited = candidate["posts"]
    if not isinstance(edited, list) or not all(isinstance(post, str) for post in edited):
        raise ValueError("編集結果は文字列のJSON配列にしてください")
    posts = cast(list[str], edited)
    validate_posts(posts)
    draft["posts"] = posts
    meta = cast(Draft, draft.get("meta", {}))
    if draft.get("kind") == "qa" and "note_markdown" in meta:
        meta["note_markdown"] = "# QA週刊ダイジェスト\n\n" + "\n\n".join(posts[1:]) + "\n"
    cast(list[Draft], draft["history"]).append({"at": now(), "action": "edited", "note": ""})
    save(queue_dir, draft)
    return draft
