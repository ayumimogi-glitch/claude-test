#!/usr/bin/env python3
"""スキル inquiry-dashboard の作業用コピーへ差分を当てる。

使い方:
    python3 apply.py <作業用コピーのディレクトリ>

例:
    python3 apply.py ~/work/inquiry-dashboard

なぜ必要か:
    スキルはプラグインとして配られており、実行環境には読み取り用の展開コピーしか無い。
    そこを書き換えても次回の実行に残らない。そのため差分をリポジトリ側に置き、
    作業用コピーを作った直後に当てる。CODE 側と Mac 側が同じリポジトリを参照するため、
    どちらで動かしても同じ差分が当たる。

当て方:
    行番号ではなく文字列の一致で当てる。
    見つからない場合と複数見つかった場合は、その場で失敗させる。
    スキル正本が更新されて当てる場所がずれたことに気づかないまま進むのを防ぐためである。
    既に当たっている場合は「適用済み」として飛ばす。

終了コード:
    0 すべて適用済み、または今回適用した
    1 1件以上の差分を当てられなかった
"""

import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
FILES_DIR = os.path.join(HERE, "files")

# 年商レンジの参照データを読み込み、社名で引けるようにする差分。
# 法人格の一覧は NFKC 正規化の後の表記で書く。
REVENUE_BLOCK = """const CONTENTS = /*__CONTENTS__*/;
/* 年商レンジの参照データ。台帳から作らず、market.json と同じく外から供給する。
   list に {company, range, basis} を入れる。確認できないものは項目ごと載せない */
const REVENUE = /*__REVENUE__*/;
/* 社名の照合。全角と半角をそろえ、空白と中黒と法人格を除いてから突き合わせる */
const REV_LEGAL = ['株式会社','有限会社','合同会社','合資会社','相互会社',
  '一般社団法人','一般財団法人','公益社団法人','公益財団法人','独立行政法人',
  '社会福祉法人','特定非営利活動法人','(株)','(有)'];
const revNorm = s => {
  let t = String(s == null ? '' : s).normalize('NFKC');
  REV_LEGAL.forEach(w => { t = t.split(w).join(''); });
  return t.replace(/[\\s\\u30fb]/g, '').toLowerCase();
};
const REV_MAP = (() => {
  const m = {};
  ((REVENUE && REVENUE.list) || []).forEach(x => {
    const k = revNorm(x.company);
    if (k) { m[k] = x; }
  });
  return m;
})();
const revOf = c => REV_MAP[revNorm(c)] || null;"""

DETAIL_COLS = """    {h:'年商レンジ', f:r=>{ const v = revOf(r.c); return esc(v ? v.range : '不明'); }},
    {h:'年商の出典', f:r=>{ const v = revOf(r.c); return `<span class="cap">${esc(v ? v.basis : '未取得')}</span>`; }},
    {h:'媒体', f:r=>esc(r.m)},"""

CSV_ROW_NEW = (
    "  F.forEach(r => { const rv = revOf(r.c);\n"
    "    lines.push([r.d, r.p, r.c, r.i, r.rs, rv ? rv.range : '不明', rv ? rv.basis : '未取得',"
    " r.m, r.k, r.f, r.note || '', DATA.sources[r.s]].map(cell).join(',')); });"
)

PATCHES = [
    (
        "assets/template.html",
        "見出しの格助詞",
        '<h2 class="big">誰に動くか</h2>',
        '<h2 class="big">誰に対して動くか</h2>',
    ),
    (
        "assets/template.html",
        "年商レンジの参照データと照合関数",
        "const CONTENTS = /*__CONTENTS__*/;",
        REVENUE_BLOCK,
    ),
    (
        "assets/template.html",
        "明細へ年商レンジと年商の出典の2列",
        "    {h:'媒体', f:r=>esc(r.m)},",
        DETAIL_COLS,
    ),
    (
        "assets/template.html",
        "CSV保存の列見出しへ2列",
        "  const cols = ['発生日','製品','客先','業種','業種の根拠','媒体',"
        "'問い合わせ区分','BC管理表との企業名照合','備考','出典'];",
        "  const cols = ['発生日','製品','客先','業種','業種の根拠','年商レンジ','年商の出典','媒体',"
        "'問い合わせ区分','BC管理表との企業名照合','備考','出典'];",
    ),
    (
        "assets/template.html",
        "CSV保存の各行へ2列の値",
        "  F.forEach(r => lines.push([r.d, r.p, r.c, r.i, r.rs, r.m, r.k, r.f,"
        " r.note || '', DATA.sources[r.s]].map(cell).join(',')));",
        CSV_ROW_NEW,
    ),
    (
        "scripts/build_dashboard.py",
        "revenue.json を分析版へ差し込む",
        '            "CONTENTS": load_text(os.path.join(a.config, "contents.js.txt")),',
        '            "CONTENTS": load_text(os.path.join(a.config, "contents.js.txt")),\n'
        '            "REVENUE": load_text(os.path.join(a.config, "revenue.json")),',
    ),
]

# 参照データの既定値。作業用コピーに無ければ置く。既にあれば触らない
CONFIG_FILES = [("revenue.json", "config/revenue.json")]


def apply_patch(work, rel, name, old, new):
    path = os.path.join(work, rel)
    if not os.path.isfile(path):
        return False, f"対象のファイルがありません: {rel}"
    with open(path, encoding="utf-8") as f:
        text = f.read()
    if new in text:
        return True, "適用済み"
    n = text.count(old)
    if n == 0:
        return False, "当てる場所が見つかりません。スキル正本が変わった可能性があります"
    if n > 1:
        return False, f"当てる場所が{n}か所あります。1か所に絞れないため中止します"
    with open(path, "w", encoding="utf-8") as f:
        f.write(text.replace(old, new, 1))
    return True, "適用しました"


def place_config(work, src_name, rel):
    dst = os.path.join(work, rel)
    if os.path.exists(dst):
        return True, "既にあります。触りません"
    src = os.path.join(FILES_DIR, src_name)
    if not os.path.isfile(src):
        return False, f"既定値のファイルがありません: {src}"
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    shutil.copyfile(src, dst)
    return True, "既定値を置きました"


def main(argv):
    if len(argv) != 2:
        print(__doc__)
        return 1
    work = os.path.abspath(os.path.expanduser(argv[1]))
    if not os.path.isdir(work):
        print(f"作業用コピーがありません: {work}")
        return 1

    ok = True
    for rel, name, old, new in PATCHES:
        done, msg = apply_patch(work, rel, name, old, new)
        print(f"{'OK  ' if done else 'NG  '}{name} [{rel}] : {msg}")
        ok = ok and done
    for src_name, rel in CONFIG_FILES:
        done, msg = place_config(work, src_name, rel)
        print(f"{'OK  ' if done else 'NG  '}参照データ [{rel}] : {msg}")
        ok = ok and done

    print("")
    if ok:
        print("上書き層をすべて適用しました。")
        return 0
    print("上書き層を当てられませんでした。生成へ進まないでください。")
    print("当たらないまま生成すると、年商レンジの列が無い版ができます。")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
