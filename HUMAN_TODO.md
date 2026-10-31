# 人間が行うこと

## アカウントと通知

- [ ] X アカウントを用意し、プロフィールに自作アプリと投稿内容を示す。文例: 「IT資格のオリジナル1日1問と QA ニュースを発信。問題作成には AI を補助的に使い、内容は人が確認。学習アプリ: https://fe-study.ykanekoo.workers.dev」
- [ ] X の最新の投稿規約、広告表記、引用と転載の条件を確認する。
- [ ] Discord サーバーに下書き確認用のチャンネルを作る。
- [ ] チャンネル設定 → 連携サービス → ウェブフック → 新しいウェブフックから URL を取得し、安全な場所に保管する。
- [ ] ローカルで `export DISCORD_WEBHOOK_URL='取得したURL'` を設定し、`uv run sns-queue notify --pending` で通知を確認する。URL を設定しない場合は `outbox/discord/` の md/json を確認する。
- [ ] GitHub Actions から通知する場合は、リポジトリの Settings → Secrets and variables → Actions → New repository secret に `DISCORD_WEBHOOK_URL` を登録する。
- [ ] `.github/workflows/drafts.yml` の schedule を有効化するか判断する。既定は手動実行のみ。

## 毎回の投稿

- [ ] ローカルで `cert daily` と `qa weekly` を実行する。Actions を使った日は artifact をダウンロードして `uv run sns-queue queue import <展開先のqueueディレクトリ>` で取り込む。
- [ ] `queue show <id>` と Discord 通知で正確さ、リンク、PR 表記、AI ラベルを確認し、必要なら `queue edit <id>` で修正する。
- [ ] QA の `ひとこと` に自分の見解を書き、`queue approve <id>` で承認する。見送る場合は `queue reject <id> --reason '理由'` を使う。
- [ ] `publish <id>` の md/html を確認して X で問題を投稿し、解答は最初の問題投稿へのリプ欄か翌日に投稿する。投稿後 `queue mark-posted <id> --url https://x.com/.../status/...` を実行する。

## 30日検証

- [ ] X アナリティクスで各投稿の表示数と保存数、および当日のフォロワー数を確認する。
- [ ] Cloudflare Workers の学習アプリのアクセス解析で X 流入の UU を確認する。`utm_source=x` 等の UTM を用いて流入元を絞り、同じ人を二重計上しない集計単位を決める。
- [ ] 毎日 `uv run sns-queue metrics add --plan B --date 2026-11-01 --impressions 320 --app-uu 8 --bookmarks 4 --post-id <id>` のように記録する。QA は `--plan A --followers 40` なども指定する。
- [ ] 30日後に `uv run sns-queue metrics judge --plan B --start 2026-11-01 --today 2026-11-30` と `--plan A` の判定を実行し、`--json` の結果も保存する。B は UU 200 以上かつ平均表示数 300 以上、A はフォロワー 150 以上または平均表示数 300 以上が GO。
