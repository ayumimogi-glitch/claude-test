#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成済みのダッシュボード2版を Box Drive へ置き、実行結果のJSONを書き出す。

スケジュールタスクでは、この工程を人が読み上げる手順として文章で指示していた。
文章の手順は実行のたびに解釈がぶれる。とくに共有版の上書きは、
ファイル名を変えると Box 上で別ファイルになり、関係者へ配ったURLが無効になる。
その一点を毎回の判断に任せないため、書き込み先をこのスクリプトへ固定する。

書き込む先は次の2か所だけである。それ以外のパスへは書かない。

  1. BOXDIR                03.問合せ フォルダ。生成物2件と実行結果JSONを置く
  2. SHAREFILE             共有フォルダにある既存の1ファイル。上書きだけを行う

SHAREFILE は検索で特定する。フォルダ名に濁点が含まれ、手で打つと合わないためである。
見つからない場合と2件以上見つかった場合は、上書き先を特定できないので中止する。
新規作成は行わない。

使い方:
    python3 place_to_box.py --work-dir ~/work/inquiry-dashboard
    python3 place_to_box.py --work-dir ~/work/inquiry-dashboard --dry-run
    python3 place_to_box.py --status aborted \\
        --decision-title "出口検査の不合格" \\
        --decision-detail "項目1の回帰確認が252件ではなく250件だった"

--status が normal 以外のときは配置を行わず、実行結果JSONだけを書き出す。
書き出さないと、集約タスクからは実行しなかった場合と区別が付かないためである。

終了コード:
    0 配置まで完了した、または中止の記録を書き出した
    1 配置の途中で失敗した。JSONには failed を記録する
    2 引数や前提の誤りで何もしていない
"""

import argparse
import datetime
import glob
import hashlib
import json
import os
import shutil
import sys
import time
import unicodedata

BOXDIR_RAW = os.path.expanduser(
    "~/Library/CloudStorage/Box-Box/ビジネス基盤統括部_販売促進G"
    "/01.グループフォルダ/01.統括部運営/02.マーケプロモ/03.問合せ"
)
SHARE_GLOB = os.path.expanduser(
    "~/Library/CloudStorage/Box-Box/*/PROCENTER_ConforMeeting_ReportFiling_*.html"
)

ANALYSIS_NAME = "問い合わせ分析ｘ市場動向含む_問い合わせダッシュボード.html"
SIMPLE_NAME = "問い合わせダッシュボード.html"
BACK_DIRNAME = "_back"
# 生成物とHTMLの退避先は BOXDIR 直下ではなく、その配下の出力フォルダである。
# 2026/09/17、BOXDIR直下に誤って置かれた事象を受けて追加した。
OUTDIR_SUBDIR = "問い合わせダッシュボード"

RESULT_NAME_FMT = "%Y%m%d_横断_ローカル実行結果_inquiry-dashboard-local.json"
TASK_ID = "inquiry-dashboard-local"

# Box Drive は書き込み後に同期する。直後の照合が合わないことがあるため一度だけ待つ。
RESYNC_WAIT_SEC = 30


class Abort(Exception):
    """前提が満たされず、何も書き込まずに止める場合に送出する。"""


class Failed(Exception):
    """書き込みの途中で失敗した場合に送出する。"""


def resolve_boxdir():
    """BOXDIR を返す。濁点の合成方法の違いで直接当たらない場合があるため両方を試す。"""
    for path in (BOXDIR_RAW,
                 unicodedata.normalize("NFC", BOXDIR_RAW),
                 unicodedata.normalize("NFD", BOXDIR_RAW)):
        if os.path.isdir(path):
            return path
    raise Abort("Box Drive の作業フォルダが見つかりません: %s" % BOXDIR_RAW)


def resolve_sharefile():
    """共有版のパスを検索で特定する。1件に定まらない場合は中止する。"""
    hits = sorted(glob.glob(SHARE_GLOB))
    if not hits:
        raise Abort(
            "共有版のファイルが見つかりません。新規作成はしません。検索条件: %s" % SHARE_GLOB)
    if len(hits) > 1:
        raise Abort(
            "共有版の候補が %d 件あり、上書き先を特定できません:\n  %s"
            % (len(hits), "\n  ".join(hits)))
    return hits[0]


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def stat_line(path):
    st = os.stat(path)
    mtime = datetime.datetime.fromtimestamp(st.st_mtime)
    return "%d バイト / %s" % (st.st_size, mtime.strftime("%Y-%m-%d %H:%M:%S"))


def assert_inside(path, boxdir, sharefile):
    """書き込み先が BOXDIR 配下か SHAREFILE そのものであることを確かめる。

    このスクリプトの許可範囲を、呼び出し側の引数ではなくここで固定する。
    """
    real = os.path.realpath(path)
    if real == os.path.realpath(sharefile):
        return
    if real.startswith(os.path.realpath(boxdir) + os.sep):
        return
    raise Failed("書き込みが許可されない場所です: %s" % path)


def backup_existing(boxdir, outdir, sharefile, today, dry_run, log):
    """出力フォルダ（OUTDIR）にある既存の2ファイルを OUTDIR/_back へ退避する。共有版は対象にしない。

    共有版を動かすと共有リンクが切れる。file_id に紐づいているためである。
    """
    backdir = os.path.join(outdir, BACK_DIRNAME)
    moved = []
    for name in (ANALYSIS_NAME, SIMPLE_NAME):
        src = os.path.join(outdir, name)
        if not os.path.isfile(src):
            log("退避なし（既存ファイルがありません）: %s" % name)
            continue
        log("退避前: %s  %s" % (name, stat_line(src)))

        dst = os.path.join(backdir, "%s_%s" % (today, name))
        seq = 1
        while os.path.exists(dst):
            stem, ext = os.path.splitext(name)
            dst = os.path.join(backdir, "%s_%s_%d%s" % (today, stem, seq, ext))
            seq += 1

        assert_inside(dst, boxdir, sharefile)
        if dry_run:
            log("退避する（実行しない）: %s -> %s" % (src, dst))
        else:
            os.makedirs(backdir, exist_ok=True)
            shutil.move(src, dst)
            log("退避しました: %s" % dst)
        moved.append(os.path.basename(dst))
    return moved


def verify_copies(expected, boxdir, sharefile, log):
    """置いた3ファイルの SHA256 を照合する。合わない場合は一度だけ待って再確認する。"""
    def mismatches():
        bad = []
        for path, want in expected:
            if not os.path.isfile(path):
                bad.append((path, "ファイルがありません"))
                continue
            got = sha256(path)
            if got != want:
                bad.append((path, "SHA256 不一致 期待 %s 実際 %s" % (want[:16], got[:16])))
        return bad

    bad = mismatches()
    if bad:
        log("SHA256 が一致しません。Box Drive の同期途中の可能性があるため %d 秒待って再確認します。"
            % RESYNC_WAIT_SEC)
        time.sleep(RESYNC_WAIT_SEC)
        bad = mismatches()
    if bad:
        raise Failed("置いたファイルの照合に失敗しました:\n  %s"
                     % "\n  ".join("%s: %s" % (p, why) for p, why in bad))
    log("SHA256 は3ファイルとも一致しました。")


def write_result_json(boxdir, status, output_count, needs_decision, note, dry_run, log):
    """実行結果のJSONを BOXDIR へ書き出す。キーは増やさない。"""
    now = datetime.datetime.now(
        datetime.timezone(datetime.timedelta(hours=9)))
    payload = {
        "task": TASK_ID,
        "environment": "ローカル実行",
        "ran_at": now.strftime("%Y-%m-%dT%H:%M:%S+09:00"),
        "status": status,
        "output": "Box Drive 03.問合せ および 共有フォルダ",
        "output_count": output_count,
        "needs_decision": needs_decision,
        "note": note,
    }
    path = os.path.join(boxdir, now.strftime(RESULT_NAME_FMT))
    if dry_run:
        log("実行結果を書き出す（実行しない）: %s" % path)
        log(json.dumps(payload, ensure_ascii=False, indent=2))
        return path
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")
    log("実行結果を書き出しました: %s（status=%s）" % (os.path.basename(path), status))
    return path


def place(work_dir, boxdir, sharefile, dry_run, log):
    """生成物2件を出力フォルダ（OUTDIR）へ置き、分析版で共有版を上書きする。"""
    outdir = os.path.join(boxdir, OUTDIR_SUBDIR)
    if not os.path.isdir(outdir):
        raise Abort("出力フォルダがありません。新規作成はしません: %s" % outdir)

    src_analysis = os.path.join(work_dir, ANALYSIS_NAME)
    src_simple = os.path.join(work_dir, SIMPLE_NAME)
    for path in (src_analysis, src_simple):
        if not os.path.isfile(path):
            raise Abort("生成物がありません。先に2つの版を生成してください: %s" % path)

    want_analysis = sha256(src_analysis)
    want_simple = sha256(src_simple)
    log("生成物の SHA256")
    log("  分析版 %s  %s" % (want_analysis[:16], stat_line(src_analysis)))
    log("  旧版   %s  %s" % (want_simple[:16], stat_line(src_simple)))

    today = datetime.date.today().strftime("%Y%m%d")
    moved = backup_existing(boxdir, outdir, sharefile, today, dry_run, log)

    dst_analysis = os.path.join(outdir, ANALYSIS_NAME)
    dst_simple = os.path.join(outdir, SIMPLE_NAME)
    for src, dst in ((src_analysis, dst_analysis), (src_simple, dst_simple)):
        assert_inside(dst, boxdir, sharefile)
        if dry_run:
            log("置く（実行しない）: %s" % dst)
        else:
            shutil.copyfile(src, dst)
            log("置きました: %s" % dst)

    log("共有版の上書き前: %s" % stat_line(sharefile))

    # 上書きの直前にもう一度存在を確かめる。無ければ新規作成せずに止める。
    if not os.path.isfile(sharefile):
        raise Abort("共有版が消えています。新規作成はしません: %s" % sharefile)
    assert_inside(sharefile, boxdir, sharefile)
    if dry_run:
        log("共有版を上書きする（実行しない）: %s" % sharefile)
    else:
        shutil.copyfile(src_analysis, sharefile)
        log("共有版を上書きしました: %s" % sharefile)

    # 共有フォルダに HTML が増えていないかを見る。名前を変えて新規作成してしまうと
    # ここが2件になる。サブフォルダと隠しファイルは数えない。
    # 参考資料などのフォルダが同居していても、この検査の目的とは関係がないためである。
    sharedir = os.path.dirname(sharefile)
    htmls = sorted(n for n in os.listdir(sharedir)
                   if not n.startswith(".")
                   and n.lower().endswith(".html")
                   and os.path.isfile(os.path.join(sharedir, n)))
    if len(htmls) != 1:
        raise Failed(
            "共有フォルダの HTML が %d 件です。1件でないため成功とは報告しません:\n  %s"
            % (len(htmls), "\n  ".join(htmls) if htmls else "（なし）"))
    log("共有フォルダの HTML: 1件（%s）" % htmls[0])

    if not dry_run:
        verify_copies(
            [(dst_analysis, want_analysis),
             (dst_simple, want_simple),
             (sharefile, want_analysis)],
            boxdir, sharefile, log)
        log("配置後の状態")
        for path in (dst_analysis, dst_simple, sharefile):
            log("  %s  %s" % (os.path.basename(path), stat_line(path)))

    return moved


def main():
    p = argparse.ArgumentParser(
        description="生成済みダッシュボードを Box Drive へ置き、実行結果JSONを書き出す")
    p.add_argument("--work-dir",
                   help="生成物2件があるディレクトリ。--status normal のとき必須")
    p.add_argument("--status", default="normal",
                   choices=("normal", "aborted", "failed"),
                   help="normal 以外は配置を行わず実行結果JSONだけを書き出す")
    p.add_argument("--note", default="",
                   help="market.json が古い場合や埋め合わせ実行の場合の一文")
    p.add_argument("--decision-title", default="",
                   help="中止または失敗のときの短い表題")
    p.add_argument("--decision-detail", default="",
                   help="中止または失敗のときに何が起きたか")
    p.add_argument("--dry-run", action="store_true",
                   help="書き込まずに、何をするかだけ表示する")
    args = p.parse_args()

    lines = []

    def log(msg):
        lines.append(msg)
        print(msg)

    needs_decision = []
    if args.status != "normal":
        if not args.decision_title:
            print("--status が normal 以外のときは --decision-title が必要です。", file=sys.stderr)
            return 2
        needs_decision = [{
            "title": args.decision_title,
            "detail": args.decision_detail,
            "since": datetime.date.today().strftime("%Y-%m-%d"),
        }]

    try:
        boxdir = resolve_boxdir()
        sharefile = resolve_sharefile()
    except Abort as e:
        print("中止: %s" % e, file=sys.stderr)
        return 2

    log("BOXDIR    %s" % boxdir)
    log("SHAREFILE %s" % sharefile)

    if args.status != "normal":
        write_result_json(boxdir, args.status, 0, needs_decision,
                          args.note, args.dry_run, log)
        log("配置は行いませんでした（status=%s）。" % args.status)
        return 0

    if not args.work_dir:
        print("--status normal のときは --work-dir が必要です。", file=sys.stderr)
        return 2
    work_dir = os.path.expanduser(args.work_dir)

    try:
        place(work_dir, boxdir, sharefile, args.dry_run, log)
    except Abort as e:
        log("中止: %s" % e)
        write_result_json(boxdir, "aborted", 0,
                          [{"title": "配置の前提を満たさない",
                            "detail": str(e),
                            "since": datetime.date.today().strftime("%Y-%m-%d")}],
                          args.note, args.dry_run, log)
        return 1
    except Failed as e:
        log("失敗: %s" % e)
        write_result_json(boxdir, "failed", 0,
                          [{"title": "Box Drive への配置に失敗",
                            "detail": str(e),
                            "since": datetime.date.today().strftime("%Y-%m-%d")}],
                          args.note, args.dry_run, log)
        return 1

    write_result_json(boxdir, "normal", 3, [], args.note, args.dry_run, log)
    log("配置まで完了しました。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
