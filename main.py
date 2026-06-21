# -*- coding: utf-8 -*-
"""
主程式：一鍵跑完整個 pipeline
==============================
流程：
  1. 蒐集 + 對齊資料（含 CPI 公布日延遲處理）。
  2. 畫探索圖（確認資料正確）。
  3. 三方比較：naive / 單因子 LSTM / 多因子 LSTM 的 RMSE / MAE / AUC。
  4. 用最新資料預測未來金價與下跌機率。
  5. Walk-forward 回測：有避險 vs 無避險。
  6. 輸出 predictions.json 與 backtest.json。

用法：
  python main.py            # 完整流程
  python main.py --quick    # 快速模式（回測步長加大，較快跑完，供 demo）
"""

import argparse
import sys

import config
from src.data_collection import build_dataset, load_dataset
from src.explore import plot_features, plot_correlation
from src.model import compare_baselines
from src.backtest import walk_forward, run_strategy
from src.output_json import forecast_future, save_predictions_json, save_backtest_json
from src.design_export import export as export_design_json


def main(quick: bool = False, refresh: bool = False):
    print("=" * 60)
    print("黃金避險專題：資料與模型 pipeline")
    print("=" * 60)

    # 1) 資料
    print("\n[步驟 1] 蒐集與對齊資料")
    df = build_dataset(save=True) if refresh else load_dataset()

    # 2) 探索圖
    print("\n[步驟 2] 產生探索圖")
    p1 = plot_features(df)
    p2 = plot_correlation(df)
    print(f"   圖檔：{p1}\n        {p2}")

    # 3) 三方比較
    print("\n[步驟 3] 訓練並比較 naive / 單因子 / 多因子 LSTM")
    compare_res = compare_baselines(df, verbose=0)
    print("\n   RMSE / MAE / AUC 比較：")
    for name, m in compare_res["table"].items():
        extra = ""
        if "auc" in m:
            extra += f" | AUC={m['auc']:.3f}"
        if "decline_acc" in m:
            extra += f" | 下跌正確率={m['decline_acc']:.3f}"
        if "base_rate_acc" in m:
            extra += f" | (基準率={m['base_rate_acc']:.3f})"
        print(f"   {name:12s} RMSE={m['rmse']:.3f} MAE={m['mae']:.3f}{extra}")

    # 4) 未來預測
    print("\n[步驟 4] 預測未來走勢與下跌機率")
    future = forecast_future(df)
    print(f"   {future['current_date']} 金價={future['current_price']} → "
          f"{future['future_date']} 預測={future['predicted_price']} "
          f"(下跌機率={future['prob_down']:.1%})")

    # 5) 回測
    print("\n[步驟 5] Walk-forward 回測（有避險 vs 無避險）")
    step = config.WF_STEP * 2 if quick else config.WF_STEP
    signals = walk_forward(df, step=step, verbose=True)
    strategy = run_strategy(signals)
    print("\n   不避險：", {k: round(v, 4) for k, v in strategy["stats_nohedge"].items()})
    print("   避險：  ", {k: round(v, 4) for k, v in strategy["stats_hedge"].items()})

    # 6) 輸出 JSON
    print("\n[步驟 6] 輸出 JSON")
    j1 = save_predictions_json(df, compare_res, future)
    j2 = save_backtest_json(signals, strategy)
    print(f"   {j1}\n   {j2}")

    # 7) 轉成前端設計檔（Gold Hedge System）所需的 JSON
    print("\n[步驟 7] 產生前端設計檔資料")
    f1, f2 = export_design_json()
    print(f"   {f1}\n   {f2}")

    print("\n完成！")
    print("  · 原生 JSON：outputs/predictions.json、outputs/backtest.json")
    print("  · 前端介面：frontend/index.html（讀 frontend/predictions.json、backtest.json）")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true", help="快速模式（回測步長加大）")
    ap.add_argument("--refresh", action="store_true", help="重新從網路抓資料")
    args = ap.parse_args()
    main(quick=args.quick, refresh=args.refresh)
