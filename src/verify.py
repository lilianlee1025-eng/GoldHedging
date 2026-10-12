# -*- coding: utf-8 -*-
"""成效驗證資料輸出
==================
把「歷史回測與實際成效驗證」功能需要的原始序列輸出成精簡 JSON，供前端即時試算。

和既有回測頁的差別：
  回測頁  = 2008~2026 全期的統計結論（報酬率、回撤、保護單價）
  成效驗證 = 使用者挑一個起始日與本金，看「如果當時照系統做，現在是賺是賠」（真實金額）

為什麼可以宣稱是「驗證」而不是事後諸葛：
  這裡用的每日下跌機率與預測報酬都來自 walk-forward（src/backtest.py），
  每個時點的模型都只用了該時點之前的資料訓練，不含前視偏誤。

輸出格式刻意用「平行陣列」而非物件陣列，檔案小很多（約 1/3）。
"""

import os
import sys
import json

import numpy as np
import pandas as pd

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

OUT_DIR = os.path.join(config.BASE_DIR, "docs")
SERIES_START = "2019-01-01"   # 前端可選的最早起始日（涵蓋新冠、2022 升息、2025 行情）


def build_series() -> dict:
    """組出前端試算所需的每日序列。

    dates/price 一路到資料結束（驗證晚期訊號要用到未來 30 天的真實價格）；
    prob/pred 只在 walk-forward 有訊號的日子有值，之後為 null。
    """
    sig = pd.read_csv(config.WF_SIGNALS_CSV, parse_dates=["Date"]).set_index("Date")
    px = pd.read_csv(config.DATASET_CSV, parse_dates=[0], index_col=0)[config.TARGET_COL]

    px = px.loc[SERIES_START:]
    sig = sig.reindex(px.index)   # 對齊到價格日期，缺的補 NaN

    def _n(v, nd):
        return None if pd.isna(v) else round(float(v), nd)

    dates = [d.strftime("%Y-%m-%d") for d in px.index]
    price = [round(float(v), 2) for v in px.values]
    prob = [_n(v, 4) for v in sig["prob_down"].values]
    pred = [_n(v, 5) for v in sig["pred_ret"].values]

    n_sig = int(sum(p is not None for p in prob))
    last_sig = next((dates[i] for i in range(len(prob) - 1, -1, -1)
                     if prob[i] is not None), None)

    return {
        "meta": {
            "horizon": config.HORIZON,
            "threshold": config.HEDGE_PROB_THRESHOLD,
            "cost_annual": config.HEDGE_COST_ANNUAL,
            "tc_oneway": config.HEDGE_TC_ONEWAY,
            "profiles": {k: v for k, v in
                         (("conservative", 0.40), ("balanced", 0.50), ("aggressive", 0.60))},
            "price_from": dates[0], "price_to": dates[-1],
            "signal_to": last_sig,      # 此日之後沒有訊號（walk-forward 需 horizon 天後的標籤才收尾）
            "n_days": len(dates), "n_signals": n_sig,
            "note": ("每日下跌機率與預測報酬均來自 walk-forward，各時點僅使用該時點之前的資料訓練，"
                     "不含前視偏誤；因此本頁為真正的事後驗證，而非回頭套用。"),
        },
        "dates": dates, "price": price, "prob": prob, "pred": pred,
    }


def export(path: str = None) -> str:
    path = path or os.path.join(OUT_DIR, "verification.json")
    os.makedirs(OUT_DIR, exist_ok=True)
    data = build_series()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    return path


# ---------------------------------------------------------------------------
# 參考實作：前端的試算邏輯與這裡一致，這支用來驗證數字正確性
# ---------------------------------------------------------------------------
def simulate(data: dict, start: str, capital: float, hold_days: int,
             threshold: float = None) -> dict:
    """從 start 起、投入 capital，持有 hold_days 個交易日的模擬結果。"""
    threshold = threshold if threshold is not None else data["meta"]["threshold"]
    ca, tc = data["meta"]["cost_annual"], data["meta"]["tc_oneway"]
    d, px, pb = data["dates"], data["price"], data["prob"]

    i0 = next(i for i, x in enumerate(d) if x >= start)
    i1 = min(i0 + hold_days, len(d) - 1)

    eq_h = eq_u = 1.0
    prev_h = 0.0
    peak_h = peak_u = 1.0
    mdd_h = mdd_u = 0.0
    hedged_days = 0
    for i in range(i0, i1):
        r = px[i + 1] / px[i] - 1.0
        p = pb[i]
        h = 0.0 if p is None else max(0.0, min(1.0, (p - threshold) / (1.0 - threshold)))
        if h > 0:
            hedged_days += 1
        eq_h *= 1.0 + r * (1.0 - h) - h * ca / 252.0 - abs(h - prev_h) * tc
        eq_u *= 1.0 + r
        prev_h = h
        peak_h, peak_u = max(peak_h, eq_h), max(peak_u, eq_u)
        mdd_h = min(mdd_h, eq_h / peak_h - 1.0)
        mdd_u = min(mdd_u, eq_u / peak_u - 1.0)

    return {
        "start": d[i0], "end": d[i1], "days": i1 - i0,
        "price_start": px[i0], "price_end": px[i1],
        "price_change_pct": (px[i1] / px[i0] - 1.0) * 100,
        "final_hedged": capital * eq_h, "final_unhedged": capital * eq_u,
        "pnl_hedged": capital * (eq_h - 1.0), "pnl_unhedged": capital * (eq_u - 1.0),
        "ret_hedged": (eq_h - 1.0) * 100, "ret_unhedged": (eq_u - 1.0) * 100,
        "mdd_hedged": mdd_h * 100, "mdd_unhedged": mdd_u * 100,
        "hedged_days": hedged_days,
    }


if __name__ == "__main__":
    p = export()
    size = os.path.getsize(p) / 1024
    print(f"已輸出：{p}（{size:.0f} KB）")
    data = json.load(open(p, encoding="utf-8"))
    m = data["meta"]
    print(f"價格 {m['price_from']} ~ {m['price_to']}（{m['n_days']} 天），"
          f"訊號 {m['n_signals']} 天，最後訊號日 {m['signal_to']}")
    print("\n=== 試算範例：投入 100 萬，持有 60 個交易日 ===")
    for s in ("2020-02-20", "2022-03-08", "2025-01-02", "2026-06-01"):
        try:
            r = simulate(data, s, 1_000_000, 60)
        except StopIteration:
            continue
        print(f"  {r['start']} ~ {r['end']}  金價 {r['price_change_pct']:+6.1f}%  |  "
              f"避險 {r['ret_hedged']:+6.1f}% (回撤 {r['mdd_hedged']:5.1f}%)  "
              f"不避險 {r['ret_unhedged']:+6.1f}% (回撤 {r['mdd_unhedged']:5.1f}%)  |  "
              f"差額 {r['pnl_hedged'] - r['pnl_unhedged']:+,.0f} 元")
