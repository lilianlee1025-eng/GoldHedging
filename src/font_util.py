# -*- coding: utf-8 -*-
"""
中文字型工具
============
讓 matplotlib 畫圖時能正常顯示中文，避免出現方框 (tofu)。

策略（依序嘗試）：
1. 專案內建字型 data/fonts/NotoSansCJKtc-Regular.otf（建議，最穩定）。
2. 系統已安裝的常見 CJK 字型。
3. 都找不到 → 回傳 False，呼叫端可改用英文標籤。
"""

import os
import sys
import matplotlib
import matplotlib.font_manager as fm

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

# 內建字型路徑
BUNDLED_FONT = os.path.join(config.DATA_DIR, "fonts", "NotoSansCJKtc-Regular.otf")

# 系統可能存在的 CJK 字型名稱
_SYSTEM_CJK = [
    "Noto Sans CJK TC", "Noto Sans CJK SC", "Microsoft JhengHei",
    "Microsoft YaHei", "PingFang TC", "Heiti TC", "SimHei",
    "WenQuanYi Zen Hei", "Source Han Sans TW",
]


def setup_chinese_font() -> bool:
    """設定 matplotlib 中文字型。成功回傳 True，否則 False。"""
    # 1) 內建字型
    if os.path.exists(BUNDLED_FONT):
        fm.fontManager.addfont(BUNDLED_FONT)
        name = fm.FontProperties(fname=BUNDLED_FONT).get_name()
        matplotlib.rcParams["font.family"] = name
        matplotlib.rcParams["axes.unicode_minus"] = False  # 負號正常顯示
        return True

    # 2) 系統字型
    available = {f.name for f in fm.fontManager.ttflist}
    for cand in _SYSTEM_CJK:
        if cand in available:
            matplotlib.rcParams["font.family"] = cand
            matplotlib.rcParams["axes.unicode_minus"] = False
            return True

    # 3) 找不到
    matplotlib.rcParams["axes.unicode_minus"] = False
    return False
