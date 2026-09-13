#!/usr/bin/env bash
# 問い合わせ分析ダッシュボードを CODE 上で生成し、出口検査まで通す。
#
# 2つの工程に分かれている。間に Claude が config を差し替える工程が入るためである。
#
#   bash run.sh prepare <作業ディレクトリ>
#       スキルの作業用コピーを作るだけ。ここで止まる。
#       この後、呼び出し側が作業用コピーの config/market.json と
#       config/contents.js.txt を差し替える。
#
#   bash run.sh build <台帳CSVのパス> <作業ディレクトリ>
#       2つの版を生成し、出口検査まで通す。作業用コピーは作り直さない。
#       差し替えた config を消さないためである。
#
# 前提: 台帳CSVは、この手順を呼ぶ側（Claude）が Box コネクタで取得して
#       作業ディレクトリへ置いてあること。コンテナからBoxへの直接通信は
#       組織のネットワークポリシーで遮断されているため、
#       スクリプト側からダウンロードすることはできない。
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export PLAYWRIGHT_BROWSERS_PATH="${PLAYWRIGHT_BROWSERS_PATH:-/opt/pw-browsers}"
export PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1

usage() {
  echo "使い方:" >&2
  echo "  bash run.sh prepare <作業ディレクトリ>" >&2
  echo "  bash run.sh build <台帳CSVのパス> <作業ディレクトリ>" >&2
  exit 2
}

prepare() {
  local work="$1"
  # スキルの同期キャッシュは書き込んでも次回に残らない。必ず作業用コピーを作る。
  # 片方のパスしか存在しない場合に ls が非ゼロで終わるため、失敗を飲み込む
  local src
  src="$(ls -d /root/.claude/skills/*/inquiry-dashboard \
               /root/.claude/skills/synced/*/inquiry-dashboard 2>/dev/null | head -1 || true)"
  if [ -z "$src" ]; then
    echo "スキル inquiry-dashboard が見つかりません。同期状況を確認してください。" >&2
    exit 1
  fi
  mkdir -p "$work"
  rm -rf "$work/inquiry-dashboard"
  cp -r "$src" "$work/inquiry-dashboard"
  echo "スキルの作業用コピーを作りました: $work/inquiry-dashboard"
  echo "次の工程で config/market.json と config/contents.js.txt を差し替えてください。"
}

build() {
  local csv="$1" work="$2"
  local skill="$work/inquiry-dashboard"
  if [ ! -d "$skill" ]; then
    echo "作業用コピーがありません。先に prepare を実行してください: $skill" >&2
    exit 1
  fi
  if [ ! -f "$csv" ]; then
    echo "台帳CSVがありません: $csv" >&2
    exit 1
  fi

  # playwright が無い環境でも検査工程まで到達させる。導入に失敗した場合、
  # ブラウザ検査は判定不能として記録され、他の検査は通常どおり行われる
  python3 -c "import playwright" 2>/dev/null || {
    echo "playwright を導入します（ブラウザは同梱のものを使う）"
    pip install --quiet playwright || \
      echo "playwright を導入できませんでした。ブラウザ検査は判定不能になります。" >&2
  }

  ( cd "$skill" && \
    python3 scripts/build_dashboard.py --csv "$csv" --variant analysis \
      --out "$work/問い合わせ分析ｘ市場動向含む_問い合わせダッシュボード.html" && \
    python3 scripts/build_dashboard.py --csv "$csv" --variant simple \
      --out "$work/問い合わせダッシュボード.html" )

  python3 "$REPO_DIR/verify_dashboard.py" \
    --skill-dir "$skill" --csv "$csv" --work-dir "$work/verify"

  echo ""
  echo "生成物"
  ls -la "$work"/*.html
  echo ""
  echo "次の工程は Box 配置である。CODE のコンテナからは Box へ直接アップロードできない。"
  echo "生成物を会話へ届け、手作業での差し替えが必要である旨を報告すること。"
}

[ $# -ge 1 ] || usage
case "$1" in
  prepare) [ $# -eq 2 ] || usage; prepare "$2" ;;
  build)   [ $# -eq 3 ] || usage; build "$2" "$3" ;;
  *)       usage ;;
esac
