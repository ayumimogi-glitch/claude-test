# Routine 定義: 問い合わせCSV 毎朝更新

- 名前: PROCENTER/ConforMeeting 問い合わせCSV 毎朝更新（CODE）
- スケジュール: 毎日 09:00（JST）。cron では `0 0 * * *`（UTC）
- 実行環境: CODE（Default、trusted network access）
- 毎回新しいセッションで動かす
- 必要なコネクタ: Microsoft 365、Box、Google Drive（実行結果の保存に使う）
- 置き換える Cowork 側 Routine: PROCENTER/ConforMeeting 問い合わせCSV 毎朝更新
- 注意: 問い合わせ分析ダッシュボードの前に走る必要がある

## プロンプト本文（ここから下をそのまま貼り付ける）

PROCENTER / ConforMeeting 問い合わせのデータ源CSVを更新し、Boxに上書き保存してください。あなたはNECマーケプロモ担当のアシスタントです。

このセッションは毎回まっさらな状態で起動します。以下の指示だけで完結させてください。重複判定・年度四半期の導出・並べ替え・BOM付与はリポジトリのスクリプトが行います。これらを自分で書き直さないでください。

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
python3 "$REPO/jobs/inquiry_csv/test_merge_inquiry_csv.py"
python3 "$REPO/jobs/status_report/test_write_run_result.py"
```

テストが失敗した場合は、更新へ進まず「回帰テストが失敗したため中止」と失敗内容を添えて報告し、終了します。リポジトリを取得できない場合も、代替手段を試さず「リポジトリを取得できなかったため中止」と報告して終了します。

## 1. 台帳CSVを取得する

Box コネクタの get_file_content で file_id=2372899647903（ファイル名 問い合わせデータ_2025-2026年度.csv、フォルダ「03.問合せ」id=376603310128）を読み、内容をそのまま `$REPO/work/ledger.csv` へ保存します。列は「発生日,年度,四半期,製品,業種,客先,媒体,宛先アドレス,備考」です。

## 2. 取得開始日を求める

```
python3 "$REPO/jobs/inquiry_csv/merge_inquiry_csv.py" --ledger "$REPO/work/ledger.csv" --since
```

台帳の最新日の2日前が表示されます。安全のため少し重複させて取得し、重複は後の工程で自動的に落とします。

## 3. メールを取得して対象を選ぶ

Microsoft 365 の outlook_email_search で、取得開始日から本日までに以下2アドレス宛に届いたメールを取得します（recipient指定、afterDateTime=取得開始日、order=newest、moreResults が出たら offset を最後まで継続取得）。

- dxs-sb-sales@nes.jp.nec.com
- sales@procenter.jp.nec.com

対象は「PROCENTER/C」または「ConforMeeting」の新規問い合わせ・資料請求、および既存案件のデモ依頼（製品デモの実施可否・候補日程の照会。デモ日程調整を含む）です。

次は必ず除外します。

- 他製品（電子帳簿保存法対応支援サービス、デジタルワークプレイス 等）
- 返信スレッド（件名が Re: ・ RE: で始まる）
- スパム・営業リスト勧誘（##spam##、VISITOR LIST など）
- 保守案件（件名または本文に「保守」「更新」「契約」「サポート」「ライセンス延長」「年間保守」を含む）
- NEC発の営業アウトバウンド（PROCENTER個別相談会案内・デモ動画案内・検証メール等）

ただし例外として、PROCENTER/C または ConforMeeting のデモ依頼・デモ日程調整は、件名が Re: ・ RE: で始まる返信スレッドであっても台帳に追記します（保守・更新・契約・ライセンス延長など保守系を除く）。

## 4. 各メールから抽出する

各対象メールを read_resource で開いて次を取り出します。

- 発生日: 本文の「お問合せ日時」または受信日時を日本時間(JST)に直し YYYY-MM-DD
- 製品: 件名から PROCENTER または ConforMeeting（両方対象なら「PROCENTER/ConforMeeting（両方）」）
- 客先: 本文の「会社名など」または「会社名」。取れなければ空にする（スクリプトが「（客先不明）」に直します）
- 宛先アドレス: dxs-sb-sales宛なら dxs-sb-sales@nes.jp.nec.com、sales@procenter宛なら sales@procenter.jp.nec.com
- 備考: 件名が資料ダウンロード・資料一式なら「資料ダウンロード」、それ以外は「問い合わせ」。デモ依頼・デモ日程調整なら「デモ依頼」（エンド企業が判明すれば「デモ依頼（エンド：〇〇）」と併記）。送信元がnec.comの営業からの代理問い合わせなら「営業が問い合わせ」
- 業種: メールからは判定不可のため省略する（スクリプトが「不明」に直します）

媒体、年度、四半期は書かないでください。宛先アドレスと発生日からスクリプトが導出します。

個人情報（氏名、メールアドレス、電話番号）を客先や備考に入れないでください。混入した場合、スクリプトがその行を弾いて中止します。

抽出した行を、次の形のJSON配列として `$REPO/work/new.json` へ保存します。1件も無い場合は空配列 `[]` を保存します。

```
[
  {"発生日": "2026-09-11", "製品": "PROCENTER", "客先": "株式会社の例",
   "宛先アドレス": "dxs-sb-sales@nes.jp.nec.com", "備考": "資料ダウンロード"}
]
```

## 5. 台帳へ追記する

```
python3 "$REPO/jobs/inquiry_csv/merge_inquiry_csv.py" \
  --ledger "$REPO/work/ledger.csv" \
  --new "$REPO/work/new.json" \
  --out "$REPO/work/ledger_out.csv"
```

このスクリプトが、重複判定（発生日・客先・製品・宛先アドレスの組）、年度と四半期の導出、発生日の昇順での並べ替え、BOM付きUTF-8での書き出し、個人情報の混入検査を行います。

出力の行数が入力より減っていないことを bash で確認してください。減っていた場合は保存せず、その旨を報告して終了します。

## 6. Box へ保存する

`$REPO/work/ledger_out.csv` の内容を、先頭のBOM（U+FEFF）を含めてそのまま upload_file_version（file_id=2372899647903）で上書き保存します。BOM はExcelでの文字化け防止のため必須です。

## 7. 報告する

追記した件数と会社名一覧を簡潔に報告します。新規が無ければ「本日新規なし」と報告します。

## 実行結果を残す

統合レポートの集約は、各タスクが実行結果を1つのJSONで残していないと、実行しなかった場合と区別が付きません。成功したときだけでなく、中止したときと失敗したときも必ず残してください。

形はリポジトリのスクリプトに固定されています。JSONを手で書かないでください。

成功したとき。

```
python3 "$REPO/jobs/status_report/write_run_result.py" \
  --task inquiry-csv --environment CODE --status normal \
  --output "Box 03.問合せ の問い合わせ台帳CSV" --output-count 1 \
  --out "$REPO/work/run_result.json"
```

中止したとき、失敗したとき。

```
python3 "$REPO/jobs/status_report/write_run_result.py" \
  --task inquiry-csv --environment CODE --status aborted \
  --decision-title "短い表題" --decision-detail "何が起きたか" \
  --out "$REPO/work/run_result.json"
```

status は normal、aborted、failed のいずれかです。出口の条件を満たさず途中でやめた場合は aborted、途中で失敗した場合は failed です。新規が0件で追記しなかった場合も残します。その場合は status を normal のままとし、--note に「本日新規なし」と入れます。

書き出したら、Google Drive コネクタで「Claude実行状況_受け渡し」フォルダへアップロードします。ファイル名は `YYYY-MM-DD_横断_実行結果_inquiry-csv.json` です。先頭のYYYY-MM-DDは実行日です。同名がある場合は上書きします。

アップロード後にフォルダを一覧し、ファイルが実在することを確認してください。確認できない場合は「実行結果の保存未確認」と報告し、成功と報告しないでください。

## 守ること

- Microsoft 365 または Box の接続が使えない場合は、代替手段を試さず、その旨を明記して終了します
- 取得できたメールの事実のみを反映し、数値や会社名を推測で作りません
- エムダッシュ・矢印記号・丸数字・特殊文字を使いません
