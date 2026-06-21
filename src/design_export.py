# -*- coding: utf-8 -*-
"""
前端設計檔資料轉接器
====================
把我們 pipeline 產生的真實結果（outputs/predictions.json、outputs/backtest.json、
data/wf_signals.csv）轉成「Gold Hedge System」設計檔（frontend/index.html）所需的
JSON schema，輸出到 frontend/predictions.json 與 frontend/backtest.json。

設計檔期望的 schema 與我們原生的略有差異，這支程式負責對接：
- pred.current / decline_prob / direction：由我們的 future 物件導出。
- pred.history + model + future(5天)：重組成設計檔的圖表格式。
- bt.equity_curve.hedged/unhedged、bt.metrics.*（百分比）、bt.scenarios（具名情境）。
不需重訓模型，純資料轉換。
"""

import os
import sys
import json
import pandas as pd

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

FRONTEND_DIR = os.path.join(config.BASE_DIR, "docs")   # GitHub Pages 從 /docs 部署
HISTORY_WINDOW = 90      # 儀表板價格圖顯示最近 N 個交易日
EQUITY_POINTS = 260      # 回測淨值曲線降採樣點數（避免 SVG 過重）


def _downsample(seq, n):
    """等距降採樣並保留最後一點。"""
    if len(seq) <= n:
        return list(seq)
    step = len(seq) / n
    idx = sorted(set([int(i * step) for i in range(n)] + [len(seq) - 1]))
    return [seq[i] for i in idx]


def _unit_factors() -> dict:
    """計算三種金價單位的換算係數（以 GLD 每股價為基準乘上 factor）。

    用 yfinance 抓即時的黃金期貨 (GC=F, 美元/盎司) 與美元台幣匯率 (TWD=X)，
    算出真實係數；抓不到時退回約略值。
        spot 美元/盎司 = GLD × (GC=F / GLD)
        台幣/公克      = GLD × (GC=F / GLD) × 匯率 ÷ 31.1035
    """
    gld_to_spot, usd_twd = 10.78, 31.67   # 離線 fallback（約略）
    try:
        import yfinance as yf

        def _last(t):
            d = yf.download(t, period="1mo", progress=False, auto_adjust=True)
            return float(d["Close"].dropna().iloc[-1])

        gld, gcf, twd = _last("GLD"), _last("GC=F"), _last("TWD=X")
        gld_to_spot, usd_twd = gcf / gld, twd
    except Exception:
        pass

    grams = 31.1035   # 1 金衡盎司 = 31.1035 公克
    return {
        "default": "gld",
        "gld_to_spot_oz": round(gld_to_spot, 4),
        "usd_twd": round(usd_twd, 3),
        "grams_per_oz": grams,
        "options": [
            {"key": "gld",  "label": "GLD 美元/股",   "symbol": "$",   "factor": 1.0, "decimals": 2},
            {"key": "spot", "label": "現貨 美元/盎司", "symbol": "$",   "factor": round(gld_to_spot, 4), "decimals": 0},
            {"key": "twd",  "label": "台幣/公克",      "symbol": "NT$", "factor": round(gld_to_spot * usd_twd / grams, 4), "decimals": 0},
        ],
    }


def _build_candles(our_pred: dict) -> dict:
    """產生日/周/月/季 K 棒(OHLC)資料。

    重抓 GLD 的開高低收，再用 pandas resample 聚合成周/月/季：
        open=區間第一筆, high=最高, low=最低, close=最後一筆。
    抓不到網路時，退回用收盤價做退化版 K 棒（開=收，僅供折線顯示）。
    """
    import pandas as pd

    daily = None
    try:
        import yfinance as yf
        df = yf.download("GLD", period="10y", progress=False, auto_adjust=True)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        daily = df[["Open", "High", "Low", "Close"]].dropna()
        daily.columns = ["o", "h", "l", "c"]
    except Exception:
        # 離線退回：用我們既有的收盤價歷史造退化 K 棒
        hist = pd.DataFrame(our_pred["history"])
        hist["date"] = pd.to_datetime(hist["date"])
        daily = hist.set_index("date")["price"].to_frame()
        daily.columns = ["c"]
        for col in ("o", "h", "l"):
            daily[col] = daily["c"]
        daily = daily[["o", "h", "l", "c"]]

    agg = {"o": "first", "h": "max", "l": "min", "c": "last"}

    def _rows(frame, tail):
        frame = frame.tail(tail)
        return [{"date": idx.strftime("%Y-%m-%d"),
                 "o": round(float(r.o), 2), "h": round(float(r.h), 2),
                 "l": round(float(r.l), 2), "c": round(float(r.c), 2)}
                for idx, r in frame.iterrows()]

    return {
        "daily":     _rows(daily, 120),
        "weekly":    _rows(daily.resample("W").agg(agg).dropna(), 104),
        "monthly":   _rows(daily.resample("ME").agg(agg).dropna(), 72),
        "quarterly": _rows(daily.resample("QE").agg(agg).dropna(), 40),
    }


def build_predictions(our_pred: dict) -> dict:
    """組出設計檔用的 predictions.json。"""
    import datetime as _dt
    fut = our_pred["future"]
    direction = "down" if fut.get("predicted_return", 0) < 0 else "up"

    # 最近 N 日歷史
    hist_all = our_pred["history"]
    hist = hist_all[-HISTORY_WINDOW:]
    hist_dates = [h["date"] for h in hist]

    # 模型擬合線：用測試期預測值，依日期對齊到這段歷史
    pred_by_date = {tp["date"]: tp["predicted"] for tp in our_pred.get("test_predictions", [])}
    model = [{"date": h["date"],
              "price": round(pred_by_date.get(h["date"], h["price"]), 3)}
             for h in hist]

    # 未來 5 個交易日：由現價幾何內插到模型的 5 日目標價
    cur_price = float(fut["current_price"])
    target = float(fut["predicted_price"])
    horizon = int(fut.get("horizon_days", config.HORIZON))
    fdates = pd.bdate_range(start=pd.Timestamp(fut["current_date"]) + pd.tseries.offsets.BDay(1),
                            periods=horizon)
    future = []
    for k, d in enumerate(fdates, start=1):
        # 幾何內插：price_k = cur * (target/cur)^(k/horizon)
        ratio = (target / cur_price) ** (k / horizon) if cur_price > 0 else 1.0
        future.append({"date": d.strftime("%Y-%m-%d"), "price": round(cur_price * ratio, 3)})

    return {
        "meta": our_pred["meta"],
        "current": {"date": fut["current_date"], "price": round(cur_price, 3)},
        "decline_prob": round(float(fut["prob_down"]), 4),
        "direction": direction,
        "suggested_hedge": our_pred.get("recommendation", {}).get("signal", "neutral"),
        "metrics": our_pred["metrics"],          # 結構與設計檔一致，直接沿用
        "units": _unit_factors(),                # 三種計價單位的換算係數
        "data_as_of": fut["current_date"],       # 資料截至日（最後交易日）
        "generated_at": _dt.datetime.now().strftime("%Y-%m-%d %H:%M"),  # 本檔產生時間
        "candles": _build_candles(our_pred),     # 日/周/月/季 K 棒
        "history": hist,
        "model": model,
        "future": future,
    }


def _pick_scenarios(scenarios_by_year: list) -> list:
    """從逐年表現挑出『大跌 / 盤整 / 大漲』三個代表情境（依真實資料）。"""
    if not scenarios_by_year:
        return []
    worst = min(scenarios_by_year, key=lambda s: s["nohedge_return"])
    best = max(scenarios_by_year, key=lambda s: s["nohedge_return"])
    flat = min(scenarios_by_year, key=lambda s: abs(s["nohedge_return"]))

    def conv(s, name):
        u = s["nohedge_return"] * 100
        h = s["hedge_return"] * 100
        return {
            "name": name,
            "period": str(s["year"]),
            "unhedged_return": round(u, 1),
            "hedged_return": round(h, 1),
            # 避險成本＝放棄的上檔（僅在避險讓出報酬時為正，抗跌時為 0）
            "hedge_cost": round(max(0.0, u - h), 1),
        }

    out, seen = [], set()
    for s, name in [(worst, "大跌"), (flat, "盤整"), (best, "大漲")]:
        key = s["year"]
        if key in seen:      # 避免同一年被選兩次
            continue
        seen.add(key)
        out.append(conv(s, name))
    return out


def build_backtest(our_bt: dict) -> dict:
    """組出設計檔用的 backtest.json。"""
    ec = our_bt["equity_curve"]
    dates = _downsample(ec["dates"], EQUITY_POINTS)
    hedged = _downsample(ec["hedge"], EQUITY_POINTS)
    unhedged = _downsample(ec["nohedge"], EQUITY_POINTS)

    sn = our_bt["stats"]["nohedge"]
    sh = our_bt["stats"]["hedge"]
    u_tot, h_tot = sn["total_return"], sh["total_return"]
    cost_ratio = (u_tot - h_tot) / u_tot * 100 if u_tot else 0.0  # 放棄的上檔佔比

    # 避險啟動天數：下跌機率超過門檻的天數
    threshold = our_bt["meta"]["hedge_threshold"]
    trigger_days = 0
    if os.path.exists(config.WF_SIGNALS_CSV):
        sig = pd.read_csv(config.WF_SIGNALS_CSV)
        trigger_days = int((sig["prob_down"] > threshold).sum())

    return {
        "meta": our_bt["meta"],
        "equity_curve": {"dates": dates, "hedged": hedged, "unhedged": unhedged},
        "metrics": {
            "total_return_hedged": round(h_tot * 100, 2),
            "total_return_unhedged": round(u_tot * 100, 2),
            "max_drawdown_hedged": round(sh["max_drawdown"] * 100, 1),
            "max_drawdown_unhedged": round(sn["max_drawdown"] * 100, 1),
            "hedge_cost_ratio": round(cost_ratio, 1),
            "hedged_trigger_days": trigger_days,
        },
        "scenarios": _pick_scenarios(our_bt.get("scenarios_by_year", [])),
    }


def export(pred_path: str = None, bt_path: str = None) -> tuple:
    """讀我們的真實輸出 → 轉成設計檔 schema → 寫到 frontend/。"""
    pred_path = pred_path or os.path.join(config.JSON_DIR, "predictions.json")
    bt_path = bt_path or os.path.join(config.JSON_DIR, "backtest.json")
    os.makedirs(FRONTEND_DIR, exist_ok=True)

    our_pred = json.load(open(pred_path, encoding="utf-8"))
    our_bt = json.load(open(bt_path, encoding="utf-8"))

    design_pred = build_predictions(our_pred)
    design_bt = build_backtest(our_bt)

    p1 = os.path.join(FRONTEND_DIR, "predictions.json")
    p2 = os.path.join(FRONTEND_DIR, "backtest.json")
    json.dump(design_pred, open(p1, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    json.dump(design_bt, open(p2, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    return p1, p2


if __name__ == "__main__":
    p1, p2 = export()
    print("已輸出設計檔資料：")
    print(" -", p1)
    print(" -", p2)
