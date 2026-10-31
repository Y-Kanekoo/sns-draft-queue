"""CLI エントリ。"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Never
from zoneinfo import ZoneInfo

from .cert import make_daily
from .config import load_config
from .metrics import add, exit_code, judge
from .notify import notify
from .publish import publish
from .qa import make_weekly, read_db, read_rss
from .queue import edit, import_drafts, list_drafts, load, save_new, transition


class JapaneseParser(argparse.ArgumentParser):
    def error(self, message: str) -> Never:
        self.exit(2, "エラー: 引数を確認してください。--help で使い方を表示できます。\n")


def parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("日付は YYYY-MM-DD で指定してください") from error


def display_metric(value: object) -> str:
    return "未記録" if value is None else str(value)


def parser() -> argparse.ArgumentParser:
    root = JapaneseParser(prog="sns-queue", description="承認付き SNS 下書きキュー")
    root.add_argument("--config", type=Path, default=Path("config.toml"))
    commands = root.add_subparsers(dest="command", required=True)

    cert = commands.add_parser("cert")
    cert_commands = cert.add_subparsers(dest="subcommand", required=True)
    daily = cert_commands.add_parser("daily")
    daily.add_argument("--source", required=True, type=Path)
    daily.add_argument("--exam", choices=("fe", "ap", "jstqb", "all"), default="all")
    daily.add_argument(
        "--date", type=parse_date, default=datetime.now(ZoneInfo("Asia/Tokyo")).date()
    )
    daily.add_argument("--queue-dir", type=Path, default=Path("queue"))

    qa = commands.add_parser("qa")
    qa_commands = qa.add_subparsers(dest="subcommand", required=True)
    weekly = qa_commands.add_parser("weekly")
    feed_group = weekly.add_mutually_exclusive_group(required=True)
    feed_group.add_argument("--feed")
    feed_group.add_argument("--db", type=Path)
    weekly.add_argument(
        "--week-end", type=parse_date, default=datetime.now(ZoneInfo("Asia/Tokyo")).date()
    )
    weekly.add_argument("--top", type=int, default=5)

    queue = commands.add_parser("queue")
    queue_commands = queue.add_subparsers(dest="subcommand", required=True)
    listing = queue_commands.add_parser("list")
    listing.add_argument("--status", choices=("pending", "approved", "rejected", "posted"))
    show = queue_commands.add_parser("show")
    show.add_argument("id")
    approve = queue_commands.add_parser("approve")
    approve.add_argument("id")
    approve.add_argument("--note", default="")
    approve.add_argument("--allow-placeholder", action="store_true")
    reject = queue_commands.add_parser("reject")
    reject.add_argument("id")
    reject.add_argument("--reason", required=True)
    editing = queue_commands.add_parser("edit")
    editing.add_argument("id")
    posted = queue_commands.add_parser("mark-posted")
    posted.add_argument("id")
    posted.add_argument("--url", required=True)
    importing = queue_commands.add_parser("import")
    importing.add_argument("dir", type=Path)

    notification = commands.add_parser("notify")
    notification.add_argument("id", nargs="?")
    notification.add_argument("--pending", action="store_true")
    publication = commands.add_parser("publish")
    publication.add_argument("id")

    metrics = commands.add_parser("metrics")
    metrics_commands = metrics.add_subparsers(dest="subcommand", required=True)
    adding = metrics_commands.add_parser("add")
    adding.add_argument("--plan", choices=("A", "B"), required=True)
    adding.add_argument("--date", type=parse_date, required=True)
    adding.add_argument("--impressions", type=int, required=True)
    for name in ("app-uu", "followers", "bookmarks"):
        adding.add_argument(f"--{name}", type=int)
    adding.add_argument("--post-id", default="")
    adding.add_argument("--note", default="")
    judging = metrics_commands.add_parser("judge")
    judging.add_argument("--plan", choices=("A", "B"), required=True)
    judging.add_argument("--start", type=parse_date, required=True)
    judging.add_argument("--days", type=int, default=30)
    judging.add_argument(
        "--today", type=parse_date, default=datetime.now(ZoneInfo("Asia/Tokyo")).date()
    )
    judging.add_argument("--json", action="store_true")
    return root


def run(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    queue_dir = Path(getattr(args, "queue_dir", "queue"))
    if args.command == "cert":
        draft = make_daily(args.source, args.exam, args.date, queue_dir, config)
        path = save_new(queue_dir, draft)
        print(f"下書きを保存しました: {path}")
    elif args.command == "qa":
        articles = read_rss(args.feed) if args.feed else read_db(args.db)
        draft = make_weekly(articles, args.week_end, args.top, config)
        path = save_new(queue_dir, draft)
        print(f"下書きを保存しました: {path}")
    elif args.command == "queue":
        if args.subcommand == "import":
            imported, skipped = import_drafts(queue_dir, args.dir)
            print(f"取込: {imported}件、既存IDをスキップ: {skipped}件")
        elif args.subcommand == "list":
            for draft in list_drafts(queue_dir, args.status):
                print(f"{draft['id']}  {draft['status']}  {draft['kind']}")
        elif args.subcommand == "show":
            print(json.dumps(load(queue_dir, args.id), ensure_ascii=False, indent=2))
        elif args.subcommand == "edit":
            edit(queue_dir, args.id)
            print("下書きを更新しました")
        else:
            action = {"approve": "approved", "reject": "rejected", "mark-posted": "posted"}[
                args.subcommand
            ]
            transition(
                queue_dir,
                args.id,
                action,
                getattr(args, "note", getattr(args, "reason", "")),
                getattr(args, "allow_placeholder", False),
                getattr(args, "url", ""),
            )
            print(f"状態を {action} に変更しました")
    elif args.command == "notify":
        if bool(args.id) == bool(args.pending):
            raise ValueError("ID または --pending のどちらかを指定してください")
        drafts = list_drafts(queue_dir, "pending") if args.pending else [load(queue_dir, args.id)]
        for draft in drafts:
            if draft["status"] != "pending":
                raise ValueError("通知できるのは pending の下書きだけです")
            paths = notify(draft, os.environ.get("DISCORD_WEBHOOK_URL"), Path("outbox/discord"))
            print(
                f"通知を処理しました: {draft['id']}"
                + (f" ({', '.join(map(str, paths))})" if paths else "")
            )
    elif args.command == "publish":
        published_paths = publish(load(queue_dir, args.id), Path("outbox/x"))
        print(f"公開用ファイルを保存しました: {published_paths[0]}, {published_paths[1]}")
    elif args.command == "metrics":
        path = Path("metrics/metrics.csv")
        if args.subcommand == "add":
            numeric = ("impressions", "app_uu", "followers", "bookmarks")
            if any(getattr(args, name) is not None and getattr(args, name) < 0 for name in numeric):
                raise ValueError("指標には0以上の値を指定してください")
            row = {
                "date": args.date.isoformat(),
                "plan": args.plan,
                "post_id": args.post_id,
                "note": args.note,
            }
            row.update(
                {
                    name: "" if getattr(args, name) is None else str(getattr(args, name))
                    for name in numeric
                }
            )
            add(path, row)
            print(f"指標を記録しました: {path}")
        else:
            result = judge(path, args.plan, args.start, args.days, args.today, config)
            if args.json:
                print(json.dumps(result, ensure_ascii=False))
            else:
                print(f"判定: {result['result']}（{result['start']}〜{result['end']}）")
                print(
                    f"件数: {result['rows']}、平均表示数: {display_metric(result['impressions_average'])}、アプリUU: {result['app_uu']}、フォロワー: {display_metric(result['followers'])}"
                )
                print(
                    f"保存率: {display_metric(result['bookmark_rate'])}（参考目安: {config.bookmark_rate_reference:.0%}）"
                )
                if result["result"] == "PENDING":
                    print(
                        f"残り{result['days_remaining']}日、必要ペース: アプリUU/日={display_metric(result['needed_app_uu_per_day'])}、フォロワー/日={display_metric(result['needed_followers_per_day'])}、今後1日1投稿なら平均表示数/投稿={display_metric(result['needed_impressions_per_future_post'])}"
                    )
            return exit_code(result["result"])
    return 0


def main() -> int:
    args = parser().parse_args()
    try:
        return run(args)
    except (ValueError, OSError, KeyError, IndexError) as error:
        print(f"エラー: {error}", file=sys.stderr)
        return 1
