#!/usr/bin/env python3
"""verify_report.py の回帰テスト。

実行:
    python3 test_verify_report.py

判定の分かれ目になった実例を固定する。とくに次の3件は実際に起きたものである。

- 2026/09/16 の初版で、対象期間の区切りにエムダッシュが使われていた
- 見出し帯の白文字は palette に無いが許容する
- 埋め込みJSONが元JSONと一致していることを確かめる必要がある
"""

import json
import unittest

from verify_report import verify

STYLE = {
    "palette": {
        "primary": "#0F1ED2",
        "text": "#282D3C",
        "muted": "#A7AFC1",
        "border": "#C9D2E3",
        "note_band": "#EAECFB",
        "sub_text": "#5B6270",
    },
    "font_stack": '"Yu Gothic","游ゴシック","Meiryo",sans-serif',
    "rules": ["角丸を使わない"],
    "canvas": {"width_px": 1160, "export_width_px": 1536},
}

DATA = {
    "schema_version": "1.1",
    "generated_at": "2026-09-16T08:45:00+09:00",
    "period": {"from": "2026-09-15T09:00:00+09:00", "to": "2026-09-16T08:45:00+09:00"},
    "summary": {"total_tasks": 21, "normal": 19, "failed_or_missing": 0, "needs_decision": 2},
    "needs_decision": [
        {
            "id": "D1",
            "title": "工数集計の実行間隔が名称と食い違う",
            "detail": "名称は毎月2日だが設定は毎日である",
            "since": "2026-09-14",
            "options": ["承認", "保留", "不採用"],
            "source": "スケジュールタスク一覧",
        },
        {
            "id": "D2",
            "title": "OneDrive変更ログが2本とも有効である",
            "detail": "旧タスクとCODE版が並走している",
            "since": "2026-09-14",
            "options": ["承認", "保留", "不採用"],
            "source": "スケジュールタスク一覧",
        },
    ],
    "failed_or_missing": [],
    "normal": [],
    "artifacts": [{"location": "Box 03.問合せ", "count": 1, "latest": "2026-09-16T09:03:00+09:00"}],
    "limits": ["成果物の中身が正しいかは判定していない"],
    "style": STYLE,
}


def build_html(data=None, period_sep="から", extra_css="", extra_body=""):
    d = data if data is not None else DATA
    s = d["style"]
    rows = "".join(
        f'<div class="decision"><span>{x["title"]}</span>'
        f'<div class="choices">{"".join("<span>" + o + "</span>" for o in x["options"])}</div></div>'
        for x in d["needs_decision"][:5]
    )
    arts = "".join(f'<div class="row"><span>{a["location"]}</span><b>{a["count"]}</b></div>'
                   for a in d["artifacts"])
    lims = "".join(f"<p>{l}</p>" for l in d["limits"])
    failed = "<p>該当なし</p>" if not d["failed_or_missing"] else "".join(
        f'<p>{f["task"]}</p>' for f in d["failed_or_missing"])
    sm = d["summary"]
    return (
        '<!doctype html><html lang="ja"><meta charset="utf-8"><style>'
        f'body{{font-family:{s["font_stack"]};color:{s["palette"]["text"]};'
        f'background:{s["palette"]["note_band"]}}}'
        f'main{{width:{s["canvas"]["width_px"]}px}}'
        f'header{{background:{s["palette"]["primary"]};color:white}}'
        f'section{{border:1px solid {s["palette"]["border"]}}}'
        f'small{{color:{s["palette"]["sub_text"]}}}'
        f'.stat{{border-top:1px solid {s["palette"]["muted"]}}}'
        f"{extra_css}</style><main><header>"
        f'<p class="period">{d["period"]["from"][:10]} 09:00 {period_sep} {d["period"]["to"][:10]} 08:45</p>'
        f'<div><span>正常</span><b>{sm["normal"]}</b></div>'
        f'<div><span>失敗または未実行</span><b>{sm["failed_or_missing"]}</b></div>'
        f'<div><span>要判断</span><b>{sm["needs_decision"]}</b></div>'
        f'<div><small>対象 {sm["total_tasks"]} 件</small></div>'
        f"</header><section>{rows}</section><section>{failed}</section>"
        f"<section>{arts}</section><section>{lims}</section>{extra_body}</main>"
        f'<script type="application/json" id="source-json">{json.dumps(d, ensure_ascii=False)}</script></html>'
    )


def failed_names(res):
    return [name for _, name, ok, _ in res.rows if not ok]


class TestVerifyReport(unittest.TestCase):
    def test_正しいレポートは全件合格(self):
        res = verify(build_html(), DATA)
        self.assertEqual(failed_names(res), [])

    def test_エムダッシュを検出する(self):
        res = verify(build_html(period_sep="—"), DATA)
        self.assertIn("禁止の文字 エムダッシュ", failed_names(res))

    def test_角丸を検出する(self):
        res = verify(build_html(extra_css="a{border-radius:4px}"), DATA)
        self.assertIn("禁止の体裁 border-radius", failed_names(res))

    def test_影を検出する(self):
        res = verify(build_html(extra_css="a{box-shadow:0 0 3px #000}"), DATA)
        self.assertIn("禁止の体裁 box-shadow", failed_names(res))

    def test_許可外の色を検出する(self):
        res = verify(build_html(extra_css="a{color:#00A040}"), DATA)
        self.assertIn("配色が palette の範囲内", failed_names(res))

    def test_見出し帯の白文字は許容する(self):
        res = verify(build_html(), DATA)
        self.assertNotIn("配色が palette の範囲内", failed_names(res))

    def test_丸数字を検出する(self):
        res = verify(build_html(extra_body="<p>①</p>"), DATA)
        self.assertIn("禁止の文字 丸数字", failed_names(res))

    def test_矢印を検出する(self):
        res = verify(build_html(extra_body="<p>A→B</p>"), DATA)
        self.assertIn("禁止の文字 矢印記号", failed_names(res))

    def test_全角数字を検出する(self):
        res = verify(build_html(extra_body="<p>１２</p>"), DATA)
        self.assertIn("禁止の文字 全角数字", failed_names(res))

    def test_フォントが1つだけなら不合格(self):
        d = json.loads(json.dumps(DATA, ensure_ascii=False))
        d["style"]["font_stack"] = "Meiryo"
        res = verify(build_html(d), d)
        self.assertIn("書体を複数並べている", failed_names(res))

    def test_数値が本文に無ければ不合格(self):
        html = build_html().replace(">19<", ">99<")
        res = verify(html, DATA)
        self.assertIn("summary.normal の値が本文にある", failed_names(res))

    def test_要判断の表題が欠けたら不合格(self):
        html = build_html().replace(DATA["needs_decision"][1]["title"], "別の表題")
        res = verify(html, DATA)
        self.assertIn("要判断 D2 の表題", failed_names(res))

    def test_3択が欠けたら不合格(self):
        html = build_html().replace("<span>不採用</span>", "")
        res = verify(html, DATA)
        self.assertIn("要判断 D1 の3択", failed_names(res))

    def test_埋め込みJSONが元と違えば不合格(self):
        html = build_html()
        other = json.loads(json.dumps(DATA, ensure_ascii=False))
        other["summary"]["normal"] = 18
        res = verify(html, other)
        self.assertIn("埋め込みJSONが元JSONと一致", failed_names(res))

    def test_埋め込みJSONが無ければ不合格(self):
        html = build_html()
        html = html[: html.index('<script type="application/json"')] + "</html>"
        res = verify(html, DATA)
        self.assertIn("元JSONの埋め込み", failed_names(res))

    def test_埋め込みJSONが壊れていれば不合格(self):
        html = build_html().replace('id="source-json">{', 'id="source-json">{{')
        res = verify(html, DATA)
        self.assertIn("元JSONの埋め込み", failed_names(res))

    def test_失敗が0件で該当なしが無ければ不合格(self):
        html = build_html().replace("該当なし", "")
        res = verify(html, DATA)
        self.assertIn("失敗が0件のときの該当なし表記", failed_names(res))

    def test_失敗があればタスク名を確認する(self):
        d = json.loads(json.dumps(DATA, ensure_ascii=False))
        d["failed_or_missing"] = [
            {"task": "鮮度点検", "environment": "クラウド実行", "expected_output": "Box",
             "last_success": "2026-09-14", "consecutive_misses": 2, "reason": "不明"}
        ]
        d["summary"]["failed_or_missing"] = 1
        res = verify(build_html(d), d)
        self.assertEqual(failed_names(res), [])

    def test_注記が欠けたら不合格(self):
        html = build_html().replace(DATA["limits"][0], "別の注記")
        res = verify(html, DATA)
        self.assertIn("注記の行", failed_names(res))

    def test_成果物の置き場が欠けたら不合格(self):
        html = build_html().replace("Box 03.問合せ", "どこか", 1)
        res = verify(html, DATA)
        self.assertIn("成果物の置き場", failed_names(res))

    def test_制作幅が違えば不合格(self):
        html = build_html().replace("width:1160px", "width:1200px")
        res = verify(html, DATA)
        self.assertIn("制作幅が canvas.width_px と一致", failed_names(res))

    def test_対象期間の日付が無ければ不合格(self):
        html = build_html().replace("2026-09-15", "2026-09-01", 1)
        res = verify(html, DATA)
        self.assertIn("対象期間のfrom", failed_names(res))

    def test_要判断が6件なら5件までの掲載になる(self):
        d = json.loads(json.dumps(DATA, ensure_ascii=False))
        base = d["needs_decision"][0]
        d["needs_decision"] = []
        for i in range(6):
            x = json.loads(json.dumps(base, ensure_ascii=False))
            x["id"] = f"D{i+1}"
            x["title"] = f"表題{i+1}"
            d["needs_decision"].append(x)
        d["summary"]["needs_decision"] = 6
        res = verify(build_html(d), d)
        self.assertEqual(failed_names(res), [])

    def test_埋め込みJSONの中のエムダッシュは本文の判定に含めない(self):
        d = json.loads(json.dumps(DATA, ensure_ascii=False))
        d["limits"] = ["区切りの説明に—を含む注記"]
        html = build_html(d)
        # 本文にも出るため不合格になる。本文から消すと合格することを確かめる
        html2 = html.replace("<p>区切りの説明に—を含む注記</p>", "<p>区切りの説明を含む注記</p>")
        res = verify(html2, d)
        self.assertNotIn("禁止の文字 エムダッシュ", failed_names(res))


if __name__ == "__main__":
    unittest.main(verbosity=2)
