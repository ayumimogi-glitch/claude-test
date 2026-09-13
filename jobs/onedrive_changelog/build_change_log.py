#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OneDrive の前日分の変更を1行1ファイルのCSVにまとめる。

変更種別（新規作成・更新・移動・名称変更・削除）の判定は、前日の在庫
（スナップショット）との突き合わせでしか決まらない。突き合わせを文章の
手順で毎回やり直すと、移動と新規作成を取り違える余地が残る。判定を
このスクリプトへ固定し、前日の在庫をファイルとして持ち回る。

入力:
    --today     当日の在庫。Microsoft Graph の driveItem 形式のJSON。
                {"value": [...]} でも [...] でも読める。
    --snapshot  前日の在庫のスナップショット（このスクリプトが出力したもの）。
                初回は省略できる。省略した場合、既存ファイルを新規作成と
                取り違えないよう、作成日時が対象日より前のものは
                「既存（前日の在庫が無く判定不能）」として記録する。

出力:
    --out           file_changes_YYYY-MM-DD.csv
    --new-snapshot  翌日の実行で使うスナップショット

判断が要る2列（内容・変更点の短い要約 と 機密区分）のうち、機械で書ける
範囲は埋め、書けない部分は空欄のままにする。推測で埋めない。
"""
import argparse
import csv
import datetime as dt
import json
import os
import sys

JST = dt.timezone(dt.timedelta(hours=9))

COLUMNS = ["処理日", "変更種別", "ファイルID", "ファイル名", "現在のフォルダ",
           "変更前のファイル名またはフォルダ", "作成日時", "更新日時", "更新者",
           "拡張子", "容量", "内容・変更点の短い要約", "機密区分", "共有リンク"]

CREATED = "新規作成"
MODIFIED = "更新"
MOVED = "移動"
RENAMED = "名称変更"
DELETED = "削除"
EXISTING_UNKNOWN = "既存（前日の在庫が無く判定不能）"


def load_items(path):
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        for key in ("value", "items", "files", "children"):
            if isinstance(data.get(key), list):
                return data[key]
        return []
    return data if isinstance(data, list) else []


def to_jst(raw):
    if not raw:
        return None
    try:
        return dt.datetime.fromisoformat(str(raw).replace("Z", "+00:00")).astimezone(JST)
    except ValueError:
        return None


def fmt_ts(d):
    return d.strftime("%Y-%m-%d %H:%M:%S") if d else ""


def folder_of(item):
    """親フォルダのパスを取り出す。Graph の parentReference.path を優先する。"""
    parent = item.get("parentReference") or {}
    path = parent.get("path") or ""
    if path:
        # /drive/root:/個人作業/… の前置きを落として読みやすくする
        marker = "root:"
        if marker in path:
            path = path.split(marker, 1)[1]
        return path or "/"
    return parent.get("name") or ""


def extension(name):
    base = os.path.basename(name or "")
    return base.rsplit(".", 1)[1].lower() if "." in base else ""


def modified_by(item):
    node = (item.get("lastModifiedBy") or {}).get("user") or {}
    return node.get("displayName") or node.get("email") or ""


def share_link(item):
    return item.get("webUrl") or ""


def size_of(item):
    v = item.get("size")
    return str(v) if isinstance(v, (int, float)) else ""


def snapshot_of(items):
    """翌日の判定に必要な最小限だけを残す。"""
    snap = {}
    for it in items:
        fid = it.get("id")
        if not fid:
            continue
        snap[fid] = {
            "name": it.get("name") or "",
            "folder": folder_of(it),
            "lastModifiedDateTime": it.get("lastModifiedDateTime") or "",
        }
    return snap


def in_target_day(ts, target):
    return ts is not None and ts.date().isoformat() == target


def classify(item, prev, target):
    """1ファイルの変更種別と、変更前の状態を返す。

    戻り値は (変更種別のリスト, 変更前の表示, 対象日に変更があったか)。
    複数の変更が1日にあった場合は種別を並べる。
    """
    fid = item.get("id")
    name = item.get("name") or ""
    folder = folder_of(item)
    created = to_jst(item.get("createdDateTime"))
    modified = to_jst(item.get("lastModifiedDateTime"))

    if prev is None:
        if in_target_day(created, target):
            return [CREATED], "", True
        if in_target_day(modified, target):
            # 前日の在庫が無いと、更新なのか移動なのかを区別できない
            return [MODIFIED], "", True
        return [EXISTING_UNKNOWN], "", False

    old = prev.get(fid)
    if old is None:
        if in_target_day(created, target):
            return [CREATED], "", True
        # 作成日が対象日より前なのに前日の在庫に無い。共有の追加などが考えられる
        return [EXISTING_UNKNOWN], "", in_target_day(modified, target)

    kinds = []
    before = []
    if old.get("name") != name:
        kinds.append(RENAMED)
        before.append("旧ファイル名 %s" % old.get("name"))
    if old.get("folder") != folder:
        kinds.append(MOVED)
        before.append("旧フォルダ %s" % old.get("folder"))
    if in_target_day(modified, target) and old.get("lastModifiedDateTime") != (
            item.get("lastModifiedDateTime") or ""):
        kinds.append(MODIFIED)
    if not kinds:
        return [], "", False
    return kinds, " / ".join(before), True


def build_rows(today_items, prev, target, classification_default):
    rows = []
    seen = set()
    for item in today_items:
        fid = item.get("id")
        if not fid or fid in seen:
            # 同じファイルが1日に複数回変わっても、最終状態の1行にまとめる
            continue
        seen.add(fid)
        kinds, before, changed = classify(item, prev, target)
        if not changed or not kinds:
            continue
        if kinds == [EXISTING_UNKNOWN] and prev is not None:
            pass
        name = item.get("name") or ""
        summary = "・".join(kinds)
        if before:
            summary += "（%s）" % before
        rows.append({
            "処理日": target,
            "変更種別": "・".join(kinds),
            "ファイルID": fid,
            "ファイル名": name,
            "現在のフォルダ": folder_of(item),
            "変更前のファイル名またはフォルダ": before,
            "作成日時": fmt_ts(to_jst(item.get("createdDateTime"))),
            "更新日時": fmt_ts(to_jst(item.get("lastModifiedDateTime"))),
            "更新者": modified_by(item),
            "拡張子": extension(name),
            "容量": size_of(item),
            "内容・変更点の短い要約": summary,
            "機密区分": classification_default,
            "共有リンク": share_link(item),
        })

    if prev is not None:
        present = {it.get("id") for it in today_items}
        for fid, old in prev.items():
            if fid in present:
                continue
            rows.append({
                "処理日": target,
                "変更種別": DELETED,
                "ファイルID": fid,
                "ファイル名": old.get("name", ""),
                "現在のフォルダ": "",
                "変更前のファイル名またはフォルダ": "旧フォルダ %s" % old.get("folder", ""),
                "作成日時": "",
                "更新日時": "",
                "更新者": "",
                "拡張子": extension(old.get("name", "")),
                "容量": "",
                "内容・変更点の短い要約":
                    "前日の在庫にあり当日の在庫に無い。削除または対象外への移動",
                "機密区分": classification_default,
                "共有リンク": "",
            })

    rows.sort(key=lambda r: (r["変更種別"], r["ファイル名"], r["ファイルID"]))
    return rows


def write_csv(path, rows):
    # Excel での文字化けを避けるため BOM 付きUTF-8で書く
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--today", required=True, help="当日の在庫JSON")
    ap.add_argument("--snapshot", default="", help="前日の在庫スナップショット")
    ap.add_argument("--date", default="", help="対象日（JST、YYYY-MM-DD）。省略すると前日")
    ap.add_argument("--out", default="", help="出力CSV。省略すると file_changes_対象日.csv")
    ap.add_argument("--new-snapshot", default="", help="翌日用のスナップショットの出力先")
    ap.add_argument("--classification-default", default="",
                    help="機密区分の既定値。人が判断する列であり、既定は空欄")
    ap.add_argument("--deletions-unavailable", action="store_true",
                    help="削除記録を取得できなかった場合に指定する。出力へ注記する")
    a = ap.parse_args()

    target = a.date or (dt.datetime.now(JST).date() - dt.timedelta(days=1)).isoformat()
    out = a.out or "file_changes_%s.csv" % target

    today_items = load_items(a.today)
    prev = None
    if a.snapshot:
        if not os.path.exists(a.snapshot):
            sys.exit("スナップショットが見つかりません: %s" % a.snapshot)
        with open(a.snapshot, encoding="utf-8") as f:
            prev = json.load(f)

    rows = build_rows(today_items, prev, target, a.classification_default)
    write_csv(out, rows)

    if a.new_snapshot:
        with open(a.new_snapshot, "w", encoding="utf-8") as f:
            json.dump(snapshot_of(today_items), f, ensure_ascii=False, indent=1)

    notes = []
    if prev is None:
        notes.append("前日のスナップショットが無いため、移動と名称変更は判定できていない")
    if a.deletions_unavailable:
        notes.append("削除記録を取得できなかったため、削除は当日の在庫からの消失でのみ推定している")
    if not rows:
        notes.append("対象日の変更は0件である。ヘッダのみのCSVを出力した")

    print("変更ログ %s: %d行 出力先 %s" % (target, len(rows), out), file=sys.stderr)
    for n in notes:
        print("注記: %s" % n, file=sys.stderr)


if __name__ == "__main__":
    main()
