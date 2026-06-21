# 黃金避險專題 — 資料與模型

用多個總經因子訓練「多變量 LSTM」，預測黃金未來走勢與下跌機率，並用 walk-forward 回測「依訊號避險」策略，最後輸出 JSON 供前端網頁使用。

---

## 1. 專案結構

```
GoldHedging/
├── config.py              # 共用設定（日期、來源代碼、超參數、路徑）
├── main.py                # 一鍵跑完整 pipeline
├── requirements.txt
├── README.md
├── src/
│   ├── data_collection.py # 抓資料 + 對齊 + CPI 公布日延遲處理
│   ├── explore.py         # 探索圖（先確認資料正確）
│   ├── preprocessing.py   # 序列化、正規化（scaler 只 fit 訓練集）
│   ├── model.py           # 雙輸出 LSTM + naive/單因子/多因子 baseline 比較
│   ├── backtest.py        # walk-forward 回測 + 避險策略
│   ├── output_json.py     # 輸出 predictions.json / backtest.json
│   ├── design_export.py   # 把真實輸出轉成前端設計檔所需的 JSON
│   └── font_util.py       # 圖表中文字型
├── frontend/              # 正式介面：黃金避險決策系統（Gold Hedge Terminal）
│   ├── index.html         # 設計檔（Claude Design）
│   ├── support.js         # 渲染 runtime
│   ├── predictions.json   # 由真實輸出轉出的設計檔資料
│   └── backtest.json
├── frontend_demo/
│   └── index.html         # 簡易 Chart.js 檢視器（驗證 JSON 用）
├── data/                  # 對齊後的 dataset.csv、walk-forward 訊號快取、內建中文字型
└── outputs/               # 圖檔 + predictions.json + backtest.json
```

## 2. 安裝

```bash
# 建議用虛擬環境（Python 3.10~3.13）
python -m venv venv && source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## 3. 怎麼跑

**建議照順序，先確認資料抓得到、能畫圖，再進到模型。**

```bash
# (1) 只抓資料並對齊，存成 data/dataset.csv
python src/data_collection.py

# (2) 探索：畫六因子走勢圖 + 相關係數熱圖（存到 outputs/）
python src/explore.py

# (3) 三方模型比較（naive / 單因子 LSTM / 多因子 LSTM）
python src/model.py

# (4) walk-forward 回測（有避險 vs 無避險）
python src/backtest.py

# (5) 一鍵跑完整 pipeline 並輸出 JSON
python main.py            # 完整版
python main.py --quick    # 快速 demo（回測步長加大，較快）
python main.py --refresh  # 重新從網路抓最新資料
```

## 4. 資料來源

| 因子 | 代碼 | 來源 | 頻率 |
|------|------|------|------|
| 黃金價格 | GLD | yfinance | 每日 |
| 10年期公債殖利率 | DGS10 | FRED | 每日 |
| 通膨 (CPI) | CPIAUCSL | FRED | 每月 |
| 美元指數 | DX-Y.NYB | yfinance | 每日 |
| S&P 500 | ^GSPC | yfinance | 每日 |
| 恐慌指數 (VIX) | ^VIX | yfinance | 每日 |

時間範圍：2010-01-01 ~ 今天。對齊後只保留「所有因子都有值」的交易日。

## 5. 三個關鍵的「防作弊」設計（避免前視偏誤 / 資料洩漏）

1. **CPI 用實際公布日生效**：CPI 是月資料，FRED 以「所屬月份」為索引，但數字要到
   *隔月中旬* 才公布。若直接用所屬月份會「偷看到未公布資訊」。本專案把 CPI 生效日
   往後延約 **1 個月又 14 天**（近似公布日）再 forward fill。
   → 見 `src/data_collection.py` 的 `_shift_cpi_to_publish_date()`。
2. **scaler 只用訓練集 fit**：正規化的 min/max（或 mean/std）只從訓練資料學，
   再套用到測試資料，避免測試期資訊洩漏到訓練。
   → 見 `src/preprocessing.py`。
3. **walk-forward 回測**：每個時間點只用「該點之前」的資料重新訓練，逐段往前滾動，
   絕不使用未來資料。→ 見 `src/backtest.py` 的 `walk_forward()`。

## 6. 模型

- **輸入**：過去 60 天 × 6 個因子。
- **雙輸出**：
  - 迴歸頭：預測未來 5 個交易日的報酬 → 還原成未來價格。
  - 分類頭：預測「未來會下跌的機率」(sigmoid 0~1)，並用加權交叉熵避免塌縮成只猜上漲。
- **Baseline 對照**：
  - `naive`：未來價格 = 今天價格（隨機漫步基準，短天期其實很難打敗）。
  - 單因子 LSTM：只用金價。
  - 多因子 LSTM：用全部 6 個因子。
- **評估指標**：
  - RMSE / MAE：衡量價格預測誤差。
  - **AUC**：衡量「下跌機率」的方向判斷力（不受漲跌基準率影響，> 0.5 才算有訊號）。
  - 下跌正確率，並附上「基準率」(永遠猜多數類別) 供對照。

> 註：短天期金價接近隨機漫步，naive 在 RMSE 上是很強的基準；多因子模型的價值主要
> 體現在 **方向判斷 (AUC)** 與 **回測的抗跌（最大回撤改善）**，而非單純的價格誤差。

## 7. 回測策略

- **不避險**：永遠 100% 持有黃金。
- **依訊號避險**：下跌機率越高 → 避險力道越大 → 黃金曝險越低。
  避險部位視為被中性化（報酬 ≈ 0）。
- 比較兩者的**累積損益曲線**與**最大回撤**，並逐年列出情境表現。

## 8. 輸出 JSON（給前端）

- `outputs/predictions.json`
  - `metrics`：三方 RMSE / MAE / AUC。
  - `history`：歷史金價。
  - `test_predictions`：測試期實際 vs 預測價格 + 下跌機率。
  - `future`：未來金價預測與下跌機率。
  - `recommendation`：由最新下跌機率換算的**避險建議**（建議避險比例、黃金曝險、
    訊號燈號 hold/neutral/light_hedge/hedge 與中文文字）。
  - `factors`：**因子儀表板**（六因子最新值、近一年變化率、與金價日報酬相關係數）。
- `outputs/backtest.json`
  - `equity_curve`：有/無避險累積損益、避險比例。
  - `stats`：總報酬、年化、波動、Sharpe、最大回撤。
  - `scenarios_by_year`：各年度表現。
  - `summary`：避險相對不避險的**改善摘要**（回撤改善、波動降低、Sharpe 變化、
    讓出的報酬）與回測末日的最新避險建議。

## 9. 前端介面

本專案有兩個前端：

### (A) 正式介面 — `frontend/`（黃金避險決策系統 / Gold Hedge Terminal）

由 Claude Design 設計的多頁終端機風格介面，含五個分頁：
**儀表板**（金價＋LSTM 預測、未來 5 日、下跌機率、避險建議）、
**避險模擬器**（部位試算＋期貨/Put/Collar 損益，Black–Scholes 計價）、
**避險原理**（期貨 vs 保護性賣權 payoff 互動圖）、
**回測**（有/無避險淨值、最大回撤、情境比較）、
**模型**（LSTM 架構、輸入因子、三方績效比較）。

- `frontend/index.html`：設計檔（用 `support.js` runtime 渲染，會自動從 CDN 載入 React）。
- `frontend/support.js`：渲染 runtime。
- `frontend/predictions.json`、`frontend/backtest.json`：由 `src/design_export.py` 從
  **真實模型輸出**轉成設計檔所需 schema（跑 `main.py` 會自動更新，或單獨執行
  `python src/design_export.py`）。內含：三種計價單位換算係數、日/周/月/季 K 棒(OHLC)、
  資料更新時間。

儀表板互動功能：
- **計價單位切換**：GLD 美元/股 ｜ 現貨 美元/盎司 ｜ 台幣/公克（換算係數即時抓 `GC=F`、`TWD=X`）。
- **時間單位切換**：日／周／月／季（由日線 OHLC resample）。
- **圖表類型切換**：折線／K 棒（蠟燭圖）。模型擬合與未來預測僅在「日線＋折線」時疊加顯示。
- 標頭顯示「資料截至 / 產生時間」。

```bash
python -m http.server          # 在專案根目錄啟動
# 瀏覽器開 http://localhost:8000/frontend/   （需可連網以載入 React CDN）
```

### (B) 簡易檢視器 — `frontend_demo/`

用 Chart.js 直接讀 `outputs/` 原生 JSON，純為快速驗證資料用：

```bash
python -m http.server
# 瀏覽器開 http://localhost:8000/frontend_demo/
```

> 兩者都需用本機伺服器開（用 `file://` 直接開會被瀏覽器擋下 fetch）。

## 10. 每天自動更新（排程）

`daily_update.py` 是輕量更新腳本：重抓最新資料、重算預測、更新前端 JSON（含 K 棒、
計價單位、更新時間），**跳過 30 分鐘的歷史回測**，約 3~5 分鐘跑完。

```bash
bash run_daily.sh          # 手動測試一次（輸出寫到 logs/daily_update.log）
```

設成每天自動跑（cron，以每天 08:07 為例）：

```bash
crontab -e
# 加入這一行：
7 8 * * * /home/lilian/GoldHedging/run_daily.sh
```

> 需要本機有網路；更新後重新整理瀏覽器即可看到新數字。若要連 walk-forward 回測
> 也一起更新，改排 `python main.py`（較久）。

## 11. 注意事項

- 第一次執行會從網路抓資料，需要網路連線；之後會讀快取的 `data/dataset.csv`。
- 完整 `main.py` 會做 walk-forward（每 60 天重訓一次，約 50 次），CPU 上約需 20~30 分鐘；
  趕時間用 `--quick`（步長加大、約 26 次重訓）。walk-forward 訊號會快取在
  `data/wf_signals.csv`，方便之後只調整避險門檻時快速重算。
- GLD 是黃金 ETF，作為金價代理；其價格已用 `auto_adjust` 還原權值。
- 本專案為學術 / 教學用途，不構成任何投資建議。
