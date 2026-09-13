# Routine 定義: 工数集計 月次レポート

- 名前: 工数集計 月次レポート（毎月2日9時、CODE）
- スケジュール: 毎月2日 09:00（JST）。cron では `0 0 2 * *`（UTC）
- 実行環境: CODE（Default、trusted network access）
- 毎回新しいセッションで動かす
- 必要なコネクタ: Google Calendar、Box
- 置き換える Cowork 側 Routine: 工数集計 月次レポート（毎月2日9時）

## プロンプト本文（ここから下をそのまま貼り付ける）

Google Calendar の実績イベントを作業種別ごとに月次集計し、結果をBoxへ保存してください。茂木さん（ayumi.mogi@gmail.com）の作業です。

このセッションは毎回まっさらな状態で起動します。以下の指示だけで完結させてください。集計そのものはリポジトリのスクリプトが行います。集計スクリプトを新しく書かないでください。

## 0. リポジトリを用意する

bash で次を実行します。

```
if [ -d /home/user/claude-test/.git ]; then
  REPO=/home/user/claude-test
  cd "$REPO" && git fetch origin claude/gallant-clarke-fkfp1x && git checkout claude/gallant-clarke-fkfp1x && git reset --hard origin/claude/gallant-clarke-fkfp1x
else
  REPO=$HOME/claude-test
  git clone --branch claude/gallant-clarke-fkfp1x https://github.com/ayumimogi-glitch/claude-test "$REPO" && cd "$REPO"
fi
mkdir -p "$REPO/work"
python3 "$REPO/jobs/kousuu_shukei/test_aggregate_kousuu.py"
```

テストが失敗した場合は、集計へ進まず「回帰テストが失敗したため中止」と失敗内容を添えて報告し、終了します。リポジトリを取得できない場合も、代替手段を試さず「リポジトリを取得できなかったため中止」と報告して終了します。

## 1. 対象月を決める

実行日の前月です。日付は bash の date で確認し、推測しないでください。

## 2. イベントを取得する

Google Calendar コネクタの list_events で、対象月の1日00:00から翌月1日00:00まで（timeZone は Asia/Tokyo）を取得します。orderBy は startTime、pageSize は 250 です。nextPageToken が返る場合は最後まで取得してください。

前月比のため、対象月の1つ前の月も同じ条件で取得します。

応答が大きい場合、ハーネスがファイルへ保存します。そのファイルのパスをそのまま次の工程へ渡してください。内容を会話へ展開して数えないでください。応答が小さくファイルに落ちなかった場合は、応答のJSONをそのまま `$REPO/work/cur.json` と `$REPO/work/prev.json` へ保存してください。複数ページある場合は、ページのJSONを並べた配列として保存すればスクリプトが読めます。

## 3. 集計する

```
python3 "$REPO/jobs/kousuu_shukei/aggregate_kousuu.py" \
  --target-month YYYY-MM \
  --events <対象月のJSONファイル> \
  --prev-events <前月のJSONファイル> \
  --report "$REPO/work/report.md" \
  --json "$REPO/work/summary.json"
```

このスクリプトが、作業種別の判定、施策IDの取り出し、所要時間の算出、前月比の要否判定、レポートの本文生成まで行います。判定順序（件名の第2トークンを優先し、一致しない場合のみ件名全体を走査する）はスクリプトに固定されています。目視で数え直さないでください。

## 4. 保存する

Box コネクタで、フォルダID 414799528232（個人作業/NES販促G/茂木_作業中/05_AI作業ドラフト/工数集計_自動生成）へ `$REPO/work/report.md` の内容を保存します。

ファイル名は `YYYYMMDD_横断_工数集計_YYYYMM_v1_0.md` です。先頭のYYYYMMDDは実行日、後ろのYYYYMMは対象月です。

保存前に list_folder_content_by_folder_id で同名ファイルの有無を確認してください。既にある場合は上書きせず、版を _v1_1 へ上げます。保存には upload_file を使います。

保存後、同フォルダを再度一覧して、ファイルが実在することを確認してください。確認できない場合は「保存未確認」と報告し、成功と報告しないでください。

## 守ること

- 数値は必ずスクリプトの出力を使います。文章を書くときに数え直したり丸めたりしないでください
- 根拠が無い推測を書かないでください。確認できない項目は「不明」と記載します
- 「常に」「必ず」などの断定表現を避け、条件付きの表現を使います
- エムダッシュ・矢印記号・丸数字・全角数字・特殊文字・絵文字を使いません。中黒（・）と丸括弧は使います
- 相対日付を使わず、YYYY/MM/DD で書きます
- Google Calendar または Box の接続が使えない場合は、代替手段を試さず、その旨を明記して終了します

## 完了時の報告

保存したファイル名、集計対象の件数、合計時間、要確認の件数を、3行から5行で報告してください。末尾に「自己チェック レイアウトOK / 文言OK」と書きます。
