# -*- coding: utf-8 -*-
"""
輸出模組
========
把模型與回測結果存成兩個 JSON，供前端網頁讀取：

1. predictions.json
   - history：歷史金價序列。
   - test_predictions：測試期的「實際 vs 模型預測」價格與下跌機率。
   - future：用最新資料預測的未來金價與下跌機率。
   - metrics：naive / 單因子 / 多因子三方的 RMSE、MAE、AUC 等誤差指標。

2. backtest.json
   - 有避險 vs 無避險的累積損益曲線、避險比例。
   - 兩者的總報酬、年化報酬、波動、Sharpe、最大回撤。
   - 各年度（情境）表現。
"""

import os
import sys
import json
import numpy as np
import pandas as pd

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from src.preprocessing import prepare_data, inverse_return
from src.model import build_lstm_model, train_model, set_seed, pos_weight_from


def _to_native(obj):
    """把 numpy 型別轉成可 JSON 序列化的 Python 原生型別。"""
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    raise TypeError(f"無法序列化型別 {type(obj)}")


# ---------------------------------------------------------------------------
# 未來預測：用最新資料訓練最終模型，預測未來 HORIZON 天
# ---------------------------------------------------------------------------
def forecast_future(df: pd.DataFrame) -> dict:
    """訓練一個用『全部資料』的最終模型，輸出未來 HORIZON 天的預測。"""
    set_seed()
    # train_ratio=1.0 → 全部資料都拿來 fit scaler 與訓練（這是要對未來預測的最終模型）
    data = prepare_data(df, feature_cols=config.FEATURE_COLS, train_ratio=0.999)
    model = build_lstm_model(n_features=len(config.FEATURE_COLS),
                             pos_weight=pos_weight_from(data["yclf_train"]))
    train_model(model, data, verbose=0)

    # 取最新一個視窗（最後 LOOKBACK 天）做預測
    scaled_all = data["scaled_all"]
    last_window = scaled_all[-config.LOOKBACK:][None, ...]
    preg, pclf = model.predict(last_window, verbose=0)
    pred_ret = float(inverse_return(preg.ravel(), data["target_scaler"])[0])
    prob_down = float(pclf.ravel()[0])

    current_price = float(df[config.TARGET_COL].iloc[-1])
    current_date = df.index[-1]
    future_price = current_price * (1.0 + pred_ret)
    # 未來目標日（約 HORIZON 個交易日後，用日曆天近似）
    future_date = current_date + pd.tseries.offsets.BDay(config.HORIZON)

    return {
        "current_date": current_date.strftime("%Y-%m-%d"),
        "current_price": round(current_price, 3),
        "horizon_days": config.HORIZON,
        "future_date": future_date.strftime("%Y-%m-%d"),
        "predicted_price": round(future_price, 3),
        "predicted_return": round(pred_ret, 5),
        "prob_down": round(prob_down, 4),
    }


# ---------------------------------------------------------------------------
# 避險建議訊號（由最新的下跌機率換算）
# ---------------------------------------------------------------------------
def build_recommendation(future: dict, threshold: float = None) -> dict:
    """把『未來下跌機率』換算成前端可直接顯示的避險建議。

    - recommended_hedge_ratio：建議避險比例 0~1（機率超過門檻後線性放大）。
    - signal / signal_label：偏多 / 中性 / 偏空的燈號與文字。
    """
    threshold = threshold if threshold is not None else config.HEDGE_PROB_THRESHOLD
    p = float(future["prob_down"])
    hedge = max(0.0, min(1.0, (p - threshold) / (1.0 - threshold)))

    if p >= 0.60:
        signal, label = "hedge", "建議避險（下跌風險偏高）"
    elif p >= 0.50:
        signal, label = "light_hedge", "偏空，建議輕度避險"
    elif p >= 0.45:
        signal, label = "neutral", "中性觀望"
    else:
        signal, label = "hold", "偏多，維持持有"

    return {
        "as_of": future["current_date"],
        "horizon_days": future["horizon_days"],
        "prob_down": round(p, 4),
        "recommended_hedge_ratio": round(hedge, 4),
        "exposure_ratio": round(1.0 - hedge, 4),   # 黃金曝險 = 1 - 避險比例
        "signal": signal,
        "signal_label": label,
        "threshold": threshold,
    }


# ---------------------------------------------------------------------------
# 因子儀表板（六因子最新值、近一年變化、與金價報酬相關性）
# ---------------------------------------------------------------------------
def build_factor_dashboard(df: pd.DataFrame, lookback_year: int = 252) -> list:
    """整理六個因子的最新狀態，供前端做總經面板。"""
    rets = df.pct_change()
    gold_ret = rets[config.TARGET_COL]
    name_map = {
        "GLD": "黃金 (GLD)", "DGS10": "10年期殖利率 (DGS10)",
        "CPI": "通膨 (CPI)", "DXY": "美元指數 (DXY)",
        "SP500": "S&P 500", "VIX": "恐慌指數 (VIX)",
    }
    out = []
    for col in config.FEATURE_COLS:
        latest = float(df[col].iloc[-1])
        # 近一年變化率（若資料不足一年則用全期）
        ref_idx = -min(lookback_year + 1, len(df))
        ref = float(df[col].iloc[ref_idx])
        change_1y = (latest / ref - 1.0) if ref != 0 else float("nan")
        corr = float(rets[col].corr(gold_ret))   # 與金價日報酬相關係數
        out.append({
            "key": col,
            "name": name_map.get(col, col),
            "latest": round(latest, 3),
            "change_1y": round(change_1y, 4),
            "corr_with_gold": round(corr, 3),
        })
    return out


# ---------------------------------------------------------------------------
# predictions.json
# ---------------------------------------------------------------------------
def save_predictions_json(df: pd.DataFrame, compare_res: dict,
                          future: dict, path: str = None) -> str:
    path = path or os.path.join(config.JSON_DIR, "predictions.json")
    eval_multi = compare_res["eval_multi"]

    history = [{"date": d.strftime("%Y-%m-%d"), "price": round(float(p), 3)}
               for d, p in zip(df.index, df[config.TARGET_COL].values)]

    test_predictions = [
        {"date": d.strftime("%Y-%m-%d"),
         "actual": round(float(a), 3),
         "predicted": round(float(p), 3),
         "prob_down": round(float(pd_), 4)}
        for d, a, p, pd_ in zip(eval_multi["dates"],
                                eval_multi["true_price"],
                                eval_multi["pred_price"],
                                eval_multi["pred_prob_down"])
    ]

    payload = {
        "meta": {
            "target": "GLD",
            "lookback": config.LOOKBACK,
            "horizon": config.HORIZON,
            "features": config.FEATURE_COLS,
            "generated_from": f"{df.index.min().date()} ~ {df.index.max().date()}",
        },
        "metrics": compare_res["table"],
        "history": history,
        "test_predictions": test_predictions,
        "future": future,
        "recommendation": build_recommendation(future),   # 避險建議訊號
        "factors": build_factor_dashboard(df),             # 因子儀表板
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=_to_native)
    return path


# ---------------------------------------------------------------------------
# backtest.json
# ---------------------------------------------------------------------------
def _yearly_scenarios(signals: pd.DataFrame, strategy: dict) -> list:
    """依年度切出『情境表現』：每年有避險 vs 無避險的報酬與回撤。"""
    df = pd.DataFrame({
        "ret_nohedge": signals["ret_1d"].values,
        "hedge_ratio": strategy["hedge_ratio"],
    }, index=signals.index)
    df["ret_hedge"] = df["ret_nohedge"] * (1.0 - df["hedge_ratio"])

    out = []
    for year, g in df.groupby(df.index.year):
        def _mdd(r):
            eq = np.cumprod(1.0 + r.values)
            return float((eq / np.maximum.accumulate(eq) - 1.0).min())
        out.append({
            "year": int(year),
            "nohedge_return": round(float(np.prod(1 + g["ret_nohedge"]) - 1), 4),
            "hedge_return": round(float(np.prod(1 + g["ret_hedge"]) - 1), 4),
            "nohedge_mdd": round(_mdd(g["ret_nohedge"]), 4),
            "hedge_mdd": round(_mdd(g["ret_hedge"]), 4),
        })
    return out


def _backtest_summary(signals: pd.DataFrame, strategy: dict) -> dict:
    """整理『避險相對不避險』的改善幅度，與目前最新的避險建議。"""
    sn = strategy["stats_nohedge"]
    sh = strategy["stats_hedge"]
    # 最新一日的避險訊號（回測期最後一天）
    last_prob = float(signals["prob_down"].iloc[-1])
    last_hedge = float(strategy["hedge_ratio"][-1])
    reco = build_recommendation(
        {"prob_down": last_prob, "current_date": signals.index[-1].strftime("%Y-%m-%d"),
         "horizon_days": config.HORIZON},
        threshold=strategy["threshold"])
    return {
        # 正值代表避險較好：回撤更淺、波動更低、Sharpe 更高
        "drawdown_reduction": round(sh["max_drawdown"] - sn["max_drawdown"], 5),
        "vol_reduction": round(sn["annual_vol"] - sh["annual_vol"], 5),
        "sharpe_delta": round(sh["sharpe"] - sn["sharpe"], 5),
        "return_giveup": round(sn["total_return"] - sh["total_return"], 5),
        "latest_recommendation": reco,
    }


def save_backtest_json(signals: pd.DataFrame, strategy: dict,
                       path: str = None) -> str:
    path = path or os.path.join(config.JSON_DIR, "backtest.json")
    payload = {
        "meta": {
            "method": "walk-forward",
            "hedge_threshold": strategy["threshold"],
            "period": f"{signals.index.min().date()} ~ {signals.index.max().date()}",
            "n_days": int(len(signals)),
        },
        "equity_curve": {
            "dates": strategy["dates"],
            "nohedge": [round(x, 5) for x in strategy["equity_nohedge"]],
            "hedge": [round(x, 5) for x in strategy["equity_hedge"]],
            "hedge_ratio": [round(x, 4) for x in strategy["hedge_ratio"]],
        },
        "stats": {
            "nohedge": {k: round(v, 5) for k, v in strategy["stats_nohedge"].items()},
            "hedge": {k: round(v, 5) for k, v in strategy["stats_hedge"].items()},
        },
        "scenarios_by_year": _yearly_scenarios(signals, strategy),
        "summary": _backtest_summary(signals, strategy),
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2, default=_to_native)
    return path
