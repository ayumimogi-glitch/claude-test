#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""merge_inquiry_csv.py の回帰テスト。合成データだけを使う。"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import merge_inquiry_csv as mic

NES = "dxs-sb-sales@nes.jp.nec.com"
ONENEC = "sales@procenter.jp.nec.com"


def raw(date, company, product="PROCENTER", address=NES, **kw):
    d = {"発生日": date, "客先": company, "製品": product, "宛先アドレス": address}
    d.update(kw)
    return d


class TestFiscal(unittest.TestCase):
    def test_year_boundary(self):
        self.assertEqual(mic.fiscal_year("2026-04-01"), "2026年度")
        self.assertEqual(mic.fiscal_year("2026-03-31"), "2025年度")

    def test_quarters(self):
        self.assertEqual(mic.quarter("2026-05-10"), "2026年度Q1")
        self.assertEqual(mic.quarter("2026-08-10"), "2026年度Q2")
        self.assertEqual(mic.quarter("2026-11-10"), "2026年度Q3")
        self.assertEqual(mic.quarter("2026-02-10"), "2025年度Q4")


class TestNormalize(unittest.TestCase):
    def test_derives_year_quarter_and_media(self):
        row = mic.normalize(raw("2026-05-20", "テスト商事"))
        self.assertEqual(row["年度"], "2026年度")
        self.assertEqual(row["四半期"], "2026年度Q1")
        self.assertEqual(row["媒体"], "NES社外サイト")

    def test_onenec_media(self):
        row = mic.normalize(raw("2026-05-20", "テスト商事", address=ONENEC))
        self.assertEqual(row["媒体"], "OneNEC")

    def test_industry_defaults_to_unknown(self):
        self.assertEqual(mic.normalize(raw("2026-05-20", "テスト商事"))["業種"], "不明")

    def test_missing_company_becomes_placeholder(self):
        row = mic.normalize(raw("2026-05-20", ""))
        self.assertEqual(row["客先"], "（客先不明）")

    def test_bad_date_is_rejected(self):
        for bad in ["2026/05/20", "20260520", "", "2026-13-01"]:
            with self.assertRaises(mic.RowError):
                mic.normalize(raw(bad, "テスト商事"))

    def test_unknown_address_is_rejected(self):
        with self.assertRaises(mic.RowError):
            mic.normalize(raw("2026-05-20", "テスト商事", address="other@example.invalid"))

    def test_given_year_is_ignored_and_recomputed(self):
        row = mic.normalize(raw("2026-02-10", "テスト商事", 年度="2026年度"))
        self.assertEqual(row["年度"], "2025年度")


class TestPersonalData(unittest.TestCase):
    def test_mail_in_company_is_rejected(self):
        with self.assertRaises(mic.RowError):
            mic.normalize(raw("2026-05-20", "山田 taro@example.co.jp"))

    def test_phone_in_note_is_rejected(self):
        with self.assertRaises(mic.RowError):
            mic.normalize(raw("2026-05-20", "テスト商事", 備考="連絡先 03-1234-5678"))

    def test_address_column_itself_is_allowed(self):
        row = mic.normalize(raw("2026-05-20", "テスト商事"))
        self.assertEqual(row["宛先アドレス"], NES)


class TestMerge(unittest.TestCase):
    def setUp(self):
        self.ledger = [mic.normalize(raw("2026-05-20", "既存商事"))]

    def test_new_row_is_added(self):
        merged, added, skipped = mic.merge(self.ledger, [raw("2026-05-21", "新規商事")])
        self.assertEqual(len(merged), 2)
        self.assertEqual(len(added), 1)
        self.assertEqual(skipped, [])

    def test_duplicate_is_skipped(self):
        merged, added, skipped = mic.merge(self.ledger, [raw("2026-05-20", "既存商事")])
        self.assertEqual(len(merged), 1)
        self.assertEqual(added, [])
        self.assertEqual(len(skipped), 1)

    def test_same_day_same_company_different_product_is_not_duplicate(self):
        merged, added, _ = mic.merge(
            self.ledger, [raw("2026-05-20", "既存商事", product="ConforMeeting")])
        self.assertEqual(len(added), 1)
        self.assertEqual(len(merged), 2)

    def test_duplicate_inside_new_rows_is_skipped(self):
        merged, added, skipped = mic.merge(
            self.ledger, [raw("2026-06-01", "A社"), raw("2026-06-01", "A社")])
        self.assertEqual(len(added), 1)
        self.assertEqual(len(skipped), 1)

    def test_sorted_by_date_ascending(self):
        merged, _, _ = mic.merge(
            self.ledger, [raw("2026-01-05", "古い商事"), raw("2026-09-09", "新しい商事")])
        dates = [r["発生日"] for r in merged]
        self.assertEqual(dates, sorted(dates))


class TestSince(unittest.TestCase):
    def test_two_days_before_latest(self):
        ledger = [mic.normalize(raw("2026-05-20", "A社")),
                  mic.normalize(raw("2026-09-10", "B社"))]
        self.assertEqual(mic.since_date(ledger), "2026-09-08")

    def test_empty_ledger_uses_fourteen_days(self):
        self.assertRegex(mic.since_date([]), r"^\d{4}-\d{2}-\d{2}$")


class TestIo(unittest.TestCase):
    def test_round_trip_keeps_bom_and_columns(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "ledger.csv")
            rows = [mic.normalize(raw("2026-05-20", "テスト商事"))]
            mic.write_ledger(path, rows)
            head = open(path, "rb").read(3)
            self.assertEqual(head, b"\xef\xbb\xbf", "BOM付きであること")
            back = mic.read_ledger(path)
            self.assertEqual(back, rows)

    def test_reads_file_without_bom(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "ledger.csv")
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(",".join(mic.COLUMNS) + "\n")
                f.write("2026-05-20,2026年度,2026年度Q1,PROCENTER,不明,テスト商事,"
                        "NES社外サイト," + NES + ",\n")
            rows = mic.read_ledger(path)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["客先"], "テスト商事")


if __name__ == "__main__":
    unittest.main(verbosity=2)
