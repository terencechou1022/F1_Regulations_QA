"""產出 30 題測試集的工作單，把「讀完 180 頁」變成「審 30 條」。

驗收標準 P0 第 1 條要 30 題含標準條號答案。原本估要 6 到 10 小時純人工，
因為 2026 規則縮寫密度高，不真的讀完不知道哪條在講什麼。

這支不代寫問題，因為問題要像車迷會問的樣子，那是領域判斷。
它做的是**分層抽樣**：確保 30 題散布在車迷真的會問的條文上，
而不是集中在同一篇。抽完輸出工作單，人工只需要看條文寫問題。

抽樣優先序依「車迷會問什麼」排：判罰與裁處 > 安全車與中斷 > 起跑程序 >
輪胎與零件 > 其他。這個排序是設計決策，不是從資料推出來的，寫在這裡供覆核。
"""

import json
import random
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

CLAUSES = Path("data/clauses.jsonl")
OUT = Path("data/testset_worksheet.jsonl")
TARGET = 30
SEED = 20260910          # 固定種子，抽樣可重現

# 車迷提問熱度分組。關鍵詞比對條文與篇名，命中就落到該組。
# 配額是主觀設計，理由：判罰與安全車是社群爭議最多的兩類。
TOPICS = [
    ("判罰與裁處", 9, r"penalt|breach|sanction|adjudicat|infring|steward|reprimand|disqualif"),
    ("安全車與中斷", 6, r"safety car|virtual safety|vsc|suspension|resumption|red flag"),
    ("起跑與排位程序", 6, r"start|grid|formation lap|false start|qualifying|pit lane starter"),
    ("輪胎與零件限制", 5, r"tyre|component|power unit|parc fermé|parc ferme|bodywork"),
    ("其他", 4, r"."),
]


def load():
    rows = [json.loads(l) for l in CLAUSES.open(encoding="utf-8")]
    # 只從可引用且有實質內容的條文出題。太短的條文問不出東西。
    return [c for c in rows if c["citable"] and len(c["text"]) >= 120]


def bucket(clauses):
    groups = defaultdict(list)
    for c in clauses:
        haystack = f"{c['text']} {c.get('article_title') or ''}".lower()
        for name, _, pattern in TOPICS:
            if re.search(pattern, haystack):
                groups[name].append(c)
                break
    return groups


def main():
    clauses = load()
    groups = bucket(clauses)
    rng = random.Random(SEED)

    print(f"可出題條文 {len(clauses)} 條（可引用且長度 ≥ 120 字元）\n")
    print(f"{'主題':<16}{'配額':>5}{'可選':>7}")
    picked = []
    for name, quota, _ in TOPICS:
        pool = groups.get(name, [])
        take = rng.sample(pool, min(quota, len(pool)))
        picked += [(name, c) for c in take]
        print(f"{name:<16}{quota:>5}{len(pool):>7}")

    # 配額湊不滿就從剩下的補齊，優先補條文最長的（資訊量高）
    if len(picked) < TARGET:
        chosen = {c["clause_id"] for _, c in picked}
        rest = sorted(
            (c for c in clauses if c["clause_id"] not in chosen),
            key=lambda c: -len(c["text"]),
        )
        for c in rest[: TARGET - len(picked)]:
            picked.append(("補齊", c))

    with OUT.open("w", encoding="utf-8") as fh:
        for i, (topic, c) in enumerate(picked[:TARGET], 1):
            fh.write(json.dumps({
                "id": i,
                "topic": topic,
                "question_zh": "",                  # 人工填：像車迷會問的繁中問題
                "expected_clause_ids": [c["clause_id"]],
                "section": c["section"],
                "article_title": c.get("article_title"),
                "page": c["page"],
                "clause_excerpt": c["text"][:400],
                "reviewed": False,
            }, ensure_ascii=False) + "\n")

    print(f"\n寫出 {min(TARGET, len(picked))} 題工作單 -> {OUT}")
    print("人工只要做兩件事：")
    print("  1. 讀 clause_excerpt，把 question_zh 填成車迷會問的樣子")
    print("  2. 若該問題其實要引用多條，把條號加進 expected_clause_ids，再把 reviewed 改 true")
    print("\n前 3 題預覽:")
    for i, (topic, c) in enumerate(picked[:3], 1):
        print(f"  [{i}] {topic}　{c['clause_id']}　{c.get('article_title')}")
        print(f"      {c['text'][:110]}")


if __name__ == "__main__":
    main()
