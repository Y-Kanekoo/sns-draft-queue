"""Discord Webhook 通知。"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from pathlib import Path

from .queue import Draft, answer_posts_of, posts_of


def payloads(draft: Draft) -> list[dict[str, object]]:
    draft_id = str(draft["id"])
    intro = (
        f"下書き {draft_id} の承認をお願いします。\nCLI: sns-queue queue approve {draft_id}\n"
        "GitHub Actions: artifact をダウンロードし、queue import で取り込んでから確認してください。"
    )
    sections = [intro]
    label = "問題" if answer_posts_of(draft) else "投稿"
    sections.extend(f"{label} {index}: {post}" for index, post in enumerate(posts_of(draft), 1))
    sections.extend(
        f"解答 {index}（リプ欄/翌日用）: {post}"
        for index, post in enumerate(answer_posts_of(draft), 1)
    )
    messages: list[str] = []
    current = ""
    for section in sections:
        candidate = f"{current}\n\n{section}" if current else section
        if len(candidate) <= 2000:
            current = candidate
        else:
            if current:
                messages.append(current)
            current = section
    if current:
        messages.append(current)
    return [{"content": message, "allowed_mentions": {"parse": []}} for message in messages]


def notify(draft: Draft, webhook: str | None, outbox: Path) -> list[Path]:
    data = payloads(draft)
    if not webhook:
        outbox.mkdir(parents=True, exist_ok=True)
        base = outbox / str(draft["id"])
        markdown = base.with_suffix(".md")
        payload_json = base.with_suffix(".json")
        markdown.write_text(
            "\n\n".join(str(item["content"]) for item in data) + "\n", encoding="utf-8"
        )
        payload_json.write_text(
            json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        return [markdown, payload_json]
    if not webhook.startswith("https://"):
        raise ValueError("Discord Webhook URL の形式が不正です")
    for item in data:
        body = json.dumps(item, ensure_ascii=False).encode("utf-8")
        for attempt in range(2):
            request = urllib.request.Request(
                webhook, data=body, headers={"Content-Type": "application/json"}, method="POST"
            )
            try:
                with urllib.request.urlopen(request, timeout=20):
                    break
            except urllib.error.HTTPError as error:
                if error.code != 429 or attempt:
                    raise ValueError(f"Discord 通知に失敗しました（HTTP {error.code}）") from None
                try:
                    details = json.loads(error.read().decode("utf-8"))
                    delay = min(max(float(details.get("retry_after", 1)), 0), 60)
                except (ValueError, TypeError):
                    delay = 1
                time.sleep(delay)
            except urllib.error.URLError:
                raise ValueError("Discord 通知に失敗しました（接続エラー）") from None
            except (OSError, ValueError):
                raise ValueError("Discord 通知に失敗しました") from None
    return []
