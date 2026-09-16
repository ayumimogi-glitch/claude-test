#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""スケジュールタスクの実行結果JSONを作る。

統合レポートの1段目（集約）は、各タスクが実行結果を1つのJSONで残していないと、
実行しなかった場合と区別が付かない。そのため、どのタスクも同じ形のJSONを残す。

形をここに固定する理由は2つある。

  1. キーが増減すると集約側が壊れる。本文に書いた形をモデルが毎回組み立てると、
     キー名の揺れや項目の追加が起きる。実際、2026/09/16 のダッシュボードの実行で
     output の値が指示と違うものになった
  2. 中止と失敗のときこそ書き出す必要がある。忘れやすいのはその経路である

このスクリプトはファイルを作るところまでを担う。置く先への転送は担わない。
CODE のコンテナから Box と Google Drive へはコネクタ経由でしか書けず、
スクリプトからは呼べないためである。作ったファイルを呼び出し側が
コネクタでアップロードする。

使い方:
    python3 write_run_result.py \\
        --task kousuu-shukei --environment CODE \\
        --status normal \\
        --output "Box 05_AI作業ドラフト/工数集計_自動生成" --output-count 1 \\
        --out "$REPO/work/run_result.json"

中止または失敗のとき:
    python3 write_run_result.py \\
        --task kousuu-shukei --environment CODE \\
        --status aborted \\
        --decision-title "回帰テストの失敗" \\
        --decision-detail "test_aggregate_kousuu.py が3件不合格" \\
        --out "$REPO/work/run_result.json"

既にあるファイルを検査するだけの場合:
    python3 write_run_result.py --validate <JSONのパス>

標準出力の最終行に、作ったファイルのパスを出す。呼び出し側はその1行を使う。

終了コード:
    0 書き出した、または検査に合格した
    1 検査に不合格
    2 引数の誤りで何もしていない
"""

import argparse
import datetime
import json
import sys

# 集約側が読むキー。増やさない。減らさない。
KEYS = ("task", "environment", "ran_at", "status",
        "output", "output_count", "needs_decision", "note")

STATUSES = ("normal", "failed", "aborted")

# needs_decision の1件が持つキー。
DECISION_KEYS = ("title", "detail", "since")

JST = datetime.timezone(datetime.timedelta(hours=9))


def build(task, environment, status, output, output_count,
          note, decision_title, decision_detail, now=None):
    """実行結果の中身を組み立てる。値の検査もここで行う。"""
    if status not in STATUSES:
        raise ValueError("status は %s のいずれかである必要がある: %s"
                         % ("、".join(STATUSES), status))
    if status != "normal" and not decision_title:
        raise ValueError("status が normal 以外のときは decision-title が必要である")
    if status == "normal" and decision_title:
        raise ValueError("status が normal のときに decision-title は付けない")
    if output_count < 0:
        raise ValueError("output-count は0以上である必要がある")

    now = now or datetime.datetime.now(JST)
    needs_decision = []
    if decision_title:
        needs_decision.append({
            "title": decision_title,
            "detail": decision_detail or "",
            "since": now.strftime("%Y-%m-%d"),
        })

    return {
        "task": task,
        "environment": environment,
        "ran_at": now.strftime("%Y-%m-%dT%H:%M:%S+09:00"),
        "status": status,
        "output": output,
        "output_count": output_count,
        "needs_decision": needs_decision,
        "note": note,
    }


def validate(payload):
    """集約側が読める形かを調べる。問題の一覧を返す。空なら合格。"""
    problems = []

    missing = [k for k in KEYS if k not in payload]
    if missing:
        problems.append("欠けているキー: %s" % "、".join(missing))
    extra = [k for k in payload if k not in KEYS]
    if extra:
        problems.append("余計なキー: %s" % "、".join(extra))

    status = payload.get("status")
    if status not in STATUSES:
        problems.append("status が %s のいずれでもない: %r" % ("、".join(STATUSES), status))

    if not isinstance(payload.get("output_count"), int):
        problems.append("output_count が整数ではない: %r" % payload.get("output_count"))

    if not isinstance(payload.get("note"), str):
        problems.append("note が文字列ではない: %r" % payload.get("note"))

    nd = payload.get("needs_decision")
    if not isinstance(nd, list):
        problems.append("needs_decision が配列ではない: %r" % nd)
    else:
        for i, item in enumerate(nd):
            if not isinstance(item, dict):
                problems.append("needs_decision[%d] が辞書ではない" % i)
                continue
            for k in DECISION_KEYS:
                if k not in item:
                    problems.append("needs_decision[%d] に %s が無い" % (i, k))
            for k in item:
                if k not in DECISION_KEYS:
                    problems.append("needs_decision[%d] に余計なキー %s がある" % (i, k))

        # 中止と失敗を記録しながら理由が空だと、集約しても打ち手が決まらない。
        if status in ("failed", "aborted") and not nd:
            problems.append("status が %s だが needs_decision が空である" % status)
        if status == "normal" and nd:
            problems.append("status が normal だが needs_decision に項目がある")

    ran_at = payload.get("ran_at", "")
    if not (isinstance(ran_at, str) and ran_at.endswith("+09:00")):
        problems.append("ran_at が +09:00 を末尾に持つ文字列ではない: %r" % ran_at)

    return problems


def main():
    p = argparse.ArgumentParser(description="スケジュールタスクの実行結果JSONを作る")
    p.add_argument("--validate", metavar="PATH",
                   help="既にあるJSONを検査するだけで、書き出しは行わない")
    p.add_argument("--task", help="タスクの識別子。例 kousuu-shukei")
    p.add_argument("--environment", default="CODE",
                   help="実行環境。CODE または ローカル実行")
    p.add_argument("--status", default="normal", choices=STATUSES)
    p.add_argument("--output", default="", help="成果物の置き場を短く書く")
    p.add_argument("--output-count", type=int, default=0, help="成果物の件数")
    p.add_argument("--note", default="",
                   help="対象日でなかった場合や埋め合わせ実行の場合の一文")
    p.add_argument("--decision-title", default="", help="中止と失敗のときの短い表題")
    p.add_argument("--decision-detail", default="", help="中止と失敗のときに何が起きたか")
    p.add_argument("--out", help="書き出し先のパス")
    args = p.parse_args()

    if args.validate:
        try:
            payload = json.load(open(args.validate, encoding="utf-8"))
        except Exception as e:
            print("読めません: %s" % e, file=sys.stderr)
            return 2
        problems = validate(payload)
        if problems:
            print("不合格")
            for x in problems:
                print("  %s" % x)
            return 1
        print("合格")
        return 0

    if not args.task or not args.out:
        print("--task と --out が必要である。検査だけ行う場合は --validate を使う。",
              file=sys.stderr)
        return 2

    try:
        payload = build(args.task, args.environment, args.status, args.output,
                        args.output_count, args.note,
                        args.decision_title, args.decision_detail)
    except ValueError as e:
        print("引数の誤り: %s" % e, file=sys.stderr)
        return 2

    problems = validate(payload)
    if problems:
        # 組み立てた直後に自分で検査する。壊れたものを置かないためである。
        print("組み立てた内容が検査に通りません:", file=sys.stderr)
        for x in problems:
            print("  %s" % x, file=sys.stderr)
        return 1

    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")

    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
