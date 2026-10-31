"""30日検証の記録と判定。"""

from __future__ import annotations

import csv
from datetime import date, timedelta
from pathlib import Path
from typing import TypedDict

from .config import Config

FIELDS = ("date", "plan", "post_id", "impressions", "app_uu", "followers", "bookmarks", "note")


class Judgment(TypedDict):
    result: str
    plan: str
    start: str
    end: str
    rows: int
    impressions_average: float | None
    app_uu: int
    followers: int | None
    bookmark_rate: float | None
    days_remaining: int
    needed_app_uu_per_day: float | None
    needed_followers_per_day: float | None
    needed_impressions_per_future_post: float | None


def add(path: Path, row: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    exists = path.is_file() and path.stat().st_size > 0
    with path.open("a", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=FIELDS)
        if not exists:
            writer.writeheader()
        writer.writerow({field: row.get(field, "") for field in FIELDS})


def read(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", newline="") as stream:
        return list(csv.DictReader(stream))


def judge(path: Path, plan: str, start: date, days: int, today: date, config: Config) -> Judgment:
    if days < 1:
        raise ValueError("--days は1以上にしてください")
    end = start + timedelta(days=days - 1)
    rows = [
        row
        for row in read(path)
        if row["plan"] == plan and start.isoformat() <= row["date"] <= min(end, today).isoformat()
    ]
    impressions = [int(row["impressions"]) for row in rows if row["impressions"] != ""]
    bookmarks = [int(row["bookmarks"]) for row in rows if row["bookmarks"] != ""]
    app_uu = sum(int(row["app_uu"]) for row in rows if row["app_uu"] != "")
    followers_rows = [row for row in rows if row["followers"] != ""]
    latest = (
        max(enumerate(followers_rows), key=lambda item: (item[1]["date"], item[0]))[1]
        if followers_rows
        else None
    )
    followers = int(latest["followers"]) if latest else None
    average = sum(impressions) / len(impressions) if impressions else None
    bookmark_rate = sum(bookmarks) / sum(impressions) if impressions and sum(impressions) else None
    remaining = max((end - today).days, 0)
    impression_target = config.b_avg_impressions if plan == "B" else config.a_avg_impressions
    future_impressions = (
        round(
            max(impression_target * (len(impressions) + remaining) - sum(impressions), 0)
            / remaining,
            2,
        )
        if remaining
        else None
    )
    if not rows:
        result = "NO_DATA"
    elif today < end:
        result = "PENDING"
    elif plan == "B":
        result = (
            "GO"
            if app_uu >= config.b_app_uu
            and average is not None
            and average >= config.b_avg_impressions
            else "NO-GO"
        )
    else:
        result = (
            "GO"
            if (followers is not None and followers >= config.a_followers)
            or (average is not None and average >= config.a_avg_impressions)
            else "NO-GO"
        )
    return Judgment(
        result=result,
        plan=plan,
        start=start.isoformat(),
        end=end.isoformat(),
        rows=len(rows),
        impressions_average=average,
        app_uu=app_uu,
        followers=followers,
        bookmark_rate=bookmark_rate,
        days_remaining=remaining,
        needed_app_uu_per_day=round(max(config.b_app_uu - app_uu, 0) / remaining, 2)
        if remaining and plan == "B"
        else None,
        needed_followers_per_day=round(max(config.a_followers - (followers or 0), 0) / remaining, 2)
        if remaining and plan == "A"
        else None,
        needed_impressions_per_future_post=future_impressions,
    )


def exit_code(result: str) -> int:
    return {"GO": 0, "NO-GO": 1, "PENDING": 2, "NO_DATA": 3}[result]
