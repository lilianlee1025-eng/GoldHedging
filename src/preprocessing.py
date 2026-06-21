# -*- coding: utf-8 -*-
"""
前處理模組
==========
把對齊後的每日資料轉成 LSTM 可用的監督式學習樣本：

- 輸入 X：過去 LOOKBACK 天、6 個因子的滑動視窗。
- 迴歸目標 y_reg：未來 HORIZON 天的「報酬率」（future_price/base_price - 1）。
- 分類目標 y_clf：未來 HORIZON 天是否「下跌」（報酬 < 0 → 1）。

防資料洩漏 (data leakage) 的兩個重點：
1. 特徵正規化的 scaler「只用訓練集 fit」，再套用到全部資料。
2. 切分訓練 / 測試時，訓練樣本的「未來目標日」也必須落在訓練區間內，
   不能跨越分界線偷看到測試期的價格。
"""

import os
import sys
import numpy as np
import pandas as pd
from sklearn.preprocessing import MinMaxScaler, StandardScaler

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config


def _build_sequences(scaled_features: np.ndarray,
                     prices: np.ndarray,
                     dates: pd.DatetimeIndex,
                     lookback: int,
                     horizon: int):
    """把連續序列切成滑動視窗樣本。

    對每個視窗：
      - 視窗範圍 [i, i+lookback)，預測「站在第 t = i+lookback-1 天結束」時做出。
      - 未來目標日 = t + horizon。
      - base_price = 第 t 天收盤價；future_price = 第 t+horizon 天收盤價。
    回傳：X, y_ret(報酬), y_clf(是否下跌), base_price, future_price, 預測日 date, 預測日索引 t。
    """
    X, y_ret, y_clf = [], [], []
    base_p, future_p, pred_dates, pred_idx = [], [], [], []

    n = len(scaled_features)
    for i in range(n - lookback - horizon + 1):
        t = i + lookback - 1            # 視窗最後一天（做預測的當下）
        f = t + horizon                 # 未來目標日
        X.append(scaled_features[i:i + lookback])
        base = prices[t]
        fut = prices[f]
        ret = fut / base - 1.0
        y_ret.append(ret)
        y_clf.append(1.0 if ret < 0 else 0.0)
        base_p.append(base)
        future_p.append(fut)
        pred_dates.append(dates[t])
        pred_idx.append(t)

    return (np.array(X, dtype="float32"),
            np.array(y_ret, dtype="float32"),
            np.array(y_clf, dtype="float32"),
            np.array(base_p, dtype="float32"),
            np.array(future_p, dtype="float32"),
            pd.DatetimeIndex(pred_dates),
            np.array(pred_idx))


def prepare_data(df: pd.DataFrame,
                 feature_cols=None,
                 lookback: int = None,
                 horizon: int = None,
                 train_ratio: float = None,
                 scaler_type: str = "minmax"):
    """產生訓練 / 測試樣本，回傳一個包含所有東西的 dict。

    feature_cols 可只給 ['GLD'] 來做「單因子 baseline」。
    """
    feature_cols = feature_cols or config.FEATURE_COLS
    lookback = lookback or config.LOOKBACK
    horizon = horizon or config.HORIZON
    train_ratio = train_ratio or config.TRAIN_RATIO

    prices = df[config.TARGET_COL].values.astype("float32")
    dates = df.index
    feats = df[feature_cols].values.astype("float32")

    # --- 時間切分點（依時間順序，不可隨機打亂）---
    split_idx = int(len(df) * train_ratio)

    # --- 關鍵：scaler 只用訓練區間 fit ---
    scaler = MinMaxScaler() if scaler_type == "minmax" else StandardScaler()
    scaler.fit(feats[:split_idx])
    scaled = scaler.transform(feats)

    # --- 建立所有滑動視窗 ---
    (X, y_ret, y_clf, base_p, future_p, pred_dates, pred_idx) = _build_sequences(
        scaled, prices, dates, lookback, horizon)

    # --- 依「預測日 t」與「未來目標日 t+horizon」分配 train / test ---
    # 訓練樣本：未來目標日仍在訓練區間內（t+horizon < split_idx），確保完全沒看到測試期。
    is_train = (pred_idx + horizon) < split_idx
    is_test = pred_idx >= split_idx

    # --- 迴歸目標標準化（只用訓練集 fit），讓訓練更穩定 ---
    target_scaler = StandardScaler()
    target_scaler.fit(y_ret[is_train].reshape(-1, 1))
    y_ret_scaled = target_scaler.transform(y_ret.reshape(-1, 1)).ravel()

    return {
        "X_train": X[is_train], "X_test": X[is_test],
        "yreg_train": y_ret_scaled[is_train], "yreg_test": y_ret_scaled[is_test],
        "yclf_train": y_clf[is_train], "yclf_test": y_clf[is_test],
        "ret_train": y_ret[is_train], "ret_test": y_ret[is_test],       # 原始報酬
        "base_train": base_p[is_train], "base_test": base_p[is_test],
        "future_train": future_p[is_train], "future_test": future_p[is_test],
        "dates_train": pred_dates[is_train], "dates_test": pred_dates[is_test],
        "feature_scaler": scaler,
        "target_scaler": target_scaler,
        "feature_cols": feature_cols,
        "lookback": lookback, "horizon": horizon,
        # 整段 scaled 序列（walk-forward 回測會用到）
        "scaled_all": scaled, "prices_all": prices, "dates_all": dates,
    }


def inverse_return(y_scaled: np.ndarray, target_scaler: StandardScaler) -> np.ndarray:
    """把標準化後的迴歸輸出還原成真實報酬率。"""
    return target_scaler.inverse_transform(np.asarray(y_scaled).reshape(-1, 1)).ravel()


if __name__ == "__main__":
    from src.data_collection import load_dataset
    df = load_dataset()
    data = prepare_data(df)
    print("多因子樣本：")
    print("  X_train:", data["X_train"].shape, "| X_test:", data["X_test"].shape)
    print("  訓練期下跌比例:", round(float(data["yclf_train"].mean()), 3))
    print("  測試期下跌比例:", round(float(data["yclf_test"].mean()), 3))
    print("  訓練最後日:", data["dates_train"][-1].date(),
          "| 測試第一日:", data["dates_test"][0].date())
