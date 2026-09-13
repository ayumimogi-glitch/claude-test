#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""aggregate_kousuu.py の判定ロジックの回帰テスト。

実データは顧客名や業務内容を含むため、このテストには合成データだけを使う。
ただし判定の分かれ目になった実例は、件名の形だけを残して再現する。
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import aggregate_kousuu as ak


def ev(summary, start=None, end=None, allday=False):
    if allday:
        return {"summary": summary,
                "start": {"date": start or "2026-08-03"},
                "end": {"date": end or "2026-08-04"}}
    return {"summary": summary,
            "start": {"dateTime": start or "2026-08-03T09:00:00+09:00"},
            "end": {"dateTime": end or "2026-08-03T10:00:00+09:00"}}


class TestClassify(unittest.TestCase):
    def test_second_token_wins_over_whole_scan(self):
        """件名規則どおりの場合、対象の側に別の種別の語があっても複数該当にしない。

        2026/09/04 に実データで確認した実例の形を再現する。件名全体を走査すると
        資料作成と会議の2語に該当するが、作業種別は第2トークンの資料作成である。
        """
        s = "【済】DWP2_資料作成_会議アジェンダ12枚と競合調査総括報告8枚"
        kind, matched = ak.classify(s)
        self.assertEqual(kind, "資料作成")
        self.assertEqual(matched, [])

    def test_whole_scan_when_naming_rule_not_followed(self):
        kind, matched = ak.classify("【済】横断 情報収集メモ")
        self.assertEqual(kind, "情報収集")
        self.assertEqual(matched, [])

    def test_whole_scan_multiple_hits_takes_first_position(self):
        kind, matched = ak.classify("【済】会議のあと議事メモ作成まで実施")
        self.assertEqual(kind, "会議")
        self.assertEqual(matched, ["会議", "議事メモ作成"])

    def test_unset_is_not_forced_into_existing_kind(self):
        kind, matched = ak.classify("【済】A1_棚卸_版数の確認")
        self.assertEqual(kind, ak.KIND_UNSET)
        self.assertEqual(matched, [])

    def test_second_token_not_in_kinds_falls_back_to_scan(self):
        kind, _ = ak.classify("【済】A1_棚卸_体裁チェックもあわせて実施")
        self.assertEqual(kind, "体裁チェック")


class TestMeasureId(unittest.TestCase):
    def test_extract(self):
        self.assertEqual(ak.measure_id("【済】横断_資料作成_台帳"), "横断")
        self.assertEqual(ak.measure_id("【済】A1_会議_定例"), "A1")

    def test_valid_ids(self):
        for ok in ["横断", "A1", "C12", "P3", "R7", "SEC2", "sec10"]:
            self.assertTrue(ak.id_is_valid(ok), ok)

    def test_invalid_ids(self):
        for ng in ["DWP2", "PROCENTER", "", "A", "12"]:
            self.assertFalse(ak.id_is_valid(ng), ng)


class TestDuration(unittest.TestCase):
    def test_minutes_from_start_and_end(self):
        e = ev("【済】横断_会議_定例",
               "2026-08-03T09:00:00+09:00", "2026-08-03T10:30:00+09:00")
        self.assertEqual(ak.duration_minutes(e), 90)

    def test_allday_has_no_duration(self):
        e = ev("【済】横断_会議_終日", allday=True)
        self.assertIsNone(ak.duration_minutes(e))

    def test_no_quarter_hour_assumption(self):
        """件数に0.25をかける方法は使わない。実データは15分単位ではない。"""
        e = ev("【済】横断_情報収集_調査",
               "2026-08-03T09:00:00+09:00", "2026-08-03T09:47:00+09:00")
        self.assertEqual(ak.duration_minutes(e), 47)


class TestAggregate(unittest.TestCase):
    def setUp(self):
        self.events = [
            ev("【済】横断_資料作成_台帳の更新",
               "2026-08-03T09:00:00+09:00", "2026-08-03T10:00:00+09:00"),
            ev("【済】DWP2_資料作成_会議アジェンダ12枚と競合調査総括報告8枚",
               "2026-08-04T13:00:00+09:00", "2026-08-04T15:30:00+09:00"),
            ev("【済】A1_棚卸_版数の確認",
               "2026-08-05T09:00:00+09:00", "2026-08-05T09:30:00+09:00"),
            ev("【済】横断_会議_終日枠", allday=True),
            ev("【実績】旧形式のもの"),
            ev("【実施済】旧形式のもの"),
            ev("【家計簿】週次TSV生成"),
            ev("定例会議"),
        ]
        self.res = ak.aggregate(self.events)

    def test_only_done_is_counted(self):
        self.assertEqual(len(self.res["done"]), 4)

    def test_excluded_counts(self):
        self.assertEqual(self.res["old"], 2)
        self.assertEqual(self.res["private"], 1)
        self.assertEqual(self.res["other"], 1)

    def test_unset_listed_separately(self):
        self.assertEqual(self.res["unset"], ["【済】A1_棚卸_版数の確認"])

    def test_no_duration_listed_and_counted_as_zero(self):
        self.assertEqual(self.res["no_duration"], ["【済】横断_会議_終日枠"])
        zero = [r for r in self.res["done"] if r["summary"].endswith("終日枠")][0]
        self.assertEqual(zero["minutes"], 0.0)

    def test_bad_id_listed(self):
        bad = [b["measure"] for b in self.res["bad_id"]]
        self.assertEqual(bad, ["DWP2"])

    def test_total_minutes(self):
        total = sum(r["minutes"] for r in self.res["done"])
        self.assertEqual(total, 60 + 150 + 30 + 0)

    def test_by_kind(self):
        table = ak.by_kind(self.res["done"])
        self.assertEqual(table["資料作成"]["n"], 2)
        self.assertEqual(table["資料作成"]["min"], 210)
        self.assertEqual(table["会議"]["n"], 1)
        self.assertEqual(table[ak.KIND_UNSET]["n"], 1)


class TestExtractEvents(unittest.TestCase):
    def test_single_page(self):
        self.assertEqual(len(ak.extract_events({"events": [1, 2]})), 2)

    def test_multiple_pages(self):
        data = [{"events": [1, 2]}, {"events": [3]}]
        self.assertEqual(len(ak.extract_events(data)), 3)

    def test_bare_event_array(self):
        data = [{"summary": "a"}, {"summary": "b"}]
        self.assertEqual(len(ak.extract_events(data)), 2)


class TestReport(unittest.TestCase):
    def test_report_keeps_all_section_four_headings(self):
        """第4章の各項目は、該当が無い場合も見出しごと残す。"""
        res = ak.aggregate([ev("【済】横断_資料作成_台帳の更新")])
        md = ak.build_report("2026-08", res, None, "2026-07", "2026/09/14")
        for heading in ["### 4.1", "### 4.2", "### 4.3", "### 4.4"]:
            self.assertIn(heading, md)
        self.assertIn("なし", md)

    def test_report_has_terms_table_and_self_check(self):
        res = ak.aggregate([ev("【済】横断_資料作成_台帳の更新")])
        md = ak.build_report("2026-08", res, None, "2026-07", "2026/09/14")
        self.assertIn("用語統一表", md)
        self.assertIn("実績イベント", md)
        self.assertIn("自己チェック レイアウトOK / 文言OK", md)

    def test_no_forbidden_characters(self):
        """エムダッシュ・矢印記号・丸数字・絵文字を使わない。"""
        res = ak.aggregate([ev("【済】横断_資料作成_台帳の更新")])
        md = ak.build_report("2026-08", res, None, "2026-07", "2026/09/14")
        for ng in ["—", "→", "①", "⇒"]:
            self.assertNotIn(ng, md)

    def test_no_comparison_when_prev_has_no_done(self):
        res = ak.aggregate([ev("【済】横断_資料作成_台帳の更新")])
        md = ak.build_report("2026-08", res, None, "2026-07", "2026/09/14")
        self.assertIn("前月は件名規則の適用前にあたるため比較していません", md)

    def test_comparison_when_prev_has_done(self):
        cur = ak.aggregate([ev("【済】横断_資料作成_台帳の更新")])
        prev = ak.aggregate([ev("【済】横断_資料作成_前月分")])
        md = ak.build_report("2026-09", cur, prev, "2026-08", "2026/09/14")
        self.assertIn("前月（2026-08）と並べて差を示します", md)


class TestMonthHelpers(unittest.TestCase):
    def test_prev_month(self):
        self.assertEqual(ak.prev_month("2026-09"), "2026-08")
        self.assertEqual(ak.prev_month("2026-01"), "2025-12")

    def test_month_bounds(self):
        s, e = ak.month_bounds("2026-12")
        self.assertEqual(str(s), "2026-12-01")
        self.assertEqual(str(e), "2027-01-01")


if __name__ == "__main__":
    unittest.main(verbosity=2)
