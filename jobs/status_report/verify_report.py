#!/usr/bin/env python3
"""実行状況レポート（HTML）の出口検査。

使い方:
    python3 verify_report.py --html <レポートのHTML> --json <元になったサマリJSON>

判定は決定的である。同じ入力なら同じ出力になる。
判断が要る工程（見た目の良し悪し、文面の適切さ）はここに入れない。

終了コード:
    0 すべて合格
    1 1件以上の不合格
    2 入力の読み取りに失敗
"""

import argparse
import json
import re
import sys
import unicodedata

# 図版の標準テイストのうち、機械で判定できるもの（2026/09/11 確定）
PALETTE_KEYS = ("primary", "text", "muted", "border", "note_band", "sub_text")

# 見出し帯の文字色として認める白。palette に無くても許容する
WHITE_OK = {"#ffffff", "#fff", "white"}

FORBIDDEN_CSS = (
    ("border-radius", r"border-radius"),
    ("box-shadow", r"box-shadow"),
    ("text-shadow", r"text-shadow"),
    ("gradient", r"gradient"),
    ("filter", r"filter\s*:"),
)

FORBIDDEN_CHARS = (
    ("丸数字", r"[①-⑳㉑-㉟㊱-㊿]"),
    ("矢印記号", r"[←-⇿➔-➿]"),
    ("エムダッシュ", r"—"),
    ("全角数字", r"[０-９]"),
    ("置換文字", r"�"),
)


class Result:
    def __init__(self):
        self.rows = []

    def add(self, level, name, ok, detail=""):
        self.rows.append((level, name, ok, detail))

    @property
    def failed(self):
        return [r for r in self.rows if not r[2]]

    def report(self):
        lines = []
        for level, name, ok, detail in self.rows:
            mark = "合格" if ok else "不合格"
            line = f"{mark} [{level}] {name}"
            if detail:
                line += f" : {detail}"
            lines.append(line)
        lines.append("")
        lines.append(f"判定 {len(self.rows) - len(self.failed)} / {len(self.rows)} 合格")
        return "\n".join(lines)


def strip_embedded_json(html):
    """埋め込みJSONを除いた本文を返す。本文だけを対象にする判定で使う。"""
    return re.sub(
        r'<script[^>]*id="source-json"[^>]*>.*?</script>', "", html, flags=re.S
    )


def extract_embedded_json(html):
    m = re.search(r'<script[^>]*id="source-json"[^>]*>(.*?)</script>', html, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except ValueError:
        return False  # 構文が壊れている


def check_forbidden_css(body, res):
    for name, pat in FORBIDDEN_CSS:
        hits = re.findall(pat, body, re.I)
        res.add("高", f"禁止の体裁 {name}", not hits, f"{len(hits)}件")


def check_forbidden_chars(body, res):
    for name, pat in FORBIDDEN_CHARS:
        hits = re.findall(pat, body)
        detail = f"{len(hits)}件"
        if hits:
            detail += f" 例 {hits[0]!r}"
        res.add("高", f"禁止の文字 {name}", not hits, detail)


def check_palette(body, style, res):
    palette = style.get("palette", {})
    allowed = {str(palette[k]).lower() for k in PALETTE_KEYS if k in palette}
    allowed |= {str(v).lower() for v in palette.values()}
    allowed |= WHITE_OK
    used = set()
    for c in re.findall(r"#[0-9A-Fa-f]{3,8}", body):
        used.add(c.lower())
    for word in re.findall(r"color\s*:\s*([a-zA-Z]+)", body):
        if word.lower() in WHITE_OK:
            used.add(word.lower())
    extra = sorted(used - allowed)
    res.add("高", "配色が palette の範囲内", not extra, f"許可外 {extra}" if extra else "許可外なし")


def check_font(body, style, res):
    want = style.get("font_stack", "")
    m = re.search(r"font-family\s*:\s*([^;}]+)", body)
    got = m.group(1).strip() if m else ""

    def norm(s):
        return re.sub(r"\s+", "", s).replace("'", '"')

    res.add("高", "font-family が font_stack と一致", bool(want) and norm(want) == norm(got),
            f"実際 {got[:60]}")
    res.add("中", "書体を複数並べている", got.count(",") >= 2, f"区切り {got.count(',')}個")


def check_width(body, style, res):
    want = style.get("canvas", {}).get("width_px")
    ok = want is not None and f"{want}px" in body
    res.add("中", "制作幅が canvas.width_px と一致", ok, f"期待 {want}px")


def check_embedded(html, data, res):
    emb = extract_embedded_json(html)
    if emb is None:
        res.add("中", "元JSONの埋め込み", False, "source-json が無い")
        return
    if emb is False:
        res.add("高", "元JSONの埋め込み", False, "JSONの構文が壊れている")
        return
    res.add("高", "埋め込みJSONが元JSONと一致", emb == data,
            "一致" if emb == data else "内容が異なる")


def check_numbers(body, data, res):
    s = data.get("summary", {})
    for key in ("total_tasks", "normal", "failed_or_missing", "needs_decision"):
        if key not in s:
            res.add("高", f"summary.{key} が存在", False, "キーが無い")
            continue
        res.add("高", f"summary.{key} の値が本文にある", str(s[key]) in body, f"値 {s[key]}")


def check_decisions(body, data, res):
    items = data.get("needs_decision", [])
    shown = items[:5]
    for d in shown:
        title = d.get("title", "")
        res.add("高", f"要判断 {d.get('id','')} の表題", title and title in body, title[:34])
        opts = d.get("options", [])
        res.add("高", f"要判断 {d.get('id','')} の3択", all(o in body for o in opts), " ".join(opts))
    if len(items) > 5:
        res.add("中", "6件以上のときの注記", "件" in body, f"総数 {len(items)}")
    res.add("中", "要判断は5件まで", len(shown) <= 5, f"掲載 {len(shown)}件")


def check_failed(body, data, res):
    items = data.get("failed_or_missing", [])
    if not items:
        res.add("中", "失敗が0件のときの該当なし表記", "該当なし" in body, "")
        return
    for f in items:
        name = f.get("task", "")
        res.add("高", "失敗の行", name and name in body, name[:34])


def check_artifacts(body, data, res):
    for a in data.get("artifacts", []):
        loc = a.get("location", "")
        res.add("中", "成果物の置き場", loc and loc in body, loc[:34])


def check_limits(body, data, res):
    for l in data.get("limits", []):
        res.add("中", "注記の行", l in body, l[:34])


def check_period(body, data, res):
    p = data.get("period", {})
    for key in ("from", "to"):
        v = str(p.get(key, ""))
        day = v[:10]
        res.add("中", f"対象期間の{key}", bool(day) and day in body, day)


def verify(html, data):
    res = Result()
    body = strip_embedded_json(html)
    style = data.get("style", {})
    check_forbidden_css(body, res)
    check_forbidden_chars(body, res)
    check_palette(body, style, res)
    check_font(body, style, res)
    check_width(body, style, res)
    check_period(body, data, res)
    check_numbers(body, data, res)
    check_decisions(body, data, res)
    check_failed(body, data, res)
    check_artifacts(body, data, res)
    check_limits(body, data, res)
    check_embedded(html, data, res)
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(description="実行状況レポートの出口検査")
    ap.add_argument("--html", required=True)
    ap.add_argument("--json", required=True)
    args = ap.parse_args(argv)
    try:
        html = open(args.html, encoding="utf-8").read()
        html = unicodedata.normalize("NFC", html)
        data = json.load(open(args.json, encoding="utf-8"))
    except (OSError, ValueError) as e:
        print(f"入力の読み取りに失敗しました: {e}")
        return 2
    res = verify(html, data)
    print(res.report())
    return 1 if res.failed else 0


if __name__ == "__main__":
    sys.exit(main())
