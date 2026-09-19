# FIA 規則問答機器人

讓 F1 中文社群車迷用繁體中文詢問規則問題，系統以繁中回答並**附上規則條號出處**。
檢索不到依據時明說「查無規則依據」，不編造。

引擎寫成 corpus agnostic，因為第二個 corpus（公開被動元件應用註記）會接上來，
用來證明同一套引用可驗證的做法能轉到工業文件域。

## 現況

檢索層完成並可跑。生成層待 Gemini API key。

| 項目 | 狀態 |
|---|---|
| 條文解析（顏色語意、未生效條文） | 完成，615 條 |
| 縮寫詞彙表 + 繁中別名 | 完成，32 條 |
| BM25 檢索 + 條號直查 + 查詢改寫 | 完成 |
| 30 題測試集 | **工作單已產出，待人工填寫** |
| 向量檢索（ChromaDB + Gemini embedding） | **待 Gemini API key** |
| 生成與引用（Gemini） | **待 Gemini API key** |

## 來源與版權

本 repo 的 `data/clauses.jsonl` 收錄下列 FIA 公開文件的條文正文，
供檢索研究與作品集展示之用。

> **© 2026 Fédération Internationale de l'Automobile.**
> 規則原文之著作權屬 FIA 所有。本專案僅重製條文內容作技術示範，
> 不主張任何權利，亦非官方版本。

| 文件 | 版本 | 發布日 |
|---|---|---|
| 2026 Formula 1 Regulations, Section A: General Regulatory Provisions | Issue 01 | 2025-12-10 |
| 2026 Formula 1 Regulations, Section B: Sporting Regulations | Issue 05 | 2026-02-27 |

兩份皆取自 fia.com，確切網址寫在 `parse_regulations.py` 的 `SOURCES`。

**一律以官方 PDF 為準。** 規則會改版，本 repo 的快照會過期。
解析過程會剝除頁首頁尾，所以 `clauses.jsonl` 不含原文件的版權頁、
圖表與格式，不能取代官方文件。任何實際用途請回 fia.com 取得現行版本。

## corpus

2026 年 FIA F1 規則已重構成 Section A／B／C。**兩份都要**：

| 文件 | 版本 | 頁數 | 解析出的條文 |
|---|---|---|---|
| Section A: General Regulatory Provisions | Issue 01（2025-12-10） | 84 | 224 |
| Section B: Sporting Regulations | Issue 05（2026-02-27） | 96 | 391 |

只灌 Sporting 會答不出旗艦示範問題。「為什麼這次判罰 5 秒」需要兩份同時在庫：
Section B 有行為條文（B5.10.6 就有 Stop-and-Go Penalty），
Section A 有裁處框架（**A6 調查與違規通報**、**A7 違規裁處與制裁**）。
只有 B 的話系統會誠實回「查無規則依據」，那是正確行為，但看起來像 demo 壞了。

## 三個解析上的陷阱，都已處理

**1. 顏色是語意標記。** 兩份 PDF 首頁的 CONVENTION 段明訂：

| 顏色 | 語意 | 可引用 |
|---|---|---|
| 黑 | 條文本體 | 是 |
| 粉紅（僅 Section B） | 本次修訂，WMSC 核准 | 是 |
| 紅 | 治理與諮詢委員會資訊 | **否** |
| 橘 | FIA 文件參照 | **否** |
| 綠 | 註解與說明，原文寫 non-binding and non-regulatory | **否** |

純文字擷取會把五種混成一團，紅橘綠會被當成規則引用。
`parse_regulations.py` 讀 `char["non_stroking_color"]` 分離，
非約束內容另存 `annotations` 欄位，`text` 只留有效條文。615 條中 152 條帶註記。

注意兩份用不同色彩空間：Section B 的黑是 RGB `(0,0,0)`，Section A 的黑是灰階 `(0.0,)`。
第一版只認 RGB，整份 Section A 都被誤判為非規則。

**2. 同一份 PDF 裡有尚未生效的規則。**
`APPENDIX B5` 底下是 Changes for 2027／2028／2029。不濾掉，系統會拿 2028 年規則
回答 2026 年問題，而且引用還是對的，比一般幻覺更難抓。已用 `in_force` 標出 9 條。

**3. 文字層有 ffi 連字 bug。** `O=icials` 應為 `Officials`。不修 BM25 查不到。

## 核心設計題：詞彙鴻溝有兩層

2026 規則把「正賽與衝刺賽」寫成 **TTCS**（Total Time Classified Session）、
「練習與排位」寫成 **LTCS**，另有 ICTE、ICTT、TCC、TPC、THC、PE、DE。
實測 TTCS 在條文出現 **139 次**、LTCS **19 次**、ISC **101 次**。

車迷用繁中問「正賽」，文件裡一個字都不會命中。所以要跨的不只是中文到英文，
還有**車迷用語到 FIA 縮寫**。

`build_glossary.py` 的英文那半是從 DEFINITIONS 附錄抽的，不是自行編寫，
所以映射有依據。例如 TTCS 的定義原文明寫
"include, but are not limited to, the Sprint session and the Race session"，
「正賽／衝刺賽」的對應由此而來。中文那半是人工映射，
28 組裡 15 組對上 PDF 定義，13 組標記為無 PDF 依據待複核（`definition` 為 `null`）。

## 檢索為什麼要 hybrid

| 層 | 負責 | 需要金鑰 |
|---|---|---|
| 查詢改寫 | 繁中別名 → FIA 縮寫與全稱 | 否 |
| 條號直查 | 使用者打 `B5.10.8` 就該拿到那一條 | 否 |
| BM25 | 改寫後的英文詞比對 | 否 |
| 向量 | 語意相近但用詞不同 | **是** |

條號直查是純向量做不到的：查 `B5.10.8` 時語意相似度不保證那一條排第一。
目前實測輸入 `B5.10.8` 會直接釘住該條。

## 指標

原 prompt 只要「檢索命中率 ≥ 80%」。500 條結構清楚的條文上那個門檻太容易達到，
量不出差別。改成四個數字：`Recall@1`、`Recall@3`、`Recall@5`、
以及**答案層級引用正確率**（第一名的條號等於標準答案的比例，不只是有出現在清單裡）。

### 第一次實測：BM25 單獨用在中文查詢上幾乎全滅

2026-09-20，30 題草稿，只有 BM25 + 條號直查 + 別名改寫，**沒有向量層**：

| 指標 | 實測 |
|---|---|
| Recall@1 | **0.000** |
| Recall@3 | 0.067 |
| Recall@5 | 0.067 |
| 引用正確率 | **0.000** |

**這組數字是暫定的**：30 題的問題措辭是我寫的草稿（`reviewed` 全為 `false`），
而系統也是我寫的，有自我評分偏誤。但方向不會因為複核而翻轉。

### 診斷：不是 BM25 爛，是跨語言

做了一組對照：

| 測試 | 結果 |
|---|---|
| 中文查詢切出的 token | **`[]`，空的** |
| 同樣問題改用英文問（3 題） | **3 題全部 rank 1 命中** |

`TOKEN_RE = [a-z0-9]+` 會把中文字整個濾掉，所以 BM25 拿到零訊號，
除非查詢剛好含有別名詞彙表裡的詞而被改寫成英文。
30 題裡只有 2 題命中別名。

### 結論：向量層不是加分項，是承重牆

原本的設計把 hybrid 檢索列為 P1「該有」，把向量層當成語意補強。
實測翻轉了這個判斷：

- **BM25 負責的是條號精確查**（打 `B5.10.8` 直接釘住那一條，這點向量做不到），
  以及英文查詢。這兩件它做得很好
- **中文自然語言查詢完全靠向量層或翻譯層**。沒有它，整個產品不成立

所以下一步的優先序要改：向量檢索從 P1 升到 P0，而且要先做。
別名詞彙表則從「核心解法」降級成「輔助」，因為 50 組別名蓋不住自然語言的變化。

另一條可行路線是**先把查詢翻成英文再進 BM25**，成本比向量庫低，
值得當對照組一起量。這個比較本身就是報告裡的一張表。

## 30 題測試集

原估要 6 到 10 小時讀完 180 頁。`make_testset.py` 做分層抽樣，
把它變成「審 30 條」，配額依車迷提問熱度分配：

| 主題 | 配額 | 可選 |
|---|---|---|
| 判罰與裁處 | 9 | 154 |
| 安全車與中斷 | 6 | 41 |
| 起跑與排位程序 | 6 | 77 |
| 輪胎與零件限制 | 5 | 62 |
| 其他 | 4 | 115 |

輸出 `data/testset_worksheet.jsonl`。人工只需要讀 `clause_excerpt`
把 `question_zh` 填成車迷會問的樣子，再把 `reviewed` 改 `true`。

`evaluate_retrieval.py` 刻意拒絕跑空工作單，因為標準答案要人工判斷，
猜的話指標就沒有意義。

## 執行

```bash
pip install pdfplumber

python parse_regulations.py     # PDF -> data/clauses.jsonl
python build_glossary.py        # -> data/glossary.json
python retrieve.py              # 檢索 demo，不需金鑰
python make_testset.py          # -> data/testset_worksheet.jsonl
python evaluate_retrieval.py    # 需要填好的工作單
```

PDF 不進版控（`.gitignore` 排除 `data/raw/`），來源網址與確切 Issue 記在
`parse_regulations.py` 的 `SOURCES`。

## 不做什麼

不做多輪對話記憶、不做即時新聞查詢、不爬非官方網站。
