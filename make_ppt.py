# -*- coding: utf-8 -*-
"""產生專題進度簡報（9 頁，16:9）。數字一律從 docs/*.json 讀，不手寫。

用法：python make_ppt.py  →  outputs/專題進度報告.pptx
資料更新後重跑即可，簡報上的數字會跟著更新。
"""
import json, copy
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE
from lxml import etree

C = dict(gold=RGBColor(0xC8,0xA9,0x51), green=RGBColor(0x1E,0x8C,0x66),
         red=RGBColor(0xC0,0x47,0x3E), dark=RGBColor(0x26,0x30,0x2B),
         grey=RGBColor(0x7A,0x84,0x7E), light=RGBColor(0xF2,0xF3,0xF2),
         white=RGBColor(0xFF,0xFF,0xFF), mint=RGBColor(0xE2,0xF0,0xEA),
         blush=RGBColor(0xF4,0xE4,0xE2), line=RGBColor(0xE4,0xE7,0xE5))
FONT = "微軟正黑體"          # Windows 內建正體中文；Mac 會自動退回系統字型

prs = Presentation()
prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
BLANK = prs.slide_layouts[6]
W = 13.333


def _ea(run, name):
    """python-pptx 只設 latin 字型，中文要另外補 <a:ea>，否則 PowerPoint 會用預設字。"""
    rPr = run._r.get_or_add_rPr()
    ns = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
    for tag in ("ea", "cs"):
        el = rPr.find(ns + tag)
        if el is None:
            el = etree.SubElement(rPr, ns + tag)
        el.set("typeface", name)


def text(slide, x, y, w, h, runs, size=18, color="dark", bold=False,
         align=PP_ALIGN.LEFT, spacing=1.25, anchor=MSO_ANCHOR.TOP):
    """runs 可以是字串，或 [(文字, {size/color/bold}), ...] 讓同一行混色。"""
    tb = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    lines = runs if isinstance(runs, list) else [runs]
    for i, line in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.line_spacing = spacing
        parts = line if isinstance(line, list) else [(line, {})]
        for s, opt in parts:
            r = p.add_run(); r.text = s
            f = r.font
            f.size = Pt(opt.get("size", size)); f.bold = opt.get("bold", bold)
            f.color.rgb = C[opt.get("color", color)]; f.name = FONT
            _ea(r, FONT)
    return tb


def card(slide, x, y, w, h, fill="white", edge="line", radius=0.06):
    sh = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE,
                                Inches(x), Inches(y), Inches(w), Inches(h))
    sh.adjustments[0] = radius
    sh.fill.solid(); sh.fill.fore_color.rgb = C[fill]
    if edge:
        sh.line.color.rgb = C[edge]; sh.line.width = Pt(1)
    else:
        sh.line.fill.background()
    sh.shadow.inherit = False
    sh.text_frame.text = ""
    return sh


def slide_head(kicker, title, sub=None):
    s = prs.slides.add_slide(BLANK)
    bar = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.9), Inches(0.62),
                             Inches(0.055), Inches(0.62))
    bar.fill.solid(); bar.fill.fore_color.rgb = C["gold"]; bar.line.fill.background()
    bar.shadow.inherit = False
    text(s, 1.15, 0.6, 10, 0.3, kicker, size=12, color="grey")
    text(s, 1.15, 0.86, 11.5, 0.5, title, size=27, bold=True)
    if sub:
        text(s, 1.15, 1.5, 11, 0.4, sub, size=14, color="grey")
    return s


pred = json.load(open("docs/predictions.json", encoding="utf-8"))
bt = json.load(open("docs/backtest.json", encoding="utf-8"))
m, bm = pred["metrics"], bt["metrics"]

# ===================== 1. 封面 =====================
s = prs.slides.add_slide(BLANK)
bg = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, prs.slide_width, prs.slide_height)
bg.fill.solid(); bg.fill.fore_color.rgb = C["dark"]; bg.line.fill.background()
bg.shadow.inherit = False
band = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(1.4), Inches(2.5),
                          Inches(0.07), Inches(0.75))
band.fill.solid(); band.fill.fore_color.rgb = C["gold"]; band.line.fill.background()
band.shadow.inherit = False
text(s, 1.4, 1.75, 10, 0.4, "專題進度報告", size=15, color="gold")
text(s, 1.72, 2.42, 11, 1.0, "黃金避險決策系統", size=44, bold=True, color="white")
text(s, 1.72, 3.45, 11, 0.8,
     "用多變量 LSTM 預測金價下跌機率，換算成避險建議，並用歷史資料驗證它划不划算",
     size=16, color="light")
text(s, 1.4, 5.5, 11, 1.2, [
    [("網站已上線　", {"color": "gold"}),
     ("lilianlee1025-eng.github.io/GoldHedging", {"color": "white"})],
    [(f"資料截至 {pred['data_as_of']}　·　每日自動更新", {"color": "grey"})],
], size=13)

# ===================== 2. 我們在做什麼 =====================
s = slide_head("01　專題定位", "我們在解決什麼問題？")
card(s, 0.9, 2.05, 11.55, 1.15, fill="light", edge=None)
text(s, 1.3, 2.35, 10.9, 0.6,
     "「我手上有黃金，現在該不該避險？該避多少？」", size=21, bold=True)
rows = [("1", "預測", "用 6 個總經因子訓練 LSTM，算出未來 5 天的「下跌機率」"),
        ("2", "決策", "把機率換算成具體避險建議：避多少比例、用哪種工具"),
        ("3", "驗證", "用 2008～2026 的真實資料回測，證明這套訊號到底有沒有用")]
for i, (n, t, d) in enumerate(rows):
    y = 3.6 + i * 1.1
    dot = s.shapes.add_shape(MSO_SHAPE.OVAL, Inches(1.0), Inches(y + 0.06),
                             Inches(0.42), Inches(0.42))
    dot.fill.solid(); dot.fill.fore_color.rgb = C["gold"]; dot.line.fill.background()
    dot.shadow.inherit = False
    text(s, 1.0, y + 0.13, 0.42, 0.3, n, size=14, bold=True,
         color="white", align=PP_ALIGN.CENTER)
    text(s, 1.65, y + 0.02, 1.3, 0.4, t, size=17, bold=True, color="green")
    text(s, 3.0, y + 0.05, 9.3, 0.5, d, size=15, color="dark")

# ===================== 3. 系統怎麼運作 =====================
s = slide_head("02　系統架構", "資料怎麼變成網頁上的建議",
               "整條流程全自動，每天早上自己重跑一次")
steps = [("資料蒐集", "yfinance + FRED\n6 個因子對齊", "gold"),
         ("LSTM 模型", "預測 5 日報酬\n＋下跌機率", "green"),
         ("回測驗證", "Walk-forward\n4,659 個交易日", "green"),
         ("網站呈現", "五個分頁\nGitHub Pages", "gold")]
bw, gap = 2.62, 0.42
x0 = (W - (bw * 4 + gap * 3)) / 2
for i, (t, d, col) in enumerate(steps):
    x = x0 + i * (bw + gap)
    card(s, x, 2.7, bw, 1.75)
    bar = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(2.7),
                             Inches(bw), Inches(0.075))
    bar.fill.solid(); bar.fill.fore_color.rgb = C[col]; bar.line.fill.background()
    bar.shadow.inherit = False
    text(s, x + 0.25, 3.0, bw - 0.5, 0.4, t, size=17, bold=True)
    text(s, x + 0.25, 3.55, bw - 0.5, 0.8, d.split("\n"), size=13, color="grey")
    if i < 3:
        text(s, x + bw + 0.02, 3.32, gap, 0.4, "→", size=20,
             color="gold", align=PP_ALIGN.CENTER)
card(s, x0, 5.0, bw * 4 + gap * 3, 1.25, fill="mint", edge=None)
text(s, x0 + 0.45, 5.28, bw * 4 + gap * 3 - 0.9, 0.8, [
    [("六個因子：", {"bold": True, "color": "green"}),
     ("金價(GC=F)、10年期公債殖利率、CPI、美元指數、S&P 500、VIX", {"color": "dark"})],
    [("網站沒有後端 —— 只讀兩個 JSON 檔，所以純靜態就能免費掛在 GitHub Pages 上",
      {"color": "grey", "size": 13})],
], size=14)

# ===================== 4. 網站五大功能 =====================
s = slide_head("03　功能總覽", "網站做了哪五個功能")
feats = [("儀表板", "金價走勢 ＋ LSTM 預測線 ＋ 未來 5 日、下跌機率、避險建議。可切換計價單位（美元/盎司、台幣/公克、GLD）、時間單位（日週月季）、折線/K棒", "gold"),
         ("避險模擬器", "輸入自己實際持有的部位（金條、存摺、ETF、金幣，可多筆），選風險偏好，算出該避多少、期貨/Put/Collar 各自損益", "green"),
         ("期貨 vs 期權原理", "互動損益圖：期貨是「鎖死」，保護性賣權是「保留上漲、付權利金買保險」", "gold"),
         ("回測結果", "2008～2026 有避險 vs 無避險淨值曲線、7 個歷史事件情境，以及本週新增的避險成本分析", "green"),
         ("模型說明", "LSTM 架構、六個輸入因子、naive/單因子/多因子三方績效比較", "gold")]
for i, (t, d, col) in enumerate(feats):
    y = 2.05 + i * 1.02
    card(s, 0.9, y, 11.55, 0.88, fill="white")
    bar = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.9), Inches(y + 0.14),
                             Inches(0.05), Inches(0.6))
    bar.fill.solid(); bar.fill.fore_color.rgb = C[col]; bar.line.fill.background()
    bar.shadow.inherit = False
    text(s, 1.2, y + 0.12, 2.35, 0.4, f"{i+1}.  {t}", size=16, bold=True)
    text(s, 3.6, y + 0.13, 8.6, 0.62, d, size=12.5, color="grey", spacing=1.15)

# ===================== 5. 個人化 =====================
s = slide_head("04　個人化", "讓它變成「你的」避險系統，而不是一份通用報告",
               "這一層是把「模型」變成「決策系統」的關鍵")
blocks = [("風險偏好", "green", [
              "保守：下跌機率過 40% 就避險",
              "穩健：過 50% 才避險（多數人）",
              "積極：過 60% 才避險，保留上漲",
              "三個門檻對齊敏感度分析，每個偏好都能",
              "秀出它在 2008～2026 的真實回測績效"]),
          ("多筆部位", "gold", [
              "台灣人常同時持有多種形式，各自單位不同：",
              "金條／金塊 → 台錢　　黃金存摺 → 公克",
              "黃金 ETF → GLD 股　　金幣 → 盎司",
              "內部統一換算成金衡盎司計算",
              "（1 台錢 = 3.75 公克 = 0.1206 盎司）"]),
          ("記住你的設定", "green", [
              "計價單位、時間單位、圖表類型、持有量單位",
              "都會記住，重新整理不會歸零",
              "未登入 → 存瀏覽器 localStorage",
              "登入後 → 同步到雲端，換手機電腦都看得到",
              "登入時比對時間戳，誰新用誰"])]
bw2 = 3.72; gap2 = 0.3
x0 = (W - (bw2 * 3 + gap2 * 2)) / 2
for i, (t, col, items) in enumerate(blocks):
    x = x0 + i * (bw2 + gap2)
    card(s, x, 2.05, bw2, 3.05)
    bar = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(2.05),
                             Inches(bw2), Inches(0.075))
    bar.fill.solid(); bar.fill.fore_color.rgb = C[col]; bar.line.fill.background()
    bar.shadow.inherit = False
    text(s, x + 0.3, 2.3, bw2 - 0.6, 0.4, t, size=18, bold=True)
    for j, it in enumerate(items):
        text(s, x + 0.3, 2.85 + j * 0.42, bw2 - 0.55, 0.38, it, size=11.5,
             color="grey", spacing=1.1)
card(s, x0, 5.35, bw2 * 3 + gap2 * 2, 1.5, fill="mint", edge=None)
text(s, x0 + 0.45, 5.6, bw2 * 3 + gap2 * 2 - 0.9, 1.0, [
    [("資料庫設計：", {"bold": True, "color": "green"}),
     ("為了支援多筆部位，把資料正規化成三張表並畫了完整 ERD", {"color": "dark"})],
    [("profiles（風險偏好與避險參數）　·　positions（部位，1:N）　·　ui_prefs（顯示偏好）",
      {"color": "dark", "size": 13})],
    [("每張表都開 Row Level Security，政策限定 auth.uid() = user_id，每個人只能讀寫自己那一列",
      {"color": "grey", "size": 12})],
], size=13.5)

# ===================== 6. 功能亮點 =====================
s = slide_head("05　功能亮點", "兩個花最多心力的功能")
card(s, 0.9, 2.05, 5.65, 4.4)
text(s, 1.3, 2.35, 5.0, 0.4, "避險模擬器", size=20, bold=True, color="green")
text(s, 1.3, 2.85, 5.0, 0.35, "把「該避險」變成看得懂的錢", size=13, color="grey")
for i, t in enumerate(["支援多筆部位（金條／存摺／ETF／金幣）",
                       "三種風險偏好：保守 40% ／ 穩健 50% ／ 積極 60%",
                       "四種持有單位：盎司／公克／台錢／GLD 股",
                       "Black–Scholes 計算期貨、Put、Collar 損益",
                       "下跌情境曝險表：跌 5%／10%／15% 各賠多少",
                       "登入後部位設定同步雲端，換裝置也看得到"]):
    text(s, 1.3, 3.4 + i * 0.48, 5.0, 0.42,
         [[("・", {"color": "gold"}), (t, {"color": "dark"})]], size=12.5)
card(s, 6.8, 2.05, 5.65, 4.4)
text(s, 7.2, 2.35, 5.0, 0.4, "回測 ＋ 避險成本分析", size=20, bold=True, color="green")
text(s, 7.2, 2.85, 5.0, 0.35, "本週新增：把「保護」標上價格", size=13, color="grey")
for i, t in enumerate(["Walk-forward：每次只用當下之前的資料重訓",
                       "有避險 vs 無避險淨值曲線、最大回撤對照",
                       "7 個真實歷史事件情境（海嘯、歐債、新冠…）",
                       "四種工具對決：不避險／期貨／Put／Collar",
                       "新增避險成本：轉倉、手續費、權利金逐日計提",
                       "新指標「保護單價」：回撤改善 1pp 要花多少報酬"]):
    text(s, 7.2, 3.4 + i * 0.48, 5.0, 0.42,
         [[("・", {"color": "gold"}), (t, {"color": "dark"})]], size=12.5)

# ===================== 7. 目前的數字 =====================
s = slide_head("06　實測結果", "目前跑出來的數字",
               f"回測期間 {bt['meta']['period']}，共 {bt['meta']['n_days']:,} 個交易日")
kpi = [("不避險 總報酬", f"{bm['total_return_unhedged']:.0f}%", "dark", "light"),
       ("避險 總報酬", f"{bm['total_return_hedged']:.0f}%", "green", "mint"),
       ("最大回撤 改善", f"{bm['max_drawdown_unhedged']:.1f}% → {bm['max_drawdown_hedged']:.1f}%", "dark", "light"),
       ("保護單價", f"{bm['protection_price']:.0f} 倍", "red", "blush")]
kw = 2.72; kx = (W - (kw * 4 + 0.3 * 3)) / 2
for i, (t, v, col, bgc) in enumerate(kpi):
    x = kx + i * (kw + 0.3)
    card(s, x, 2.15, kw, 1.5, fill=bgc, edge=None)
    text(s, x + 0.25, 2.4, kw - 0.5, 0.3, t, size=12, color="grey")
    text(s, x + 0.25, 2.8, kw - 0.5, 0.55, v, size=21, bold=True, color=col)
text(s, 0.9, 3.95, 11.55, 0.4, "模型三方比較（AUC 要 > 0.5 才算有方向判斷力）",
     size=15, bold=True)
tbl = [("naive 隨機漫步（基準）", f"{m['naive']['rmse']:.1f}", "—"),
       ("LSTM 單因子（只用金價）", f"{m['lstm_single']['rmse']:.1f}", f"{m['lstm_single']['auc']:.3f}"),
       ("LSTM 多因子（6 個因子）", f"{m['lstm_multi']['rmse']:.1f}", f"{m['lstm_multi']['auc']:.3f}")]
text(s, 1.3, 4.45, 5.0, 0.3, "模型", size=11.5, color="grey")
text(s, 6.6, 4.45, 1.6, 0.3, "RMSE", size=11.5, color="grey", align=PP_ALIGN.RIGHT)
text(s, 8.6, 4.45, 1.6, 0.3, "AUC", size=11.5, color="grey", align=PP_ALIGN.RIGHT)
for i, (n, rmse, auc) in enumerate(tbl):
    y = 4.8 + i * 0.45
    ln = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(1.3), Inches(y),
                            Inches(9.0), Inches(0.012))
    ln.fill.solid(); ln.fill.fore_color.rgb = C["line"]; ln.line.fill.background()
    ln.shadow.inherit = False
    hot = (i == 2)
    text(s, 1.3, y + 0.08, 5.0, 0.35, n, size=13, bold=hot)
    text(s, 6.6, y + 0.08, 1.6, 0.35, rmse, size=13, align=PP_ALIGN.RIGHT)
    text(s, 8.6, y + 0.08, 1.6, 0.35, auc, size=13, bold=hot,
         color="red" if hot else "dark", align=PP_ALIGN.RIGHT)
card(s, 0.9, 6.3, 11.55, 0.75, fill="light", edge=None)
text(s, 1.3, 6.5, 10.9, 0.4,
     [[("要誠實面對：", {"bold": True, "color": "red"}),
       (f"多因子 AUC = {m['lstm_multi']['auc']:.3f}，略低於 0.5，方向判斷力目前約等同亂猜。",
        {"color": "dark"})]], size=13.5)

# ===================== 8. 主要發現 =====================
s = slide_head("07　主要發現", "回測告訴我們的三件事")
finds = [("避險確實有壓低風險，但代價很高",
          f"最大回撤從 {bm['max_drawdown_unhedged']:.1f}% 改善到 {bm['max_drawdown_hedged']:.1f}%（+2.6pp），"
          f"但總報酬從 {bm['total_return_unhedged']:.0f}% 掉到 {bm['total_return_hedged']:.0f}%（−52pp）。", "red"),
         ("成本不是瓶頸，訊號品質才是",
          "本週把轉倉、手續費、權利金都算進去後才發現：模型平均只降低 9% 曝險、一年換手 0.4 次，"
          "所以就算假設保險完全免費，保護單價仍有 19 倍。", "gold"),
         ("但訊號不是完全沒用 —— 有兩個正面證據",
          "同樣用保護性賣權，「聽訊號才避」283% ／ −40.5%，優於「無腦每月都避」225% ／ −41.8%；"
          "而 Collar 回撤 −37.8%，是四種做法裡權衡最好的。", "green")]
for i, (t, d, col) in enumerate(finds):
    y = 2.1 + i * 1.55
    card(s, 0.9, y, 11.55, 1.35, fill="white")
    bar = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.9), Inches(y),
                             Inches(0.05), Inches(1.35))
    bar.fill.solid(); bar.fill.fore_color.rgb = C[col]; bar.line.fill.background()
    bar.shadow.inherit = False
    text(s, 1.25, y + 0.22, 11.0, 0.4, f"{i+1}.　{t}", size=17, bold=True, color=col)
    text(s, 1.25, y + 0.7, 10.9, 0.6, d, size=13, color="grey", spacing=1.2)

# ===================== 9. 下一步 =====================
s = slide_head("08　下一步", "想請教老師的三個方向")
nexts = [("AUC < 0.5 要怎麼處理？",
          "換 horizon（5 天太短？）／換標籤定義（改預測「大跌」而非「下跌」）／"
          "或接受它，把論文定位改成「驗證訊號式避險在黃金上不成立」的負面結論研究"),
         ("波動率改用市場隱含波動率",
          "目前模擬器的波動率是使用者手打（預設 18%），但權利金對它極度敏感。"
          "想改抓 GVZ（黃金版 VIX）當隱含波動率"),
         ("台灣落地",
          "補上台銀黃金存摺約 1% 的買賣價差 —— 這是台灣散戶真實會付的成本，"
          "也是這個專題才做得出來的角度")]
for i, (t, d) in enumerate(nexts):
    y = 2.15 + i * 1.5
    num = s.shapes.add_shape(MSO_SHAPE.OVAL, Inches(1.0), Inches(y + 0.1),
                             Inches(0.5), Inches(0.5))
    num.fill.solid(); num.fill.fore_color.rgb = C["green"]; num.line.fill.background()
    num.shadow.inherit = False
    text(s, 1.0, y + 0.2, 0.5, 0.35, str(i + 1), size=16, bold=True,
         color="white", align=PP_ALIGN.CENTER)
    text(s, 1.75, y + 0.08, 10.5, 0.4, t, size=18, bold=True)
    text(s, 1.75, y + 0.58, 10.5, 0.75, d, size=13, color="grey", spacing=1.2)
card(s, 0.9, 6.55, 11.55, 0.6, fill="dark", edge=None)
text(s, 1.3, 6.7, 10.9, 0.35,
     [[("網站 demo：", {"color": "gold"}),
       ("lilianlee1025-eng.github.io/GoldHedging", {"color": "white"})]], size=13)

out = "outputs/專題進度報告.pptx"
prs.save(out)
print("已產生：", out, f"（{len(prs.slides.__iter__.__self__._sldIdLst)} 頁）")
