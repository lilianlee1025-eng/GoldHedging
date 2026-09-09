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
  避險部位視為被中性化（報酬 ≈ 0），因此當天組合毛報酬 = 黃金報酬 ×(1 - 避險比例)。

避險成本（重要）：
  現實中避險不是免費的。本模組把成本拆成兩塊，從毛報酬扣除：
    · 持有成本 carry    = 避險比例 × 年化成本 ÷ 252   （轉倉價差、保證金機會成本、權利金）
    · 調倉成本 turnover = |避險比例變動| × 單邊交易成本 （手續費、滑價、買賣價差）
  同時保留「未扣成本」的毛曲線，讓兩者並列 —— 差距就是這份保險的實際價格。
  cost_sweep() 進一步掃過多種成本假設，回答「保險貴到什麼程度就不划算」。
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


def _apply_costs(ret: np.ndarray, h: np.ndarray,
                 cost_annual: float, tc_oneway: float) -> tuple:
    """把避險成本從毛報酬中扣除，回傳 (淨報酬, 持有成本序列, 調倉成本序列)。

    - 持有成本：只要當天有避險部位就要付，按避險比例與在市天數計價
      （年化成本平均攤到 252 個交易日）。
    - 調倉成本：避險比例每變動 1 個單位就要進出市場一次，按單邊收取。
      prepend=0 代表第一天是從「零避險」開始建倉，這筆建倉成本要算。
    """
    gross = ret * (1.0 - h)
    carry = h * (cost_annual / 252.0)
    turnover = np.abs(np.diff(h, prepend=0.0))
    trade = turnover * tc_oneway
    return gross - carry - trade, carry, trade


def _stats(eq: np.ndarray, r: np.ndarray) -> dict:
    """由淨值曲線與日報酬序列算出績效指標。"""
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


def run_strategy(signals: pd.DataFrame, threshold: float = None,
                 cost_annual: float = None, tc_oneway: float = None) -> dict:
    """根據訊號計算『避險 vs 不避險』的累積損益與最大回撤（含避險成本）。

    同時輸出「毛」（gross，未扣成本）與「淨」（扣成本）兩條避險曲線：
    毛曲線是舊版行為，等於假設保險免費，留著當理論上限對照。
    """
    threshold = threshold if threshold is not None else config.HEDGE_PROB_THRESHOLD
    cost_annual = cost_annual if cost_annual is not None else config.HEDGE_COST_ANNUAL
    tc_oneway = tc_oneway if tc_oneway is not None else config.HEDGE_TC_ONEWAY

    # 因果對齊：prob_down[t] 在第 t 日收盤後即可得知，據此決定「t→t+1」的曝險，
    # 而 ret_1d[t] 正是 t→t+1 的報酬，兩者配對不含前視偏誤。
    prob_down = signals["prob_down"].values
    ret = signals["ret_1d"].values   # t→t+1 報酬
    h = _hedge_ratio(prob_down, threshold)

    # 不避險：全額持有黃金
    ret_nohedge = ret
    # 避險（毛）：黃金曝險 = (1 - 避險比例)，不計成本
    ret_hedge_gross = ret * (1.0 - h)
    # 避險（淨）：再扣掉持有成本與調倉成本
    ret_hedge, carry, trade = _apply_costs(ret, h, cost_annual, tc_oneway)

    eq_nohedge = np.cumprod(1.0 + ret_nohedge)
    eq_hedge_gross = np.cumprod(1.0 + ret_hedge_gross)
    eq_hedge = np.cumprod(1.0 + ret_hedge)

    n_years = len(ret) / 252.0
    return {
        "dates": [d.strftime("%Y-%m-%d") for d in signals.index],
        "equity_nohedge": eq_nohedge.tolist(),
        "equity_hedge": eq_hedge.tolist(),
        "equity_hedge_gross": eq_hedge_gross.tolist(),
        "hedge_ratio": h.tolist(),
        "stats_nohedge": _stats(eq_nohedge, ret_nohedge),
        "stats_hedge": _stats(eq_hedge, ret_hedge),
        "stats_hedge_gross": _stats(eq_hedge_gross, ret_hedge_gross),
        "threshold": threshold,
        "cost": {
            "cost_annual": cost_annual,
            "tc_oneway": tc_oneway,
            # 累計付出的成本（佔期初本金的比例）
            "carry_total": float(carry.sum()),
            "trade_total": float(trade.sum()),
            "total": float(carry.sum() + trade.sum()),
            # 平均每年付多少保費、平均避險比例、平均年換手次數
            "carry_annual_avg": float(carry.sum() / n_years),
            "avg_hedge_ratio": float(h.mean()),
            "hedged_days_ratio": float((h > 0).mean()),
            "turnover_per_year": float(np.abs(np.diff(h, prepend=0.0)).sum() / n_years),
            # 成本讓避險曲線少賺多少（總報酬的百分點差）
            "drag_on_return": float(eq_hedge_gross[-1] - eq_hedge[-1]),
        },
    }


def cost_sweep(signals: pd.DataFrame, threshold: float = None,
               scenarios=None, tc_oneway: float = None) -> list:
    """掃過多組年化避險成本，量化「保險費 vs 回撤改善」的權衡。

    回答的問題：避險確實壓低了回撤，但那個保護值多少錢？成本升到哪裡就不划算？
    每一列附上 protection_price —— 每買到 1 個百分點的回撤改善，要放棄幾個百分點
    的總報酬。數字越小代表這份保險越划算。

    注意：scenarios 只變動「年化持有成本」，調倉成本 tc_oneway 各列一律照收，
    所以成本 0 的那一列是「零持有成本」的對照組，不是完全免費。
    """
    threshold = threshold if threshold is not None else config.HEDGE_PROB_THRESHOLD
    tc_oneway = tc_oneway if tc_oneway is not None else config.HEDGE_TC_ONEWAY
    scenarios = scenarios if scenarios is not None else config.HEDGE_COST_SCENARIOS

    prob_down = signals["prob_down"].values
    ret = signals["ret_1d"].values
    h = _hedge_ratio(prob_down, threshold)

    eq_nohedge = np.cumprod(1.0 + ret)
    base_return = float(eq_nohedge[-1] - 1.0)
    base_mdd = _max_drawdown(eq_nohedge)

    out = []
    for cost_annual, label in scenarios:
        net, _, _ = _apply_costs(ret, h, cost_annual, tc_oneway)
        eq = np.cumprod(1.0 + net)
        total_return = float(eq[-1] - 1.0)
        mdd = _max_drawdown(eq)
        # 回撤改善（正值＝回撤變淺）、報酬讓出（正值＝比不避險少賺）
        dd_gain = (mdd - base_mdd) * 100.0
        ret_giveup = (base_return - total_return) * 100.0
        out.append({
            "cost_annual": cost_annual,
            "label": label,
            "total_return": round(total_return * 100, 1),
            "max_drawdown": round(mdd * 100, 1),
            "dd_improvement": round(dd_gain, 1),
            "return_giveup": round(ret_giveup, 1),
            # 每換到 1pp 回撤改善，要付出幾 pp 報酬（越小越划算；<=0 代表白賺）
            "protection_price": round(ret_giveup / dd_gain, 1) if dd_gain > 0.05 else None,
            "worth_it": bool(dd_gain > 0.05 and ret_giveup <= dd_gain),
        })
    return out


if __name__ == "__main__":
    from src.data_collection import load_dataset

    sig = load_signals()
    if sig is None:
        df = load_dataset()
        print("執行 walk-forward 回測（可能需要數分鐘）...")
        sig = walk_forward(df, verbose=True)
    else:
        print(f"使用快取訊號 {config.WF_SIGNALS_CSV}（不重訓模型）")

    print(f"\n共 {len(sig)} 個每日訊號，區間 "
          f"{sig.index.min().date()} ~ {sig.index.max().date()}")
    res = run_strategy(sig)
    print("\n========= 策略比較 =========")
    print("不避險：      ", {k: round(v, 4) for k, v in res["stats_nohedge"].items()})
    print("避險（毛）：  ", {k: round(v, 4) for k, v in res["stats_hedge_gross"].items()})
    print("避險（扣成本）:", {k: round(v, 4) for k, v in res["stats_hedge"].items()})
    c = res["cost"]
    print(f"\n避險成本：年化假設 {c['cost_annual']:.2%}，平均避險比例 {c['avg_hedge_ratio']:.1%}，"
          f"年換手 {c['turnover_per_year']:.1f} 次")
    print(f"          累計付出 {c['total']:.1%} 期初本金，"
          f"經複利後拖累總報酬 {c['drag_on_return'] * 100:.1f} 個百分點")

    print("\n========= 成本 vs 回撤改善 權衡 =========")
    print(f"{'避險工具':<22}{'年化成本':>8}{'總報酬':>9}{'最大回撤':>9}"
          f"{'回撤改善':>9}{'報酬讓出':>9}{'保護單價':>9}")
    for r in cost_sweep(sig):
        price = "—" if r["protection_price"] is None else f"{r['protection_price']:.1f}"
        print(f"{r['label']:<22}{r['cost_annual']:>7.1%}{r['total_return']:>8.1f}%"
              f"{r['max_drawdown']:>8.1f}%{r['dd_improvement']:>8.1f}pp"
              f"{r['return_giveup']:>8.1f}pp{price:>9}")
