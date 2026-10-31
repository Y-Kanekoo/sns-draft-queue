"""TOML 設定。"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Config:
    apps: dict[str, str] = field(
        default_factory=lambda: {
            "fe": "https://fe-study.ykanekoo.workers.dev",
            "ap": "https://ap-study.ykanekoo.workers.dev",
            "jstqb": "https://jstqb-study.ykanekoo.workers.dev",
        }
    )
    utm_source: str = "x"
    utm_medium: str = "social"
    utm_campaign: str = "daily_question"
    hashtags: dict[str, tuple[str, ...]] = field(
        default_factory=lambda: {
            "fe": ("#基本情報技術者試験", "#1日1問"),
            "ap": ("#応用情報技術者試験", "#1日1問"),
            "jstqb": ("#JSTQB", "#1日1問"),
        }
    )
    app_label: str = "自作の学習アプリ"
    ai_label: str = "※問題はAIの支援で作成し、人手で検証しています"
    original_label: str = "IPA/JSTQBの公式問題ではなくオリジナル問題です"
    answer_hint: str = "答えはリプ欄/明日"
    sponsored: bool = False
    rss_url: str = "https://y-kanekoo.github.io/qa-radar/feed.xml"
    b_app_uu: int = 200
    b_avg_impressions: int = 300
    a_followers: int = 150
    a_avg_impressions: int = 300
    bookmark_rate_reference: float = 0.01


def load_config(path: Path = Path("config.toml")) -> Config:
    if not path.exists():
        return Config()
    with path.open("rb") as stream:
        raw = tomllib.load(stream)
    apps = raw.get("apps", {})
    utm = raw.get("utm", {})
    display = raw.get("display", {})
    qa = raw.get("qa", {})
    metrics = raw.get("metrics", {})
    default = Config()
    return Config(
        apps={**default.apps, **apps},
        utm_source=utm.get("source", default.utm_source),
        utm_medium=utm.get("medium", default.utm_medium),
        utm_campaign=utm.get("campaign", default.utm_campaign),
        hashtags={
            exam: tuple(display.get("hashtags", {}).get(exam, tags))
            for exam, tags in default.hashtags.items()
        },
        app_label=display.get("app_label", default.app_label),
        ai_label=display.get("ai_label", default.ai_label),
        original_label=display.get("original_label", default.original_label),
        answer_hint=display.get("answer_hint", default.answer_hint),
        sponsored=display.get("sponsored", default.sponsored),
        rss_url=qa.get("rss_url", default.rss_url),
        b_app_uu=metrics.get("b_app_uu", default.b_app_uu),
        b_avg_impressions=metrics.get("b_avg_impressions", default.b_avg_impressions),
        a_followers=metrics.get("a_followers", default.a_followers),
        a_avg_impressions=metrics.get("a_avg_impressions", default.a_avg_impressions),
        bookmark_rate_reference=metrics.get(
            "bookmark_rate_reference", default.bookmark_rate_reference
        ),
    )
