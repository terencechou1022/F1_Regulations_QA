"""把 FIA 2026 規則 PDF 解析成可引用的條文單位。

這支是整個 RAG 的地基：條號是 4 層階層（B5.10.8 → a. → i.），
所以「按條號切 chunk」天生就是可引用單位，不需要滑動視窗。

處理三個 spike 階段查出來的陷阱：
  1. 顏色當語意標記。紅字是治理資訊、橘字是文件參照，兩者都不是規則，
     不能被當成引用來源。純文字擷取會把它們跟條文混成一團。
  2. APPENDIX B5 底下是 Changes for 2027／2028／2029，尚未生效的規則。
     不標記出來，系統會拿 2028 年規則回答 2026 年問題，而且引用還是對的。
  3. 頁首頁尾有斷字（「2026 Form ula 1」）與白色隱形字元，都要剝除。

輸出 data/clauses.jsonl，一行一條。
"""

import json
import re
import sys
from pathlib import Path

import pdfplumber

sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

RAW = Path("data/raw")
OUT = Path("data/clauses.jsonl")

SOURCES = [
    ("A", "fia_2026_section_a_general_iss01_2025-12-10.pdf", "Issue 01", "2025-12-10"),
    ("B", "fia_2026_section_b_sporting_iss05_2026-02-27.pdf", "Issue 05", "2026-02-27"),
]

# 依兩份 PDF 首頁的 CONVENTION 段，加上實測字元顏色。
# 兩份的 legend 一致：紅／橘／綠三種都明文非約束，綠字寫的是
# "Comments / explanations / indication of further work: non-binding and non-regulatory"。
# Section B 另有粉紅＝本次修訂，那是 WMSC 核准的條文變更，仍然有效。
#
# 注意兩份用不同色彩空間：Section B 的黑是 RGB (0,0,0)，
# Section A 的黑是灰階 (0.0,)。normalise_color 負責攤平。
COLOR_CLASS = {
    (0.0, 0.0, 0.0): "regulation",       # 黑，有效條文（A 143078 / B 148359 字元）
    (1.0, 0.0, 1.0): "amendment",        # 粉紅，本次修訂，仍有效（B 9942）
    (0.0, 0.176, 0.373): "heading",      # 深藍，標題（A 12435 / B 10966）
    (0.0, 0.125, 0.376): "heading",      # 深藍變體，標題（A 1001）
    (0.69, 0.141, 0.094): "governance",  # 暗紅，治理資訊，非規則（B 348）
    (0.753, 0.0, 0.0): "governance",     # 亮紅，治理資訊，非規則（A 1586）
    (1.0, 0.6, 0.0): "reference",        # 橘，文件參照，非規則（A 35 / B 29）
    (0.0, 0.69, 0.314): "comment",       # 綠，註解，明文非約束（A 107）
    (1.0, 1.0, 1.0): "invisible",        # 白，頁邊標記（A 716 / B 869）
    (0.141, 0.125, 0.129): "regulation", # 近黑，視為條文（A 1）
}
CITABLE = {"regulation", "amendment"}

# PDF 文字層把 ffi 連字擷取成 "=i"（例：O=icials 應為 Officials）。
# 不修的話 BM25 關鍵字查詢會查不到 Officials。
LIGATURE_RE = re.compile(r"(?<=[A-Za-z])=i")


def normalise_color(c):
    """把灰階 (v,) 與 CMYK 攤平成 RGB tuple，好對同一張顏色表。"""
    if not isinstance(c, (list, tuple)):
        return None
    v = tuple(round(x, 3) for x in c)
    if len(v) == 1:
        return (v[0], v[0], v[0])
    if len(v) == 4:                       # CMYK -> RGB
        cy, m, y, k = v
        return tuple(round((1 - min(1.0, ch + k)), 3) for ch in (cy, m, y))
    return v

CLAUSE_RE = re.compile(r"^([AB]\d{1,2}(?:\.\d{1,2}){1,2})\s+(.*)$")
ARTICLE_RE = re.compile(r"^ARTICLE\s+([AB]\d{1,2}):\s*(.+?)\s*\d*$")
APPENDIX_RE = re.compile(r"^APPENDIX\s+([AB]\d+):\s*(.+?)\s*\d*$")
NOT_IN_FORCE_RE = re.compile(r"APPROVED CHANGES TO SECTION [AB] FOR SUBSEQUENT YEARS", re.I)
FOOTER_RE = re.compile(
    r"©\s*20\d\d|Fédération Internationale|^Issue \d+$|^[AB]\s+\d+$|"
    r"^\d+$|Form\s*ula 1|^SECTION [AB][:\s]|^[AB]$",
    re.I,
)


def line_color_class(line):
    """一行的語意由它的多數字元顏色決定。"""
    tally = {}
    for ch in line["chars"]:
        cls = COLOR_CLASS.get(normalise_color(ch.get("non_stroking_color")), "unknown")
        tally[cls] = tally.get(cls, 0) + 1
    tally.pop("invisible", None)
    if not tally:
        return "invisible"
    return max(tally, key=tally.get)


def parse(section, filename, issue, issue_date):
    clauses = []
    article = article_title = None
    in_force = True
    cur = None

    with pdfplumber.open(RAW / filename) as pdf:
        total_pages = len(pdf.pages)
        for page in pdf.pages[3:]:            # 前 3 頁是封面與目錄
            for line in page.extract_text_lines():
                text = line["text"].strip()
                if not text or FOOTER_RE.search(text):
                    continue

                cls = line_color_class(line)
                if cls == "invisible":
                    continue

                if NOT_IN_FORCE_RE.search(text):
                    in_force = False
                    cur = None       # 未生效區段開始，不要再往前一條附加          # 之後全部是未生效條文

                m = ARTICLE_RE.match(text) or APPENDIX_RE.match(text)
                if m:
                    article, article_title = m.group(1), m.group(2).strip()
                    # 標題要關掉目前這條，否則附錄那些不帶編號的內容
                    # （DEFINITIONS、表單、未來年度變更）會全部被附加到
                    # 最後一條編號條文上。實測 A9.8.3 曾因此膨脹到 94884 字元，
                    # 還被標成可引用進了索引，嚴重扭曲 BM25 的 IDF 與長度正規化。
                    cur = None
                    continue

                m = CLAUSE_RE.match(text)
                if m:
                    cur = {
                        "clause_id": m.group(1),
                        "section": section,
                        "article": article,
                        "article_title": article_title,
                        # text 只收有約束力的內容，供檢索與引用
                        "text": m.group(2).strip() if cls in CITABLE else "",
                        # 非約束註記另存，可以顯示但不得當引用依據
                        "annotations": [] if cls in CITABLE else [[cls, text]],
                        "page": page.page_number,
                        "opening_class": cls,
                        "in_force": in_force,
                        "source": filename,
                        "issue": issue,
                        "issue_date": issue_date,
                    }
                    clauses.append(cur)
                elif cur is not None:
                    # 續行，含 a. / i. 這些子項
                    if cls in CITABLE or cls == "heading":
                        cur["text"] = (cur["text"] + " " + text).strip()
                    else:
                        cur["annotations"].append([cls, text])

    for c in clauses:
        c["text"] = LIGATURE_RE.sub("ffi", c["text"])
        c["annotations"] = [[k, LIGATURE_RE.sub("ffi", v)] for k, v in c["annotations"]]
        # 沒有任何約束文字的條目不該被檢索到
        c["citable"] = bool(c["text"]) and c["in_force"]

    return clauses, total_pages


def main():
    all_clauses = []
    for section, filename, issue, issue_date in SOURCES:
        clauses, pages = parse(section, filename, issue, issue_date)
        cite = sum(c["citable"] for c in clauses)
        force = sum(c["in_force"] for c in clauses)
        print(
            f"Section {section}  {pages} 頁  {len(clauses)} 條  "
            f"可引用 {cite}  現行 {force}  未生效 {len(clauses) - force}"
        )
        all_clauses += clauses

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", encoding="utf-8") as fh:
        for c in all_clauses:
            fh.write(json.dumps(c, ensure_ascii=False) + "\n")
    print(f"\n寫出 {len(all_clauses)} 條 -> {OUT}")


if __name__ == "__main__":
    main()
