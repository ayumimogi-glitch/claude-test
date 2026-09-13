#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
問い合わせ台帳CSVへ新着分を追記する。重複判定・年度四半期の導出・並べ替え・
BOM付与・個人情報の混入検査を、すべてこのスクリプトで固定する。

メール本文から会社名や製品を読み取る工程は機械にできないため、
その工程は呼び出し側（Claude がコネクタで読み取る）が担う。
このスクリプトは、抽出済みの行を受け取ってからの決定的な処理だけを担う。

入力:
    --ledger  既存の台帳CSV（BOM有無は問わない）
    --new     追記候補の行。JSONの配列。各要素の形は次のとおり。
              必須 発生日・製品・客先・宛先アドレス
              任意 業種・備考（省略時は 業種=不明、備考=空）
              年度と四半期は発生日から導出するため、与えても無視する

出力:
    --out     追記後の台帳CSV（BOM付きUTF-8）
    --since   このオプションを付けると、取得開始日だけを表示して終了する。
              台帳の最新日の2日前を返す。安全のため少し重複させて取得し、
              重複はこのスクリプトの重複判定で落とす。

重複判定は（発生日・客先・製品・宛先アドレス）の組で行う。
"""
import argparse
import csv
import datetime as dt
import json
import re
import sys

COLUMNS = ["発生日", "年度", "四半期", "製品", "業種", "客先", "媒体", "宛先アドレス", "備考"]

# 宛先アドレスと媒体の対応。台帳の媒体はこの2つの窓口から決まる
MEDIA_BY_ADDRESS = {
    "dxs-sb-sales@nes.jp.nec.com": "NES社外サイト",
    "sales@procenter.jp.nec.com": "OneNEC",
}

UNKNOWN = "不明"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
TEL_RE = re.compile(r"0\d{1,4}-\d{1,4}-\d{3,4}")


class RowError(ValueError):
    pass


def fiscal_year(date_str):
    """年度を返す。4月以降はその年、3月までは前年。"""
    y, m, _ = (int(x) for x in date_str.split("-"))
    return "%d年度" % (y if m >= 4 else y - 1)


def quarter(date_str):
    """年度基準の四半期を返す。Q1=4-6月、Q2=7-9、Q3=10-12、Q4=1-3。"""
    _, m, _ = (int(x) for x in date_str.split("-"))
    q = {4: 1, 5: 1, 6: 1, 7: 2, 8: 2, 9: 2, 10: 3, 11: 3, 12: 3,
         1: 4, 2: 4, 3: 4}[m]
    return "%sQ%d" % (fiscal_year(date_str), q)


def read_ledger(path):
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    if rows:
        missing = [c for c in COLUMNS if c not in rows[0]]
        if missing:
            raise RowError("台帳に必要な列がありません: %s" % ", ".join(missing))
    return [{c: (r.get(c) or "").strip() for c in COLUMNS} for r in rows]


def key_of(row):
    return (row["発生日"], row["客先"], row["製品"], row["宛先アドレス"])


def check_no_personal_data(row):
    """個人情報（メールアドレス・電話番号）を台帳へ入れない。

    宛先アドレスは窓口のアドレスであり、個人のアドレスではないため対象外とする。
    """
    for col in ("客先", "備考", "業種"):
        value = row.get(col, "")
        if MAIL_RE.search(value):
            raise RowError("%s にメールアドレスが含まれています: %s" % (col, value))
        if TEL_RE.search(value):
            raise RowError("%s に電話番号が含まれています: %s" % (col, value))


def normalize(raw):
    """追記候補の1件を台帳の形に整える。導出できる列は導出する。"""
    date = str(raw.get("発生日", "")).strip()
    if not DATE_RE.match(date):
        raise RowError("発生日が YYYY-MM-DD 形式ではありません: %r" % date)
    try:
        dt.date.fromisoformat(date)
    except ValueError:
        raise RowError("発生日が実在しない日付です: %s" % date)

    address = str(raw.get("宛先アドレス", "")).strip()
    if address not in MEDIA_BY_ADDRESS:
        raise RowError("宛先アドレスが台帳の対象窓口ではありません: %r" % address)

    product = str(raw.get("製品", "")).strip()
    if not product:
        raise RowError("製品が空です: %s" % date)

    row = {
        "発生日": date,
        "年度": fiscal_year(date),
        "四半期": quarter(date),
        "製品": product,
        "業種": str(raw.get("業種", "")).strip() or UNKNOWN,
        "客先": str(raw.get("客先", "")).strip() or "（客先不明）",
        "媒体": MEDIA_BY_ADDRESS[address],
        "宛先アドレス": address,
        "備考": str(raw.get("備考", "")).strip(),
    }
    check_no_personal_data(row)
    return row


def merge(ledger, new_rows):
    """新規分だけを足して、発生日の昇順に並べ直す。

    戻り値は (並べ替え後の全行, 追加した行, 重複として落とした行)。
    """
    seen = {key_of(r) for r in ledger}
    added = []
    skipped = []
    for raw in new_rows:
        row = normalize(raw)
        if key_of(row) in seen:
            skipped.append(row)
            continue
        seen.add(key_of(row))
        added.append(row)
    merged = ledger + added
    # 発生日の昇順。同じ日は製品と客先で安定させる
    merged.sort(key=lambda r: (r["発生日"], r["製品"], r["客先"]))
    return merged, added, skipped


def since_date(ledger, days=2):
    """取得開始日を返す。台帳の最新日の2日前。台帳が空なら14日前。"""
    dates = [r["発生日"] for r in ledger if DATE_RE.match(r["発生日"])]
    if not dates:
        return (dt.date.today() - dt.timedelta(days=14)).isoformat()
    return (dt.date.fromisoformat(max(dates)) - dt.timedelta(days=days)).isoformat()


def write_ledger(path, rows):
    # Excel での文字化けを防ぐため BOM 付きUTF-8で書く。これは必須である
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", required=True, help="既存の台帳CSV")
    ap.add_argument("--new", default="", help="追記候補のJSON配列")
    ap.add_argument("--out", default="", help="出力先。省略すると台帳を上書きする")
    ap.add_argument("--since", action="store_true",
                    help="取得開始日だけを表示して終了する")
    a = ap.parse_args()

    try:
        ledger = read_ledger(a.ledger)
    except (OSError, RowError) as e:
        sys.exit("台帳を読めません: %s" % e)

    if a.since:
        print(since_date(ledger))
        return

    if not a.new:
        sys.exit("--new を指定してください（追記候補が無い場合は空配列のJSONを渡す）")
    with open(a.new, encoding="utf-8") as f:
        new_rows = json.load(f)
    if not isinstance(new_rows, list):
        sys.exit("--new はJSONの配列で渡してください")

    try:
        merged, added, skipped = merge(ledger, new_rows)
    except RowError as e:
        sys.exit("追記候補に不正な行があります: %s" % e)

    out = a.out or a.ledger
    write_ledger(out, merged)

    print("台帳 %d行 追記%d件 重複除外%d件 出力先 %s"
          % (len(merged), len(added), len(skipped), out), file=sys.stderr)
    if added:
        print("追記した客先: %s" % "、".join(r["客先"] for r in added), file=sys.stderr)
    else:
        print("本日新規なし", file=sys.stderr)


if __name__ == "__main__":
    main()
