"""承認済みの下書きを X intent とコピー用ファイルに出力する。"""

from __future__ import annotations

from html import escape
from pathlib import Path
from urllib.parse import quote

from .queue import Draft, answer_posts_of, posts_of


def intent_url(post: str) -> str:
    return f"https://x.com/intent/post?text={quote(post, safe='')}"


def publish(draft: Draft, outbox: Path) -> tuple[Path, Path]:
    if draft["status"] != "approved":
        raise ValueError("承認済みの下書きだけを公開用に出力できます")
    posts = posts_of(draft)
    outbox.mkdir(parents=True, exist_ok=True)
    base = outbox / str(draft["id"])
    markdown = base.with_suffix(".md")
    html = base.with_suffix(".html")
    answers = answer_posts_of(draft)
    instruction = (
        "問題を順に投稿し、解答は最初の問題投稿へのリプ欄に投稿するか、翌日に投稿してください。"
        if answers
        else "1件目を投稿後、返信として2件目以降を順に投稿してください。"
        if len(posts) > 1
        else "リンクを開いて投稿内容を確認してください。"
    )
    md_sections = [f"# {draft['id']}", instruction]
    html_sections = [
        f"<!doctype html><html lang='ja'><meta charset='utf-8'><title>{escape(str(draft['id']))}</title><body><h1>{escape(str(draft['id']))}</h1><p>{instruction}</p>"
    ]
    for role, group in (("問題" if answers else "投稿", posts), ("解答（リプ欄/翌日用）", answers)):
        for index, post in enumerate(group, 1):
            url = intent_url(post)
            md_sections.append(f"## {role} {index}\n\n{post}\n\n[投稿画面を開く]({url})")
            html_sections.append(
                f"<section><h2>{escape(role)} {index}</h2><textarea rows='8' cols='70' readonly>{escape(post)}</textarea><p><a href='{escape(url, quote=True)}' target='_blank' rel='noopener noreferrer'>投稿画面を開く</a></p></section>"
            )
    html_sections.append("</body></html>")
    markdown.write_text("\n\n".join(md_sections) + "\n", encoding="utf-8")
    html.write_text("\n".join(html_sections) + "\n", encoding="utf-8")
    return markdown, html
