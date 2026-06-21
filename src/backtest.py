# -*- coding: utf-8 -*-
"""
回測模組（Walk-forward 滾動視窗）
================================
核心原則：模型在每個時間點「只能用該時間點之前的資料」訓練，絕不碰未來資料。

流程：
1. 以 WF_INITIAL_TRAIN 天為初始訓練集。
2. 每往前 WF_STEP 天，就用「截至當下」的所有歷史重新訓練一次模型，
   並對接下來 WF_STEP 天逐日產生「下跌機率」訊號（每天用各自截止當天的視窗）。
   - scaler 每次都只用「當下訓練區間」fit，避免資料洩漏。
3. 把整段測試期的每日下跌機率訊號串起來。

策略比較：
- 不避險 (buy & hold)：永遠 100% 持有黃金。
- 依訊號避險：下跌機率越高 → 避險力道越大 → 黃金曝險越低。
  避險部位視為被中性化（報酬 ≈ 0），因此當天組合報酬 = 黃金報酬 ×(1 - 避險比例)。
計算兩者的累積損益曲線與最大回撤 (max drawdown)。
"""

import os
import sys
import numpy as np
import pandas as pd

os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from src.preprocessing import _build_sequences
from src.model import build_lstm_model, set_seed, pos_weight_from
from sklearn.preprocessing import MinMaxScaler, StandardScaler
import tensorflow as tf


def walk_forward(df: pd.DataFrame,
                 feature_cols=None,
                 lookback: int = None,
                 horizon: int = None,
                 initial_train: int = None,
                 step: int = None,
                 epochs: int = None,
                 verbose: bool = True) -> pd.DataFrame:
    """執行 walk-forward，回傳每日訊號 DataFrame（index=日期）。

    欄位：price(當日金價), prob_down(未來下跌機率), pred_ret(預測報酬),
          ret_1d(該日到隔日的實際報酬，回測用)。
    """
    feature_cols = feature_cols or config.FEATURE_COLS
    lookback = lookback or config.LOOKBACK
    horizon = horizon or config.HORIZON
    initial_train = initial_train or config.WF_INITIAL_TRAIN
    step = step or config.WF_STEP
    epochs = epochs or config.WF_EPOCHS

    set_seed()
    prices = df[config.TARGET_COL].values.astype("float32")
    feats = df[feature_cols].values.astype("float32")
    dates = df.index
    n = len(df)
    n_features = len(feature_cols)

    rows = []
    n_retrain = 0
    # train_end：訓練資料的右界（不含），也是開始預測的第一天
    for train_end in range(initial_train, n - horizon, step):
        # --- 只用過去資料 fit scaler ---
        fscaler = MinMaxScaler().fit(feats[:train_end])
        scaled = fscaler.transform(feats)

        # --- 建立訓練序列（未來目標日須 < train_end，確保不偷看）---
        Xtr, yret, yclf, _, _, _, _ = _build_sequences(
            scaled[:train_end], prices[:train_end], dates[:train_end],
            lookback, horizon)
        if len(Xtr) < 100:
            continue

        tscaler = StandardScaler().fit(yret.reshape(-1, 1))
        yreg = tscaler.transform(yret.reshape(-1, 1)).ravel()

        # --- 重新訓練模型（pos_weight 依當下訓練集的下跌比例調整）---
        model = build_lstm_model(n_features=n_features, lookback=lookback,
                                 pos_weight=pos_weight_from(yclf))
        model.fit(Xtr, {"reg": yreg, "clf": yclf},
                  epochs=epochs, batch_size=config.BATCH_SIZE,
                  validation_split=0.1,
                  callbacks=[tf.keras.callbacks.EarlyStopping(
                      monitor="val_loss", patience=4, restore_best_weights=True)],
                  verbose=0)
        n_retrain += 1

        # --- 對 [train_end, train_end+step) 逐日預測（批次一次算完）---
        block_end = min(train_end + step, n - horizon)
        pred_days = list(range(train_end, block_end))
        windows = np.stack([scaled[t - lookback + 1: t + 1] for t in pred_days])
        preg, pclf = model.predict(windows, verbose=0)
        pred_ret = tscaler.inverse_transform(preg.reshape(-1, 1)).ravel()
        prob_down = pclf.ravel()

        for k, t in enumerate(pred_days):
            rows.append({
                "Date": dates[t],
                "price": prices[t],
                "prob_down": float(prob_down[k]),
                "pred_ret": float(pred_ret[k]),
                # 該日到隔日的實際報酬（決策在 t 日收盤後，用於 t+1 持有）
                "ret_1d": float(prices[t + 1] / prices[t] - 1.0),
            })

        if verbose:
            print(f"   walk-forward 進度：訓練到 {dates[train_end].date()} "
                  f"(第 {n_retrain} 次重訓, 已產生 {len(rows)} 個訊號)")

    out = pd.DataFrame(rows).set_index("Date")
    # 快取每日訊號，之後可用 load_signals() 快速重算回測，不必重訓模型
    out.to_csv(config.WF_SIGNALS_CSV, encoding="utf-8-sig")
    return out


def load_signals():
    """讀取快取的 walk-forward 訊號（若不存在回傳 None）。"""
    if os.path.exists(config.WF_SIGNALS_CSV):
        return pd.read_csv(config.WF_SIGNALS_CSV, index_col="Date", parse_dates=True)
    return None


# ---------------------------------------------------------------------------
# 策略：依訊號避險 vs 不避險
# ---------------------------------------------------------------------------
def _hedge_ratio(prob_down: np.ndarray, threshold: float) -> np.ndarray:
    """把下跌機率轉成避險比例 0~1。

    機率 <= threshold 不避險；超過後線性放大到機率=1 時全額避險。
    """
    h = (prob_down - threshold) / (1.0 - threshold)
    return np.clip(h, 0.0, 1.0)


def _max_drawdown(equity: np.ndarray) -> float:
    """計算最大回撤（負值，例如 -0.25 代表 -25%）。"""
    running_max = np.maximum.accumulate(equity)
    dd = equity / running_max - 1.0
    return float(dd.min())


def run_strategy(signals: pd.DataFrame, threshold: float = None) -> dict:
    """根據訊號計算『避險 vs 不避險』的累積損益與最大回撤。"""
    threshold = threshold if threshold is not None else config.HEDGE_PROB_THRESHOLD

    # 因果對齊：prob_down[t] 在第 t 日收盤後即可得知，據此決定「t→t+1」的曝險，
    # 而 ret_1d[t] 正是 t→t+1 的報酬，兩者配對不含前視偏誤。
    prob_down = signals["prob_down"].values
    ret = signals["ret_1d"].values   # t→t+1 報酬
    h = _hedge_ratio(prob_down, threshold)

    # 不避險：全額持有黃金
    ret_nohedge = ret
    # 避險：黃金曝險 = (1 - 避險比例)
    ret_hedge = ret * (1.0 - h)

    eq_nohedge = np.cumprod(1.0 + ret_nohedge)
    eq_hedge = np.cumprod(1.0 + ret_hedge)

    def _stats(eq, r):
        total_return = float(eq[-1] - 1.0)
        ann = float((1.0 + total_return) ** (252.0 / len(r)) - 1.0)
        vol = float(np.std(r) * np.sqrt(252))
        sharpe = float(np.mean(r) / (np.std(r) + 1e-9) * np.sqrt(252))
        return {
            "total_return": total_return,
            "annual_return": ann,
            "annual_vol": vol,
            "sharpe": sharpe,
            "max_drawdown": _max_drawdown(eq),
        }

    return {
        "dates": [d.strftime("%Y-%m-%d") for d in signals.index],
        "equity_nohedge": eq_nohedge.tolist(),
        "equity_hedge": eq_hedge.tolist(),
        "hedge_ratio": h.tolist(),
        "stats_nohedge": _stats(eq_nohedge, ret_nohedge),
        "stats_hedge": _stats(eq_hedge, ret_hedge),
        "threshold": threshold,
    }


if __name__ == "__main__":
    from src.data_collection import load_dataset
    df = load_dataset()
    print("執行 walk-forward 回測（可能需要數分鐘）...")
    sig = walk_forward(df, verbose=True)
    print(f"\n共產生 {len(sig)} 個每日訊號，區間 "
          f"{sig.index.min().date()} ~ {sig.index.max().date()}")
    res = run_strategy(sig)
    print("\n========= 策略比較 =========")
    print("不避險：", {k: round(v, 4) for k, v in res["stats_nohedge"].items()})
    print("避險：  ", {k: round(v, 4) for k, v in res["stats_hedge"].items()})
