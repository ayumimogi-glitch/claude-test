#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
問い合わせ分析ダッシュボードの出口検査を CODE 上で自動実行する。

Cowork のスケジュールタスクでは、この検査を人が読み上げる手順として
文章で指示していた。文章の手順は実行のたびに解釈がぶれるため、
判定できる項目だけをこのスクリプトへ移して機械判定に切り替える。

判定する項目は次のとおり。1つでも落ちたら終了コード1で終わる。

  1. 回帰確認   基準日を固定したときのレコード件数が期待値と一致する
  2. 再現性     同じ引数で2回生成した出力がバイト一致する
  3. JSエラー   明るいテーマと暗いテーマの両方でコンソールエラーが0件
  4. 横スクロール 375 / 768 / 1280 / 1600 px で横スクロールが発生しない
  5. 個人情報   メールアドレスと電話番号がHTMLに現れない
  6. 件数整合   MARKET と CONTENTS の件数が config の件数と一致する

使い方:
    python3 verify_dashboard.py \
        --skill-dir /path/to/inquiry-dashboard \
        --csv /path/to/ledger.csv \
        --work-dir /path/to/work

Playwright を使う検査（3と4）は、playwright が入っていない環境では
判定不能として扱い、その旨を出力する。黙って成功と報告しない。
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys

VARIANTS = ("analysis", "simple")
WIDTHS = (375, 768, 1280, 1600)

MAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
TEL_RE = re.compile(r"0\d{1,4}-\d{1,4}-\d{3,4}")


class Result:
    def __init__(self):
        self.rows = []
        self.failed = False

    def add(self, name, ok, detail=""):
        # ok は True（合格）、False（不合格）、None（判定不能）のいずれか
        self.rows.append((name, ok, detail))
        if ok is False:
            self.failed = True

    def report(self):
        print("")
        print("出口検査の結果")
        print("-" * 72)
        for name, ok, detail in self.rows:
            mark = {True: "合格", False: "不合格", None: "判定不能"}[ok]
            print("%-8s %-28s %s" % (mark, name, detail))
        print("-" * 72)
        return 1 if self.failed else 0


def build(skill_dir, csv_path, variant, out_path, as_of=""):
    """build_dashboard.py を1回実行し、標準エラーの生成行を返す。"""
    cmd = [sys.executable, os.path.join(skill_dir, "scripts", "build_dashboard.py"),
           "--csv", csv_path, "--variant", variant, "--out", out_path]
    if as_of:
        cmd += ["--as-of", as_of]
    p = subprocess.run(cmd, cwd=skill_dir, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError("生成に失敗しました（%s）: %s" % (variant, p.stderr.strip()))
    return p.stderr.strip()


def parse_count(stderr_line):
    """生成[...]: ... レコード252件 ... から件数を取り出す。"""
    m = re.search(r"レコード(\d+)件", stderr_line)
    if not m:
        raise RuntimeError("生成結果から件数を読み取れません: %s" % stderr_line)
    return int(m.group(1))


def check_regression(res, skill_dir, csv_path, work_dir, as_of, expect):
    for variant in VARIANTS:
        out = os.path.join(work_dir, "regression_%s.html" % variant)
        try:
            line = build(skill_dir, csv_path, variant, out, as_of=as_of)
            got = parse_count(line)
        except RuntimeError as e:
            res.add("回帰確認 %s" % variant, False, str(e))
            continue
        want = expect[variant]
        res.add("回帰確認 %s" % variant, got == want,
                "基準日%s 期待%d件 実際%d件" % (as_of, want, got))


def check_reproducible(res, skill_dir, csv_path, work_dir):
    for variant in VARIANTS:
        a = os.path.join(work_dir, "repro_a_%s.html" % variant)
        b = os.path.join(work_dir, "repro_b_%s.html" % variant)
        try:
            build(skill_dir, csv_path, variant, a)
            build(skill_dir, csv_path, variant, b)
        except RuntimeError as e:
            res.add("再現性 %s" % variant, False, str(e))
            continue
        with open(a, "rb") as f1, open(b, "rb") as f2:
            same = f1.read() == f2.read()
        res.add("再現性 %s" % variant, same,
                "2回生成してバイト一致" if same else "2回の出力が一致しません")


def check_personal_data(res, work_dir):
    for variant in VARIANTS:
        path = os.path.join(work_dir, "repro_a_%s.html" % variant)
        if not os.path.exists(path):
            res.add("個人情報 %s" % variant, None, "生成物が無いため判定不能")
            continue
        text = open(path, encoding="utf-8").read()
        mails = sorted(set(MAIL_RE.findall(text)))
        tels = sorted(set(TEL_RE.findall(text)))
        ok = not mails and not tels
        detail = "検出なし" if ok else "メール%s 電話%s" % (mails[:3], tels[:3])
        res.add("個人情報 %s" % variant, ok, detail)


def count_list_objects(raw):
    """JSリテラル（キーが引用符なし）の list: [...] に並ぶ要素数を数える。

    contents.js.txt は JSON ではなく JS のオブジェクトリテラルであるため、
    json.loads では読めない。波括弧の深さを数えて要素数だけを求める。
    """
    i = raw.find("list")
    if i < 0:
        return None
    i = raw.find("[", i)
    if i < 0:
        return None
    depth = 0
    n = 0
    for ch in raw[i:]:
        if ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                break
        elif ch == "{" and depth == 1:
            n += 1
    return n


def check_counts(res, skill_dir, work_dir):
    """供給元の config が、そのまま分析版へ入っているかを確かめる。

    build_dashboard.py は config の中身を差し込み位置へ verbatim で入れる。
    よって「config の本文がHTMLに現れること」を確かめれば、
    供給が届いたこと（取り込み漏れや切れが無いこと）を機械判定できる。
    """
    config_dir = os.path.join(skill_dir, "config")
    analysis = os.path.join(work_dir, "repro_a_analysis.html")
    simple = os.path.join(work_dir, "repro_a_simple.html")
    if not os.path.exists(analysis):
        res.add("件数整合", None, "分析版が無いため判定不能")
        return
    text = open(analysis, encoding="utf-8").read()

    # 差し込み位置が残っていないこと。残っていれば供給が届いていない
    left = re.findall(r"/\*__[A-Z0-9_]+__\*/", text)
    res.add("差し込み位置", not left,
            "未置換なし" if not left else "未置換 %s" % sorted(set(left))[:3])

    market_path = os.path.join(config_dir, "market.json")
    if os.path.exists(market_path):
        raw = open(market_path, encoding="utf-8").read()
        n = len(json.loads(raw).get("items", []))
        res.add("件数整合 MARKET", raw.strip() in text,
                "config %d件が分析版に入っている" % n)
        if os.path.exists(simple):
            stext = open(simple, encoding="utf-8").read()
            res.add("旧版にMARKET無し", raw.strip() not in stext,
                    "旧版は市場動向を持たないのが正しい")

    contents_path = os.path.join(config_dir, "contents.js.txt")
    if os.path.exists(contents_path):
        raw = open(contents_path, encoding="utf-8").read()
        n = count_list_objects(raw)
        detail = "config %s件が分析版に入っている" % ("不明" if n is None else n)
        if n == 0:
            detail += "。供給元が空のため Content Gap は判定不可になる"
        res.add("件数整合 CONTENTS", raw.strip() in text, detail)


def check_browser(res, work_dir):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        res.add("JSエラー", None, "playwright 未導入のため判定不能")
        res.add("横スクロール", None, "playwright 未導入のため判定不能")
        return

    exe = None
    base = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers")
    for name in sorted(os.listdir(base)) if os.path.isdir(base) else []:
        cand = os.path.join(base, name, "chrome-linux", "chrome")
        if name.startswith("chromium-") and os.path.exists(cand):
            exe = cand
            break

    with sync_playwright() as pw:
        kw = {"executable_path": exe} if exe else {}
        try:
            browser = pw.chromium.launch(**kw)
        except Exception as e:
            # 実行環境に chromium が無い場合がある。検査を落とさず判定不能として残す。
            # 黙って合格にしないことが要点である
            res.add("JSエラー", None, "chromium を起動できず判定不能（%s）" % type(e).__name__)
            res.add("横スクロール", None, "chromium を起動できず判定不能")
            return
        for variant in VARIANTS:
            path = os.path.join(work_dir, "repro_a_%s.html" % variant)
            if not os.path.exists(path):
                res.add("JSエラー %s" % variant, None, "生成物が無いため判定不能")
                continue
            url = "file://" + os.path.abspath(path)
            for scheme in ("light", "dark"):
                ctx = browser.new_context(color_scheme=scheme,
                                          viewport={"width": 1280, "height": 900})
                page = ctx.new_page()
                errors = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.on("console", lambda m: errors.append(m.text)
                        if m.type == "error" else None)
                page.goto(url, wait_until="load")
                page.wait_for_timeout(1200)
                res.add("JSエラー %s %s" % (variant, scheme), not errors,
                        "0件" if not errors else "%d件 %s" % (len(errors), errors[:2]))
                ctx.close()

            ctx = browser.new_context(viewport={"width": WIDTHS[0], "height": 900})
            page = ctx.new_page()
            page.goto(url, wait_until="load")
            over = []
            for w in WIDTHS:
                page.set_viewport_size({"width": w, "height": 900})
                page.wait_for_timeout(400)
                sw, cw = page.evaluate(
                    "() => [document.documentElement.scrollWidth,"
                    " document.documentElement.clientWidth]")
                # 1px の端数は丸め誤差として許容する
                if sw - cw > 1:
                    over.append("%dpx(%d>%d)" % (w, sw, cw))
            res.add("横スクロール %s" % variant, not over,
                    "全幅で発生なし" if not over else "発生 " + " ".join(over))
            ctx.close()
        browser.close()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--skill-dir", required=True,
                    help="inquiry-dashboard の作業用コピー")
    ap.add_argument("--csv", required=True, help="問い合わせ台帳CSV")
    ap.add_argument("--work-dir", required=True, help="生成物の置き場。git管理外にする")
    ap.add_argument("--as-of", default="2026-08-31", help="回帰確認の基準日")
    ap.add_argument("--expect-analysis", type=int, default=252)
    ap.add_argument("--expect-simple", type=int, default=223)
    ap.add_argument("--skip-browser", action="store_true",
                    help="ブラウザ検査を行わない。判定不能として記録する")
    a = ap.parse_args()

    os.makedirs(a.work_dir, exist_ok=True)
    if not os.path.exists(a.csv):
        sys.exit("台帳CSVが見つかりません: %s" % a.csv)
    if shutil.which("python3") is None:
        sys.exit("python3 が見つかりません")

    expect = {"analysis": a.expect_analysis, "simple": a.expect_simple}
    res = Result()
    check_regression(res, a.skill_dir, a.csv, a.work_dir, a.as_of, expect)
    check_reproducible(res, a.skill_dir, a.csv, a.work_dir)
    check_personal_data(res, a.work_dir)
    check_counts(res, a.skill_dir, a.work_dir)
    if a.skip_browser:
        res.add("JSエラー", None, "--skip-browser の指定により判定不能")
        res.add("横スクロール", None, "--skip-browser の指定により判定不能")
    else:
        check_browser(res, a.work_dir)
    sys.exit(res.report())


if __name__ == "__main__":
    main()
