# -*- coding: utf-8 -*-
"""
資料探索與視覺化模組
====================
在進入模型之前，先確認資料抓得對、畫得出來。
產生兩張圖存到 outputs/：
1. features_overview.png：六個因子各自的時間序列。
2. correlation_heatmap.png：各因子「日報酬」的相關係數熱圖。
"""

import os
import sys
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")   # 無視窗環境也能存圖
import matplotlib.pyplot as plt

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from src.data_collection import load_dataset
from src.font_util import setup_chinese_font

setup_chinese_font()   # 啟用中文字型，避免圖中出現方框


def plot_features(df: pd.DataFrame) -> str:
    """畫出六個因子的時間序列，各自一個子圖。"""
    cols = config.FEATURE_COLS
    fig, axes = plt.subplots(len(cols), 1, figsize=(12, 14), sharex=True)
    titles = {
        "GLD": "黃金 ETF (GLD)",
        "DGS10": "10年期公債殖利率 (DGS10)",
        "CPI": "消費者物價指數 (CPI, 已延後公布日)",
        "DXY": "美元指數 (DXY)",
        "SP500": "S&P 500",
        "VIX": "恐慌指數 (VIX)",
    }
    for ax, col in zip(axes, cols):
        ax.plot(df.index, df[col], linewidth=0.8)
        ax.set_title(titles.get(col, col), fontsize=10)
        ax.grid(alpha=0.3)
    axes[-1].set_xlabel("日期")
    fig.suptitle("影響金價的總經因子總覽 (2010~)", fontsize=13)
    fig.tight_layout(rect=[0, 0, 1, 0.99])
    path = os.path.join(config.OUTPUT_DIR, "features_overview.png")
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return path


def plot_correlation(df: pd.DataFrame) -> str:
    """畫出各因子『日報酬率』的相關係數熱圖。

    用報酬率而非原始價格算相關，才能反映真正的同向 / 反向關係
    （原始價格因為都有長期趨勢，相關係數會被高估）。
    """
    returns = df.pct_change().dropna()
    corr = returns.corr()

    fig, ax = plt.subplots(figsize=(7, 6))
    im = ax.imshow(corr, cmap="coolwarm", vmin=-1, vmax=1)
    ax.set_xticks(range(len(corr.columns)))
    ax.set_yticks(range(len(corr.columns)))
    ax.set_xticklabels(corr.columns, rotation=45, ha="right")
    ax.set_yticklabels(corr.columns)
    # 在每格標上數值
    for i in range(len(corr.columns)):
        for j in range(len(corr.columns)):
            ax.text(j, i, f"{corr.iloc[i, j]:.2f}",
                    ha="center", va="center", fontsize=9)
    fig.colorbar(im, ax=ax, fraction=0.046, pad=0.04)
    ax.set_title("各因子日報酬相關係數")
    fig.tight_layout()
    path = os.path.join(config.OUTPUT_DIR, "correlation_heatmap.png")
    fig.savefig(path, dpi=110)
    plt.close(fig)
    return path


def main():
    df = load_dataset()
    print(f"資料形狀：{df.shape}")
    print(f"區間：{df.index.min().date()} ~ {df.index.max().date()}")
    print("\n缺值檢查（應全為 0）：")
    print(df.isna().sum())

    p1 = plot_features(df)
    p2 = plot_correlation(df)
    print(f"\n已輸出圖檔：\n - {p1}\n - {p2}")

    # 印出與金價報酬最相關的因子，快速 sanity check
    rets = df.pct_change().dropna()
    print("\n各因子與『金價日報酬』的相關係數：")
    print(rets.corr()["GLD"].sort_values(ascending=False))


if __name__ == "__main__":
    main()
