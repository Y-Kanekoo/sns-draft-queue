#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
cd "$work"
export DISCORD_WEBHOOK_URL=""

uv run --project "$root" sns-queue cert daily --source "$root/tests/fixtures/cert-study" --exam fe --date 2026-11-01
uv run --project "$root" sns-queue qa weekly --feed "$root/tests/fixtures/qa-feed.xml" --week-end 2026-11-01
uv run --project "$root" sns-queue notify --pending
cert_id="$(basename "$(find queue -name 'cert-*.json' -print -quit)" .json)"
uv run --project "$root" sns-queue queue approve "$cert_id"
uv run --project "$root" sns-queue publish "$cert_id"

uv run --project "$root" python - <<'PY'
import csv
from datetime import date, timedelta
from pathlib import Path

path = Path("metrics/metrics.csv")
path.parent.mkdir(parents=True, exist_ok=True)
with path.open("w", encoding="utf-8", newline="") as stream:
    writer = csv.writer(stream)
    writer.writerow(["date", "plan", "post_id", "impressions", "app_uu", "followers", "bookmarks", "note"])
    for offset in range(30):
        day = (date(2026, 11, 1) + timedelta(days=offset)).isoformat()
        writer.writerow([day, "B", f"demo-b-{offset + 1}", 320, 7, "", 4, "架空のデモ値"])
        writer.writerow([day, "A", f"demo-a-{offset + 1}", 200, "", 60 + offset, 1, "架空のデモ値"])
PY

judge_example() {
  local expected="$1"
  local output="$2"
  shift 2
  local actual
  set +e
  uv run --project "$root" sns-queue metrics judge "$@" > "$output"
  actual=$?
  set -e
  if [[ "$actual" != "$expected" ]]; then
    echo "判定の終了コードが想定と異なります: $output ($actual)" >&2
    exit 1
  fi
}

mkdir -p "$root/examples/demo/queue" "$root/examples/demo/discord" "$root/examples/demo/x" "$root/examples/demo/metrics"
judge_example 0 "$root/examples/demo/metrics/b-go.txt" --plan B --start 2026-11-01 --today 2026-11-30
judge_example 0 "$root/examples/demo/metrics/b-go.json" --plan B --start 2026-11-01 --today 2026-11-30 --json
judge_example 1 "$root/examples/demo/metrics/a-no-go.txt" --plan A --start 2026-11-01 --today 2026-11-30
judge_example 1 "$root/examples/demo/metrics/a-no-go.json" --plan A --start 2026-11-01 --today 2026-11-30 --json
judge_example 2 "$root/examples/demo/metrics/b-pending.txt" --plan B --start 2026-11-01 --today 2026-11-15
judge_example 2 "$root/examples/demo/metrics/b-pending.json" --plan B --start 2026-11-01 --today 2026-11-15 --json

cp queue/*.json "$root/examples/demo/queue/"
cp outbox/discord/* "$root/examples/demo/discord/"
cp outbox/x/* "$root/examples/demo/x/"
cp metrics/metrics.csv "$root/examples/demo/metrics/"
echo "デモ成功: $root/examples/demo（指標は架空のデモ値）"
