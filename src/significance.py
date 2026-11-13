# -*- coding: utf-8 -*-
"""
統計顯著性檢定（移動區塊自助法）
================================
回答一個問題：回測看到的差異，有多少可能只是運氣？

為什麼不能直接套一般的檢定
--------------------------
預測期間是 30 個交易日，但訊號每天都產生一次，所以相鄰兩天的「未來視窗」
重疊了 29/30 天。樣本之間高度自我相關，有效樣本數遠小於看起來的四千多筆。
一般的 t 檢定、或逐點隨機重抽的 bootstrap，都假設樣本彼此獨立——用在這裡
會把信賴區間算得太窄，讓結論看起來比實際上更可靠。

解法：移動區塊自助法（moving block bootstrap）
----------------------------------------------
把整段時間切成長度 L 的「連續區塊」再重抽，區塊內部的順序與相關性都保留下來。
L 必須明顯大於預測期間，否則重疊造成的相關性還是會被切斷。
預設 L = 120 個交易日（約半年），是預測期間的 4 倍。

檢定四件事
----------
1. AUC 是否真的大於 0.5      → 模型到底有沒有方向判斷力
2. 避險效率 HE 是否真的大於 0 → 避險有沒有真的降低波動
3. 最大回撤是否真的變淺
4. 讓出多少報酬

前三項只要 95% 信賴區間包含「沒有效果」那個值（AUC 的 0.5、HE 的 0、回撤的 0），
就不能宣稱有效。

注意：自助法的 p 值是近似值，不是精確檢定；它衡量的是「在這段歷史的統計特性下，
觀察到的結果有多容易單靠運氣出現」。
"""

import os
import sys

import numpy as np
from sklearn.metrics import roc_auc_score

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from src.backtest import load_signals, _hedge_ratio, _apply_costs, _max_drawdown

BLOCK_LEN = 120      # 區塊長度（交易日）；需明顯大於 HORIZON
N_BOOT = 2000        # 自助重抽次數
SEED = 42


# ---------------------------------------------------------------------------
# 自助法核心
# ---------------------------------------------------------------------------
def _block_index(n: int, L: int, rng) -> np.ndarray:
    """產生一組長度 n 的重抽索引。

    隨機挑 ceil(n/L) 個起點，每個起點往後取 L 天連續資料接起來，再截到 n。
    這樣重抽出來的序列，局部的自我相關結構跟原始序列相近。
    """
    k = int(np.ceil(n / L))
    starts = rng.integers(0, n - L + 1, size=k)
    return np.concatenate([np.arange(s, s + L) for s in starts])[:n]


def _summarise(obs: float, boots: np.ndarray, null_value: float) -> dict:
    """把自助分布整理成：觀察值、95% 信賴區間、雙尾 p 值、方向。

    verdict 三種：
      "above"  信賴區間整段在虛無值之上 → 顯著為正
      "below"  信賴區間整段在虛無值之下 → 顯著為負
      "none"   區間跨過虛無值           → 不顯著

    注意一定要分「顯著為負」而不是只說「不顯著」：避險的報酬差就是典型例子，
    它穩定地低於 0（確實會少賺），這是一個明確的結論，不是沒有結論。
    """
    lo, hi = np.percentile(boots, [2.5, 97.5])
    # 雙尾 p：自助分布落在虛無值較少的那一側的比例 × 2
    side = min(np.mean(boots <= null_value), np.mean(boots >= null_value))
    p = float(min(1.0, 2.0 * side))
    verdict = "above" if lo > null_value else ("below" if hi < null_value else "none")
    return {
        "value": float(obs), "ci_low": float(lo), "ci_high": float(hi),
        "p": p, "verdict": verdict, "significant": verdict != "none",
    }


# ---------------------------------------------------------------------------
# 檢定 1：AUC 是否大於 0.5
# ---------------------------------------------------------------------------
def test_auc(price: np.ndarray, prob: np.ndarray, horizon: int,
             L: int = BLOCK_LEN, B: int = N_BOOT, seed: int = SEED) -> dict:
    """用 walk-forward 的每日訊號檢定「下跌機率」的排序能力。

    y_true 的定義跟訓練時完全一致：horizon 天後的收盤價低於今天 → 1（下跌）。
    最後 horizon 天沒有答案，必須丟掉，否則就是在用還沒發生的事當答案。
    """
    n = len(price) - horizon
    y = (price[horizon:] < price[:n]).astype(float)
    s = prob[:n]

    obs = roc_auc_score(y, s)
    rng = np.random.default_rng(seed)
    boots = []
    for _ in range(B):
        i = _block_index(n, L, rng)
        yy = y[i]
        if yy.min() == yy.max():      # 重抽到全漲或全跌，AUC 無定義，跳過
            continue
        boots.append(roc_auc_score(yy, s[i]))
    boots = np.array(boots)

    out = _summarise(obs, boots, 0.5)
    out.update({"n": int(n), "n_blocks": int(np.ceil(n / L)),
                "down_rate": float(y.mean()), "n_boot_ok": int(len(boots))})
    return out


# ---------------------------------------------------------------------------
# 檢定 2~4：避險效果
# ---------------------------------------------------------------------------
def _one_side(r_u: np.ndarray, r_h: np.ndarray) -> tuple:
    """同一段報酬序列下，避險相對不避險的三個效果量。"""
    eq_u = np.cumprod(1.0 + r_u)
    eq_h = np.cumprod(1.0 + r_h)
    n = len(r_u)
    # 避險效率（Ederington 1979）：避險後把報酬變異數降低了幾成
    var_u = np.var(r_u)
    he = 1.0 - np.var(r_h) / var_u if var_u > 0 else np.nan
    # 回撤改善：正值代表回撤變淺
    dmdd = _max_drawdown(eq_h) - _max_drawdown(eq_u)
    # 年化報酬差：用年化而不是總報酬，因為總報酬經過複利後尾巴極長，不好讀
    ann = lambda eq: (eq[-1]) ** (252.0 / n) - 1.0
    dann = ann(eq_h) - ann(eq_u)
    return he, dmdd, dann


def test_hedge(ret: np.ndarray, prob: np.ndarray, threshold: float,
               cost_annual: float, tc_oneway: float,
               L: int = BLOCK_LEN, B: int = N_BOOT, seed: int = SEED) -> dict:
    """檢定避險效果，並且額外回答一個更關鍵的問題：訊號本身有沒有價值。

    為什麼需要「固定比例避險」這個對照組
    ------------------------------------
    只要把曝險降低，報酬變異數一定會跟著降——這是算術，不是模型的功勞。
    所以「避險效率 > 0」幾乎必然成立，單看它會高估模型的價值。

    真正該問的是：同樣平均只持有這麼多曝險，但完全不看訊號、每天都用固定比例，
    結果會差多少？兩者的差距才是「模型判斷時機」這件事的貢獻。

    配對重抽：每次重抽都用同一組索引套在三條序列（不避險／依訊號／固定比例）上，
    算出來的差異才是同一段模擬歷史裡的差異。
    """
    h_sig = _hedge_ratio(prob, threshold)
    h_con = np.full_like(h_sig, float(h_sig.mean()))   # 同樣的平均曝險，但不看訊號
    net_sig, _, _ = _apply_costs(ret, h_sig, cost_annual, tc_oneway)
    net_con, _, _ = _apply_costs(ret, h_con, cost_annual, tc_oneway)

    def triple(i):
        a = _one_side(ret[i], net_sig[i])
        b = _one_side(ret[i], net_con[i])
        return a, b

    idx0 = np.arange(len(ret))
    o_sig, o_con = triple(idx0)

    n = len(ret)
    rng = np.random.default_rng(seed)
    bs = {"sig": [[], [], []], "con": [[], [], []], "diff": [[], [], []]}
    for _ in range(B):
        i = _block_index(n, L, rng)
        a, b = triple(i)
        for k in range(3):
            bs["sig"][k].append(a[k])
            bs["con"][k].append(b[k])
            bs["diff"][k].append(a[k] - b[k])

    names = ["hedging_effectiveness", "drawdown_improvement", "annual_return_difference"]
    out = {"n": int(n), "n_blocks": int(np.ceil(n / L)),
           "avg_hedge_ratio": float(h_sig.mean())}
    for k, name in enumerate(names):
        out[name] = _summarise(o_sig[k], np.array(bs["sig"][k]), 0.0)
        out[name + "_const"] = _summarise(o_con[k], np.array(bs["con"][k]), 0.0)
        # 訊號 − 固定比例：>0 才代表「看訊號挑時機」真的有加分
        out[name + "_vs_const"] = _summarise(
            o_sig[k] - o_con[k], np.array(bs["diff"][k]), 0.0)
    return out


# ---------------------------------------------------------------------------
def run(L: int = BLOCK_LEN, B: int = N_BOOT) -> dict:
    sig = load_signals()
    if sig is None:
        raise SystemExit("找不到 walk-forward 訊號快取，請先跑 python main.py")

    price = sig["price"].values.astype(float)
    prob = sig["prob_down"].values.astype(float)
    ret = sig["ret_1d"].values.astype(float)

    auc = test_auc(price, prob, config.HORIZON, L, B)
    hedge = test_hedge(ret, prob, config.HEDGE_PROB_THRESHOLD,
                       config.HEDGE_COST_ANNUAL, config.HEDGE_TC_ONEWAY, L, B)
    return {
        "method": "moving block bootstrap",
        "block_len": L, "n_boot": B, "horizon": config.HORIZON,
        "period": f"{sig.index.min().date()} ~ {sig.index.max().date()}",
        "auc": auc, "hedge": hedge,
    }


def _dump(r: dict) -> list:
    """寫到 outputs/（原始輸出）與 docs/（網頁讀的那份），兩邊數字一定一致。"""
    import json
    paths = [os.path.join(config.JSON_DIR, "significance.json"),
             os.path.join(config.BASE_DIR, "docs", "significance.json")]
    for path in paths:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(r, f, ensure_ascii=False, indent=2)
    return paths


def save(**kw) -> list:
    """跑完檢定並存檔，供書面報告與網頁引用（數字只算一次，不會前後不一致）。"""
    return _dump(run(**kw))


_MARK = {"above": "✅ 顯著為正", "below": "🔻 顯著為負", "none": "❌ 不顯著"}


def _line(name: str, d: dict, pct: bool = False) -> str:
    k, u = (100.0, "pp") if pct else (1.0, "")
    return (f"  {name:<22}{d['value'] * k:>9.3f}{u:<2}  "
            f"95% CI [{d['ci_low'] * k:>8.3f}, {d['ci_high'] * k:>8.3f}]{u:<2}  "
            f"p={d['p']:.3f}  {_MARK[d['verdict']]}")


if __name__ == "__main__":
    r = run()
    a, hg = r["auc"], r["hedge"]
    print("=" * 92)
    print("統計顯著性檢定 — 移動區塊自助法")
    print("=" * 92)
    print(f"期間 {r['period']}｜預測期間 {r['horizon']} 個交易日")
    print(f"樣本 {a['n']:,} 天，但相鄰樣本的未來視窗重疊 {r['horizon'] - 1}/{r['horizon']}，"
          f"實際上只有約 {a['n_blocks']} 個獨立區塊")
    print(f"區塊長度 {r['block_len']} 天，重抽 {r['n_boot']:,} 次")
    print()
    print(f"【1】模型方向判斷力　（實際下跌比例 {a['down_rate']:.1%}，虛無值 AUC=0.5）")
    print(_line("AUC", a))
    print()
    print(f"【2】避險效果 vs 不避險　（平均曝險降低 {hg['avg_hedge_ratio']:.1%}，虛無值 0）")
    print(_line("避險效率 HE", hg["hedging_effectiveness"], True))
    print(_line("最大回撤改善", hg["drawdown_improvement"], True))
    print(_line("年化報酬差", hg["annual_return_difference"], True))
    print()
    print("【3】訊號有沒有價值　（對照組：同樣平均曝險、但完全不看訊號的固定比例避險）")
    print(_line("避險效率 HE（固定）", hg["hedging_effectiveness_const"], True))
    print(_line("　→ 訊號 − 固定", hg["hedging_effectiveness_vs_const"], True))
    print(_line("回撤改善（固定）", hg["drawdown_improvement_const"], True))
    print(_line("　→ 訊號 − 固定", hg["drawdown_improvement_vs_const"], True))
    print(_line("年化報酬差（固定）", hg["annual_return_difference_const"], True))
    print(_line("　→ 訊號 − 固定", hg["annual_return_difference_vs_const"], True))
    print()
    print("讀法：")
    print("  ・【2】只說明「降低曝險有沒有降低風險」——降低曝險本來就會降風險，不算模型的功勞。")
    print("  ・【3】才是模型的真正價值：同樣的平均曝險下，看訊號挑時機有沒有贏過固定比例。")

    for out in _dump(r):
        print(f"已存檔：{out}")
