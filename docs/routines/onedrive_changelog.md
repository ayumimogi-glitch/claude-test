# Routine 定義: OneDrive 日次変更ログ

- 名前: OneDrive daily change log（CODE）
- スケジュール: 毎日 09:00（JST）。cron では `0 0 * * *`（UTC）
- 実行環境: CODE（Default、trusted network access）
- 毎回新しいセッションで動かす
- 必要なコネクタ: Microsoft 365、Box
- 置き換える Cowork 側 Routine: OneDrive daily change log

## 移行前に決めること

移動と名称変更を新規作成と区別するには、前日の在庫（スナップショット）が必要である。
CODE のコンテナは実行ごとに消えるため、スナップショットの置き場を決める必要がある。

置き場の候補は次のとおりで、いずれも一長一短がある。判断は人が行う。

1. Box の作業フォルダへJSONとして置く。確実だが、毎日その本文をコネクタ経由で
   受け渡すことになり、ファイル数が多いと現実的ではない
2. スナップショットを使わずに運用する。移動と名称変更は判定できないままになる
3. このタスクは Cowork に残す

下のプロンプトは2番（スナップショット無し）を前提に書いている。
1番を採る場合は、手順2と手順5を実際の置き場に合わせて書き換えること。

## プロンプト本文（ここから下をそのまま貼り付ける）

OneDrive の前日分（日本時間の00:00から23:59）のファイル変更を、1行1ファイルのCSVにまとめてください。

このセッションは毎回まっさらな状態で起動します。以下の指示だけで完結させてください。変更種別の判定とCSVの組み立てはリポジトリのスクリプトが行います。自分で書き直さないでください。

## 0. リポジトリを用意する

```
if [ -d /home/user/claude-test/.git ]; then
  REPO=/home/user/claude-test
  cd "$REPO" && git fetch origin claude/gallant-clarke-fkfp1x && git checkout claude/gallant-clarke-fkfp1x && git reset --hard origin/claude/gallant-clarke-fkfp1x
else
  REPO=$HOME/claude-test
  git clone --branch claude/gallant-clarke-fkfp1x https://github.com/ayumimogi-glitch/claude-test "$REPO" && cd "$REPO"
fi
mkdir -p "$REPO/work"
python3 "$REPO/jobs/onedrive_changelog/test_build_change_log.py"
```

テストが失敗した場合は、集計へ進まず「回帰テストが失敗したため中止」と失敗内容を添えて報告し、終了します。

## 1. 対象日を決める

実行日の前日（JST）です。日付は bash の date で確認し、推測しないでください。

## 2. 当日の在庫を取得する

Microsoft 365 コネクタで、対象日に作成または更新されたファイルを取得します。取得できる項目は id、name、size、createdDateTime、lastModifiedDateTime、lastModifiedBy、parentReference、webUrl です。

応答が大きい場合、ハーネスがファイルへ保存します。そのファイルをそのまま次の工程へ渡してください。ファイルに落ちなかった場合は、応答のJSONを `$REPO/work/today.json` へ保存します。

削除の記録が取得できない場合は、その事実を控えておきます。推測で削除を書かないでください。

## 3. CSVを作る

```
python3 "$REPO/jobs/onedrive_changelog/build_change_log.py" \
  --today <当日の在庫JSON> \
  --date YYYY-MM-DD \
  --out "$REPO/work/file_changes_YYYY-MM-DD.csv" \
  --deletions-unavailable
```

削除の記録が取得できた場合は `--deletions-unavailable` を外します。

このスクリプトが、1ファイル1行への集約、UTCからJSTへの変換、拡張子の抽出、列順の固定、BOM付きUTF-8での書き出しを行います。変更が0件の場合はヘッダのみのCSVを出力します。

機密区分の列は空欄のままにします。人の判断が要る列であり、推測で埋めないためです。

## 4. 制約を明記する

前日の在庫（スナップショット）を持ち回っていないため、移動と名称変更は新規作成や更新と区別できません。この制約を実行結果に必ず明記してください。判定できていないことを、判定できたかのように報告しないでください。

## 5. 報告する

出力したCSVのファイル名、行数、変更種別ごとの内訳を報告します。スクリプトが出力した注記（スナップショット無し、削除記録の取得可否）もそのまま添えます。

CSVの受け渡し先が決まっている場合は、その手順に従って置きます。決まっていない場合は、CSVを会話へ届けます。

## 守ること

- Microsoft 365 の接続が使えない場合は、代替手段を試さず、その旨を明記して終了します
- 取得できた事実のみを反映し、ファイル名や変更内容を推測で作りません
- エムダッシュ・矢印記号・丸数字・特殊文字を使いません
- 相対日付を使わず、YYYY/MM/DD で書きます
