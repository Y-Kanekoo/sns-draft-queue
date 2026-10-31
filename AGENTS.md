# このリポジトリの AI エージェント向けルール

## 禁止事項

- X への自動投稿、X API 投稿、ブラウザ操作による投稿を実装しない。
- 人間の承認ゲートを外さない。`publish` は `approved` のみ受け付ける。
- シークレット、`.env`、実運用の `queue/`・`outbox/`・`metrics/*.csv` をコミットしない。
- 実行時依存に Python 標準ライブラリ以外を追加しない。

## 状態遷移

`pending → approved → posted`、または `pending → rejected`。`edit` と `notify` は pending のみ。`publish` は approved のみ。`mark-posted` には X の投稿 URL が必要。プレースホルダが残る QA 下書きは原則承認しない。

## コマンド

`cert daily`、`qa weekly`、`queue list/show/edit/approve/reject/mark-posted/import`、`notify`、`publish`、`metrics add/judge`。Actions の artifact は `queue import <dir>` でローカルへ取り込む。既存 ID を上書きしない。

## ディレクトリ

- `src/sns_draft_queue/`: CLI と下書き生成、承認、通知、公開用ファイル、判定の実装。
- `tests/fixtures/`: 外部入力を模した固定データ。`tests/`: 自動テスト。
- `examples/demo/{queue,discord,x,metrics}/`: 架空のデモ出力。
- `examples/real/{queue,discord}/`: 2026-11-01 の実データによる出力。
- `queue/`, `outbox/`, `metrics/metrics.csv`: ローカル実運用データ。Git 対象外。
- `.github/workflows/`: CI と手動の下書き生成。Actions のキューは一時的。

## 必須チェック

変更後は以下をすべて通す。デモ出力を変更した場合は `bash scripts/demo.sh` も通す。

```sh
uv run ruff check . && uv run ruff format --check . && uv run mypy src && uv run pytest
bash scripts/demo.sh
```
