#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""build_change_log.py の判定の回帰テスト。合成データだけを使う。"""
import csv
import io
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import build_change_log as bcl

TARGET = "2026-09-13"


def item(fid, name, folder, created, modified, size=100, user="茂木 あゆみ"):
    return {
        "id": fid,
        "name": name,
        "size": size,
        "createdDateTime": created,
        "lastModifiedDateTime": modified,
        "lastModifiedBy": {"user": {"displayName": user}},
        "parentReference": {"path": "/drive/root:" + folder},
        "webUrl": "https://example.invalid/%s" % fid,
    }


class TestHelpers(unittest.TestCase):
    def test_folder_strips_graph_prefix(self):
        it = item("1", "a.md", "/個人作業/メモ", "2026-09-13T01:00:00Z", "2026-09-13T01:00:00Z")
        self.assertEqual(bcl.folder_of(it), "/個人作業/メモ")

    def test_extension(self):
        self.assertEqual(bcl.extension("報告書_v1_0.md"), "md")
        self.assertEqual(bcl.extension("拡張子なし"), "")

    def test_utc_is_converted_to_jst(self):
        d = bcl.to_jst("2026-09-13T23:30:00Z")
        # UTC 23:30 は JST では翌日の 08:30
        self.assertEqual(bcl.fmt_ts(d), "2026-09-14 08:30:00")

    def test_load_items_accepts_value_wrapper_and_bare_array(self):
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            wrapped = os.path.join(d, "w.json")
            bare = os.path.join(d, "b.json")
            with open(wrapped, "w", encoding="utf-8") as f:
                json.dump({"value": [{"id": "1"}, {"id": "2"}]}, f)
            with open(bare, "w", encoding="utf-8") as f:
                json.dump([{"id": "1"}], f)
            self.assertEqual(len(bcl.load_items(wrapped)), 2)
            self.assertEqual(len(bcl.load_items(bare)), 1)


class TestClassify(unittest.TestCase):
    def test_created_today(self):
        it = item("1", "a.md", "/f", "2026-09-13T02:00:00+09:00", "2026-09-13T02:00:00+09:00")
        kinds, before, changed = bcl.classify(it, {}, TARGET)
        self.assertEqual(kinds, [bcl.CREATED])
        self.assertTrue(changed)

    def test_renamed_only(self):
        prev = {"1": {"name": "old.md", "folder": "/f",
                      "lastModifiedDateTime": "2026-09-12T02:00:00+09:00"}}
        it = item("1", "new.md", "/f", "2026-09-01T02:00:00+09:00",
                  "2026-09-12T02:00:00+09:00")
        kinds, before, changed = bcl.classify(it, prev, TARGET)
        self.assertEqual(kinds, [bcl.RENAMED])
        self.assertIn("old.md", before)

    def test_moved_only(self):
        prev = {"1": {"name": "a.md", "folder": "/old",
                      "lastModifiedDateTime": "2026-09-12T02:00:00+09:00"}}
        it = item("1", "a.md", "/new", "2026-09-01T02:00:00+09:00",
                  "2026-09-12T02:00:00+09:00")
        kinds, before, _ = bcl.classify(it, prev, TARGET)
        self.assertEqual(kinds, [bcl.MOVED])
        self.assertIn("/old", before)

    def test_moved_and_renamed_and_modified(self):
        prev = {"1": {"name": "old.md", "folder": "/old",
                      "lastModifiedDateTime": "2026-09-12T02:00:00+09:00"}}
        it = item("1", "new.md", "/new", "2026-09-01T02:00:00+09:00",
                  "2026-09-13T05:00:00+09:00")
        kinds, _, _ = bcl.classify(it, prev, TARGET)
        self.assertEqual(kinds, [bcl.RENAMED, bcl.MOVED, bcl.MODIFIED])

    def test_move_is_not_reported_as_new_creation(self):
        """ファイルIDが前日の在庫にあれば、場所が変わっても新規作成にしない。"""
        prev = {"1": {"name": "a.md", "folder": "/old",
                      "lastModifiedDateTime": "2026-09-12T02:00:00+09:00"}}
        it = item("1", "a.md", "/new", "2026-09-13T02:00:00+09:00",
                  "2026-09-13T02:00:00+09:00")
        kinds, _, _ = bcl.classify(it, prev, TARGET)
        self.assertNotIn(bcl.CREATED, kinds)
        self.assertIn(bcl.MOVED, kinds)

    def test_unchanged_file_is_skipped(self):
        prev = {"1": {"name": "a.md", "folder": "/f",
                      "lastModifiedDateTime": "2026-09-01T02:00:00+09:00"}}
        it = item("1", "a.md", "/f", "2026-08-01T02:00:00+09:00",
                  "2026-09-01T02:00:00+09:00")
        kinds, _, changed = bcl.classify(it, prev, TARGET)
        self.assertFalse(changed)
        self.assertEqual(kinds, [])

    def test_without_snapshot_existing_file_is_marked_unknown(self):
        it = item("1", "a.md", "/f", "2026-08-01T02:00:00+09:00",
                  "2026-08-02T02:00:00+09:00")
        kinds, _, changed = bcl.classify(it, None, TARGET)
        self.assertEqual(kinds, [bcl.EXISTING_UNKNOWN])
        self.assertFalse(changed)


class TestRows(unittest.TestCase):
    def test_deleted_row_is_added(self):
        prev = {"1": {"name": "消えた.md", "folder": "/f",
                      "lastModifiedDateTime": "2026-09-12T02:00:00+09:00"}}
        rows = bcl.build_rows([], prev, TARGET, "")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["変更種別"], bcl.DELETED)
        self.assertEqual(rows[0]["ファイル名"], "消えた.md")

    def test_one_row_per_file_id(self):
        it = item("1", "a.md", "/f", "2026-09-13T02:00:00+09:00",
                  "2026-09-13T09:00:00+09:00")
        rows = bcl.build_rows([it, dict(it)], {}, TARGET, "")
        self.assertEqual(len(rows), 1)

    def test_columns_are_exactly_the_specified_order(self):
        it = item("1", "a.md", "/f", "2026-09-13T02:00:00+09:00",
                  "2026-09-13T02:00:00+09:00")
        rows = bcl.build_rows([it], {}, TARGET, "")
        self.assertEqual(list(rows[0].keys()), bcl.COLUMNS)

    def test_classification_is_blank_unless_given(self):
        it = item("1", "a.md", "/f", "2026-09-13T02:00:00+09:00",
                  "2026-09-13T02:00:00+09:00")
        rows = bcl.build_rows([it], {}, TARGET, "")
        self.assertEqual(rows[0]["機密区分"], "")

    def test_no_changes_gives_no_rows(self):
        prev = {"1": {"name": "a.md", "folder": "/f",
                      "lastModifiedDateTime": "2026-09-01T02:00:00+09:00"}}
        it = item("1", "a.md", "/f", "2026-08-01T02:00:00+09:00",
                  "2026-09-01T02:00:00+09:00")
        self.assertEqual(bcl.build_rows([it], prev, TARGET, ""), [])


class TestCsv(unittest.TestCase):
    def test_header_only_when_empty(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "out.csv")
            bcl.write_csv(path, [])
            raw = open(path, "rb").read()
            self.assertTrue(raw.startswith(b"\xef\xbb\xbf"), "BOM付きであること")
            text = raw.decode("utf-8-sig")
            reader = list(csv.reader(io.StringIO(text)))
            self.assertEqual(reader[0], bcl.COLUMNS)
            self.assertEqual(len(reader), 1)


class TestSnapshot(unittest.TestCase):
    def test_snapshot_keeps_name_and_folder(self):
        it = item("1", "a.md", "/f", "2026-09-13T02:00:00+09:00",
                  "2026-09-13T02:00:00+09:00")
        snap = bcl.snapshot_of([it])
        self.assertEqual(snap["1"]["name"], "a.md")
        self.assertEqual(snap["1"]["folder"], "/f")


if __name__ == "__main__":
    unittest.main(verbosity=2)
