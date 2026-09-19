"""解析、詞彙表、檢索三層的不變量測試。

重點不在覆蓋率，在守住幾條「錯了會讓機器人說錯話」的規則：
非約束內容不能被引用、未生效條文不能被當現行、條號直查必須精確。
"""

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

CLAUSES = ROOT / "data" / "clauses.jsonl"
GLOSSARY = ROOT / "data" / "glossary.json"

pytestmark = pytest.mark.skipif(
    not CLAUSES.exists(), reason="先跑 parse_regulations.py 產生 data/clauses.jsonl"
)


@pytest.fixture(scope="module")
def clauses():
    return [json.loads(l) for l in CLAUSES.open(encoding="utf-8")]


@pytest.fixture(scope="module")
def retriever():
    from retrieve import Retriever
    return Retriever(CLAUSES, GLOSSARY)


class TestParser:
    def test_兩份文件都在庫裡(self, clauses):
        # 只灌 Sporting 會答不出「為什麼判 5 秒」，見 README
        sections = {c["section"] for c in clauses}
        assert sections == {"A", "B"}

    def test_裁處條文在庫裡(self, clauses):
        # A7 是違規裁處與制裁，旗艦示範問題需要它
        assert any(c["clause_id"].startswith("A7.") for c in clauses)

    def test_條號格式一致(self, clauses):
        import re
        pat = re.compile(r"^[AB]\d{1,2}(\.\d{1,2}){1,2}$")
        bad = [c["clause_id"] for c in clauses if not pat.match(c["clause_id"])]
        assert not bad, f"條號格式異常: {bad[:5]}"

    def test_非約束內容不可引用(self, clauses):
        # 紅字治理資訊、橘字文件參照、綠字註解都不是規則
        for c in clauses:
            if c["opening_class"] in {"governance", "reference", "comment"}:
                assert not c["citable"], f"{c['clause_id']} 是非約束內容卻可引用"

    def test_未生效條文不可引用(self, clauses):
        # APPENDIX B5 底下是 2027／2028／2029 的變更
        not_in_force = [c for c in clauses if not c["in_force"]]
        assert not_in_force, "應該要抓到未生效條文"
        for c in not_in_force:
            assert not c["citable"], f"{c['clause_id']} 未生效卻可引用"

    def test_可引用的條文一定有內容(self, clauses):
        for c in clauses:
            if c["citable"]:
                assert c["text"].strip(), f"{c['clause_id']} 可引用但沒有內容"

    def test_註記與條文分開存(self, clauses):
        annotated = [c for c in clauses if c["annotations"]]
        assert annotated, "應該要有帶註記的條文"
        for c in annotated:
            for kind, text in c["annotations"]:
                assert text not in c["text"], f"{c['clause_id']} 的註記混進條文了"

    def test_連字修復(self, clauses):
        # 文字層把 ffi 擷取成 =i，Officials 會變成 O=icials
        broken = [c["clause_id"] for c in clauses if "=i" in c["text"]]
        assert not broken, f"ffi 連字未修復: {broken[:5]}"


class TestGlossary:
    def test_有定義的條目不可為空(self):
        g = json.loads(GLOSSARY.read_text(encoding="utf-8"))
        for key, v in g.items():
            if key.startswith("_"):
                continue
            assert v.get("term"), f"{key} 沒有 term"

    def test_關鍵縮寫有抽到定義(self):
        g = json.loads(GLOSSARY.read_text(encoding="utf-8"))
        for key in ("TTCS", "LTCS"):
            assert key in g, f"{key} 不在詞彙表裡"
            assert g[key].get("definition"), f"{key} 沒有 PDF 定義"

    def test_沒有依據的別名要標示出來(self):
        # definition 為 null 代表那組別名沒有 PDF 依據，需要人工複核。
        # 這不是錯誤，但必須看得出來。
        g = json.loads(GLOSSARY.read_text(encoding="utf-8"))
        unbacked = [k for k, v in g.items()
                    if not k.startswith("_") and v.get("cn_aliases")
                    and not v.get("definition")]
        for k in unbacked:
            assert g[k]["source"] is None, f"{k} 沒有定義卻標了來源"


class TestRetriever:
    def test_只索引可引用條文(self, retriever, clauses):
        assert len(retriever.clauses) == sum(c["citable"] for c in clauses)

    def test_條號直查必須精確(self, retriever):
        hits, _ = retriever.search("B5.10.8", k=5)
        assert hits[0]["clause"]["clause_id"] == "B5.10.8"
        assert hits[0]["why"] == "clause_id"

    def test_條號直查不分大小寫(self, retriever):
        hits, _ = retriever.search("b5.10.8", k=3)
        assert hits[0]["clause"]["clause_id"] == "B5.10.8"

    def test_英文查詢可用(self, retriever):
        # 這是對照組：BM25 本身沒問題，中文查不到是跨語言造成的
        hits, _ = retriever.search("safety car immediate physical danger", k=3)
        assert "B5.13" in [h["clause"]["clause_id"] for h in hits]

    def test_重音符要攤平(self):
        from retrieve import tokenize
        assert tokenize("Parc Fermé") == ["parc", "ferme"]

    def test_中文查詢會觸發改寫(self, retriever):
        _, meta = retriever.search("正賽開始前", k=3)
        assert "正賽" in meta["aliases"]
        assert "TTCS" in meta["rewritten"]

    def test_中文單獨用BM25幾乎無效(self, retriever):
        from retrieve import tokenize
        # 這條測試記錄的是已知限制而不是期望行為：
        # 沒有別名命中的純中文查詢會切出空 token，BM25 拿到零訊號。
        # 接上向量層之後這條會失效，那時就該改寫它。
        assert tokenize("車隊被送交審查團之前會先通知嗎") == []

    def test_不會回傳未生效條文(self, retriever):
        for c in retriever.clauses:
            assert c["in_force"]
