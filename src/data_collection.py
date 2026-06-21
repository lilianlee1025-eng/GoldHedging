# -*- coding: utf-8 -*-
"""
資料蒐集與對齊模組
==================
負責：
1. 從 yfinance 抓黃金(GLD)、美元指數(DXY)、S&P500、VIX 的每日收盤價。
2. 從 FRED 抓 10 年期公債殖利率(DGS10) 與 CPI(CPIAUCSL)。
3. 對齊成「以日期為索引」的每日資料。
4. 特別處理 CPI：用「實際公布日」生效（避免前視偏誤），再 forward fill。
5. 只保留所有欄位都有值的交易日，輸出乾淨的 dataset.csv。

設計原則：抓資料與對齊分開兩個函式，方便單獨測試與除錯。
"""

import os
import sys
import pandas as pd
import yfinance as yf
import pandas_datareader.data as web

# 讓 `python src/data_collection.py` 直接執行時也能 import 到根目錄的 config
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config


# ---------------------------------------------------------------------------
# 1. 個別資料來源
# ---------------------------------------------------------------------------
def _download_yf(ticker: str, name: str) -> pd.Series:
    """從 yfinance 抓單一標的的每日收盤價，回傳以日期為索引的 Series。

    注意：新版 yfinance 回傳的欄位是 MultiIndex (Price, Ticker)，
    這裡統一取 'Close' 並壓平成一維 Series。
    """
    df = yf.download(
        ticker,
        start=config.START_DATE,
        end=config.END_DATE,
        progress=False,
        auto_adjust=True,   # 用還原權值後的價格，較適合長期分析
    )
    if df is None or df.empty:
        raise RuntimeError(f"yfinance 抓不到資料：{ticker}")

    # 處理 MultiIndex 欄位
    if isinstance(df.columns, pd.MultiIndex):
        close = df["Close"]
        # 取出唯一的那一欄
        close = close.iloc[:, 0] if close.shape[1] == 1 else close[ticker]
    else:
        close = df["Close"]

    s = close.copy()
    s.name = name
    s.index = pd.to_datetime(s.index)
    s.index.name = "Date"
    return s


def _download_fred(series_id: str, name: str) -> pd.Series:
    """從 FRED 抓單一序列，回傳以日期為索引的 Series。"""
    df = web.DataReader(series_id, "fred", config.START_DATE, config.END_DATE)
    s = df[series_id].copy()
    s.name = name
    s.index = pd.to_datetime(s.index)
    s.index.name = "Date"
    return s


# ---------------------------------------------------------------------------
# 2. CPI 公布日延遲處理（核心：避免前視偏誤）
# ---------------------------------------------------------------------------
def _shift_cpi_to_publish_date(cpi: pd.Series) -> pd.Series:
    """把 CPI 的生效日往後延到「實際公布日」。

    為什麼要這樣做？
    ----------------
    CPIAUCSL 在 FRED 以「所屬月份的第一天」為索引：
        2023-01-01 這筆 = 2023 年「一月份」的 CPI。
    但這個數字實際上要到「隔月中旬」(約 2 月 14 日) 才由 BLS 公布。
    如果直接用 2023-01-01 當生效日，模型在 1 月初就用到了 2 月中才會知道的資訊，
    這就是典型的前視偏誤 (look-ahead bias)，會讓回測績效虛高、實盤卻失靈。

    處理方式：把索引日期整體往後平移約「1 個月又 14 天」，近似真實公布日。
    平移後 2023-01-01 → 約 2023-02-15，代表「2 月中旬起，市場才知道一月 CPI」。
    """
    shifted = cpi.copy()
    shifted.index = shifted.index + pd.DateOffset(
        months=config.CPI_PUBLISH_LAG_MONTHS,
        days=config.CPI_PUBLISH_LAG_DAYS,
    )
    return shifted


# ---------------------------------------------------------------------------
# 3. 對齊所有資料
# ---------------------------------------------------------------------------
def build_dataset(save: bool = True) -> pd.DataFrame:
    """抓取所有來源 → 對齊 → 處理 CPI → 輸出乾淨的每日資料表。"""
    print("[1/3] 從 yfinance 下載市場資料 ...")
    series = {}
    for name, ticker in config.YF_TICKERS.items():
        print(f"   - {name} ({ticker})")
        series[name] = _download_yf(ticker, name)

    print("[2/3] 從 FRED 下載總經資料 ...")
    dgs10 = _download_fred(config.FRED_SERIES["DGS10"], "DGS10")
    cpi_raw = _download_fred(config.FRED_SERIES["CPI"], "CPI")
    # CPI 套用公布日延遲
    cpi = _shift_cpi_to_publish_date(cpi_raw)

    print("[3/3] 對齊資料 ...")
    # 先把每日型資料 (4 個 yfinance + DGS10) 外部合併
    df = pd.concat(
        [series["GLD"], series["DXY"], series["SP500"], series["VIX"], dgs10],
        axis=1,
    )

    # DGS10 在美國假日會缺值；用 forward fill 補（沿用前一交易日殖利率，合理且無未來資訊）
    df["DGS10"] = df["DGS10"].ffill()

    # CPI 是月資料：先 reindex 到每日，再 forward fill
    # （此時 cpi 的索引已是「公布日」，ffill 不會用到未公布的數字）
    cpi_daily = cpi.reindex(df.index.union(cpi.index)).ffill().reindex(df.index)
    df["CPI"] = cpi_daily

    # 只保留所有欄位都有值的交易日（去掉資料起點 CPI 尚未公布的那段，與任何缺值列）
    df = df[config.FEATURE_COLS].dropna()
    df.index.name = "Date"

    print(f"   對齊完成：{df.shape[0]} 個交易日, {df.shape[1]} 個特徵")
    print(f"   區間：{df.index.min().date()} ~ {df.index.max().date()}")

    if save:
        df.to_csv(config.DATASET_CSV, encoding="utf-8-sig")
        print(f"   已存檔：{config.DATASET_CSV}")
    return df


def load_dataset() -> pd.DataFrame:
    """讀取已存檔的 dataset.csv；若不存在則重新抓取。"""
    if os.path.exists(config.DATASET_CSV):
        df = pd.read_csv(config.DATASET_CSV, index_col="Date", parse_dates=True)
        return df
    return build_dataset(save=True)


if __name__ == "__main__":
    # 直接執行此檔 = 重新抓取並存檔
    df = build_dataset(save=True)
    print("\n資料預覽：")
    print(df.head())
    print("...")
    print(df.tail())
    print("\n基本統計：")
    print(df.describe())
