#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Google Calendar の実績イベントを作業種別ごとに月次集計し、Markdownレポートを作る。

Cowork のスケジュールタスクでは、毎回この集計スクリプトを書き起こす手順に
なっていた。書き起こすたびに判定順序や除外条件の解釈がぶれる余地があるため、
判定を固定してテストを付ける。数値は必ずこのスクリプトの出力を使う。

入力:
    Google Calendar コネクタの list_events の応答を保存したJSONファイル。
    1ファイルに1ページでも、複数ページを並べても読める。
    受け付ける形は次の3つ。
      - {"events": [...]} の単体
      - [{"events": [...]}, ...] のページの配列
      - [ {イベント}, ... ] のイベントの配列

使い方:
    python3 aggregate_kousuu.py --target-month 2026-08 \\
        --events current.json --prev-events prev.json \\
        --report report.md --json summary.json

判定の順序は次のとおり。順序を入れ替えると集計が歪む。
  1. 件名が「【済】」で始まるものだけを集計対象にする
  2. 「【済】」を除いた残りをアンダースコアで分割し、第2トークンが
     8語と完全一致すればそれを作業種別とする（対象の側に別の種別の語が
     含まれていても複数該当として扱わない）
  3. 第2トークンが一致しない場合だけ、件名全体を走査して語を探す
"""
import argparse
import collections
import datetime as dt
import json
import os
import re
import sys

DONE = "【済】"
OLD_PREFIXES = ("【実績】", "【実施済】")
PRIVATE_PREFIX = "【家計簿】"

KINDS = ["資料作成", "体裁チェック", "用語チェック", "ファイル整理",
         "情報収集", "議事メモ作成", "会議", "調整連絡"]
KIND_UNSET = "種別未設定"

# 施策IDの採番ルール。横断、英字1文字と数字、SECと数字
ID_RULES = [
    re.compile(r"^横断$"),
    re.compile(r"^[A-Za-z]\d+$"),
    re.compile(r"^SEC\d+$", re.IGNORECASE),
]

# 施策IDの採番ルールを適用し始めた日。これより前の実績は遡って直さない方針
ID_RULE_START = "2026-09-03"
# 件名規則が確定した日。これより前は旧形式で記録されている
NAMING_RULE_FIXED = "2026-08-25"


def load_events(paths):
    """複数のJSONファイルからイベントを集めて1つの配列にする。"""
    events = []
    for path in paths:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        events.extend(extract_events(data))
    return events


def extract_events(data):
    if isinstance(data, dict):
        return list(data.get("events") or [])
    if isinstance(data, list):
        out = []
        for item in data:
            if isinstance(item, dict) and "events" in item:
                out.extend(item.get("events") or [])
            elif isinstance(item, dict):
                out.append(item)
        return out
    return []


def parse_dt(node):
    """start / end ノードから (datetime, 終日かどうか) を返す。"""
    if not isinstance(node, dict):
        return None, False
    if node.get("dateTime"):
        raw = node["dateTime"].replace("Z", "+00:00")
        try:
            return dt.datetime.fromisoformat(raw), False
        except ValueError:
            return None, False
    if node.get("date"):
        try:
            return dt.datetime.fromisoformat(node["date"]), True
        except ValueError:
            return None, True
    return None, False


def duration_minutes(ev):
    """所要時間を分で返す。取れない場合は None。

    件数に0.25をかける方法は使わない。実データは15分単位ではない。
    """
    s, s_allday = parse_dt(ev.get("start"))
    e, e_allday = parse_dt(ev.get("end"))
    if s is None or e is None:
        return None
    if s_allday or e_allday:
        return None
    delta = (e - s).total_seconds() / 60.0
    return delta if delta >= 0 else None


def split_subject(summary):
    """【済】を外した残りをアンダースコアで分割する。"""
    body = summary[len(DONE):]
    return body.split("_")


def classify(summary):
    """作業種別を決める。戻り値は (種別, 複数該当した語のリスト)。"""
    tokens = split_subject(summary)
    if len(tokens) >= 2 and tokens[1] in KINDS:
        # 第2トークンが規則どおりの場合、対象の側の語は見ない
        return tokens[1], []
    # 規則に従っていない件名を黙って落とさないため、全体を走査する
    hits = [(summary.find(k), k) for k in KINDS if k in summary]
    if not hits:
        return KIND_UNSET, []
    hits.sort()
    matched = [k for _, k in hits]
    return matched[0], matched if len(matched) > 1 else []


def measure_id(summary):
    """施策IDを取り出す。【済】の直後から最初のアンダースコアまで。"""
    tokens = split_subject(summary)
    return tokens[0] if tokens else ""


def id_is_valid(measure):
    return any(r.match(measure) for r in ID_RULES)


def month_bounds(month):
    y, m = (int(x) for x in month.split("-"))
    start = dt.date(y, m, 1)
    end = dt.date(y + (1 if m == 12 else 0), 1 if m == 12 else m + 1, 1)
    return start, end


def prev_month(month):
    y, m = (int(x) for x in month.split("-"))
    return "%04d-%02d" % ((y - 1, 12) if m == 1 else (y, m - 1))


def aggregate(events):
    """イベント配列を集計し、機械可読な結果を返す。"""
    out = {
        "done": [],            # 集計対象（【済】）
        "old": 0,              # 旧形式の実績
        "private": 0,          # 業務外
        "other": 0,            # その他
        "unset": [],           # 8語に当てはまらない件名
        "multi": [],           # 複数該当した件名
        "no_duration": [],     # 所要時間が取れない件名
        "bad_id": [],          # 採番ルールに合わない施策ID
    }
    for ev in events:
        summary = (ev.get("summary") or "").strip()
        if not summary:
            out["other"] += 1
            continue
        if summary.startswith(OLD_PREFIXES):
            out["old"] += 1
            continue
        if summary.startswith(PRIVATE_PREFIX):
            out["private"] += 1
            continue
        if not summary.startswith(DONE):
            out["other"] += 1
            continue

        kind, matched = classify(summary)
        measure = measure_id(summary)
        minutes = duration_minutes(ev)
        rec = {
            "summary": summary,
            "kind": kind,
            "measure": measure,
            "minutes": 0.0 if minutes is None else minutes,
        }
        out["done"].append(rec)
        if kind == KIND_UNSET:
            out["unset"].append(summary)
        if matched:
            out["multi"].append({"summary": summary, "matched": matched})
        if minutes is None:
            out["no_duration"].append(summary)
        if not id_is_valid(measure):
            out["bad_id"].append({"summary": summary, "measure": measure})
    return out


def by_kind(done):
    table = collections.OrderedDict((k, {"n": 0, "min": 0.0}) for k in KINDS)
    table[KIND_UNSET] = {"n": 0, "min": 0.0}
    for r in done:
        cell = table.setdefault(r["kind"], {"n": 0, "min": 0.0})
        cell["n"] += 1
        cell["min"] += r["minutes"]
    return table


def by_measure(done):
    table = collections.defaultdict(lambda: {"n": 0, "min": 0.0})
    for r in done:
        table[r["measure"]]["n"] += 1
        table[r["measure"]]["min"] += r["minutes"]
    return collections.OrderedDict(sorted(table.items(), key=lambda kv: kv[0]))


def hhmm(minutes):
    """分を「N時間M分」で書く。丸めない。"""
    total = int(round(minutes))
    return "%d時間%d分" % (total // 60, total % 60)


def fmt_date(d):
    return d.strftime("%Y/%m/%d")


TERMS = [
    ("実績イベント", "実績記録・カレンダー登録", "件名が【済】で始まるカレンダーの予定を指す"),
    ("作業種別", "作業区分・タスク種別", "8語のいずれか。件名の第2トークンで判定する"),
    ("施策ID", "案件ID・プロジェクトID", "【済】の直後から最初のアンダースコアまで"),
    ("所要時間", "工数・作業時間", "イベントの開始と終了の差。件数からの推計は使わない"),
]


def build_report(month, cur, prev, prev_month_label, generated_on):
    k_cur = by_kind(cur["done"])
    total_n = len(cur["done"])
    total_min = sum(r["minutes"] for r in cur["done"])
    start, end = month_bounds(month)

    L = []
    L.append("# 工数集計 %s" % month.replace("-", "年") + "月")
    L.append("")
    L.append("## 用語統一表")
    L.append("")
    L.append("| 正式表記 | NG表記 | 備考 |")
    L.append("|---|---|---|")
    for a, b, c in TERMS:
        L.append("| %s | %s | %s |" % (a, b, c))
    L.append("")

    L.append("## 1. 基本情報")
    L.append("")
    L.append("- 対象月: %s から %s まで" % (fmt_date(start), fmt_date(end - dt.timedelta(days=1))))
    L.append("- 集計対象の定義: 件名が「【済】」で始まる実績イベント")
    L.append("- 件数: %d件" % total_n)
    L.append("- 合計時間: %s" % hhmm(total_min))
    L.append("- 時間の求め方: イベントの開始と終了の差を分で求めて合計する。件数への係数掛けは使わない")
    L.append("- 生成日: %s" % generated_on)
    if month < "2026-09":
        L.append("- 施策IDの採番規則は %s 以降に登録する分へ適用される。"
                 "対象月がそれより前のため、採番ルールに合わない施策IDに製品名や仮称が並ぶことは想定内である"
                 % fmt_date(dt.date.fromisoformat(ID_RULE_START)))
    L.append("")

    L.append("## 2. 作業種別ごとの集計")
    L.append("")
    if prev is None:
        L.append("前月は件名規則の適用前にあたるため比較していません。"
                 "件名規則の適用は %s に確定しています。"
                 % fmt_date(dt.date.fromisoformat(NAMING_RULE_FIXED)))
        L.append("")
        L.append("| 作業種別 | 件数 | 合計時間 | 構成比 |")
        L.append("|---|---:|---:|---:|")
        for kind, cell in k_cur.items():
            if cell["n"] == 0:
                continue
            ratio = (cell["min"] / total_min * 100) if total_min else 0.0
            L.append("| %s | %d | %s | %.1f パーセント |"
                     % (kind, cell["n"], hhmm(cell["min"]), ratio))
    else:
        k_prev = by_kind(prev["done"])
        L.append("前月（%s）と並べて差を示します。" % prev_month_label)
        L.append("")
        L.append("| 作業種別 | 件数 | 前月件数 | 件数差 | 合計時間 | 前月合計時間 | 時間差 |")
        L.append("|---|---:|---:|---:|---:|---:|---:|")
        keys = list(k_cur.keys())
        for kind in keys:
            c = k_cur[kind]
            p = k_prev.get(kind, {"n": 0, "min": 0.0})
            if c["n"] == 0 and p["n"] == 0:
                continue
            L.append("| %s | %d | %d | %+d | %s | %s | %+d分 |"
                     % (kind, c["n"], p["n"], c["n"] - p["n"],
                        hhmm(c["min"]), hhmm(p["min"]),
                        int(round(c["min"] - p["min"]))))
    L.append("")

    L.append("## 3. 施策IDごとの内訳")
    L.append("")
    L.append("| 施策ID | 件数 | 合計時間 |")
    L.append("|---|---:|---:|")
    for measure, cell in by_measure(cur["done"]).items():
        L.append("| %s | %d | %s |" % (measure or "（空）", cell["n"], hhmm(cell["min"])))
    if not cur["done"]:
        L.append("| なし | 0 | 0時間0分 |")
    L.append("")

    L.append("## 4. 確認が必要な件名")
    L.append("")
    L.append("### 4.1 8語に当てはまらない件名")
    L.append("")
    L.extend(["- " + s for s in cur["unset"]] or ["- なし"])
    L.append("")
    L.append("### 4.2 複数の語に該当した件名")
    L.append("")
    L.extend(["- %s（該当した語 %s。先に現れた語を採用した）"
              % (m["summary"], "・".join(m["matched"])) for m in cur["multi"]] or ["- なし"])
    L.append("")
    L.append("### 4.3 所要時間が取れない件名")
    L.append("")
    L.extend(["- %s（0分として算入した）" % s for s in cur["no_duration"]] or ["- なし"])
    L.append("")
    L.append("### 4.4 採番ルールに合わない施策ID")
    L.append("")
    L.extend(["- %s（施策ID %s）" % (b["summary"], b["measure"] or "（空）")
              for b in cur["bad_id"]] or ["- なし"])
    L.append("")

    L.append("## 5. 集計対象外のイベント")
    L.append("")
    L.append("- 旧形式の実績（【実績】または【実施済】で始まるもの）: %d件" % cur["old"])
    L.append("- 業務外（【家計簿】で始まるもの）: %d件" % cur["private"])
    L.append("- その他（定例会議・予定枠など）: %d件" % cur["other"])
    L.append("")

    L.append("## 6. この集計の限界")
    L.append("")
    L.append("- 集計できるのはカレンダーに登録された実績イベントだけである。登録が漏れた作業は数に入らない")
    L.append("- 作業種別は件名の記載から判定している。件名が実態と異なる場合、集計も実態と異なる")
    L.append("- 所要時間はイベントの長さであり、実作業時間と一致するとは限らない")
    L.append("- 終日イベントは所要時間を0分として算入している。第4章の4.3に件名を挙げている")
    L.append("")
    L.append("自己チェック レイアウトOK / 文言OK")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--target-month", required=True, help="対象月。YYYY-MM 形式")
    ap.add_argument("--events", nargs="+", required=True,
                    help="対象月の list_events 応答を保存したJSONファイル")
    ap.add_argument("--prev-events", nargs="*", default=[],
                    help="前月の list_events 応答。省略すると前月比を出さない")
    ap.add_argument("--report", default="", help="Markdownレポートの出力先")
    ap.add_argument("--json", dest="json_out", default="", help="機械可読な集計結果の出力先")
    ap.add_argument("--generated-on", default="",
                    help="レポートに書く生成日。省略すると実行日のJST日付")
    a = ap.parse_args()

    if not re.match(r"^\d{4}-\d{2}$", a.target_month):
        sys.exit("対象月は YYYY-MM 形式で指定してください: %s" % a.target_month)
    for p in list(a.events) + list(a.prev_events):
        if not os.path.exists(p):
            sys.exit("入力ファイルが見つかりません: %s" % p)

    cur = aggregate(load_events(a.events))
    prev = None
    prev_label = prev_month(a.target_month)
    if a.prev_events:
        prev_raw = aggregate(load_events(a.prev_events))
        # 前月に【済】が1件も無い場合は比較しない。無理に比べると読み違える
        prev = prev_raw if prev_raw["done"] else None

    generated = a.generated_on or fmt_date(
        dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date())
    report = build_report(a.target_month, cur, prev, prev_label, generated)

    if a.report:
        with open(a.report, "w", encoding="utf-8") as f:
            f.write(report)
    else:
        sys.stdout.write(report)

    if a.json_out:
        summary = {
            "targetMonth": a.target_month,
            "count": len(cur["done"]),
            "totalMinutes": sum(r["minutes"] for r in cur["done"]),
            "byKind": {k: v for k, v in by_kind(cur["done"]).items()},
            "byMeasure": dict(by_measure(cur["done"])),
            "needsCheck": {
                "unset": cur["unset"],
                "multi": cur["multi"],
                "noDuration": cur["no_duration"],
                "badId": cur["bad_id"],
            },
            "excluded": {"old": cur["old"], "private": cur["private"], "other": cur["other"]},
        }
        with open(a.json_out, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

    n_check = (len(cur["unset"]) + len(cur["multi"])
               + len(cur["no_duration"]) + len(cur["bad_id"]))
    print("集計 %s: 対象%d件 合計%s 要確認%d件"
          % (a.target_month, len(cur["done"]),
             hhmm(sum(r["minutes"] for r in cur["done"])), n_check),
          file=sys.stderr)


if __name__ == "__main__":
    main()
