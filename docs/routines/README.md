# CODE 環境で動かす Routine の定義

このディレクトリには、Cowork から CODE へ移すスケジュールタスクのプロンプトを置く。

## なぜここに置くのか

2026/09/14 に実測したところ、エージェント（Claude）が `create_trigger` で作った Routine は、
この組織ではコネクタ（Box、Microsoft 365、Google Calendar、Google Drive）を持てない。
作成時に次の警告が返る。

```
warning: this trigger stores no MCP connectors, so the sessions it fires will run
without connector (mcp__<server>__*) tools.
```

コネクタ無しでは、どのジョブも入力を取得できず必ず失敗する。
したがって、CODE 環境の Routine は claude.ai の Routines 画面から人が作る必要がある。
このディレクトリのファイルは、その画面へ貼り付けるための本文である。

## 作り方（2026/09/14 時点の公式ドキュメントに基づく）

出典: Claude Code ドキュメント「Automate work with routines」
https://code.claude.com/docs/en/routines

### コネクタについての前提

Routines の作成フォームでは、claude.ai に接続済みのコネクタが**既定ですべて含まれる**。
つまり、探して追加する操作は通常は要らない。フォーム下部の「Connectors」節で、
このジョブに要らないものを外すだけでよい。必要なら同じ節から追加もできる。

コネクタそのものの接続や管理は https://claude.ai/customize/connectors で行う。

### 新規に作る場合

1. https://claude.ai/code/routines を開き、「New routine」を押す
2. 名前と、各ファイルの「プロンプト本文」を入れる（プロンプト欄にモデル選択もある）
3. リポジトリに `ayumimogi-glitch/claude-test` を選ぶ。実行のたびに既定ブランチが clone される
4. 環境に Default（Trusted network access）を選ぶ
5. 「Select a trigger」で Schedule を選び、各ファイルのスケジュールを入れる。
   時刻はローカル時間で入れると自動でUTCへ変換される。毎月2日のような
   プリセットに無い間隔は、近いプリセットを選んでから CLI の `/schedule update` で
   cron 式を設定する
6. 下部の「Connectors」節を確認し、各ファイルに書いてあるコネクタが含まれていることを
   確かめる。要らないものは外す
7. 「Create」を押す
8. 詳細画面の「Run now」で、スケジュールを待たずに1回試せる

### 既にある Routine を直す場合

1. https://claude.ai/code/routines で対象の Routine を開く
2. 鉛筆アイコンを押して「Edit routine」を開く
3. 名前、プロンプト、リポジトリ、環境、コネクタ、トリガーを変更できる

### 切り替え時の注意

- Cowork 側の同じ処理は、Cowork のスケジュールタスク画面で無効にする（削除しない）
- Cowork 側と CODE 側を同時に有効にしないこと。成果物が二重に作られる
- 実行一覧の緑表示は「セッションが異常終了しなかった」ことだけを意味する。
  中身が成功したかは実行を開いて確かめる

## ファイル一覧

| ファイル | 対応するスケジュールタスク | 状態 |
|---|---|---|
| `inquiry_dashboard.md` | 問い合わせ分析ダッシュボード 週次生成 火曜10時 | Box配置が未解決。下記参照 |
| `kousuu_shukei.md` | 工数集計 月次レポート 毎月2日9時 | CODE だけで完結する |
| `inquiry_csv.md` | 問い合わせCSV 毎朝更新 | CODE だけで完結する |
| `onedrive_changelog.md` | OneDrive daily change log | 移動と名称変更の判定に制約あり。下記参照 |

## 移行前に決める必要がある2点

### ダッシュボードの Box 配置

CODE のコンテナから Box へは、直接HTTPSが遮断されており、
コネクタの `upload_file` は本文を引数で渡す方式のため、約337KBのHTMLには向かない。
生成と出口検査は CODE で完結するが、Box への差し替えは人手が1回入る。
この点を許容できない場合、このタスクは Cowork に残す方がよい。

### OneDrive 変更ログのスナップショット

移動と名称変更を新規作成と区別するには、前日の在庫（スナップショット）が要る。
CODE のコンテナは実行ごとに消えるため、スナップショットの置き場を決める必要がある。
置き場が決まるまでは、スナップショット無しで動かすことになり、
移動と名称変更は判定できない。この制約を許容できない場合、
このタスクは Cowork に残す方がよい。
