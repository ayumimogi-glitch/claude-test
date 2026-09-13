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

## 作り方

1. claude.ai の Routines 画面を開く
2. 新規 Routine を作る
3. 実行環境に CODE 環境（Default、trusted network access）を選ぶ
4. 毎回新しいセッションで動かす設定にする
5. 各ファイルの「スケジュール」と「必要なコネクタ」を設定に写す
6. 各ファイルの「プロンプト本文」以下をそのまま貼り付ける
7. 同じ内容の Cowork 側 Routine を無効にする（削除しない。切り戻せるようにする）

Cowork 側と CODE 側を同時に有効にしないこと。成果物が二重に作られる。

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
