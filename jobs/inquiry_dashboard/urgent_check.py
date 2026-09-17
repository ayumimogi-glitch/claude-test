#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""台帳CSVの新規行だけを対象に、急ぎ対応が必要な問い合わせが無いかを判定する。

このスクリプトは毎日実行する軽量な判定だけを行う。ダッシュボードのHTML生成
（市場動向の取り込みや出口検査を含む重い工程）はここでは行わない。呼び出す側
（Desktopスケジュールタスクの指示文）が、この判定結果を見てHTML生成へ進むか
どうかを決める。

判定基準（2026/09/17 茂木さん確定、暫定運用。実例を見ながら調整する前提）は
次の2つのいずれかに該当すれば急ぎとする。

  1. キーワード   備考欄に「急ぎ」「至急」「大至急」のいずれかを含む
  2. リピート     正規化した客先名で、直近30日以内に2件以上の問い合わせがある

リピートの正規化ルールは、既存のダッシュボード（リピート企業一覧）と同じにする。
NFKC正規化のうえ、法人格・空白・中黒・敬称「様」を除去して比較する。

新規行の特定は、台帳CSVが追記のみで運用されている前提に立ち、行数を基準にする。
前回チェック時点の行数を状態ファイルに記録し、それより後ろの行だけを新規として
扱う。状態ファイルが無い場合（初回実行）は、既存の行をすべて確認済みとして
基準だけ作り、通知は出さない。過去分をまとめて急ぎ扱いにしないためである。

使い方:
    python3 urgent_check.py --csv ~/work/inquiry-dashboard/台帳.csv \
        --state ~/work/inquiry-dashboard/.urgent_check_state.json

終了コード:
    0 急ぎ無し（または初回実行で基準だけ作った）
    1 急ぎあり。標準出力にJSONで一覧を書き出す
    2 引数やファイルの誤りで判定できなかった
"""

import argparse
import csv
import datetime
import json
import os
import sys
import unicodedata

KEYWORDS = ("急ぎ", "至急", "大至急")
REPEAT_WINDOW_DAYS = 30
REPEAT_THRESHOLD = 2

LEGAL_FORMS = (
    "株式会社", "有限会社", "合同会社", "合資会社", "相互会社",
    "一般社団法人", "一般財団法人", "公益社団法人", "公益財団法人",
    "独立行政法人", "社会福祉法人", "特定非営利活動法人", "社会医療法人",
    "(株)", "（株）", "(有)", "（有）",
)


def normalize_company(name):
    """客先名を正規化する。既存のリピート企業判定と同じ規則にそろえる。"""
    t = unicodedata.normalize("NFKC", name or "")
    for w in LEGAL_FORMS:
        t = t.replace(w, "")
    t = t.replace("様", "")
    t = "".join(ch for ch in t if not ch.isspace() and ch != "・")
    return t


def load_state(path):
    if not os.path.isfile(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_state(path, row_count):
    payload = {
        "last_checked_row_count": row_count,
        "last_checked_at": datetime.datetime.now(
            datetime.timezone(datetime.timedelta(hours=9))
        ).strftime("%Y-%m-%dT%H:%M:%S+09:00"),
    }
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")


def read_rows(csv_path):
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        return list(reader)


def parse_date(s):
    try:
        return datetime.date.fromisoformat((s or "").strip())
    except ValueError:
        return None


def check(rows, new_from_index, today):
    """新規行（new_from_index以降）だけを対象に急ぎ判定を行う。

    リピート判定は、比較対象を新規行に限らず全行から行う（直近30日以内に
    他の既存行があれば、それも根拠に含める）。
    """
    by_company = {}
    for r in rows:
        d = parse_date(r.get("発生日", ""))
        if d is None:
            continue
        by_company.setdefault(normalize_company(r.get("客先", "")), []).append(d)

    hits = []
    for i in range(new_from_index, len(rows)):
        r = rows[i]
        note = r.get("備考", "") or ""
        company = r.get("客先", "")
        d = parse_date(r.get("発生日", ""))

        reasons = []
        if any(k in note for k in KEYWORDS):
            reasons.append("キーワード（備考に急ぎを示す語あり）")

        norm = normalize_company(company)
        if norm and d is not None:
            window_start = d - datetime.timedelta(days=REPEAT_WINDOW_DAYS)
            count = sum(1 for dd in by_company.get(norm, [])
                        if window_start <= dd <= d)
            if count >= REPEAT_THRESHOLD:
                reasons.append(
                    "リピート（直近%d日以内に%d件）" % (REPEAT_WINDOW_DAYS, count))

        if reasons:
            hits.append({
                "発生日": r.get("発生日", ""),
                "製品": r.get("製品", ""),
                "客先": company,
                "媒体": r.get("媒体", ""),
                "備考": note,
                "理由": reasons,
            })
    return hits


def main():
    p = argparse.ArgumentParser(description="台帳CSVの新規行から急ぎ対応の要否を判定する")
    p.add_argument("--csv", required=True, help="台帳CSVのパス")
    p.add_argument("--state", required=True, help="状態ファイルのパス")
    args = p.parse_args()

    csv_path = os.path.expanduser(args.csv)
    state_path = os.path.expanduser(args.state)

    if not os.path.isfile(csv_path):
        print("台帳CSVがありません: %s" % csv_path, file=sys.stderr)
        return 2

    try:
        rows = read_rows(csv_path)
    except Exception as e:
        print("台帳CSVを読めませんでした: %s" % e, file=sys.stderr)
        return 2

    state = load_state(state_path)
    if state is None:
        save_state(state_path, len(rows))
        print(json.dumps({
            "急ぎ判定": "初回実行のため基準のみ作成しました。通知はしません。",
            "現在の行数": len(rows),
        }, ensure_ascii=False, indent=2))
        return 0

    last_count = state.get("last_checked_row_count", len(rows))
    if len(rows) < last_count:
        # 行が減っている（訂正等）。基準がずれるため作り直し、今回は急ぎ無しとする。
        save_state(state_path, len(rows))
        print(json.dumps({
            "急ぎ判定": "台帳の行数が前回より減っていたため基準を作り直しました。通知はしません。",
            "前回の行数": last_count,
            "現在の行数": len(rows),
        }, ensure_ascii=False, indent=2))
        return 0

    today = datetime.date.today()
    hits = check(rows, last_count, today)
    save_state(state_path, len(rows))

    if not hits:
        print(json.dumps({
            "急ぎ判定": "急ぎ無し",
            "新規行数": len(rows) - last_count,
        }, ensure_ascii=False, indent=2))
        return 0

    print(json.dumps({
        "急ぎ判定": "急ぎあり",
        "新規行数": len(rows) - last_count,
        "該当件数": len(hits),
        "該当一覧": hits,
    }, ensure_ascii=False, indent=2))
    return 1


if __name__ == "__main__":
    sys.exit(main())
