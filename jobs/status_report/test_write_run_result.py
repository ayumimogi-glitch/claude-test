#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""write_run_result.py の回帰テスト。

実行:
    python3 test_write_run_result.py

判定の分かれ目になった実例を固定する。次の2件は実際に起きたものである。

- 2026/09/16 のダッシュボードの実行で、中止したときの output に
  指示と違う値が入った。本文に書いた形をモデルが毎回組み立てると値が揺れる
- 中止と失敗のときこそ実行結果を残す必要がある。書き出されないと、
  集約側からは実行しなかった場合と区別が付かない
"""

import datetime
import json
import unittest

from write_run_result import KEYS, build, validate

FIXED = datetime.datetime(2026, 9, 22, 11, 4, 5,
                          tzinfo=datetime.timezone(datetime.timedelta(hours=9)))


def ok(**kw):
    """合格する中身を作る。個々のテストで必要な値だけ差し替える。"""
    args = dict(task="kousuu-shukei", environment="CODE", status="normal",
                output="Box 工数集計_自動生成", output_count=1, note="",
                decision_title="", decision_detail="", now=FIXED)
    args.update(kw)
    return build(**args)


class 組み立て(unittest.TestCase):

    def test_キーは8つで増減しない(self):
        self.assertEqual(tuple(ok().keys()), KEYS)

    def test_ran_atはJSTで末尾が09時間(self):
        self.assertEqual(ok()["ran_at"], "2026-09-22T11:04:05+09:00")

    def test_normalではneeds_decisionが空になる(self):
        self.assertEqual(ok()["needs_decision"], [])

    def test_abortedでは理由が1件入る(self):
        d = ok(status="aborted", decision_title="回帰テストの失敗",
               decision_detail="3件不合格")
        self.assertEqual(len(d["needs_decision"]), 1)
        self.assertEqual(d["needs_decision"][0]["title"], "回帰テストの失敗")
        self.assertEqual(d["needs_decision"][0]["since"], "2026-09-22")

    def test_理由のキーは3つで増減しない(self):
        d = ok(status="failed", decision_title="表題")
        self.assertEqual(tuple(d["needs_decision"][0].keys()),
                         ("title", "detail", "since"))

    def test_detailを省いても空文字で入る(self):
        d = ok(status="failed", decision_title="表題")
        self.assertEqual(d["needs_decision"][0]["detail"], "")

    def test_知らないstatusは組み立てない(self):
        with self.assertRaises(ValueError):
            ok(status="success")

    def test_normal以外で理由が無ければ組み立てない(self):
        with self.assertRaises(ValueError):
            ok(status="aborted")

    def test_normalに理由を付けたら組み立てない(self):
        with self.assertRaises(ValueError):
            ok(decision_title="表題")

    def test_件数が負なら組み立てない(self):
        with self.assertRaises(ValueError):
            ok(output_count=-1)

    def test_対象日でない日の記録もnormalで残せる(self):
        # 毎日起動して対象日以外は何もしない Routine がある。
        # 何もしなかったことを note に残し、成果物0件の normal として扱う
        d = ok(output="", output_count=0, note="本日は対象日ではないため実行していない")
        self.assertEqual(validate(d), [])
        self.assertEqual(d["output_count"], 0)


class 検査(unittest.TestCase):

    def test_正しい中身は合格(self):
        self.assertEqual(validate(ok()), [])

    def test_キーが欠けたら不合格(self):
        d = ok()
        del d["note"]
        self.assertIn("欠けているキー: note", validate(d))

    def test_キーが増えたら不合格(self):
        d = ok()
        d["duration_sec"] = 12
        self.assertIn("余計なキー: duration_sec", validate(d))

    def test_知らないstatusは不合格(self):
        d = ok()
        d["status"] = "success"
        self.assertTrue(any("status" in x for x in validate(d)))

    def test_件数が文字列なら不合格(self):
        d = ok()
        d["output_count"] = "1"
        self.assertTrue(any("output_count" in x for x in validate(d)))

    def test_noteがnullなら不合格(self):
        d = ok()
        d["note"] = None
        self.assertTrue(any("note" in x for x in validate(d)))

    def test_abortedで理由が空なら不合格(self):
        d = ok()
        d["status"] = "aborted"
        self.assertIn("status が aborted だが needs_decision が空である", validate(d))

    def test_normalで理由が入っていたら不合格(self):
        d = ok()
        d["needs_decision"] = [{"title": "a", "detail": "b", "since": "2026-09-22"}]
        self.assertIn("status が normal だが needs_decision に項目がある", validate(d))

    def test_理由のキーが欠けたら不合格(self):
        d = ok(status="failed", decision_title="表題")
        del d["needs_decision"][0]["since"]
        self.assertIn("needs_decision[0] に since が無い", validate(d))

    def test_理由に余計なキーがあれば不合格(self):
        d = ok(status="failed", decision_title="表題")
        d["needs_decision"][0]["owner"] = "茂木"
        self.assertIn("needs_decision[0] に余計なキー owner がある", validate(d))

    def test_needs_decisionが配列でなければ不合格(self):
        d = ok()
        d["needs_decision"] = {}
        self.assertTrue(any("配列ではない" in x for x in validate(d)))

    def test_ran_atにタイムゾーンが無ければ不合格(self):
        d = ok()
        d["ran_at"] = "2026-09-22T11:04:05"
        self.assertTrue(any("ran_at" in x for x in validate(d)))

    def test_ran_atがUTCなら不合格(self):
        # 集約側はJSTで日付を突き合わせる。UTCのまま置くと1日ずれる
        d = ok()
        d["ran_at"] = "2026-09-22T02:04:05Z"
        self.assertTrue(any("ran_at" in x for x in validate(d)))


class 実際に起きたこと(unittest.TestCase):

    def test_中止時のoutputが指示と違う値になっていた件(self):
        # 2026/09/16 のダッシュボードの実行で "なし（手順0の前提確認で中止）" が入った。
        # 値そのものは検査で弾けない。弾けるのは形だけである。
        # このスクリプトを通せば output は呼び出し側の引数で固定される
        d = ok(status="aborted", output="Box Drive 03.問合せ および 共有フォルダ",
               output_count=0, decision_title="前提不足",
               decision_detail="contents.js.txt とスキルが見つからない")
        self.assertEqual(validate(d), [])
        self.assertEqual(d["output"], "Box Drive 03.問合せ および 共有フォルダ")

    def test_JSONへ書き出して読み直しても合格する(self):
        d = ok(status="failed", decision_title="表題", decision_detail="詳細")
        again = json.loads(json.dumps(d, ensure_ascii=False))
        self.assertEqual(validate(again), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
