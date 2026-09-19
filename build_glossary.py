"""從 FIA 規則的 DEFINITIONS 附錄抽出權威縮寫表，再疊上繁中車迷用語別名。

這支處理的是整個專案的核心設計題：詞彙鴻溝有兩層。
  第一層　中文到英文：車迷用繁中問，文件是英文
  第二層　車迷用語到 FIA 縮寫：車迷說「正賽」，2026 規則寫 TTCS

實測 TTCS 在條文裡出現 139 次、LTCS 19 次。不做查詢改寫，
使用者問「正賽」會一條都命中不到。

英文那半是從 PDF 抽的，不是我編的。中文那半是人工映射，
每一條都必須能從英文定義推出來，理由記在 CN_ALIASES 的註解裡。
"""

import json
import re
import sys
from pathlib import Path

import pdfplumber

sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)

RAW = Path("data/raw")
OUT = Path("data/glossary.json")

# DEFINITIONS 附錄的頁碼範圍（1-based，含）與句型
DEF_PAGES = {
    "fia_2026_section_b_sporting_iss05_2026-02-27.pdf": (84, 86),
    "fia_2026_section_a_general_iss01_2025-12-10.pdf": (45, 54),
}

# “Full Term” (or “ACR”) is / shall be defined as ...
WITH_ACRONYM = re.compile(
    r"[“\"]([^”\"]{3,80})[”\"]\s*\(\s*or\s*[“\"]([A-Za-z0-9/ ]{2,8})[”\"]\s*\)\s*"
    r"(?:is|shall be|are|means)\s+(.{20,600}?)(?=\s*[“\"]|\Z)",
    re.S,
)
# “Term”: definition
BARE_TERM = re.compile(r"[“\"]([^”\"]{3,60})[”\"]\s*:\s*(.{20,400}?)(?=\s*[“\"]|\Z)", re.S)

FOOTER = re.compile(
    r"©\s*20\d\d|Fédération Internationale|^Issue \d+$|Form\s*ula 1|"
    r"^SECTION [AB][:\s]|^APPENDIX [AB]\d|^[AB]\s*\d*$",
    re.M,
)

# 繁中車迷用語別名。每一條都由上面抽出的英文定義推出，不是自行發明。
# key 是 FIA 縮寫或術語，value 是車迷可能打出來的說法。
CN_ALIASES = {
    # 定義明文寫 "include, but are not limited to, the Sprint session and the Race session"
    "TTCS": ["正賽", "決賽", "衝刺賽", "短衝刺", "比賽"],
    # 定義是 classification 依單圈時間決定，即自由練習與排位
    "LTCS": ["排位賽", "排位", "自由練習", "練習賽", "FP1", "FP2", "FP3"],
    "AFC": ["有衝刺賽的分站", "衝刺賽週末"],
    "SFC": ["標準賽制分站", "沒有衝刺賽的週末"],
    "PU": ["動力單元", "引擎", "動力系統"],
    "ERS": ["能量回收系統", "電能回收"],
    "VSC": ["虛擬安全車"],
    "SC": ["安全車", "實體安全車"],
    "ISC": ["國際運動規則", "國際賽車運動規則"],
    "WMSC": ["世界賽車運動理事會"],
    "ASN": ["國家賽車運動總會"],
    "ECU": ["電子控制單元"],
    "DMS": ["文件管理系統"],
    "RNC": ["限用數量零件", "限量零件"],
    "RP": ["禁制期間", "宵禁"],
    "TCC": ["現役賽車測試"],
    "TPC": ["前代賽車測試"],
    "DE": ["示範活動"],
    "PE": ["宣傳活動"],
    "CC": ["現役賽車"],
    "PC": ["前代賽車"],
    "HC": ["古董賽車"],
    "Fast Lane": ["快車道"],
    "Inner Lane": ["內車道"],
    "Pit Lane": ["維修道", "P房通道"],
    "Parc Fermé": ["封閉檢查區", "帕克費爾梅"],
    "Stop-and-Go Penalty": ["停車再走罰則", "進站罰停"],
    "Safety Car Line": ["安全車線"],
}


def page_text(pdf_path, first, last):
    chunks = []
    with pdfplumber.open(pdf_path) as pdf:
        for i in range(first - 1, min(last, len(pdf.pages))):
            chunks.append(pdf.pages[i].extract_text() or "")
    text = "\n".join(chunks)
    text = FOOTER.sub("", text)
    return re.sub(r"\s+", " ", text)


def extract(pdf_path, first, last):
    text = page_text(pdf_path, first, last)
    found = {}

    for term, acronym, body in WITH_ACRONYM.findall(text):
        key = acronym.strip()
        found[key] = {
            "acronym": key,
            "term": term.strip(),
            "definition": re.sub(r"\s+", " ", body).strip(),
            "source": Path(pdf_path).name,
        }

    for term, body in BARE_TERM.findall(text):
        key = term.strip()
        if key in found or any(v["term"] == key for v in found.values()):
            continue
        found[key] = {
            "acronym": None,
            "term": key,
            "definition": re.sub(r"\s+", " ", body).strip(),
            "source": Path(pdf_path).name,
        }

    return found


def main():
    glossary = {}
    for filename, (first, last) in DEF_PAGES.items():
        got = extract(RAW / filename, first, last)
        print(f"{filename[:34]:<34} p{first}-{last}  抽到 {len(got)} 條")
        glossary.update(got)

    matched = unmatched = 0
    for key, aliases in CN_ALIASES.items():
        if key in glossary:
            glossary[key]["cn_aliases"] = aliases
            matched += 1
        else:
            hit = next((k for k, v in glossary.items() if v["term"] == key), None)
            if hit:
                glossary[hit]["cn_aliases"] = aliases
                matched += 1
            else:
                # 別名對不上抽出來的定義，另立一筆並標明沒有 PDF 依據
                glossary[key] = {
                    "acronym": key if key.isupper() else None,
                    "term": key,
                    "definition": None,
                    "source": None,
                    "cn_aliases": aliases,
                }
                unmatched += 1

    print(f"\n中文別名 {len(CN_ALIASES)} 組：{matched} 組對上 PDF 定義，"
          f"{unmatched} 組沒有 PDF 依據（definition 為 null，需人工複核）")

    OUT.write_text(
        json.dumps(glossary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"寫出 {len(glossary)} 條 -> {OUT}")

    print("\n關鍵幾條:")
    for k in ("TTCS", "LTCS", "TCC", "PE"):
        v = glossary.get(k)
        if v:
            d = (v["definition"] or "")[:150]
            print(f"  {k:<6} {v['term']}")
            print(f"         定義 {d}")
            print(f"         別名 {v.get('cn_aliases')}")


if __name__ == "__main__":
    main()
