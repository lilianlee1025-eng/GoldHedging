# -*- coding: utf-8 -*-
"""
每日更新腳本（輕量版，給排程用）
================================
每天自動跑這支即可，把「最新資料、最新預測、K 棒、計價單位、更新時間」更新到前端。

做的事（約 3~5 分鐘）：
1. 重新從 Yahoo / FRED 抓最新資料並對齊。
2. 重新訓練（三方比較 + 未來預測），更新 outputs/predictions.json。
3. 重新產生 frontend/ 的設計檔 JSON（含日/周/月/季 K 棒、計價單位、資料更新時間）。

刻意「不重跑 walk-forward 回測」（那是歷史驗證，30 分鐘且每天結果幾乎不變）。
若要連回測一起更新，請改跑完整的 `python main.py`。
"""

import sys
from src.data_collection import build_dataset
from src.model import compare_baselines
from src.output_json import forecast_future, save_predictions_json
from src.design_export import export as export_design_json


def main():
    print("[每日更新 1/4] 重新抓取並對齊資料 ...")
    df = build_dataset(save=True)

    print("[每日更新 2/4] 重新訓練模型（三方比較）...")
    compare_res = compare_baselines(df, verbose=0)

    print("[每日更新 3/4] 預測未來走勢，更新 predictions.json ...")
    future = forecast_future(df)
    j1 = save_predictions_json(df, compare_res, future)

    print("[每日更新 4/4] 產生前端設計檔 JSON（含 K 棒/單位/時間）...")
    f1, f2 = export_design_json()

    print("完成：")
    print("  ", j1)
    print("  ", f1)
    print("  ", f2)
    print(f"  最新金價 {future['current_price']}（資料截至 {future['current_date']}），"
          f"下跌機率 {future['prob_down']:.0%}")


if __name__ == "__main__":
    sys.exit(main())
