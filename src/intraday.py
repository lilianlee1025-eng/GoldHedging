# -*- coding: utf-8 -*-
"""
盤中走勢（當日 / 五日）
======================
純粹是給首頁走勢圖多兩個分頁用的，跟模型、回測完全無關——
模型預測的是 30 個交易日後，分時圖幫不上忙。

為什麼需要獨立一支、獨立排程：
  daily_update.py 一天只跑一次（要重算預測），盤中資料一天跑一次等於沒有意義。
  這支只做「抓 → 寫 JSON」，幾十秒跑完，可以用比較密的排程單獨呼叫。

交易時段的切法（重要）：
  黃金期貨幾乎 24 小時交易，台北時間 07:00 開到隔天 06:00，中間只休息一小時。
  所以「一個交易日」會跨日曆日，不能直接用日期分組。
  做法是把台北時間往前推 7 小時再取日期——07:00 的那根會落在當天 00:00，
  隔天 05:55 的那根會落在當天 22:55，剛好整段歸在同一個交易日底下。
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta

import pandas as pd

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

TZ = "Asia/Taipei"
SESSION_SHIFT = 7          # 時段起點 07:00，往前推這麼多小時就能把跨日的一段歸成同一天
OUT_NAME = "intraday.json"


def _fetch(interval: str, period: str) -> pd.DataFrame:
    """抓盤中 K 線，回傳以台北時間為索引、含 session 欄位的 DataFrame。"""
    import yfinance as yf
    df = yf.download(config.YF_TICKERS[config.TARGET_COL], period=period,
                     interval=interval, progress=False, auto_adjust=True)
    if df is None or len(df) == 0:
        raise RuntimeError(f"抓不到盤中資料（interval={interval}, period={period}）")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df[["Close"]].dropna()
    df.columns = ["c"]
    df = df.tz_convert(TZ)
    df["session"] = (df.index - pd.Timedelta(hours=SESSION_SHIFT)).date
    return df


def _one_session(df: pd.DataFrame) -> dict:
    """最近一個完整／進行中的交易時段。"""
    last = df["session"].iloc[-1]
    cur = df[df["session"] == last]
    prev = df[df["session"] < last]
    return {
        "session": str(last),
        # 參考線：上一個時段的收盤。沒有上一段資料時用本段第一筆，圖還是畫得出來。
        "prev_close": round(float(prev["c"].iloc[-1] if len(prev) else cur["c"].iloc[0]), 2),
        # 帶上日期：時段跨午夜，X 軸與查價提示框都需要知道是哪一天
        "t": [ts.strftime("%m/%d %H:%M") for ts in cur.index],
        "c": [round(float(v), 2) for v in cur["c"]],
        "marks": [],
    }


def _multi_session(df: pd.DataFrame, n: int) -> dict:
    """最近 n 個交易時段接在一起，附上每段的起點索引（前端用來畫日分隔與標 X 軸）。"""
    keep = sorted(df["session"].unique())[-n:]
    sub = df[df["session"].isin(keep)]
    first = keep[0]
    prev = df[df["session"] < first]
    marks, seen = [], set()
    for i, s in enumerate(sub["session"]):
        if s not in seen:
            seen.add(s)
            marks.append({"i": i, "date": str(s)})
    return {
        "from": str(keep[0]), "to": str(keep[-1]),
        "prev_close": round(float(prev["c"].iloc[-1] if len(prev) else sub["c"].iloc[0]), 2),
        "t": [ts.strftime("%m/%d %H:%M") for ts in sub.index],
        "c": [round(float(v), 2) for v in sub["c"]],
        "marks": marks,
    }


def build() -> dict:
    # 當日用 5 分鐘（一段約 276 根），五日用 30 分鐘（五段約 230 根）——
    # 再細下去 JSON 會變大，但圖上看不出差別。
    d1 = _one_session(_fetch("5m", "7d"))
    d5 = _multi_session(_fetch("30m", "1mo"), 5)
    now = datetime.now(timezone(timedelta(hours=8)))
    return {
        "generated_at": now.strftime("%Y-%m-%d %H:%M"),
        "tz": TZ,
        "note": "黃金期貨幾乎 24 小時交易，一個交易時段為台北時間 07:00 至隔日 06:00。",
        "d1": d1, "d5": d5,
    }


def save(path: str = None) -> str:
    path = path or os.path.join(config.BASE_DIR, "docs", OUT_NAME)
    data = build()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    return path


if __name__ == "__main__":
    p = save()
    d = json.load(open(p, encoding="utf-8"))
    print(f"已寫出 {p}（{os.path.getsize(p) / 1024:.1f} KB）")
    print(f"  當日 {d['d1']['session']}  {len(d['d1']['c'])} 根  "
          f"{d['d1']['t'][0]} ~ {d['d1']['t'][-1]}  昨收 {d['d1']['prev_close']}")
    print(f"  五日 {d['d5']['from']} ~ {d['d5']['to']}  {len(d['d5']['c'])} 根  "
          f"{len(d['d5']['marks'])} 個時段")
