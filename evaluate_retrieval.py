"""檢索指標。Recall@1／@3／@5 + 答案層級引用正確率。

原 prompt 只要「檢索命中率 ≥ 80%」，那個門檻在 500 條結構清楚的條文上
太容易達到，量不出差別。改成四個數字：

  Recall@1  第一名就對，這才是使用者實際體驗
  Recall@3  前三名有對的
  Recall@5  前五名有對的，原本的 80% 門檻對應這一欄
  引用正確率 檢索到的第一名條號等於標準答案的比例，不只是「有出現在清單裡」

只讀 reviewed=true 的題目。工作單填一半就跑會得到虛高的數字。
"""

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

from retrieve import Retriever

TESTSET = Path("data/testset_worksheet.jsonl")


def load_testset(path=TESTSET, provisional=False):
    """預設只讀 reviewed=true 的題目。

    provisional=True 時連草稿一起讀，但指標要標示為暫定值。
    草稿的問題措辭是我寫的，而系統也是我寫的，
    所以那組數字有自我評分的偏誤，不能當成最終指標對外報告。
    """
    if not path.exists():
        return [], []
    rows = [json.loads(l) for l in path.open(encoding="utf-8") if l.strip()]
    ready = [r for r in rows if r.get("reviewed") and r.get("question_zh")]
    drafts = [r for r in rows if not r.get("reviewed") and r.get("question_zh")]
    if provisional:
        return ready + drafts, drafts
    return ready, drafts


def evaluate(retriever, cases, k=5):
    hits = {1: 0, 3: 0, 5: 0}
    top1_exact = 0
    per_case = []

    for case in cases:
        expected = {c.upper() for c in case["expected_clause_ids"]}
        results, meta = retriever.search(case["question_zh"], k=k)
        got = [r["clause"]["clause_id"].upper() for r in results]

        rank = next((i + 1 for i, cid in enumerate(got) if cid in expected), None)
        for cutoff in hits:
            if rank is not None and rank <= cutoff:
                hits[cutoff] += 1
        if got and got[0] in expected:
            top1_exact += 1

        per_case.append({
            "id": case["id"],
            "question": case["question_zh"],
            "expected": sorted(expected),
            "retrieved": got,
            "rank": rank,
            "aliases": meta["aliases"],
        })

    n = len(cases)
    return {
        "n_cases": n,
        "recall@1": round(hits[1] / n, 4) if n else None,
        "recall@3": round(hits[3] / n, 4) if n else None,
        "recall@5": round(hits[5] / n, 4) if n else None,
        "citation_accuracy": round(top1_exact / n, 4) if n else None,
    }, per_case


def main():
    provisional = "--provisional" in sys.argv
    cases, drafts = load_testset(provisional=provisional)

    if not cases:
        print(f"{TESTSET} 沒有 reviewed=true 的題目。")
        if drafts:
            print(f"但有 {len(drafts)} 題草稿。加 --provisional 可以先跑暫定指標：")
            print("  python evaluate_retrieval.py --provisional")
            print("草稿的問題措辭與這套系統都出自同一人，數字有自我評分偏誤，")
            print("對外報告前必須人工複核並把 reviewed 改成 true。")
        else:
            print("先跑 make_testset.py 產生工作單，填完 question_zh 並把 reviewed 改 true。")
        return

    retriever = Retriever()
    summary, per_case = evaluate(retriever, cases)

    if provisional and drafts:
        print("=" * 62)
        print(f"暫定指標：{len(drafts)} / {len(cases)} 題是未複核的草稿。")
        print("問題措辭與系統出自同一人，有自我評分偏誤，不可當最終數字對外引用。")
        print("=" * 62 + "\n")

    print(f"索引 {len(retriever.clauses)} 條可引用條文，測試 {summary['n_cases']} 題\n")
    for key in ("recall@1", "recall@3", "recall@5", "citation_accuracy"):
        print(f"  {key:<20} {summary[key]}")

    misses = [c for c in per_case if c["rank"] is None]
    if misses:
        print(f"\n完全沒命中的 {len(misses)} 題:")
        for c in misses:
            print(f"  [{c['id']}] {c['question'][:44]}")
            print(f"       期望 {c['expected']}  拿到 {c['retrieved'][:3]}")
            print(f"       改寫命中別名 {c['aliases']}")

    Path("data/retrieval_metrics.json").write_text(
        json.dumps({"summary": summary, "cases": per_case}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("\n寫出 data/retrieval_metrics.json")


if __name__ == "__main__":
    main()
