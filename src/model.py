# -*- coding: utf-8 -*-
"""
LSTM 模型模組
=============
提供：
1. build_lstm_model：多變量、雙輸出 LSTM
   - 迴歸頭 (reg)：預測未來 HORIZON 天的報酬率（標準化後）。
   - 分類頭 (clf)：預測未來「下跌機率」(sigmoid, 0~1)。
2. train_model：封裝訓練流程（含 EarlyStopping）。
3. evaluate_price：把預測報酬還原成未來價格，算 RMSE / MAE。
4. baseline 比較：
   - naive：未來價格 = 今天價格。
   - 單因子 LSTM：只用金價當輸入。
   - 多因子 LSTM：用全部 6 個因子。
   證明多因子模型較佳。
"""

import os
import sys
import numpy as np

# 關掉 TensorFlow 過多的 log；關閉 oneDNN 以降低 run-to-run 浮點數差異（提升可重現性）
os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "3")
os.environ.setdefault("TF_ENABLE_ONEDNN_OPTS", "0")

import tensorflow as tf
from tensorflow.keras import layers, Model, Input, optimizers, callbacks
from sklearn.metrics import roc_auc_score

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from src.preprocessing import prepare_data, inverse_return


def set_seed(seed: int = None):
    """固定亂數種子，讓結果可重現。"""
    seed = seed or config.RANDOM_SEED
    np.random.seed(seed)
    tf.random.set_seed(seed)


# ---------------------------------------------------------------------------
# 類別平衡用的加權交叉熵
# ---------------------------------------------------------------------------
def pos_weight_from(yclf) -> float:
    """由訓練標籤算出『下跌類別』的加權倍率 = 上漲數 / 下跌數。

    下跌是少數類別時 pos_weight > 1，讓模型更重視抓下跌，
    避免分類頭塌縮成永遠猜上漲（只賺基準率）。
    """
    p = max(float(np.mean(yclf)), 1e-6)
    return (1.0 - p) / p


def make_weighted_bce(pos_weight: float):
    """產生一個對『下跌(正類)』加權的 binary cross-entropy 損失。"""
    pw = tf.constant(pos_weight, dtype=tf.float32)

    def loss(y_true, y_pred):
        y_true = tf.cast(y_true, tf.float32)
        y_pred = tf.clip_by_value(y_pred, 1e-7, 1.0 - 1e-7)
        bce = -(pw * y_true * tf.math.log(y_pred)
                + (1.0 - y_true) * tf.math.log(1.0 - y_pred))
        return tf.reduce_mean(bce)

    return loss


# ---------------------------------------------------------------------------
# 模型結構
# ---------------------------------------------------------------------------
def build_lstm_model(n_features: int,
                     lookback: int = None,
                     units: int = None,
                     dropout: float = None,
                     lr: float = None,
                     pos_weight: float = 1.0) -> Model:
    """建立雙輸出多變量 LSTM。

    共享一段 LSTM 特徵萃取，再分出兩個頭：
      - reg 頭：線性輸出，預測標準化報酬（用 Huber loss，對離群值較穩健）。
      - clf 頭：sigmoid 輸出，預測下跌機率（用 binary_crossentropy）。
    """
    lookback = lookback or config.LOOKBACK
    units = units or config.LSTM_UNITS
    dropout = dropout if dropout is not None else config.DROPOUT
    lr = lr or config.LEARNING_RATE

    inp = Input(shape=(lookback, n_features), name="seq_input")
    x = layers.LSTM(units, return_sequences=True)(inp)
    x = layers.Dropout(dropout)(x)
    x = layers.LSTM(units // 2)(x)
    x = layers.Dropout(dropout)(x)
    shared = layers.Dense(32, activation="relu")(x)

    reg_out = layers.Dense(1, name="reg")(shared)                       # 報酬（標準化）
    clf_out = layers.Dense(1, activation="sigmoid", name="clf")(shared) # 下跌機率

    model = Model(inputs=inp, outputs=[reg_out, clf_out])
    model.compile(
        optimizer=optimizers.Adam(learning_rate=lr),
        # clf 用加權 BCE（對下跌類別加權）；reg 用對離群值穩健的 Huber
        loss={"reg": tf.keras.losses.Huber(), "clf": make_weighted_bce(pos_weight)},
        loss_weights={"reg": 1.0, "clf": 3.0},
    )
    return model


# ---------------------------------------------------------------------------
# 訓練
# ---------------------------------------------------------------------------
def train_model(model: Model, data: dict, epochs: int = None,
                batch_size: int = None, verbose: int = 0) -> Model:
    """訓練雙輸出模型。"""
    epochs = epochs or config.EPOCHS
    batch_size = batch_size or config.BATCH_SIZE

    es = callbacks.EarlyStopping(monitor="val_loss", patience=6,
                                 restore_best_weights=True)
    # 類別平衡已透過 build_lstm_model 的加權 BCE 處理（見 pos_weight）。
    model.fit(
        data["X_train"],
        {"reg": data["yreg_train"], "clf": data["yclf_train"]},
        validation_split=0.15,
        epochs=epochs, batch_size=batch_size,
        callbacks=[es], verbose=verbose,
    )
    return model


# ---------------------------------------------------------------------------
# 評估：把預測報酬還原成價格後算誤差
# ---------------------------------------------------------------------------
def _rmse(a, b):
    return float(np.sqrt(np.mean((np.asarray(a) - np.asarray(b)) ** 2)))


def _mae(a, b):
    return float(np.mean(np.abs(np.asarray(a) - np.asarray(b))))


def evaluate_price(model: Model, data: dict) -> dict:
    """用測試集評估『未來價格』的 RMSE / MAE，並回傳分類正確率。"""
    pred_reg_scaled, pred_clf = model.predict(data["X_test"], verbose=0)
    pred_ret = inverse_return(pred_reg_scaled.ravel(), data["target_scaler"])
    pred_price = data["base_test"] * (1.0 + pred_ret)   # 還原成未來價格
    true_price = data["future_test"]

    # 分類評估
    y_true = data["yclf_test"]
    prob = pred_clf.ravel()
    pred_decline = (prob > 0.5).astype(float)
    acc = float(np.mean(pred_decline == y_true))
    # 基準率：永遠猜「多數類別」能拿到的正確率（衡量是否真的有方向判斷力）
    base_rate_acc = float(max(y_true.mean(), 1.0 - y_true.mean()))
    # AUC：不受基準率/門檻影響，衡量『機率排序』能力，>0.5 才算有訊號
    try:
        auc = float(roc_auc_score(y_true, prob))
    except ValueError:
        auc = float("nan")

    return {
        "rmse": _rmse(pred_price, true_price),
        "mae": _mae(pred_price, true_price),
        "decline_acc": acc,
        "base_rate_acc": base_rate_acc,
        "auc": auc,
        "pred_price": pred_price,
        "true_price": true_price,
        "pred_prob_down": prob,
        "dates": data["dates_test"],
    }


def evaluate_naive(data: dict) -> dict:
    """Baseline 1：naive 預測，未來價格 = 今天價格。"""
    pred_price = data["base_test"]            # 直接拿今天當預測
    true_price = data["future_test"]
    return {"rmse": _rmse(pred_price, true_price),
            "mae": _mae(pred_price, true_price)}


# ---------------------------------------------------------------------------
# 三方比較：naive / 單因子 LSTM / 多因子 LSTM
# ---------------------------------------------------------------------------
def compare_baselines(df, verbose: int = 0) -> dict:
    """訓練並比較三個模型的 RMSE / MAE，回傳比較表與多因子模型評估結果。"""
    set_seed()

    # 多因子資料
    data_multi = prepare_data(df, feature_cols=config.FEATURE_COLS)
    # 單因子資料（只有金價）
    data_single = prepare_data(df, feature_cols=["GLD"])

    # Baseline 1：naive
    naive = evaluate_naive(data_multi)

    # Baseline 2：單因子 LSTM
    print("   訓練單因子 LSTM (僅金價) ...")
    m_single = build_lstm_model(n_features=1,
                                pos_weight=pos_weight_from(data_single["yclf_train"]))
    train_model(m_single, data_single, verbose=verbose)
    eval_single = evaluate_price(m_single, data_single)

    # 主模型：多因子 LSTM
    print("   訓練多因子 LSTM (6 因子) ...")
    m_multi = build_lstm_model(n_features=len(config.FEATURE_COLS),
                               pos_weight=pos_weight_from(data_multi["yclf_train"]))
    train_model(m_multi, data_multi, verbose=verbose)
    eval_multi = evaluate_price(m_multi, data_multi)

    table = {
        "naive":        {"rmse": naive["rmse"],        "mae": naive["mae"]},
        "lstm_single":  {"rmse": eval_single["rmse"],  "mae": eval_single["mae"],
                         "decline_acc": eval_single["decline_acc"],
                         "auc": eval_single["auc"]},
        "lstm_multi":   {"rmse": eval_multi["rmse"],   "mae": eval_multi["mae"],
                         "decline_acc": eval_multi["decline_acc"],
                         "auc": eval_multi["auc"],
                         "base_rate_acc": eval_multi["base_rate_acc"]},
    }
    return {"table": table, "eval_multi": eval_multi,
            "model_multi": m_multi, "data_multi": data_multi}


if __name__ == "__main__":
    from src.data_collection import load_dataset
    df = load_dataset()
    print("開始三方比較 ...")
    res = compare_baselines(df, verbose=0)
    print("\n========= RMSE / MAE 比較 (未來價格, 越小越好) =========")
    for name, m in res["table"].items():
        extra = ""
        if "decline_acc" in m:
            extra += f" | 下跌正確率={m['decline_acc']:.3f}"
        if "auc" in m:
            extra += f" | AUC={m['auc']:.3f}"
        if "base_rate_acc" in m:
            extra += f" | (基準率={m['base_rate_acc']:.3f})"
        print(f"  {name:12s}  RMSE={m['rmse']:.3f}  MAE={m['mae']:.3f}{extra}")
