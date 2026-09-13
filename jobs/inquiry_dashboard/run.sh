#!/usr/bin/env bash
# 問い合わせ分析ダッシュボードを CODE 上で生成し、出口検査まで通す。
#
# 前提: 台帳CSVは、この手順を呼ぶ側（Claude）が Box コネクタで取得して
#       作業ディレクトリへ置いてあること。コンテナからBoxへの直接通信は
#       組織のネットワークポリシーで遮断されているため、
#       スクリプト側からダウンロードすることはできない。
#
# 使い方:
#   bash jobs/inquiry_dashboard/run.sh <台帳CSVのパス> [作業ディレクトリ]
#
# 出力: 作業ディレクトリに2つの版のHTMLを置く。
#   分析版 問い合わせ分析ｘ市場動向含む_問い合わせダッシュボード.html
#   旧版   問い合わせダッシュボード.html
set -euo pipefail

CSV="${1:?台帳CSVのパスを指定してください}"
WORK="${2:-$PWD/work/inquiry_dashboard}"
REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-/opt/pw-browsers}"
export PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1

# スキルの同期キャッシュは書き込んでも次回に残らない。必ず作業用コピーを作る
# 片方のパスしか存在しない場合に ls が非ゼロで終わる。pipefail と set -e に
# 拾われて何も出力せず落ちるため、失敗を明示的に飲み込む
SKILL_SRC="$(ls -d /root/.claude/skills/*/inquiry-dashboard \
                   /root/.claude/skills/synced/*/inquiry-dashboard 2>/dev/null | head -1 || true)"
if [ -z "${SKILL_SRC}" ]; then
  echo "スキル inquiry-dashboard が見つかりません。同期状況を確認してください。" >&2
  exit 1
fi

mkdir -p "$WORK"
SKILL="$WORK/inquiry-dashboard"
rm -rf "$SKILL"
cp -r "$SKILL_SRC" "$SKILL"
echo "スキルの作業用コピー: $SKILL"

python3 -c "import playwright" 2>/dev/null || {
  echo "playwright を導入します（ブラウザは同梱のものを使う）"
  pip install --quiet playwright
}

cd "$SKILL"
python3 scripts/build_dashboard.py --csv "$CSV" --variant analysis \
  --out "$WORK/問い合わせ分析ｘ市場動向含む_問い合わせダッシュボード.html"
python3 scripts/build_dashboard.py --csv "$CSV" --variant simple \
  --out "$WORK/問い合わせダッシュボード.html"
cd - >/dev/null

python3 "$REPO_DIR/verify_dashboard.py" \
  --skill-dir "$SKILL" --csv "$CSV" --work-dir "$WORK/verify"

echo ""
echo "生成物"
ls -la "$WORK"/*.html
echo ""
echo "次の工程は人手またはコネクタ経由での Box 配置である。"
echo "CODE のコンテナからは Box へ直接アップロードできない点に注意すること。"
