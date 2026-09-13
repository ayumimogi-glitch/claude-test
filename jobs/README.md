# jobs ディレクトリ

Cowork のスケジュールタスクのうち、決定的な処理（毎回同じ入力なら同じ出力になる処理）を
CODE 側へ移したものを置く。

## 用語統一表

| 正式表記 | NG表記 | 備考 |
|---|---|---|
| Cowork | コワーク、CoWork | スケジュールタスクの従来の実行環境 |
| CODE | Claude code、コード | claude.ai/code のリモートセッション |
| Routine | 定期実行、cron、自動化 | スケジュールタスクの正式名 |
| コネクタ | 連携、MCP接続 | Box、Microsoft 365、Google Drive などの外部接続 |
| 決定的な処理 | 自動処理、機械処理 | 同じ入力なら同じ出力になる処理 |
| 出口検査 | 最終チェック、QA | 成果物を出す前の検査工程 |

## 分担の原則

CODE では、コネクタの呼び出しはモデル（Claude）しかできない。bash や Python から
Box や Microsoft 365 を直接叩くことはできない（理由は下の「ネットワークの制約」）。
そのため、各ジョブは次の3段に分ける。

1. 取得: Claude がコネクタでデータを取り、ファイルへ落とす
2. 処理: このディレクトリのスクリプトが、ファイルを入力に決定的な処理を行う
3. 配置: Claude がコネクタで成果物を置く、または人へ渡す

2段目だけをスクリプトに固定することで、毎回の解釈のぶれを減らす。
判断が必要な工程（メール本文からの会社名の読み取り、機密区分の判定など）は
2段目に入れない。空欄のまま残し、推測で埋めない。

## ネットワークの制約

CODE のコンテナからの外向き通信は、環境のネットワークポリシーで制限されている。
2026/09/14 時点の実測では次のとおり。

- 通る: pypi.org、files.pythonhosted.org、registry.npmjs.org、Anthropic の API
- 通らない: api.box.com、fupload-ane1.ent.box.com（いずれも CONNECT に 403）

したがって、curl や Python の requests で Box からダウンロードしたり
Box へアップロードしたりすることはできない。Box とのやり取りはコネクタ経由に限られる。

大きなコネクタ応答は、ハーネスが自動でファイルへ保存する。2026/09/14 の実測では
Google Calendar の1か月分（340,799文字）がファイルへ落ちた。このファイルを
スクリプトの入力にすれば、内容を会話へ展開せずに処理できる。

## ジョブ一覧

| ディレクトリ | 元のスケジュールタスク | スクリプトが担う範囲 |
|---|---|---|
| inquiry_dashboard | 問い合わせ分析ダッシュボード 週次生成 火曜10時 | 2つの版の生成と出口検査 |
| kousuu_shukei | 工数集計 月次レポート 毎月2日9時 | 実績イベントの集計とレポート生成 |
| onedrive_changelog | OneDrive daily change log | 前日との突き合わせと変更ログCSVの生成 |
| inquiry_csv | 問い合わせCSV 毎朝更新 | 重複判定・年度四半期の導出・並べ替え・BOM付与 |

## テストの実行

```
python3 jobs/kousuu_shukei/test_aggregate_kousuu.py
python3 jobs/onedrive_changelog/test_build_change_log.py
python3 jobs/inquiry_csv/test_merge_inquiry_csv.py
```

## 実データの扱い

顧客名、業績値、問い合わせ台帳などの実データは、このリポジトリへコミットしない。
`.gitignore` で `work/` と `data/` と `*.csv` を除外している。
実行時の作業ファイルは、コンテナ内の作業ディレクトリかスクラッチ領域に置く。
