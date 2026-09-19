"""條文檢索。BM25 查詞 + 條號精確查 + 繁中查詢改寫。

三層設計都是為了同一個問題：詞彙鴻溝有兩層。
  查詢改寫　車迷說「正賽」→ 補上 TTCS / Total Time Classified Session
  BM25　　　查改寫後的英文詞
  條號直查　使用者直接打 B5.10.8 時，純向量做不到，BM25 也不保證第一名

向量檢索那一層需要 Gemini API key，還沒接。這支不需要金鑰就能跑，
所以先把不需要金鑰的部分做完並量測。

BM25 自己實作而不裝 rank_bm25，因為只有 30 行，而且 corpus 是英文，
tokenizer 用不到中文分詞。
"""

import json
import math
import re
import unicodedata
from collections import Counter
from pathlib import Path

CLAUSES = Path("data/clauses.jsonl")
GLOSSARY = Path("data/glossary.json")

CLAUSE_ID_RE = re.compile(r"\b([AB]\d{1,2}(?:\.\d{1,2}){0,2})\b", re.I)
TOKEN_RE = re.compile(r"[a-z0-9]+")

K1, B = 1.5, 0.75


def tokenize(text):
    """先把重音符攤平再切詞。

    不攤平的話「Parc Fermé」會被切成 parc + ferm，因為 [a-z0-9] 吃不下 é，
    而條文裡寫的是 Fermé，兩邊就對不上。規則全文有 é、è、ç 等法文殘留。
    """
    flat = unicodedata.normalize("NFKD", text.lower())
    flat = "".join(c for c in flat if not unicodedata.combining(c))
    return TOKEN_RE.findall(flat)


class Retriever:
    def __init__(self, clauses_path=CLAUSES, glossary_path=GLOSSARY):
        rows = [json.loads(l) for l in clauses_path.open(encoding="utf-8")]
        # 只索引有約束力且現行的條文。非約束註記與未生效條文不得被引用。
        self.clauses = [c for c in rows if c["citable"]]
        self.skipped = len(rows) - len(self.clauses)
        self.by_id = {}
        for c in self.clauses:
            self.by_id.setdefault(c["clause_id"].upper(), c)

        self.glossary = json.loads(glossary_path.read_text(encoding="utf-8"))
        # 中文別名 -> 要補進查詢的英文詞
        self.alias_map = {}
        for key, entry in self.glossary.items():
            if key.startswith("_"):
                continue
            expansion = " ".join(
                x for x in (entry.get("acronym"), entry.get("term")) if x
            )
            for alias in entry.get("cn_aliases", []):
                self.alias_map[alias] = expansion

        self._build_index()

    def _build_index(self):
        self.docs = [tokenize(c["text"]) for c in self.clauses]
        self.lengths = [len(d) for d in self.docs]
        self.avg_len = sum(self.lengths) / max(1, len(self.lengths))
        self.tf = [Counter(d) for d in self.docs]
        df = Counter()
        for d in self.docs:
            df.update(set(d))
        n = len(self.docs)
        self.idf = {
            term: math.log(1 + (n - freq + 0.5) / (freq + 0.5))
            for term, freq in df.items()
        }

    def rewrite(self, query):
        """把繁中車迷用語換成 FIA 術語。回傳 (改寫後查詢, 命中的別名)。"""
        hits = []
        extra = []
        for alias, expansion in self.alias_map.items():
            if alias in query:
                hits.append(alias)
                extra.append(expansion)
        return (query + " " + " ".join(extra)).strip(), hits

    def _bm25(self, tokens):
        scores = []
        for i, tf in enumerate(self.tf):
            s = 0.0
            for term in tokens:
                if term not in tf:
                    continue
                freq = tf[term]
                s += self.idf.get(term, 0.0) * freq * (K1 + 1) / (
                    freq + K1 * (1 - B + B * self.lengths[i] / self.avg_len)
                )
            scores.append(s)
        return scores

    def search(self, query, k=5):
        """回傳前 k 條。條號直查的結果永遠排第一。"""
        rewritten, aliases = self.rewrite(query)

        # 條號直查。使用者打 B5.10.8 就該拿到那一條，不靠語意猜。
        pinned = []
        for raw in CLAUSE_ID_RE.findall(query):
            hit = self.by_id.get(raw.upper())
            if hit and hit not in pinned:
                pinned.append(hit)

        scores = self._bm25(tokenize(rewritten))
        ranked = sorted(range(len(scores)), key=lambda i: -scores[i])

        out = [{"clause": c, "score": None, "why": "clause_id"} for c in pinned]
        seen = {c["clause_id"] for c in pinned}
        for i in ranked:
            c = self.clauses[i]
            if c["clause_id"] in seen or scores[i] <= 0:
                continue
            seen.add(c["clause_id"])
            out.append({"clause": c, "score": round(scores[i], 3), "why": "bm25"})
            if len(out) >= k:
                break

        return out[:k], {"rewritten": rewritten, "aliases": aliases}


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8")
    r = Retriever()
    print(f"索引 {len(r.clauses)} 條可引用條文，"
          f"排除 {r.skipped} 條（非約束註記或未生效）")
    print(f"中文別名 {len(r.alias_map)} 組\n")

    demos = [
        "正賽開始前如果賽道狀況不佳會怎麼處理",
        "B5.10.8",
        "排位賽的分段規則",
        "違規之後裁處的程序是什麼",
    ]
    for q in demos:
        hits, meta = r.search(q, k=3)
        print(f"Q: {q}")
        if meta["aliases"]:
            print(f"   改寫命中別名 {meta['aliases']}")
        for h in hits:
            c = h["clause"]
            print(f"   {c['clause_id']:<9} [{h['why']:<9}] {c['text'][:72]}")
        print()
