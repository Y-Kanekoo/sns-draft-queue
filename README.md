# sns-draft-queue

IT資格「1日1問」（プランB）と QA 週刊ダイジェスト（プランA）の SNS 下書きを生成し、人間の承認後に X の投稿画面リンクとコピー用テキストを出す CLI です。実行時依存は Python 標準ライブラリだけです。

## なぜ自動投稿しないか

投稿内容の確認、独自の見解の追加、規約上の判断を人間が行えるようにするためです。X API や自動投稿は実装していません。Discord Webhook は一方向の通知です。承認は CLI で行います。将来 Bot を追加する場合も承認ゲートを維持してください。

## 全体フロー

```text
cert-study / qa-radar → 下書き生成 → queue/*.json (pending)
                                      ↓ notify
                              Discord / outbox
                                      ↓ 人間が確認・編集
                              approve / reject
                                      ↓ approved のみ
                              publish → X intent + コピー用テキスト
                                      ↓ 人間が X で投稿
                              mark-posted → metrics add / judge
```

## インストール

Python 3.11 以上と [uv](https://docs.astral.sh/uv/) を用意します。

```sh
uv sync --group dev
cp config.example.toml config.toml
uv run sns-queue --help
uv run python -m sns_draft_queue --help
```

`config.toml` は任意です。未作成なら同梱の既定値を使います。アプリ URL、UTM、ハッシュタグ、表記、指標基準はここで変更できます。

## 使い方

```sh
uv run sns-queue cert daily --source ~/Projects/cert-study --exam all --date 2026-11-01
uv run sns-queue qa weekly --feed https://y-kanekoo.github.io/qa-radar/feed.xml --week-end 2026-11-01 --top 5
uv run sns-queue qa weekly --db ~/Projects/qa-radar/data/articles.db --week-end 2026-11-01
uv run sns-queue queue list --status pending
uv run sns-queue queue show <id>
uv run sns-queue queue edit <id>
uv run sns-queue notify --pending
uv run sns-queue queue approve <id> --note "確認済み"
uv run sns-queue queue reject <id> --reason "今回は見送り"
uv run sns-queue publish <id>
uv run sns-queue queue mark-posted <id> --url https://x.com/example/status/123
```

cert 下書き JSON は `posts` が問題スレッド、`answer_posts` が解答投稿群です。解答は最初の問題投稿へのリプ欄、または翌日に人が投稿します。問題は見出し・問題文・選択肢・自作アプリリンク・ハッシュタグを可能な限り1投稿に詰めます。解答は正解・解説・選択肢ごとの一言・AIラベルをまとめます。各投稿は X の重み付き280字以内です。試験別の既定タグは FE `#基本情報技術者試験`、AP `#応用情報技術者試験`、JSTQB `#JSTQB` と共通の `#1日1問` で、`config.toml` の `display.hashtags` で変更できます。

`queue edit` は `$EDITOR` で投稿文を開きます。cert は `posts` と `answer_posts` を含む JSON オブジェクト、QA は投稿文の JSON 配列です。保存時に両方の文字数を再検証します。QA の `ひとこと:（ここに自分の見解を書く）` を自分の言葉に置き換えるまで承認できません。例外として `--allow-placeholder` を指定できますが、原則は見解を追記してください。note/ブログ用 Markdown は下書き JSON の `meta.note_markdown` に入ります。`queue edit` で QA 投稿文を変えると、Markdown も投稿文から更新されます。

出力例（短縮）:

```text
問題 1: 【FE 1日1問】…
A. …
B. …
自作の学習アプリ: https://…
#基本情報技術者試験 #1日1問
解答 1（リプ欄/翌日用）: 【解答】D
…
※問題はAIの支援で作成し、人手で検証しています
```

### Discord Webhook

```sh
export DISCORD_WEBHOOK_URL='https://discord.com/api/webhooks/...'
uv run sns-queue notify --pending
```

Discord のチャンネル設定 → 連携サービス → ウェブフック → 新しいウェブフックで作成し、URL を環境変数に設定します。公開リポジトリや設定ファイルには入れません。環境変数がなければ `outbox/discord/<id>.md` と `.json` に送信予定内容を書きます。メッセージは2000字以内に分け、メンションを無効化します。Webhook URL は出力しません。Webhook は承認ボタンではありません。Discord 上で確認した後、CLI の `queue approve` を実行します。

### 30日検証

```sh
uv run sns-queue metrics add --plan B --date 2026-11-01 --impressions 320 --app-uu 8 --bookmarks 4 --post-id <id>
uv run sns-queue metrics add --plan A --date 2026-11-01 --impressions 350 --followers 40
uv run sns-queue metrics judge --plan B --start 2026-11-01 --days 30 --today 2026-11-30
uv run sns-queue metrics judge --plan A --start 2026-11-01 --json
```

プランBはアプリ流入 UU 合計 200 以上 **かつ** 表示数のある投稿の平均 300 以上で GO。プランAは期間末までの最新フォロワー数 150 以上 **または** 平均表示数 300 以上で GO。保存率 1% は参考値です。期間中は `PENDING`、データがなければ `NO_DATA`、期間終了後の未達は `NO-GO`。終了コードは順に 0/1/2/3 です。`--json` は機械可読形式です。

`examples/demo/metrics/metrics.csv` は **架空のデモ値** で、A と B の各30日分を収録しています。同ディレクトリに B の GO、A の NO-GO、途中日の PENDING をそれぞれテキストと `--json` で保存しています。実測値には使わないでください。表示数の平均など未入力の項目はテキスト表示で「未記録」と示します。

## GitHub Actions

CI は push と PR で lint、型、テストを実行します。`drafts` は Actions 画面から **Run workflow** を押した場合だけ動きます。`Y-Kanekoo/cert-study` を checkout し、JST の日付を指定して下書きを生成します。`DISCORD_WEBHOOK_URL` シークレットがあれば Discord に通知します。schedule はコメントアウトしており、有効化はユーザー判断です。

Actions の `queue/` は一時ランナー上の artifact で、過去の問題 ID や承認履歴を保持しません。**推奨運用はローカル実行**です。ローカルの `queue/` が使用済み問題の履歴を持ちます。Actions を使った場合は、artifact `sns-drafts` をダウンロードして展開し、次の順に進めます。既存 ID は上書きせず、import は取込件数とスキップ件数を表示します。

```sh
uv run sns-queue queue import ~/Downloads/sns-drafts/queue
uv run sns-queue queue list --status pending
uv run sns-queue queue show <id>
uv run sns-queue queue approve <id> --note "内容を確認済み"
uv run sns-queue publish <id>
```

`publish` は `approved` のみを受け付け、X intent とコピー用 md/html を `outbox/x/` に出します。投稿後は `queue mark-posted` で URL を記録します。

## 規約・法令とコンテンツ

- X の [Automation rules](https://help.x.com/en/rules-and-policies/x-automation) と [Original Content Rewards](https://help.x.com/en/using-x/original-content-rewards) の最新条件を投稿前に確認してください。後者では自動的に作成**または**投稿されたコンテンツを報酬対象外としています。人間が独自性と正確さを確認して投稿します。
- 案件・広告の場合は `config.toml` の `display.sponsored = true` に設定し、先頭に `PR` を付けます。表示要否は [消費者庁のステルスマーケティング規制](https://www.caa.go.jp/policies/policy/representation/fair_labeling/stealth_marketing/) を確認してください。
- AI 支援と人手検証の表記を解答投稿・図解メモに含めます。IPA/JSTQB の公式問題ではない旨も明記します。IPA の[過去問題利用条件](https://www.ipa.go.jp/shiken/mondai-kaiotu/index.html)は公表済み問題の利用を認めていますが、著作権と出典明記などの留意点があります。JSTQB の[公開資料](https://www.jstqb.jp/)も個別条件を確認してください。このツールが扱うのは `cert-study` の `verified` かつ `original` の選択式問題だけです。
- QA 記事はタイトル、出所、リンクと自分の短い見解だけを紹介し、本文は転載しません。引用が必要な場合は個別に引用要件と原著者の利用条件を確認してください。

## 設計判断

- 日付による選定は SHA-256 の順位で固定し、過去の全状態のキューにある問題 ID を避けます。使い切った試験だけ再利用します。同じ日付でもキューに新しい下書きが増えれば候補集合が変わります。
- `--exam all` は日付の通算日数を3で割った余りで FE/AP/JSTQB を循環します。
- X の URL は23文字、ASCII は1、全角や絵文字は2として数えます。cert は段落ブロックを順に貪欲に詰め、280を超える段落だけ `。` で文分割します。長い単文は文字境界で分割します。実際の X 画面でも最終確認してください。
- QA の期間は Asia/Tokyo の暦日で末日を含む7日です。日本語を優先し、英語も混ぜ、同一ソースは最大2件、タグの重複を減点する決定的な貪欲選定です。RSS に言語情報がない場合はタイトル文字種で推定します。
- QA の記事1件はXの1投稿とし、長いタイトルは投稿側だけ末尾を省略記号に置き換えます。ブログ用 Markdown には元のタイトルを残します。
- `metrics add` は1行を1投稿・1計測として記録します。UU は各行の合計で、重複ユーザーの排除は計測元で行う想定です。空欄の表示数は平均から除き、フォロワーは期間内の最新値を使います。
- `PENDING` の必要表示数ペースは残り期間に1日1投稿を続ける前提で計算します。
- GitHub Actions の一時ランナーのキューは実運用の承認履歴にならないため、artifact の持ち帰りを必須にしました。

## 出典

- 問題データとテスト用フィクスチャ: [Y-Kanekoo/cert-study](https://github.com/Y-Kanekoo/cert-study) の `content/{fe,ap,jstqb}`。同リポジトリのオリジナル問題から各試験の数問を同じ構造でコピーしています。
- ニュースデータ: [Y-Kanekoo/qa-radar](https://github.com/Y-Kanekoo/qa-radar) の公開 RSS と SQLite。
- 既定の30日判定基準: 2026-10-31 の調査レポート（依頼者提供）。

`scripts/demo.sh` はフィクスチャで一連の操作を一時ディレクトリで実行し、`examples/demo/{queue,discord,x,metrics}/` にサンプルを保存します。`examples/real/{queue,discord}/` は 2026-11-01 に `~/Projects/cert-study` と公開 RSS から生成した実データのサンプルです（queue は承認前の状態）。`examples/real/x/` は、出力例を作るためにその cert 下書きを一時ディレクトリで承認して `publish` したもので、実際の投稿はしていません。Webhook は使っていません。`UV_CACHE_DIR` を設定した場合、demo.sh はその値を尊重します。
