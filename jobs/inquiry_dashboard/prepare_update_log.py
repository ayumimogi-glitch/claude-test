#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ダッシュボードHTMLへ埋め込む「前回生成からの差分」（config/update_log.json）を作る。

urgent_check.py が持つ判定ロジック（客先名の正規化、急ぎキーワード、
リピート判定）を再利用し、「前回チェック」ではなく「前回生成」を基準に
新規行を数える点が urgent_check.py と異なる。

このスクリプトは2つの使い方をする。

  build     生成の直前に呼ぶ。前回生成の状態（generation_state.json）と
            台帳CSVを比べ、config/update_log.json を書き出す。
            generation_state.json は書き換えない。

  finalize  Box Driveへの配置（place_to_box.py）が成功した後に呼ぶ。
            generation_state.json を今回の生成時刻と行数で更新する。
            配置が失敗した回はfinalizeを呼ばない。そうしないと、
            実際には配置されなかった生成が「前回生成」として記録され、
            次回の差分がずれる。

状態ファイルの置き場所について、作業ディレクトリ（~/work/inquiry-dashboard）
は毎回 rm -rf されるため、状態ファイルはリポジトリ側の
jobs/inquiry_dashboard/.state/ に置く。このディレクトリはリポジトリには
含めない（.gitignoreで除外）。

使い方:
    python3 prepare_update_log.py build \
        --csv ~/work/inquiry-dashboard/台帳.csv \
        --state-dir jobs/inquiry_dashboard/.state \
        --out ~/work/inquiry-dashboard/config/update_log.json \
        --trigger "定例（火曜）"

    python3 prepare_update_log.py finalize \
        --csv ~/work/inquiry-dashboard/台帳.csv \
        --state-dir jobs/inquiry_dashboard/.state

終了コード:
    0 正常に完了した
    2 引数やファイルの誤りで実行できなかった
"""

import argparse
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import urgent_check as uc  # normalize_company / parse_date / read_rows を再利用する

GENERATION_STATE_NAME = "generation_state.json"


def now_iso():
    return datetime.datetime.now(
        datetime.timezone(datetime.timedelta(hours=9))
    ).strftime("%Y-%m-%dT%H:%M:%S+09:00")


def load_generation_state(state_dir):
    path = os.path.join(state_dir, GENERATION_STATE_NAME)
    if not os.path.isfile(path):
        return {"generated_at": None, "row_count": 0}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_generation_state(state_dir, generated_at, row_count):
    os.makedirs(state_dir, exist_ok=True)
    path = os.path.join(state_dir, GENERATION_STATE_NAME)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"generated_at": generated_at, "row_count": row_count},
                   f, ensure_ascii=False, indent=2)
        f.write("\n")


def annotate(rows, new_from_index):
    """新規行（new_from_index以降）へ、urgent_check.py と同じ規則で急ぎの注釈を付ける。"""
    by_company = {}
    for r in rows:
        d = uc.parse_date(r.get("発生日", ""))
        if d is None:
            continue
        by_company.setdefault(uc.normalize_company(r.get("客先", "")), []).append(d)

    out = []
    for i in range(new_from_index, len(rows)):
        r = rows[i]
        note = r.get("備考", "") or ""
        company = r.get("客先", "")
        d = uc.parse_date(r.get("発生日", ""))

        reasons = []
        if any(k in note for k in uc.KEYWORDS):
            reasons.append("キーワード（備考に急ぎを示す語あり）")
        norm = uc.normalize_company(company)
        if norm and d is not None:
            window_start = d - datetime.timedelta(days=uc.REPEAT_WINDOW_DAYS)
            count = sum(1 for dd in by_company.get(norm, [])
                        if window_start <= dd <= d)
            if count >= uc.REPEAT_THRESHOLD:
                reasons.append(
                    "リピート（直近%d日以内に%d件）" % (uc.REPEAT_WINDOW_DAYS, count))

        out.append({
            "date": r.get("発生日", ""),
            "product": r.get("製品", ""),
            "company": company,
            "medium": r.get("媒体", ""),
            "urgent": bool(reasons),
            "urgent_reasons": reasons,
        })
    return out


def cmd_build(args):
    if not os.path.isfile(args.csv):
        print("台帳CSVがありません: %s" % args.csv, file=sys.stderr)
        return 2
    rows = uc.read_rows(args.csv)
    state = load_generation_state(args.state_dir)
    if state.get("generated_at") is None:
        # generation_state.json が無い（この機能の初回実行）。
        # 台帳の既存行をすべて「新規」として差分表示すると過去分が
        # まとめて急ぎ扱いのように見えてしまうため、基準だけ作り
        # new_count は0とする。urgent_check.py の初回実行と同じ考え方。
        prev_count = len(rows)
    else:
        prev_count = state.get("row_count", 0)
        if len(rows) < prev_count:
            # 行が減っている（訂正等）。差分は数えず、空として扱う。
            prev_count = len(rows)

    new_rows = annotate(rows, prev_count)
    payload = {
        "generated_at": now_iso(),
        "previous_generated_at": state.get("generated_at"),
        "new_count": len(new_rows),
        "new_rows": new_rows,
        "trigger": args.trigger,
    }
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
    print("update_log.json を書き出しました: %s（新規%d件）" % (args.out, len(new_rows)))
    return 0


def cmd_finalize(args):
    if not os.path.isfile(args.csv):
        print("台帳CSVがありません: %s" % args.csv, file=sys.stderr)
        return 2
    rows = uc.read_rows(args.csv)
    save_generation_state(args.state_dir, now_iso(), len(rows))
    print("generation_state.json を更新しました（行数%d）" % len(rows))
    return 0


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build")
    b.add_argument("--csv", required=True)
    b.add_argument("--state-dir", required=True)
    b.add_argument("--out", required=True)
    b.add_argument("--trigger", required=True, choices=("定例（火曜）", "急ぎ検知"))
    b.set_defaults(func=cmd_build)

    f = sub.add_parser("finalize")
    f.add_argument("--csv", required=True)
    f.add_argument("--state-dir", required=True)
    f.set_defaults(func=cmd_finalize)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
