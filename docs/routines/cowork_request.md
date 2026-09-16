# Cowork の Claude に Routine を作らせるための依頼文

## なぜ Cowork に頼むのか

CODE セッションのエージェントが `create_trigger` で作った Routine は、この組織では
コネクタを持てない（2026/09/14 実測）。一方、既存の Cowork の Routine は
`created_via: meta_mcp` でありながら Box や Microsoft 365 を含む10件のコネクタを持つ。

つまり、コネクタを持つセッションから作れば、そのセッションのコネクタが引き継がれる。
Cowork はコネクタを持つため、Cowork の Claude に依頼すれば作れる見込みがある。
ただし、Cowork から CODE 環境（env_018Vn3RidJiDubEoadwZzWVT）を指定できるかは未検証である。
指定できない場合は Cowork 環境で作られてしまうため、作成後に実行環境を必ず確認すること。

## 依頼文（ここから下を Cowork の Claude へ貼り付ける）

スケジュールタスク（Routine）を1件作ってください。作成には create_trigger を使います。

設定は次のとおりです。

- 名前: 問い合わせCSV 毎朝更新（CODE）
- スケジュール: 毎日 09:00（JST）。cron では `0 0 * * *`（UTC）
- 実行環境: `env_018Vn3RidJiDubEoadwZzWVT`（Claude Code の Default 環境）
- 毎回新しいセッションで起動する設定にする（create_new_session_on_fire を true にする）
- 通知: プッシュをオンにする

プロンプト本文は、次のURLのファイルの「プロンプト本文（ここから下をそのまま貼り付ける）」という
見出しより下の全文です。WebFetch などで取得し、一字一句そのまま使ってください。要約や省略をしないでください。

https://raw.githubusercontent.com/ayumimogi-glitch/claude-test/claude/gallant-clarke-fkfp1x/docs/routines/inquiry_csv.md

取得できない場合は、その旨を報告して作成を中止してください。推測で本文を書かないでください。

作成後に次を必ず確認し、報告してください。

- 作られた Routine の ID（trig_ で始まる）
- コネクタが引き継がれているか。少なくとも Box、Microsoft 365、Google Drive が入っている必要がある
- 実行環境が `env_018Vn3RidJiDubEoadwZzWVT` になっているか
- スケジュールが毎日 09:00（JST）になっているか

コネクタが0件だった場合、その Routine は動きません。その場合は作成した Routine を
いったん無効にし、コネクタが入らなかったことを明記して報告してください。

## 他の3件を作る場合

上の依頼文の名前、スケジュール、URL を次のように差し替えてください。

### 問い合わせ分析ダッシュボード

- 名前: 問い合わせ分析ダッシュボード 週次生成 火曜10時（CODE）
- スケジュール: 毎週火曜 10:00（JST）。cron では `0 1 * * 2`（UTC）
- URL: https://raw.githubusercontent.com/ayumimogi-glitch/claude-test/claude/gallant-clarke-fkfp1x/docs/routines/inquiry_dashboard.md
- 必要なコネクタ: Box、Google Drive
- 注意: Box 配置は Mac のローカルスケジュールタスク inquiry-dashboard-local が
  担うようにした（2026/09/16）。CODE 側と同時に有効にしないこと。成果物が二重に作られる

### OneDrive 日次変更ログ

- 名前: OneDrive daily change log（CODE）
- スケジュール: 毎日 09:00（JST）。cron では `0 0 * * *`（UTC）
- URL: https://raw.githubusercontent.com/ayumimogi-glitch/claude-test/claude/gallant-clarke-fkfp1x/docs/routines/onedrive_changelog.md
- 必要なコネクタ: Microsoft 365、Box、Google Drive
- 注意: 移動と名称変更の判定に制約がある。移行前に docs/routines/README.md を読むこと

### 工数集計 月次レポート

- 名前: 工数集計 月次レポート（毎月2日9時、CODE）
- スケジュール: 毎日 09:00（JST）で作る。cron では `0 0 * * *`（UTC）。
  Routines 画面のプリセットに月次が無いため、毎日起動し、対象日（毎月2日）以外は
  プロンプト側で何もせず終える作りにしてある
- URL: https://raw.githubusercontent.com/ayumimogi-glitch/claude-test/claude/gallant-clarke-fkfp1x/docs/routines/kousuu_shukei.md
- 必要なコネクタ: Google Calendar、Box、Google Drive
- 注意: Cowork 側でまだ一度も実行されていない。初回を CODE で組む方が手戻りが小さい

## 作成後に必ずやること

1. 実行環境が CODE 側になっているかを確認する。Cowork 環境で作られていた場合、
   リポジトリの clone ができず、スクリプトを使えない
2. コネクタが入っているかを確認する。0件なら動かない
3. 対応する Cowork 側の Routine を無効にする（削除しない。切り戻せるようにする）
4. 「今すぐ実行」で1回試し、結果を読んでから常用に移す
5. Google Drive の「Claude実行状況_受け渡し」フォルダに
   `YYYY-MM-DD_横断_実行結果_<タスク名>.json` が置かれたことを確認する。
   これが無いと、統合レポートの集約からは実行しなかった場合と区別が付かない

## リポジトリを private にした場合

上のURLは公開リポジトリであることを前提にしている。private へ変更した場合、
WebFetch では取得できなくなる。その場合は、各ファイルの「プロンプト本文」を
人が直接コピーして依頼文へ貼り付けること。
